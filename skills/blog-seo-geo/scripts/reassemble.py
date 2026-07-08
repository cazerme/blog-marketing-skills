#!/usr/bin/env python3
"""reassemble.py — apply an EditPlan to a blog HTML file, fail-closed.

Stdlib only. No network. Splices edits into the original source by byte
span: regions not named in the plan are byte-identical by construction.

Refuses to write anything unless every validation and integrity check
passes. Default is a dry run; pass --write to actually modify the file.

Backups live in `<input-dir>/.seo-optimizer/backups/` (a dot-directory
that static site generators and build tools ignore by convention):
  <name>.original            first-ever pre-run copy — never overwritten
  <name>.YYYYMMDD-HHMMSS     this run's pre-write state (collision-safe)

EditPlan JSON:
{
  "source_sha256": "...",                # from extract.py's ContentModel
  "keywords": {"primary": "..."},        # optional, used for scoring
  "block_edits": [{"block_id": "b003", "new_inner_html": "...",
                    "reason": "...", "tag": "seo"}],
  "meta_edits": {"title": "...", "meta_description": "..."},   # optional
  "insertions": [{"after_block_id": "b005", "html": "<h2>..</h2>",
                   "reason": "..."}]     # optional
}

Exit codes: 0 ok · 2 usage/IO error · 4 file changed since extract ·
5 invalid plan · 6 integrity violation (nothing written).
"""
import argparse
import datetime
import html as htmllib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402
import md as mdlib  # noqa: E402


def fail(code, report, msg):
    report["ok"] = False
    report["violations"].append(msg)
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return code


NUM_RE = re.compile(r"\d[\d,\.]*")
ENTITY_RE = re.compile(r"&#x?[0-9a-fA-F]+;")


def _canonical_numbers(text):
    """Digit sequences, comma-stripped, trailing punctuation trimmed."""
    out = set()
    for m in NUM_RE.finditer(ENTITY_RE.sub(" ", text)):
        tok = m.group(0).rstrip(".,").replace(",", "")
        if tok:
            out.add(tok)
    return out


def check_numbers(source, plan, report):
    """Fabrication guard: every number a rewrite introduces must already
    exist somewhere in the original document. Statistics are where
    fabrication hurts most AND where checking is purely mechanical.
    Integers 0-10 are exempt (legitimate word-to-digit rewrites like
    "eight steps" -> "8 steps")."""
    allowed = _canonical_numbers(source)
    pieces = []
    for e in plan.get("block_edits", []):
        pieces.append(("block_edit %s" % e.get("block_id"),
                       e.get("new_content") or e.get("new_inner_html") or ""))
    for ins in plan.get("insertions", []):
        pieces.append(("insertion after %s" % ins.get("after_block_id"),
                       ins.get("html", "")))
    meta = plan.get("meta_edits") or {}
    for k in ("title", "meta_description"):
        if meta.get(k):
            pieces.append(("meta_edits.%s" % k, meta[k]))
    for where, text in pieces:
        for num in sorted(_canonical_numbers(text) - allowed):
            if num.isdigit() and int(num) <= 10:
                continue
            report["violations"].append(
                "fabricated or altered number %r in %s — not found in the "
                "original document" % (num, where))


def build_splices(model, plan, report):
    """Return list of (start, end, replacement) or None on invalid plan."""
    splices = []
    blocks = {b["id"]: b for b in model["blocks"]}
    seen = set()
    is_md = model.get("format") == "markdown"
    ins_sep = "\n\n" if is_md else "\n"

    for e in plan.get("block_edits", []):
        bid = e.get("block_id")
        b = blocks.get(bid)
        # new_content is the preferred field (markdown or HTML); new_inner_html kept for compat
        new = e.get("new_content") or e.get("new_inner_html") or ""
        if b is None:
            report["violations"].append("block_edit: unknown block_id %r" % bid)
        elif not b["editable"]:
            report["violations"].append("block_edit: block %s (<%s>) is not editable" % (bid, b["tag"]))
        elif bid in seen:
            report["violations"].append("block_edit: duplicate edit for %s" % bid)
        elif not new.strip():
            report["violations"].append("block_edit: empty replacement for %s" % bid)
        elif ("</%s>" % b["tag"]) in new.lower():
            report["violations"].append("block_edit: %s replacement contains closing </%s>" % (bid, b["tag"]))
        else:
            seen.add(bid)
            splices.append((b["inner_span"][0], b["inner_span"][1], new))
            report["changed_blocks"].append(bid)

    for ins in plan.get("insertions", []):
        bid = ins.get("after_block_id")
        b = blocks.get(bid)
        content = ins.get("html", "")
        if b is None:
            report["violations"].append("insertion: unknown after_block_id %r" % bid)
        elif not content.strip():
            report["violations"].append("insertion: empty html")
        else:
            splices.append((b["span"][1], b["span"][1], ins_sep + content))
            report["insertions"].append(bid)

    meta = plan.get("meta_edits") or {}
    fm_off = model["head"].get("fm_insert_offset")
    if meta.get("title"):
        t = model["head"]["title"]
        if is_md:
            if t:
                splices.append((t["inner_span"][0], t["inner_span"][1],
                                mdlib.yaml_quote(meta["title"])))
                report["meta_changes"].append("title")
            elif fm_off is not None:
                splices.append((fm_off, fm_off, "title: %s\n" % mdlib.yaml_quote(meta["title"])))
                report["meta_changes"].append("title")
            else:
                report["violations"].append("meta_edits.title: markdown file has no front matter")
        elif not t:
            report["violations"].append("meta_edits.title: document has no <title> element")
        else:
            splices.append((t["inner_span"][0], t["inner_span"][1],
                            htmllib.escape(meta["title"])))
            report["meta_changes"].append("title")
    if meta.get("meta_description"):
        if is_md:
            md = model["head"]["meta_description"]
            if md:
                splices.append((md["span"][0], md["span"][1],
                                mdlib.yaml_quote(meta["meta_description"])))
                report["meta_changes"].append("meta_description")
            elif fm_off is not None:
                splices.append((fm_off, fm_off,
                                "description: %s\n" % mdlib.yaml_quote(meta["meta_description"])))
                report["meta_changes"].append("meta_description")
            else:
                report["violations"].append("meta_edits.meta_description: markdown file has no front matter")
        else:
            tag = '<meta name="description" content="%s">' % htmllib.escape(meta["meta_description"], quote=True)
            md = model["head"]["meta_description"]
            if md:
                splices.append((md["span"][0], md["span"][1], tag))
                report["meta_changes"].append("meta_description")
            elif model["head"]["head_end_offset"] is not None:
                off = model["head"]["head_end_offset"]
                splices.append((off, off, tag + "\n"))
                report["meta_changes"].append("meta_description")
            else:
                report["violations"].append("meta_edits.meta_description: no <head> to place it in")

    if report["violations"]:
        return None

    splices.sort(key=lambda s: (s[0], s[1]))
    for (s1, e1, _), (s2, _e2, _r) in zip(splices, splices[1:]):
        if s2 < e1:
            report["violations"].append("overlapping edits at offsets %d/%d" % (s1, s2))
            return None
    return splices


def check_integrity(before, after_source, keyword, report):
    """Parse the edited source and compare inventories. Returns after-model or None."""
    try:
        after = extract.build_model(after_source, source_path=before["source_path"],
                                    keyword=keyword)
    except ValueError as e:
        report["violations"].append("edited document no longer parses: %s" % e)
        return None

    lost_links = sorted({l["href"] for l in before["links"]} -
                        {l["href"] for l in after["links"]})
    if lost_links:
        report["violations"].append("links lost in rewrite: %s" % ", ".join(lost_links))
    lost_imgs = sorted({i["src"] for i in before["images"]} -
                       {i["src"] for i in after["images"]})
    if lost_imgs:
        report["violations"].append("images lost in rewrite: %s" % ", ".join(lost_imgs))

    h1b = sum(1 for b in before["blocks"] if b["tag"] == "h1")
    h1a = sum(1 for b in after["blocks"] if b["tag"] == "h1")
    if h1a != h1b:
        report["violations"].append("h1 count changed %d -> %d" % (h1b, h1a))
    if after["stats"]["block_count"] < before["stats"]["block_count"]:
        report["violations"].append("block count shrank %d -> %d" %
                                    (before["stats"]["block_count"], after["stats"]["block_count"]))
    return after if not report["violations"] else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="path to the blog post HTML file")
    ap.add_argument("editplan", help="path to the EditPlan JSON")
    ap.add_argument("--write", action="store_true",
                    help="apply the plan (default: dry run, no file touched)")
    args = ap.parse_args(argv)

    report = {"ok": True, "wrote": False, "backup": None, "violations": [],
              "changed_blocks": [], "insertions": [], "meta_changes": [],
              "mechanical_before": None, "mechanical_after": None}

    try:
        with open(args.input, encoding="utf-8") as f:
            source = f.read()
        with open(args.editplan, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    keyword = (plan.get("keywords") or {}).get("primary")
    try:
        model = extract.build_model(source, source_path=args.input, keyword=keyword)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    report["mechanical_before"] = model["mechanical"]["score"]

    if plan.get("source_sha256") != model["source_sha256"]:
        return fail(4, report, "file changed since extract (sha256 mismatch) — re-run extract.py")

    if not (plan.get("block_edits") or plan.get("insertions") or plan.get("meta_edits")):
        # empty plan is legal: round-trip no-op, used by tests
        pass

    check_numbers(source, plan, report)
    splices = build_splices(model, plan, report)
    if splices is None:
        return fail(5, report, "plan rejected — nothing written")

    new_source = source
    for start, end, replacement in sorted(splices, key=lambda s: s[0], reverse=True):
        new_source = new_source[:start] + replacement + new_source[end:]

    after = check_integrity(model, new_source, keyword, report)
    if after is None:
        return fail(6, report, "integrity check failed — nothing written")
    report["mechanical_after"] = after["mechanical"]["score"]
    report["identical"] = new_source == source

    if args.write:
        d = os.path.dirname(os.path.abspath(args.input)) or "."
        base = os.path.basename(args.input)
        bdir = os.path.join(d, ".seo-optimizer", "backups")
        try:
            os.makedirs(bdir, exist_ok=True)
            original = os.path.join(bdir, base + ".original")
            if not os.path.exists(original):  # first ever run: preserve forever
                with open(original, "w", encoding="utf-8") as f:
                    f.write(source)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            snapshot = os.path.join(bdir, "%s.%s" % (base, stamp))
            n = 1
            while os.path.exists(snapshot):
                n += 1
                snapshot = os.path.join(bdir, "%s.%s-%d" % (base, stamp, n))
            with open(snapshot, "w", encoding="utf-8") as f:
                f.write(source)
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_source)
            os.replace(tmp, args.input)
        except OSError as e:
            return fail(2, report, "write failed: %s" % e)
        report["wrote"] = True
        report["backup"] = {"original": original, "snapshot": snapshot}

    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
