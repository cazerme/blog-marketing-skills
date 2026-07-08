#!/usr/bin/env python3
"""extract.py — parse a static blog HTML file into a ContentModel JSON.

Stdlib only. No network. Read-only: never modifies any file.

The model maps every content block to its exact byte span in the source so
that reassemble.py can splice edits without re-serializing the document —
untouched regions stay byte-identical by construction.

Exit codes: 0 ok · 2 usage/IO error · 3 not parseable as a static article.
"""
import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser

BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol",
              "blockquote", "table", "pre", "figure", "img"}
EDITABLE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "blockquote"}
SKIP_CONTAINERS = {"nav", "footer", "header", "aside", "script", "style", "head", "form"}
VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "embed", "area", "base", "col", "track", "wbr"}


class ModelParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        line_starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                line_starts.append(i + 1)
        self._line_starts = line_starts

        self.blocks = []
        self.links = []
        self.images = []
        self.head = {"title": None, "meta_description": None, "og_count": 0,
                     "canonical_present": False, "jsonld_present": False,
                     "head_end_offset": None, "has_head": False}
        self.body_text_parts = []

        self._open = None          # {tag, depth, start, inner_start, text_parts}
        self._skip_depth = 0
        self._in_title = False
        self._title_parts = []
        self._title_inner_start = None
        self.parse_error = None

    def _abs(self):
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def _tag_end(self, start):
        gt = self.source.find(">", start)
        return (gt + 1) if gt != -1 else start

    # -- inventory helpers -------------------------------------------------
    def _record_link(self, attrs):
        href = dict(attrs).get("href")
        if not href:
            return
        self.links.append({
            "href": href,
            "internal": not re.match(r"^[a-z][a-z0-9+.-]*:", href) and not href.startswith("//"),
            "in_content": self._skip_depth == 0,
        })

    def _record_image(self, attrs):
        d = dict(attrs)
        if d.get("src") is None:
            return
        self.images.append({"src": d.get("src"), "alt": d.get("alt"),
                            "in_content": self._skip_depth == 0})

    # -- parser events -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        start = self._abs()
        raw = self.get_starttag_text() or ""

        if tag == "head":
            self.head["has_head"] = True
        if tag == "a":
            self._record_link(attrs)
        if tag == "img":
            self._record_image(attrs)
        if tag == "meta":
            d = dict(attrs)
            if d.get("name", "").lower() == "description":
                self.head["meta_description"] = {"content": d.get("content", ""),
                                                 "span": [start, start + len(raw)]}
            if d.get("property", "").startswith("og:"):
                self.head["og_count"] += 1
        if tag == "link" and dict(attrs).get("rel", "").lower() == "canonical":
            self.head["canonical_present"] = True
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.head["jsonld_present"] = True
        if tag == "title":
            self._in_title = True
            self._title_parts = []
            self._title_inner_start = start + len(raw)

        if tag in SKIP_CONTAINERS:
            self._skip_depth += 1
            return

        if self._open is not None:
            if tag == self._open["tag"] and tag not in VOID_TAGS:
                self._open["depth"] += 1
            return

        if tag in BLOCK_TAGS and self._skip_depth == 0:
            if tag in VOID_TAGS:  # img: complete immediately
                end = start + len(raw)
                self._add_block(tag, start, end, None, "")
            else:
                self._open = {"tag": tag, "depth": 1, "start": start,
                              "inner_start": start + len(raw), "text_parts": []}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        pos = self._abs()
        if tag == "title":
            self._in_title = False
            title_text = "".join(self._title_parts).strip()
            self.head["title"] = {"text": title_text,
                                  "inner_span": [self._title_inner_start, pos]}
        if tag == "head":
            self.head["head_end_offset"] = pos

        if tag in SKIP_CONTAINERS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._open is not None and tag == self._open["tag"]:
            self._open["depth"] -= 1
            if self._open["depth"] == 0:
                end = self._tag_end(pos)
                b = self._open
                self._open = None
                self._add_block(b["tag"], b["start"], end,
                                [b["inner_start"], pos], "".join(b["text_parts"]))

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        if self._skip_depth == 0:
            self.body_text_parts.append(data)
        if self._open is not None:
            self._open["text_parts"].append(data)

    def _add_block(self, tag, start, end, inner_span, text):
        self.blocks.append({
            "id": "b%03d" % (len(self.blocks) + 1),
            "tag": tag,
            "editable": tag in EDITABLE_TAGS,
            "span": [start, end],
            "inner_span": inner_span,
            "text": re.sub(r"\s+", " ", text).strip(),
            "html": self.source[start:end],
        })


# --- mechanical checks ------------------------------------------------------

def run_checks(model, keyword=None):
    checks = []
    is_fragment = model.get("doc_kind") == "fragment"

    def add(cid, status, detail, weight):
        checks.append({"id": cid, "status": status, "detail": detail, "weight": weight})

    def skip(cid, why):
        # skipped checks carry no weight and do not affect the score
        add(cid, "skipped", why, 0)

    title = model["head"]["title"]
    if is_fragment:
        skip("title", "fragment — <title> lives in the page template")
    elif not title or not title["text"]:
        add("title", "fail", "no <title> found", 15)
    elif 30 <= len(title["text"]) <= 60:
        add("title", "pass", "title length %d ok" % len(title["text"]), 15)
    else:
        add("title", "warn", "title length %d (recommended 30-60)" % len(title["text"]), 15)

    md = model["head"]["meta_description"]
    if is_fragment:
        skip("meta_description", "fragment — meta description lives in the page template")
    elif not md:
        add("meta_description", "fail", "no meta description", 15)
    elif 70 <= len(md["content"]) <= 160:
        add("meta_description", "pass", "length %d ok" % len(md["content"]), 15)
    else:
        add("meta_description", "warn", "length %d (recommended 70-160)" % len(md["content"]), 15)

    h1s = [b for b in model["blocks"] if b["tag"] == "h1"]
    if is_fragment and not h1s:
        skip("h1_unique", "fragment — h1 typically provided by the template")
    else:
        add("h1_unique", "pass" if len(h1s) == 1 else "fail", "%d h1 element(s)" % len(h1s), 10)

    levels = [int(b["tag"][1]) for b in model["blocks"] if re.match(r"h[1-6]$", b["tag"])]
    skips = [(a, b) for a, b in zip(levels, levels[1:]) if b > a + 1]
    add("heading_order", "pass" if not skips else "warn",
        "no level skips" if not skips else "level skips: %s" % skips, 10)

    imgs = [i for i in model["images"] if i["in_content"]]
    missing_alt = [i["src"] for i in imgs if not (i["alt"] or "").strip()]
    if not imgs:
        add("img_alt", "pass", "no content images", 10)
    else:
        add("img_alt", "pass" if not missing_alt else "fail",
            "all %d image(s) have alt" % len(imgs) if not missing_alt
            else "missing alt: %s" % ", ".join(missing_alt), 10)

    wc = model["stats"]["word_count"]
    add("word_count", "pass" if wc >= 300 else "warn", "%d words" % wc, 10)

    content_links = [l for l in model["links"] if l["in_content"]]
    internal = [l for l in content_links if l["internal"]]
    external = [l for l in content_links if not l["internal"]]
    add("links", "pass" if internal and external else "warn",
        "%d internal / %d external content links" % (len(internal), len(external)), 10)

    if is_fragment:
        skip("canonical", "fragment — canonical link lives in the page template")
        skip("jsonld", "fragment — structured data lives in the page template")
    else:
        add("canonical", "pass" if model["head"]["canonical_present"] else "warn",
            "canonical link %s" % ("present" if model["head"]["canonical_present"] else "missing"), 5)
        add("jsonld", "pass" if model["head"]["jsonld_present"] else "warn",
            "JSON-LD structured data %s" % ("present" if model["head"]["jsonld_present"] else "missing"), 5)

    if keyword:
        kw = keyword.lower()
        if is_fragment:
            skip("kw_title", "fragment — <title> lives in the page template")
        else:
            t = (title["text"] if title else "").lower()
            add("kw_title", "pass" if kw in t else "fail", "keyword in title: %s" % (kw in t), 4)
        if is_fragment and not h1s:
            skip("kw_h1", "fragment — h1 typically provided by the template")
        else:
            h1t = (h1s[0]["text"] if h1s else "").lower()
            add("kw_h1", "pass" if kw in h1t else "fail", "keyword in h1: %s" % (kw in h1t), 3)
        first_p = next((b["text"] for b in model["blocks"] if b["tag"] == "p" and b["editable"]), "")
        opening = " ".join(first_p.split()[:100]).lower()
        add("kw_opening", "pass" if kw in opening else "fail",
            "keyword in first 100 words: %s" % (kw in opening), 3)

    scored = [c for c in checks if c["status"] != "skipped"]
    earned = sum({"pass": 1.0, "warn": 0.5, "fail": 0.0}[c["status"]] * c["weight"] for c in scored)
    total = sum(c["weight"] for c in scored) or 1
    return {"score": round(100.0 * earned / total, 1), "max": 100,
            "checks": checks}


def build_model(source, source_path="<string>", keyword=None):
    parser = ModelParser(source)
    parser.feed(source)
    parser.close()
    if parser._open is not None:
        raise ValueError("unclosed <%s> block — file is not well-formed static HTML"
                         % parser._open["tag"])

    words = re.findall(r"[A-Za-z0-9'À-ɏ-]+", " ".join(parser.body_text_parts))
    model = {
        "source_path": source_path,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "doc_kind": "document" if parser.head["has_head"] else "fragment",
        "head": parser.head,
        "blocks": parser.blocks,
        "links": parser.links,
        "images": parser.images,
        "stats": {
            "word_count": len(words),
            "block_count": len(parser.blocks),
            "editable_count": sum(1 for b in parser.blocks if b["editable"]),
        },
    }
    if not any(b["editable"] for b in parser.blocks):
        raise ValueError("no editable article content found — is this a build "
                         "artifact / SPA shell rather than a static blog post?")
    model["mechanical"] = run_checks(model, keyword=keyword)
    return model


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="path to the blog post HTML file")
    ap.add_argument("--keyword", help="target keyword for keyword-placement checks")
    ap.add_argument("--out", help="write full ContentModel JSON to this path "
                                  "(default: print JSON to stdout)")
    args = ap.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    try:
        model = build_model(source, source_path=args.input, keyword=args.keyword)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 3

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(model, f, indent=2, ensure_ascii=False)
        mech = model["mechanical"]
        issues = [c for c in mech["checks"] if c["status"] != "pass"]
        print("model written to %s" % args.out)
        print("kind=%s blocks=%d editable=%d words=%d" % (
            model["doc_kind"], model["stats"]["block_count"],
            model["stats"]["editable_count"], model["stats"]["word_count"]))
        print("mechanical score: %s/100 — %d issue(s):" % (mech["score"], len(issues)))
        for c in issues:
            print("  [%s] %s: %s" % (c["status"], c["id"], c["detail"]))
    else:
        json.dump(model, sys.stdout, indent=2, ensure_ascii=False)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
