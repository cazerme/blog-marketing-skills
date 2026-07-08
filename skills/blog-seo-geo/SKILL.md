---
name: blog-seo-geo
description: 'Optimize a local static blog post HTML file for SEO and GEO (AI-citation readiness): parse into blocks, audit with aaron-marketing:on-page-seo-auditor, rewrite blocks with aaron-marketing:content-writer (refresh mode), write the file back safely (backup + fail-closed integrity checks), and emit a change report. Use when the user asks to optimize a blog post, improve a post''s SEO, or make a post more citable by AI engines. Input is a path to an HTML file whose article content is in the file. Not for live URLs, SPA/build-artifact HTML, or site-level technical SEO.'
version: "0.1.0"
license: MIT
argument-hint: "<path/to/post.html> [target keyword]"
allowed-tools: Read, Write, Bash, Skill
---

# Blog SEO/GEO Optimizer

Optimize one static blog post HTML file in place, safely, and report what changed.

## Contract (read first, never violate)

1. **Never edit the HTML yourself** — not with Edit/Write, not by generating a full document. All file mutation goes through `reassemble.py`, which enforces integrity checks and refuses unsafe plans. Your only editing output is an **EditPlan JSON**.
2. **No fabrication**: rewrites reorganize, tighten, and clarify what the post already says. Never introduce new facts, numbers, statistics, quotes, or claims that are not in the original text.
3. **Preserve every inline link and image**: if a block you rewrite contains `<a>`/`<img>`, the rewritten HTML must contain the same `href`/`src`. (reassemble.py refuses the plan if any are lost — don't rely on that; get it right.)
4. **Fail closed**: if any step fails twice, stop, leave the file untouched, and tell the user exactly what happened. Never hand-patch around a refused plan.
5. Report wording: say "resolved N of M issues" — never claim subjective before/after quality scores. Only the deterministic mechanical score may be quoted as numbers.

All paths below use `$SKILL` for this skill's directory: set `SKILL="${CLAUDE_PLUGIN_ROOT}/skills/blog-seo-geo"` (if `CLAUDE_PLUGIN_ROOT` is unset, resolve relative to this SKILL.md's location). Use a temp directory (the session scratchpad) for `model.json` / `editplan.json`.

## Step 0 — Preflight

- The input path exists and is an `.html`/`.htm` file. If the user gave a URL instead of a path: stop and explain that v0.1 optimizes local source files (edit → deploy), not live pages.
- The aaron-marketing plugin is installed (the skills `aaron-marketing:on-page-seo-auditor` and `aaron-marketing:content-writer` are available). If not, stop and print:
  ```
  claude plugin marketplace add aaron-he-zhu/aaron-marketing-skills
  claude plugin install aaron-marketing@aaron
  ```

## Step 1 — Extract (read-only)

```bash
python3 "$SKILL/scripts/extract.py" <input.html> --out <tmp>/model.json [--keyword "<kw>"]
```

- Exit 3 means the file is not a static article (SPA shell / build artifact / malformed). Relay the script's message and stop: the right target is the content source file.
- Read `model.json`. If `doc_kind` is `"fragment"` (no `<head>`): stop politely — fragment support lands in v0.2; suggest running on a full-document post meanwhile.
- Note the mechanical score and its failing checks — these are the deterministic half of "M issues".

## Step 2 — Target keyword

If the user supplied one, use it. Otherwise derive a primary keyword from the title/h1/dominant topic (a real search phrase, 2–5 words, e.g. "camping packing list"), then re-run extract with `--keyword` so keyword checks join the baseline. The report must state the keyword was heuristically derived (no search-volume data behind it).

## Step 3 — Audit (aaron-marketing call point 1)

Invoke the Skill tool: `aaron-marketing:on-page-seo-auditor`, giving it the file path, the keyword, and a note that it is a local file audit. Collect its prioritized findings. Merge with the mechanical failures into one deduplicated issue list — this is **M** (total issues found). Keep the list; the report needs it.

## Step 4 — Rewrite (aaron-marketing call point 2)

Invoke the Skill tool: `aaron-marketing:content-writer` in **refresh mode**. Provide:

- the target keyword and the audit findings from Step 3
- the editable blocks as `(id, tag, text)` triples from `model.json`
- the red lines from the Contract (no new facts; preserve inline links/images verbatim; keep the author's voice; English)
- instruction: propose rewrites **only for blocks that fix a finding** — an unchanged block is a valid outcome; also propose `title` / `meta_description` text if the audit flags them.

## Step 5 — Build the EditPlan

Assemble the results into `<tmp>/editplan.json`:

```json
{
  "source_sha256": "<from model.json>",
  "keywords": {"primary": "<kw>"},
  "block_edits": [
    {"block_id": "b003", "new_inner_html": "…", "reason": "front-load keyword; tighten intro", "tag": "seo"}
  ],
  "meta_edits": {"title": "…", "meta_description": "…"},
  "insertions": []
}
```

Rules: only `block_id`s that exist in `model.json` with `editable: true`; `new_inner_html` is the block's inner HTML (inline tags allowed, the block's own start/end tags excluded); omit `meta_edits`/`insertions` when not needed.

## Step 6 — Apply (the only step that writes)

```bash
python3 "$SKILL/scripts/reassemble.py" <input.html> <tmp>/editplan.json          # dry run
python3 "$SKILL/scripts/reassemble.py" <input.html> <tmp>/editplan.json --write  # apply
```

- Dry-run first. If it reports violations, fix the plan **once** and retry; a second rejection means stop and report (file untouched).
- Exit 4 (sha mismatch): the file changed since extract — restart from Step 1.
- On success the JSON output contains `mechanical_before`/`mechanical_after`, changed blocks, and the backup path. The original is preserved at `<input>.bak`.

## Step 7 — Report

Write `<input-dir>/<basename>.seo-report.md` (e.g. `post.html` → `post.seo-report.md`):

```markdown
# SEO/GEO report — <basename>.html
- Target keyword: "<kw>" (user-provided | heuristically derived — not backed by search-volume data)
- Resolved <N> of <M> issues · mechanical score <before> → <after> (deterministic checks)
- Backup: <input>.html.bak

## Changes
| Block | Type | What changed | Why |
|---|---|---|---|

## Resolved issues
## Remaining suggestions
(head-level items v0.1 does not apply — canonical, JSON-LD, OG/Twitter cards — plus anything the audit raised that is out of scope; say where each belongs, e.g. the page template)
```

## Step 8 — Tell the user

Summarize in chat: keyword, resolved N of M, mechanical score movement, the three artifacts (optimized file, `.bak`, report), and the top remaining suggestion. Keep it short; the report holds the detail.
