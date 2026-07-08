#!/usr/bin/env python3
"""md.py — line-based Markdown parsing for extract.py. Stdlib only.

Scope (v0.3): ATX headings, fenced code blocks, paragraphs, lists,
blockquotes, GFM tables, raw HTML blocks, thematic breaks, setext
headings (recognized, kept non-editable), and YAML front matter limited
to flat `key: value` entries. Anything that cannot be classified safely
becomes a non-editable block — the engine must never let a rewrite
corrupt code samples or embedded HTML.

Front matter keys with nested/multiline values are reported as
"complex" and are never edited.
"""
import re

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(\S*)\s*$")
ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
LIST_RE = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])[ \t]+\S")
QUOTE_RE = re.compile(r"^ {0,3}>")
HR_RE = re.compile(r"^ {0,3}([-*_])[ \t]*(\1[ \t]*){2,}$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-{2,})[ \t]*$")
TABLE_SEP_RE = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
HTML_BLOCK_RE = re.compile(r"^ {0,3}</?[a-zA-Z][^>]*>?")
INDENT_RE = re.compile(r"^ {2,}\S")
INDENT_CODE_RE = re.compile(r"^( {4,}|\t)\S")
FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):[ \t]*(.*)$")
IMG_ONLY_RE = re.compile(r"^ {0,3}!\[[^\]]*\]\([^)]*\)[ \t]*$")

MD_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)")
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
HTML_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
HTML_SRC_RE = re.compile(r"""src=["']([^"']+)["']""", re.I)
HTML_ALT_RE = re.compile(r"""alt=["']([^"']*)["']""", re.I)


def yaml_quote(value):
    """Always double-quote on write — safe for colons, quotes, hashes."""
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def _line_table(source):
    """[(start_offset, text_without_newline, end_offset_excl_newline), ...]"""
    out, off = [], 0
    for raw in source.splitlines(keepends=True):
        text = raw.rstrip("\r\n")
        out.append((off, text, off + len(text)))
        off += len(raw)
    return out


def _parse_frontmatter(lines):
    """Returns (head_dict, first_body_line_index)."""
    head = {"frontmatter_present": False, "fm_insert_offset": None,
            "complex_keys": [], "title": None, "meta_description": None}
    if not lines or lines[0][1].strip() != "---":
        return head, 0
    close = None
    for i in range(1, len(lines)):
        if lines[i][1].strip() in ("---", "..."):
            close = i
            break
    if close is None:
        return head, 0  # no closing delimiter: treat as body, not front matter
    head["frontmatter_present"] = True
    head["fm_insert_offset"] = lines[close][0]

    i = 1
    while i < close:
        start, text, _end = lines[i]
        m = FM_KEY_RE.match(text)
        if not m or text[:1] in (" ", "\t"):
            i += 1
            continue
        key, raw_val = m.group(1), m.group(2).strip()
        # nested/multiline value (list items or indented continuation)?
        nxt = lines[i + 1][1] if i + 1 < close else ""
        if not raw_val or nxt[:1] in (" ", "\t"):
            head["complex_keys"].append(key)
            i += 1
            continue
        val_start = start + text.index(":") + 1
        val_start += len(text[text.index(":") + 1:]) - len(text[text.index(":") + 1:].lstrip())
        val_end = start + len(text)
        value = raw_val
        if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in "\"'":
            value = raw_val[1:-1]
        entry = {"value": value, "value_span": [val_start, val_end]}
        if key == "title":
            head["title"] = {"text": value, "inner_span": entry["value_span"]}
        elif key == "description":
            head["meta_description"] = {"content": value, "span": entry["value_span"]}
        i += 1
    return head, close + 1


def _block_text(tag, slice_):
    """Light plain-text view of a block for keyword checks / LLM feeding."""
    t = MD_LINK_RE.sub(lambda m: m.group(2), slice_)
    out_lines = []
    for ln in t.splitlines():
        ln = re.sub(r"^ {0,3}#{1,6}[ \t]+", "", ln)
        ln = re.sub(r"^ {0,3}>[ \t]?", "", ln)
        ln = re.sub(r"^( {0,6})([-*+]|\d{1,9}[.)])[ \t]+", r"\1", ln)
        out_lines.append(ln)
    return re.sub(r"\s+", " ", " ".join(out_lines)).strip()


def parse(source):
    """Parse markdown into the pieces build_model needs."""
    lines = _line_table(source)
    head, body_start = _parse_frontmatter(lines)
    blocks = []
    code_spans = []

    def add(tag, editable, first, last, inner_span=None, text=None):
        span = [lines[first][0], lines[last][2]]
        slice_ = source[span[0]:span[1]]
        blocks.append({
            "tag": tag, "editable": editable, "span": span,
            "inner_span": inner_span if inner_span is not None else list(span),
            "text": text if text is not None else _block_text(tag, slice_),
            "html": slice_,
        })

    n = len(lines)
    j = body_start
    while j < n:
        start, text, _end = lines[j]
        stripped = text.strip()
        if not stripped:
            j += 1
            continue

        m = FENCE_RE.match(text)
        if m:
            fence, k = m.group(1), j + 1
            while k < n:
                m2 = FENCE_RE.match(lines[k][1])
                if m2 and m2.group(1)[0] == fence[0] and len(m2.group(1)) >= len(fence) and not m2.group(2):
                    break
                k += 1
            last = min(k, n - 1)
            add("code", False, j, last, text="")
            code_spans.append(tuple(blocks[-1]["span"]))
            j = last + 1
            continue

        m = ATX_RE.match(text)
        if m:
            tag = "h%d" % len(m.group(1))
            add(tag, True, j, j,
                inner_span=[start + m.start(2), start + m.end(2)],
                text=m.group(2))
            j += 1
            continue

        if HR_RE.match(text):
            add("hr", False, j, j, text="")
            j += 1
            continue

        if "|" in text and j + 1 < n and TABLE_SEP_RE.match(lines[j + 1][1]) and "|" in lines[j + 1][1]:
            k = j
            while k + 1 < n and lines[k + 1][1].strip() and "|" in lines[k + 1][1]:
                k += 1
            add("table", False, j, k)
            j = k + 1
            continue

        if HTML_BLOCK_RE.match(text) and not AUTOLINK_RE.match(stripped) and not IMG_ONLY_RE.match(text):
            k = j
            while k + 1 < n and lines[k + 1][1].strip():
                k += 1
            add("html", False, j, k)
            j = k + 1
            continue

        if QUOTE_RE.match(text):
            k = j
            while k + 1 < n and QUOTE_RE.match(lines[k + 1][1]):
                k += 1
            add("blockquote", True, j, k)
            j = k + 1
            continue

        m = LIST_RE.match(text)
        if m:
            tag = "ol" if m.group(2)[:1].isdigit() else "ul"
            k = j
            while k + 1 < n:
                nxt = lines[k + 1][1]
                if nxt.strip():
                    if LIST_RE.match(nxt) or INDENT_RE.match(nxt):
                        k += 1
                        continue
                    break
                # blank line: continue only if the list resumes after it
                p = k + 2
                while p < n and not lines[p][1].strip():
                    p += 1
                if p < n and (LIST_RE.match(lines[p][1]) or INDENT_RE.match(lines[p][1])):
                    k = p
                    continue
                break
            add(tag, True, j, k)
            j = k + 1
            continue

        if IMG_ONLY_RE.match(text):
            add("img", False, j, j, text="")
            j += 1
            continue

        # indented code block (classic 4-space style) — only at block start;
        # indented lines directly after paragraph text stay lazy continuation
        if INDENT_CODE_RE.match(text):
            k = j
            while k + 1 < n:
                nxt = lines[k + 1][1]
                if nxt.strip():
                    if INDENT_CODE_RE.match(nxt):
                        k += 1
                        continue
                    break
                p = k + 2  # blank: continue only if the indented block resumes
                while p < n and not lines[p][1].strip():
                    p += 1
                if p < n and INDENT_CODE_RE.match(lines[p][1]):
                    k = p
                    continue
                break
            add("code", False, j, k, text="")
            code_spans.append(tuple(blocks[-1]["span"]))
            j = k + 1
            continue

        # paragraph (or setext heading)
        k = j
        setext = None
        while k + 1 < n:
            nxt = lines[k + 1][1]
            if SETEXT_RE.match(nxt):  # setext underline wins over thematic break here
                setext = "h1" if nxt.strip().startswith("=") else "h2"
                break
            if (not nxt.strip() or FENCE_RE.match(nxt) or ATX_RE.match(nxt)
                    or QUOTE_RE.match(nxt) or LIST_RE.match(nxt) or HR_RE.match(nxt)):
                break
            k += 1
        if setext:
            add(setext, False, j, k + 1)  # conservative: setext headings stay non-editable
            j = k + 2
        else:
            add("p", True, j, k)
            j = k + 1

    links, images = _inventory(source, code_spans)
    return head, blocks, links, images


def _in_code(pos, code_spans):
    return any(s <= pos < e for s, e in code_spans)


def _inventory(source, code_spans):
    links, images = [], []
    for m in MD_LINK_RE.finditer(source):
        if _in_code(m.start(), code_spans):
            continue
        href = m.group(3)
        if m.group(1) == "!":
            images.append({"src": href, "alt": m.group(2), "in_content": True})
        else:
            links.append({"href": href,
                          "internal": not re.match(r"^[a-z][a-z0-9+.-]*:", href) and not href.startswith("//"),
                          "in_content": True})
    for m in AUTOLINK_RE.finditer(source):
        if not _in_code(m.start(), code_spans):
            links.append({"href": m.group(1), "internal": False, "in_content": True})
    for m in HTML_HREF_RE.finditer(source):
        if not _in_code(m.start(), code_spans):
            href = m.group(1)
            links.append({"href": href,
                          "internal": not re.match(r"^[a-z][a-z0-9+.-]*:", href) and not href.startswith("//"),
                          "in_content": True})
    for m in HTML_IMG_RE.finditer(source):
        if _in_code(m.start(), code_spans):
            continue
        src = HTML_SRC_RE.search(m.group(0))
        alt = HTML_ALT_RE.search(m.group(0))
        if src:
            images.append({"src": src.group(1),
                           "alt": alt.group(1) if alt else None, "in_content": True})
    return links, images
