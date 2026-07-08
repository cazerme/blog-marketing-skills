---
name: blog-seo-geo
description: 'Optimize a local blog post file (HTML or Markdown) for SEO and GEO (AI-citation readiness): parse into blocks, audit with aaron-marketing:on-page-seo-auditor, rewrite blocks with aaron-marketing:content-writer, make content citation-ready with aaron-marketing:geo-content-optimizer, build head markup with aaron-marketing:serp-markup-builder, write the file back safely (backup + fail-closed integrity checks), and emit a change report. Handles full HTML documents, body fragments, and Markdown posts with YAML front matter (Jekyll/Hugo/GitHub Pages style); code fences and embedded HTML in markdown are never touched. Use when the user asks to optimize a blog post, improve a post''s SEO, or make a post more citable by AI engines. Input is a path to an .html or .md file whose article content is in the file. Not for live URLs, SPA/build-artifact HTML, or site-level technical SEO.'
version: "0.3.2"
license: MIT
argument-hint: "<path/to/post.html|.md> [target keyword]"
allowed-tools: Read, Write, Bash, Skill
---

# Blog SEO/GEO Optimizer

Optimize one static blog post HTML file in place, safely, and report what changed.
The aaron-marketing call-point contracts live in `references/pipeline-playbook.md` — consult it if a sub-skill's behavior seems off (upstream may have drifted).

## Contract (read first, never violate)

1. **Never edit the HTML yourself** — not with Edit/Write, not by generating a full document. All file mutation goes through `reassemble.py`, which enforces integrity checks and refuses unsafe plans. Your only editing output is an **EditPlan JSON**.
2. **No fabrication**: rewrites and GEO insertions (FAQ/answer blocks) may only reorganize, tighten, and restate what the post already says. Never introduce new facts, numbers, statistics, quotes, or claims that are not in the original text.
3. **Preserve every inline link and image**: if a block you rewrite contains `<a>`/`<img>`, the rewritten HTML must contain the same `href`/`src`. (reassemble.py refuses the plan if any are lost — don't rely on that; get it right.)
4. **Fragment rule**: when `doc_kind` is `"fragment"`, or `"markdown"` **without front matter**, never put `meta_edits` in the plan. Every head-level item (title, meta description, OG/Twitter, JSON-LD, canonical) goes into the report's **Template suggestions** section instead, with a pointer to where it belongs (the site's page template / post registry / SSG config). Markdown **with** front matter is different: title and description ARE in the file — apply them via `meta_edits`.
5. **Fail closed**: if any step fails twice, stop, leave the file untouched, and tell the user exactly what happened. Never hand-patch around a refused plan.
6. Report wording: say "resolved N of M issues" — never claim subjective before/after quality scores. Only the deterministic mechanical score may be quoted as numbers.

All paths below use `$SKILL` for this skill's directory: set `SKILL="${CLAUDE_PLUGIN_ROOT}/skills/blog-seo-geo"` (if `CLAUDE_PLUGIN_ROOT` is unset, resolve relative to this SKILL.md's location). Use a temp directory (the session scratchpad) for `model.json` / `editplan.json`.

## Step 0 — Preflight

- The input path exists and is an `.html`/`.htm`/`.md`/`.markdown` file. If the user gave a URL instead of a path: stop and explain that this skill optimizes local source files (edit → deploy), not live pages.
- The aaron-marketing plugin is installed (the `aaron-marketing:*` skills from the playbook are available). If not, stop and print:
  ```
  /plugin marketplace add aaron-he-zhu/aaron-marketing-skills
  /plugin install aaron-marketing@aaron
  ```

## Step 1 — Extract (read-only)

```bash
python3 "$SKILL/scripts/extract.py" <input.html> --out <tmp>/model.json [--keyword "<kw>"]
```

- Exit 3 means the file is not a static article (SPA shell / build artifact / malformed). Relay the script's message and stop: the right target is the content source file.
- Note `doc_kind`:
  - `"document"` — full HTML page; head edits can be applied to the file.
  - `"fragment"` — body-only HTML that a server/SSG injects into a template. Body optimization proceeds normally; head-level checks are auto-`skipped` by the script (they score against the template, not this file) and all head-level output must follow the Fragment rule.
  - `"markdown"` — a Markdown post. If `head.frontmatter_present` is true, front-matter `title`/`description` are the file's head equivalents and can be edited via `meta_edits`; if false, follow the Fragment rule. Code fences, embedded HTML, tables, setext headings and thematic breaks are non-editable blocks — never try to work around that.
- Note the mechanical score and its failing checks — the deterministic half of "M issues".

## Step 2 — Target keyword

If the user supplied one, use it. Otherwise derive a primary keyword from the title/h1/dominant topic (a real search phrase, 2–5 words), then re-run extract with `--keyword` so keyword checks join the baseline. The report must state the keyword was heuristically derived (no search-volume data behind it).

## Step 3 — SEO audit (call point 1)

Invoke `aaron-marketing:on-page-seo-auditor` with the file path, the keyword, and a note that it is a local file audit (fragment note if applicable: title/meta live in a template). Merge its prioritized findings with the mechanical failures into one deduplicated issue list — this is **M** (total issues found). Keep the list; the report needs it.

## Step 4 — SEO rewrite (call point 2)

Invoke `aaron-marketing:content-writer` in **refresh mode**. Provide:

- the target keyword and the audit findings from Step 3
- the editable blocks as `(id, tag, text)` triples from `model.json`
- the red lines from the Contract (no new facts; preserve inline links/images verbatim; keep the author's voice; English)
- the output format: rewritten content must be **markdown for `.md` inputs, HTML for `.html` inputs** — same syntax the block already uses (heading rewrites are text-only: the engine preserves `##`/tag prefixes itself)
- instruction: propose rewrites **only for blocks that fix a finding** — an unchanged block is a valid outcome; also propose `title` / `meta_description` text if the audit flags them.

## Step 5 — GEO pass (call point 3)

Invoke `aaron-marketing:geo-content-optimizer` targeting **Gemini-style AI citation**. Feed it the post content *as it will read after Step 4's rewrites*, plus the keyword. Ask for:

- block-level rewrites that make key passages **quotable**: self-contained, direct-answer phrasing an AI can lift verbatim (map each to a `block_id`)
- optional **insertions** (e.g. a short FAQ or "quick answer" block as block-level HTML, mapped to `after_block_id`) — only where the post lacks a liftable answer to the query the keyword implies

Red line reminder: every rewrite/insertion must only restate facts already in the post. If Step 4 and Step 5 both touch the same block, merge them into one edit yourself — one edit per block.

## Step 6 — Head & markup (call point 4)

Invoke `aaron-marketing:serp-markup-builder` with the (post-rewrite) content and keyword to produce: title tag, meta description, OG/Twitter tags, and JSON-LD (Article/BlogPosting; FAQPage only if Step 5 added a real FAQ).

- `doc_kind == "document"`: put **title + meta description** into `meta_edits` (the engine can write those); OG/Twitter/JSON-LD go to the report's Template suggestions (the engine does not inject head markup blocks).
- `doc_kind == "markdown"` with front matter: put **title + description** into `meta_edits` (the engine writes them into the front matter, adding missing keys); OG/Twitter/JSON-LD → Template suggestions ("your SSG theme/config handles these").
- `doc_kind == "fragment"` (or markdown without front matter): **everything** from this step goes to Template suggestions — include the exact text/JSON so the user can paste it into their template, post registry, or SSG config.

## Step 7 — Build the EditPlan

Assemble Steps 4–6 into `<tmp>/editplan.json`:

```json
{
  "source_sha256": "<from model.json>",
  "keywords": {"primary": "<kw>"},
  "block_edits": [
    {"block_id": "b003", "new_content": "…", "reason": "front-load keyword", "tag": "seo"},
    {"block_id": "b007", "new_content": "…", "reason": "quotable direct answer", "tag": "geo"}
  ],
  "insertions": [
    {"after_block_id": "b010", "html": "…", "reason": "…", "tag": "geo"}
  ],
  "meta_edits": {"title": "…", "meta_description": "…"}
}
```

Rules: only `block_id`s that exist in `model.json` with `editable: true`; `new_content` is the block's inner content in the file's own format — for HTML the inner HTML (inline tags allowed, the block's start/end tags excluded), for markdown the block's markdown (heading text without `#` markers); insertions are full blocks in the file's format; at most one edit per block; omit `meta_edits` for fragments and front-matter-less markdown; omit empty sections. (`new_inner_html` is accepted as a legacy alias of `new_content`.)

## Step 8 — Apply (the only step that writes)

```bash
python3 "$SKILL/scripts/reassemble.py" <input.html> <tmp>/editplan.json          # dry run
python3 "$SKILL/scripts/reassemble.py" <input.html> <tmp>/editplan.json --write  # apply
```

- Dry-run first. If it reports violations, fix the plan **once** and retry; a second rejection means stop and report (file untouched).
- Exit 4 (sha mismatch): the file changed since extract — restart from Step 1.
- On success the JSON output contains `mechanical_before`/`mechanical_after`, changed blocks, and the backup paths. Backups live in `<input-dir>/.seo-optimizer/backups/`: `<name>.original` is the first-ever pre-run copy (never overwritten across runs) and `<name>.<timestamp>` is this run's pre-write state — build tools ignore dot-directories, so neither can leak into a published site.

## Step 9 — Report

Write `<input-dir>/.seo-optimizer/reports/<basename>.seo-report.md` (e.g. `post.html` → `.seo-optimizer/reports/post.seo-report.md`). **Never write the report next to the input file**: content directories are scanned by static site generators, and a date-prefixed `.md` report inside e.g. Jekyll's `_posts/` would be published as an article. The dot-directory is ignored by every mainstream build tool.

```markdown
# SEO/GEO report — <basename>.html
- Target keyword: "<kw>" (user-provided | heuristically derived — not backed by search-volume data)
- Input kind: document | fragment (rendered by a page template) | markdown (front matter: yes/no)
- Resolved <N> of <M> issues · mechanical score <before> → <after> (deterministic checks)
- Backups: .seo-optimizer/backups/<name>.original (first-ever) · <name>.<timestamp> (this run)

## Changes
| Block | Type (seo/geo/meta) | What changed | Why |
|---|---|---|---|

## Resolved issues
## Template suggestions (not applied)
(everything head-level that belongs in the page template or post registry —
title, meta description, OG/Twitter, JSON-LD, canonical — with exact
paste-ready values and where each goes)

## Remaining suggestions
```

## Step 10 — Tell the user

Summarize in chat: keyword, resolved N of M, mechanical score movement, the artifacts (optimized file, backups, report — with the `.seo-optimizer/` paths), whether template suggestions need their attention, and the top remaining item. Keep it short; the report holds the detail.

Housekeeping hint (suggest, never do): if the input sits in a git repo and `git check-ignore -q .seo-optimizer` (run from the input's directory) exits non-zero, append one line to the summary suggesting the user add `.seo-optimizer/` to their `.gitignore` to keep backups local. **Do not edit their `.gitignore` yourself** — it is outside this skill's write whitelist (input file, backups, report, temp files only).
