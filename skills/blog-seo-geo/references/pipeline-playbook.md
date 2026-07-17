# aaron-marketing call-point playbook

The single place that tracks every aaron-marketing sub-skill this plugin
invokes. When upstream aaron-marketing releases a new major version, re-verify
each row here (names, modes, expected outputs) — nothing else in this repo
talks to aaron-marketing.

**Tested against: aaron-marketing 18.0.0.** These are natural-language
contracts, not APIs: sub-skill output shapes can drift between versions.
If a call point misbehaves, compare against this table before changing SKILL.md.
(The version in the line above is machine-read by the rebaseline workflow and
must match the `aaron_version` default in `optimize/action.yml` and
`pipeline/action.yml` — keep the `Tested against: aaron-marketing <version>`
wording when updating it.)

| # | Sub-skill | Mode / focus | We feed it | We expect back | Step |
|---|---|---|---|---|---|
| 1 | `aaron-marketing:on-page-seo-checker` | local-file audit | file path, target keyword, fragment note if applicable | prioritized on-page findings (title/meta/headings/keyword placement/links/images) | 3 |
| 2 | `aaron-marketing:content-writer` | **refresh** mode | editable blocks `(id, tag, text)`, audit findings, keyword, red lines (no new facts, preserve links/images, keep voice) | block-level rewrite proposals + title/meta text if flagged | 4 |
| 3 | `aaron-marketing:geo-content-optimizer` | Gemini-style AI citation | post-rewrite content, keyword | quotable block rewrites (by `block_id`) + optional FAQ/answer insertions (by `after_block_id`) | 5 |
| 4 | `aaron-marketing:serp-markup-builder` | **both** modes: `meta` + `schema` | post-rewrite content, keyword | title tag, meta description, OG/Twitter block, JSON-LD (Article/BlogPosting, FAQPage only if a real FAQ exists) | 6 |

Call-point notes (verified against 18.0.0):

- **1** — renamed upstream in 18.0.0 (see Known renames); the contract itself is
  unchanged from the 16.x `on-page-seo-auditor`.
- **3** — since 18.0.0 this skill consults `memory/entities/<slug>.md` for any
  brand/person/product it detects and may answer `DONE_WITH_CONCERNS`,
  recommending `entity-registry`, when profiles are missing. That is
  **non-blocking** for this pipeline: take the block rewrites/insertions it
  produced, surface the concern under the report's "Remaining suggestions",
  and never halt or run `entity-registry` yourself.
- **4** — since 18.0.0 this skill is split into `meta` and `schema` modes.
  Request **both** explicitly, or the JSON-LD half of the expected output
  will be missing.

## Known renames

When the installed version and this playbook disagree, check here before
improvising a substitute:

| Name at ≤ 16.x | Name at ≥ 18.0.0 | Renamed in |
|---|---|---|
| `on-page-seo-auditor` | `on-page-seo-checker` | 18.0.0 |

## If a call point is missing (fallback policies)

Applies when a call point's skill cannot be found under either name above.
Never substitute a merely similar-sounding skill beyond the renames table —
degrade or abort per this table and say so in the report:

| Call point | Policy |
|---|---|
| 1 (audit) | **Degrade**: continue with extract.py's mechanical checks only (M = mechanical failures); the report states "no upstream audit — call point unavailable". |
| 2 (rewrite) | **Abort, fail closed**: this is the pipeline's core. Stop with the file untouched; tell the user which skill is missing and the installed aaron-marketing version. |
| 3 (GEO) | **Degrade**: skip the GEO pass; note it in the report. |
| 4 (markup) | **Degrade**: skip head/markup output; note it under Template suggestions. |

Disposal of outputs:

- Call points 2–3 → `block_edits` / `insertions` in the EditPlan (one edit per block; merge when 2 and 3 touch the same block). Content is in the file's own format: HTML for `.html`, markdown for `.md`.
- Call point 4 → `meta_edits` for **HTML documents** (title + meta description) and **markdown with front matter** (front-matter `title`/`description`, missing keys added); everything else (OG/Twitter/JSON-LD/canonical — and for fragments / front-matter-less markdown, all of it) → the report's "Template suggestions" section as paste-ready values.

Dependency install (what Step 0 prints when the plugin is missing):

```
claude plugin marketplace add aaron-he-zhu/aaron-marketing-skills
claude plugin install aaron-marketing@aaron
```

(The GitHub Actions in this repo don't use the floating install above — they
clone upstream at the tag matching this playbook's baseline; see the
`aaron_version` input in `optimize/action.yml` / `pipeline/action.yml`.)
