# blog-marketing-skills

Claude Code skills that optimize blog posts for **SEO** (Google rankings) and **GEO** (getting cited by AI engines like Gemini). Built on top of the open-source [aaron-marketing](https://github.com/aaron-he-zhu/aaron-marketing-skills) skill pack: this plugin orchestrates its auditing/writing skills and adds a deterministic, fail-closed engine for safely editing your HTML or Markdown files in place.

> **Status: v0.3.** One skill, `blog-seo-geo`. See [Scope](#scope-v03) for exactly what it does and refuses to do.

## What it does

```
/blog-marketing:blog-seo-geo path/to/post.html [target keyword]
/blog-marketing:blog-seo-geo posts/2026-07-08-my-post.md [target keyword]
```

1. Parses your post into content blocks and runs deterministic mechanical checks (title/meta, heading structure, alt text, links…) → baseline score
2. Diagnoses it with `aaron-marketing:on-page-seo-auditor`
3. Rewrites content blocks with `aaron-marketing:content-writer` (refresh mode) — facts, links and images are preserved; nothing is invented
4. Runs a **GEO pass** with `aaron-marketing:geo-content-optimizer`: makes key passages quotable by AI engines (Gemini-style citation) and adds answer/FAQ blocks where warranted — restating only what the post already says
5. Builds head markup with `aaron-marketing:serp-markup-builder`: title + meta description are applied to full HTML documents and to markdown front matter; OG/Twitter/JSON-LD land in the report as paste-ready template suggestions
6. Writes the file back **safely**: `.bak` backup first, then an atomic write that is refused entirely if any link/image/structure would be lost (fail-closed)
7. Emits `post.seo-report.md` next to your file: keyword rationale, what changed and why, resolved issues, mechanical score before/after, template suggestions

### Markdown blogs (Jekyll / Hugo / GitHub Pages)

`.md` posts are first-class input. Front-matter `title:` and `description:` are treated as the post's head: checked, and **edited in place** (missing keys are added to existing front matter). Body optimization works exactly as for HTML — and the parser hard-protects what a rewrite must never touch: **code fences, embedded raw HTML, tables, thematic breaks**. Complex front-matter values (nested lists, multiline) are left alone. Posts without front matter get the fragment treatment below.

### Fragment mode (template-driven blogs)

If your posts are **body fragments** (no `<html>/<head>` — a server or SSG injects them into a page template, e.g. Flask/Jinja/Hugo partials), the skill detects this automatically: body optimization is applied to the fragment file as usual, while every head-level item (title, meta description, canonical, OG/Twitter, JSON-LD) is delivered in the report as paste-ready values with a pointer to where they belong (your template / post registry). Head-level mechanical checks are marked `skipped` instead of failing — they score against your template, not your fragment.

## Install

Requires [Claude Code](https://claude.com/claude-code) and the aaron-marketing plugin:

```
claude plugin marketplace add aaron-he-zhu/aaron-marketing-skills
claude plugin install aaron-marketing@aaron

claude plugin marketplace add cazerme/blog-marketing-skills
claude plugin install blog-marketing@blog-marketing-skills
```

Then, inside your blog project:

```
/blog-marketing:blog-seo-geo posts/my-post.html
```

Try it on the bundled sample first: copy `examples/sample-post.html` somewhere and run the command on it.

## Scope (v0.3)

| | |
|---|---|
| ✅ Input | A **local HTML or Markdown file** whose article content is in the file — full HTML documents, body fragments, or `.md` posts with YAML front matter (hand-written HTML, Jekyll/Hugo/GitHub Pages sources, server-rendered pages committed to your repo) |
| ✅ Output | The same file, optimized in place + `<name>.seo-report.md` + `.bak` backup; head-level items for fragments/front-matter-less markdown go to the report, never guessed into the file |
| ✅ Language / engines | English content; SEO for Google, GEO for Gemini-style AI citation |
| ❌ Live URLs | Not supported: there is no "original file" to write back to. Edit the source file in your repo, then deploy |
| ❌ SPA shells / build artifacts | Refused with an explanation — the right edit target is your content source, not compiled output |
| ❌ Technical SEO | Crawling, sitemaps, Core Web Vitals are site-level concerns, out of scope |

## Safety guarantees

- **Write whitelist**: only your input file (after a `.bak` backup), the report file, and temp files. Nothing else is touched.
- **Fail-closed**: unknown blocks, lost links/images, structural damage, or the file changing mid-run ⇒ the plan is rejected and **nothing is written**.
- **Byte-exact splicing**: unedited regions of your file are byte-identical by construction — the document is never re-serialized. In markdown, code fences and embedded HTML are structurally non-editable.
- **No fabrication**: rewrites reorganize and tighten what the post already says; new facts, stats, or claims are out of bounds.
- Scripts are Python stdlib only — no pip installs, no network access.

## Roadmap

URL read-only audits, head-markup injection for full documents (OG/Twitter/JSON-LD blocks), image `alt` editing, MDX/setext-heading editability, opt-in secondary write targets (e.g. `--meta-target` for a post registry file).

## Development

```
python3 -m unittest discover tests    # engine round-trip + fail-closed suite
claude plugin validate .              # manifest check
```

## License

MIT. Tested against aaron-marketing 16.1.0.
