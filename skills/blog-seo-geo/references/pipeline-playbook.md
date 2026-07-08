# aaron-marketing call-point playbook

The single place that tracks every aaron-marketing sub-skill this plugin
invokes. When upstream aaron-marketing releases a new major version, re-verify
each row here (names, modes, expected outputs) — nothing else in this repo
talks to aaron-marketing.

**Tested against: aaron-marketing 16.1.0.** These are natural-language
contracts, not APIs: sub-skill output shapes can drift between versions.
If a call point misbehaves, compare against this table before changing SKILL.md.

| # | Sub-skill | Mode / focus | We feed it | We expect back | Step |
|---|---|---|---|---|---|
| 1 | `aaron-marketing:on-page-seo-auditor` | local-file audit | file path, target keyword, fragment note if applicable | prioritized on-page findings (title/meta/headings/keyword placement/links/images) | 3 |
| 2 | `aaron-marketing:content-writer` | **refresh** mode | editable blocks `(id, tag, text)`, audit findings, keyword, red lines (no new facts, preserve links/images, keep voice) | block-level rewrite proposals + title/meta text if flagged | 4 |
| 3 | `aaron-marketing:geo-content-optimizer` | Gemini-style AI citation | post-rewrite content, keyword | quotable block rewrites (by `block_id`) + optional FAQ/answer insertions (by `after_block_id`) | 5 |
| 4 | `aaron-marketing:serp-markup-builder` | head markup | post-rewrite content, keyword | title tag, meta description, OG/Twitter block, JSON-LD (Article/BlogPosting, FAQPage only if a real FAQ exists) | 6 |

Disposal of outputs:

- Call points 2–3 → `block_edits` / `insertions` in the EditPlan (one edit per block; merge when 2 and 3 touch the same block). Content is in the file's own format: HTML for `.html`, markdown for `.md`.
- Call point 4 → `meta_edits` for **HTML documents** (title + meta description) and **markdown with front matter** (front-matter `title`/`description`, missing keys added); everything else (OG/Twitter/JSON-LD/canonical — and for fragments / front-matter-less markdown, all of it) → the report's "Template suggestions" section as paste-ready values.

Dependency install (what Step 0 prints when the plugin is missing):

```
claude plugin marketplace add aaron-he-zhu/aaron-marketing-skills
claude plugin install aaron-marketing@aaron
```
