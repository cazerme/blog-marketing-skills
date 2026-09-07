# aaron-marketing call-point playbook

The single place that tracks every aaron-marketing sub-skill this plugin
invokes. When upstream aaron-marketing releases a new major version, re-verify
each row here (names, modes, expected outputs) — nothing else in this repo
talks to aaron-marketing.

**Tested against: aaron-marketing 20.1.0.** These are natural-language
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

Call-point notes (verified against 19.1.0):

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
- **19.0.0 re-verification** — upstream's 19.0.0 release is a "runtime and
  distribution simplification" only: its own changelog states "no skill was
  added, removed, merged, or renamed," and all four `SKILL.md` files here are
  byte-identical between 18.0.0 and 19.0.0 except the `version` field. No
  contract, mode, or path changes to absorb.
- **19.1.0 re-verification** — upstream's 19.1.0 release ("progressive context
  disclosure and host-aware harnessing") is a version-only bump for three of
  the four call points: `content-writer`, `serp-markup-builder`, and
  `on-page-seo-checker`'s `SKILL.md` are byte-identical between 19.0.0 and
  19.1.0 except the `version` field, and no skill was added, removed, merged,
  or renamed. **3**'s `geo-content-optimizer/SKILL.md` also has no contract
  change, but its linked `references/ai-citation-patterns.md` was rewritten:
  it now documents per-provider crawler/retrieval controls sourced from each
  provider's own docs instead of citation-count/lift-percentage claims, folds
  Bing into a "Bing-backed Copilot Studio" surface, and drops Grok as a
  covered engine. This is deeper editorial background for the sub-skill, not
  a change to what it expects as input or promises as output — no call-point
  edit needed.
- **Tag anomaly** — upstream never cut a `v19.1.0` git tag (`gh api
  repos/aaron-he-zhu/aaron-marketing-skills/tags` lists `v19.0.0` then jumps to
  `v19.2.0`), even though `VERSIONS.md` documents a `19.1.0` "Progressive
  context disclosure and host-aware harnessing" release dated 2026-08-01. The
  19.1.0 bullet above (already in this file pre-rebaseline) was verified
  against that changelog entry plus a `v19.0.0` vs `v19.2.0` diff, which
  isolates the 19.1.0-only change to exactly the `geo-content-optimizer`
  reference rewrite described above — nothing else moved between those two
  tags. Not a call-point problem, just a note for whoever runs the next
  rebaseline: don't expect `git checkout v19.1.0` to work.
- **19.2.0 re-verification** — release theme is "Agent Plugins v1 Portable
  Lite delivery" (a release-projection/packaging change: a stricter Agent
  Plugins 1.0.0 output directory, no automatic MCP registration). All four
  call points' `SKILL.md` files are byte-identical to `v19.0.0` except the
  `version` field; no skill added, removed, merged, or renamed. No call-point
  edit needed.
- **20.0.0 re-verification** — release theme is "AI Staff positioning" (a
  branding/README change: named-bot roster becomes a first-class install
  surface, chief bot handle shortens to `aaron-chief`). All four call points'
  `SKILL.md` files are byte-identical to `v19.2.0` except the `version` field.
  No call-point edit needed.
- **20.1.0 re-verification** — release theme is "Cross-discipline control
  plane": 49 execution/measurement-heavy skills across the whole bundle adopt
  a shared typed artifact protocol (evidence records, page/change bindings,
  measurement contracts, index-submission receipts, cycle retros — see
  `seo-geo/evaluate/performance-monitor/references/evidence-and-cycle-control.md`).
  `on-page-seo-checker`, `geo-content-optimizer`, and `serp-markup-builder`
  are byte-identical to `v20.0.0` except the `version` field — not among the
  49. **2**'s `content-writer` picked up additive changes in **refresh mode
  only**, confirmed non-blocking:
  - `Reads` now also lists "stable page ref, prior content version/hash,
    change ref" — phrased alongside the other already-optional refresh
    inputs (traffic history, publish dates, competitor examples), and the
    skill's own Decision Gates still say to continue silently on missing
    analytics/history. Nothing new to feed; this pipeline has no page
    registry or prior-version hash to offer, and the skill doesn't gate on
    their absence.
  - `Done when` now additionally reports `page_ref`, `content_version`,
    `content_sha256`, and `change_ref` in the handoff summary, alongside the
    pre-existing `narrative_canon_id` / `narrative_canon_version` /
    `claims_projection_offset` / `dependency_status`. Purely additive output
    — ignore the extra fields, same as we already ignore the narrative/claims
    ones.
  - The "Publish-time index push" guidance (indexnow/baidu submission) now
    requires binding the intent to an exact `content_sha256` and treating
    only an actual provider/HTTP response as a receipt. This pipeline never
    invokes that index-push path (no live publish step here), so it's
    inert for this call point.
  No call-point edit needed for **1**, **3**, or **4**.

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
