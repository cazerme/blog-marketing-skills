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
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md as mdmod  # noqa: E402

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
        self._article_depth = 0    # inside <article>/<main>: a <header> there belongs to the post
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

    def _is_skip_container(self, tag):
        """Site chrome is skipped; an article-scoped <header> is post content."""
        if tag not in SKIP_CONTAINERS:
            return False
        return not (tag == "header" and self._article_depth > 0)

    # -- parser events -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        start = self._abs()
        raw = self.get_starttag_text() or ""

        if tag in ("article", "main"):
            self._article_depth += 1
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

        if self._is_skip_container(tag):
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

        if self._is_skip_container(tag):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in ("article", "main"):
            self._article_depth = max(0, self._article_depth - 1)

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
    doc_kind = model.get("doc_kind")
    is_fragment = doc_kind == "fragment"
    is_md = doc_kind == "markdown"
    fm_present = model["head"].get("frontmatter_present", False)

    def add(cid, status, detail, weight):
        checks.append({"id": cid, "status": status, "detail": detail, "weight": weight})

    def skip(cid, why):
        # skipped checks carry no weight and do not affect the score
        add(cid, "skipped", why, 0)

    title = model["head"]["title"]
    title_text = (title or {}).get("text") or ""
    if is_fragment:
        skip("title", "fragment — <title> lives in the page template")
    elif is_md and not fm_present:
        skip("title", "no front matter — title lives in your SSG config/template")
    elif not title_text:
        add("title", "fail",
            "no title in front matter" if is_md else "no <title> found", 15)
    elif 30 <= len(title_text) <= 60:
        add("title", "pass", "title length %d ok" % len(title_text), 15)
    else:
        add("title", "warn", "title length %d (recommended 30-60)" % len(title_text), 15)

    md = model["head"]["meta_description"]
    if is_fragment:
        skip("meta_description", "fragment — meta description lives in the page template")
    elif is_md and not fm_present:
        skip("meta_description", "no front matter — description lives in your SSG config/template")
    elif not md:
        add("meta_description", "fail",
            "no description in front matter" if is_md else "no meta description", 15)
    elif 70 <= len(md["content"]) <= 160:
        add("meta_description", "pass", "length %d ok" % len(md["content"]), 15)
    else:
        add("meta_description", "warn", "length %d (recommended 70-160)" % len(md["content"]), 15)

    h1s = [b for b in model["blocks"] if b["tag"] == "h1"]
    if is_md:
        if not h1s and title_text:
            add("h1_unique", "pass", "no body h1 — front-matter title renders as the h1", 10)
        elif len(h1s) == 1 and title_text:
            add("h1_unique", "warn", "body h1 may duplicate the front-matter title", 10)
        elif len(h1s) == 1:
            add("h1_unique", "pass", "1 h1 element", 10)
        else:
            add("h1_unique", "fail",
                "no h1 or front-matter title" if not h1s else "%d h1 elements" % len(h1s), 10)
    elif is_fragment and not h1s:
        skip("h1_unique", "fragment — h1 typically provided by the template")
    else:
        add("h1_unique", "pass" if len(h1s) == 1 else "fail", "%d h1 element(s)" % len(h1s), 10)

    levels = [int(b["tag"][1]) for b in model["blocks"] if re.match(r"h[1-6]$", b["tag"])]
    if is_md and fm_present and title_text:
        levels = [1] + levels  # front-matter title renders as the page h1
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
    elif is_md:
        skip("canonical", "markdown — canonical is handled by your SSG/theme")
        skip("jsonld", "markdown — structured data is handled by your SSG/theme")
    else:
        add("canonical", "pass" if model["head"]["canonical_present"] else "warn",
            "canonical link %s" % ("present" if model["head"]["canonical_present"] else "missing"), 5)
        add("jsonld", "pass" if model["head"]["jsonld_present"] else "warn",
            "JSON-LD structured data %s" % ("present" if model["head"]["jsonld_present"] else "missing"), 5)

    if keyword:
        kw = keyword.lower()
        if not title_text:
            skip("kw_title", "no title available in this file (see title check)")
        else:
            add("kw_title", "pass" if kw in title_text.lower() else "fail",
                "keyword in title: %s" % (kw in title_text.lower()), 4)
        h1_equiv = (h1s[0]["text"] if h1s else "") or (title_text if is_md else "")
        if not h1_equiv:
            skip("kw_h1", "no h1 available in this file")
        else:
            add("kw_h1", "pass" if kw in h1_equiv.lower() else "fail",
                "keyword in h1: %s" % (kw in h1_equiv.lower()), 3)
        first_p = next((b["text"] for b in model["blocks"] if b["tag"] == "p" and b["editable"]), "")
        opening = " ".join(first_p.split()[:100]).lower()
        add("kw_opening", "pass" if kw in opening else "fail",
            "keyword in first 100 words: %s" % (kw in opening), 3)

    # coverage honesty indicator: weight 0 — informs, never scores
    ratio = model.get("stats", {}).get("capture_ratio", 1.0)
    pct = round(ratio * 100)
    if ratio < 0.7:
        add("capture", "warn",
            "only %d%% of visible body text was recognized as content blocks — "
            "diagnosis and edits cover that portion only" % pct, 0)
    else:
        add("capture", "pass", "%d%% of visible body text captured" % pct, 0)

    scored = [c for c in checks if c["status"] != "skipped"]
    earned = sum({"pass": 1.0, "warn": 0.5, "fail": 0.0}[c["status"]] * c["weight"] for c in scored)
    total = sum(c["weight"] for c in scored) or 1
    return {"score": round(100.0 * earned / total, 1), "max": 100,
            "checks": checks}


def build_model(source, source_path="<string>", keyword=None):
    """Dispatch on file extension: .md/.markdown → markdown, else HTML."""
    if source_path.lower().endswith((".md", ".markdown")):
        return _build_model_md(source, source_path, keyword)
    return _build_model_html(source, source_path, keyword)


def _finish_model(model, source, keyword):
    model["source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    model["stats"] = {
        "word_count": model["stats"]["word_count"],
        "block_count": len(model["blocks"]),
        "editable_count": sum(1 for b in model["blocks"] if b["editable"]),
        "capture_ratio": model["stats"].get("capture_ratio", 1.0),
    }
    model["mechanical"] = run_checks(model, keyword=keyword)
    return model


def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def _build_model_html(source, source_path, keyword):
    parser = ModelParser(source)
    parser.feed(source)
    parser.close()
    if parser._open is not None:
        raise ValueError("unclosed <%s> block — file is not well-formed static HTML"
                         % parser._open["tag"])
    if not any(b["editable"] for b in parser.blocks):
        raise ValueError("no editable article content found — is this a build "
                         "artifact / SPA shell rather than a static blog post?")
    words = re.findall(r"[A-Za-z0-9'À-ɏ-]+", " ".join(parser.body_text_parts))
    # coverage honesty: how much of the visible body text landed in blocks
    body_text = _collapse(" ".join(parser.body_text_parts))
    captured = _collapse(" ".join(b["text"] for b in parser.blocks))
    ratio = 1.0 if not body_text else min(1.0, round(len(captured) / len(body_text), 3))
    return _finish_model({
        "source_path": source_path,
        "format": "html",
        "doc_kind": "document" if parser.head["has_head"] else "fragment",
        "head": parser.head,
        "blocks": parser.blocks,
        "links": parser.links,
        "images": parser.images,
        "stats": {"word_count": len(words), "capture_ratio": ratio},
    }, source, keyword)


def _build_model_md(source, source_path, keyword):
    fm_head, blocks, links, images = mdmod.parse(source)
    for i, b in enumerate(blocks):
        b["id"] = "b%03d" % (i + 1)
    if not any(b["editable"] for b in blocks):
        raise ValueError("no editable article content found — this markdown file "
                         "appears to be all code/HTML/front matter")
    head = {
        "title": fm_head["title"],
        "meta_description": fm_head["meta_description"],
        "og_count": 0, "canonical_present": False, "jsonld_present": False,
        "head_end_offset": None, "has_head": False,
        "frontmatter_present": fm_head["frontmatter_present"],
        "fm_insert_offset": fm_head["fm_insert_offset"],
        "complex_keys": fm_head["complex_keys"],
    }
    words = re.findall(r"[A-Za-z0-9'À-ɏ-]+",
                       " ".join(b["text"] for b in blocks if b["editable"]))
    return _finish_model({
        "source_path": source_path,
        "format": "markdown",
        "doc_kind": "markdown",
        "head": head,
        "blocks": blocks,
        "links": links,
        "images": images,
        # markdown has no skip containers and a paragraph catch-all:
        # every non-blank line lands in some block by construction
        "stats": {"word_count": len(words), "capture_ratio": 1.0},
    }, source, keyword)


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
