# blog-marketing-skills

Claude Code skills that optimize blog posts for **SEO** (Google rankings) and **GEO** (getting cited by AI engines like Gemini). Built on top of the open-source [aaron-marketing](https://github.com/aaron-he-zhu/aaron-marketing-skills) skill pack: this plugin orchestrates its auditing/writing skills and adds a deterministic, fail-closed engine for safely editing your HTML files in place.

> **Status: v0.1 — minimal working loop.** One skill, `blog-seo-geo`. See [Scope](#scope-v01) for exactly what it does and refuses to do.

## What it does

```
/blog-marketing:blog-seo-geo path/to/post.html [target keyword]
```

1. Parses your post into content blocks and runs deterministic mechanical checks (title/meta, heading structure, alt text, links…) → baseline score
2. Diagnoses it with `aaron-marketing:on-page-seo-auditor`
3. Rewrites content blocks with `aaron-marketing:content-writer` (refresh mode) — facts, links and images are preserved; nothing is invented
4. Writes the file back **safely**: `.bak` backup first, then an atomic write that is refused entirely if any link/image/structure would be lost (fail-closed)
5. Emits `post.seo-report.md` next to your file: keyword rationale, what changed and why, resolved issues, mechanical score before/after

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

## Scope (v0.1)

| | |
|---|---|
| ✅ Input | A **local, static HTML file** whose article content is in the file (hand-written HTML, Hugo/Jekyll/SSG output, server-rendered pages committed to your repo) |
| ✅ Output | The same file, optimized in place + `<name>.seo-report.md` + `<name>.html.bak` backup |
| ✅ Language / engines | English content; SEO for Google, GEO for Gemini-style AI citation |
| ❌ Live URLs | Not supported: there is no "original file" to write back to. Edit the source file in your repo, then deploy |
| ❌ SPA shells / build artifacts | Refused with an explanation — the right edit target is your content source, not compiled output |
| ❌ Technical SEO | Crawling, sitemaps, Core Web Vitals are site-level concerns, out of scope |

## Safety guarantees

- **Write whitelist**: only your input file (after a `.bak` backup), the report file, and temp files. Nothing else is touched.
- **Fail-closed**: unknown blocks, lost links/images, structural damage, or the file changing mid-run ⇒ the plan is rejected and **nothing is written**.
- **Byte-exact splicing**: unedited regions of your HTML are byte-identical by construction — the document is never re-serialized.
- **No fabrication**: rewrites reorganize and tighten what the post already says; new facts, stats, or claims are out of bounds.
- Scripts are Python stdlib only — no pip installs, no network access.

## Roadmap

Fragment-mode input (posts without `<head>`, meta suggestions go to the report), GEO rewrite pass (`geo-content-optimizer` + `serp-markup-builder` for FAQ blocks and JSON-LD), Markdown input, URL read-only audits.

## Development

```
python3 -m unittest discover tests    # engine round-trip + fail-closed suite
claude plugin validate .              # manifest check
```

## License

MIT. Tested against aaron-marketing 16.1.0.
