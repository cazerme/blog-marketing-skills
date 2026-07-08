"""Markdown-mode tests: Jekyll-style posts with front matter, plus
plain markdown without front matter.

Run with:  python3 -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "blog-seo-geo", "scripts")
JEKYLL = os.path.join(ROOT, "tests", "fixtures", "jekyll-post.md")
PLAIN = os.path.join(ROOT, "tests", "fixtures", "plain-post.md")


def run(script, *args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True)


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.md")
        shutil.copy(JEKYLL, self.post)
        self.model_path = os.path.join(self.dir, "model.json")
        r = run("extract.py", self.post, "--out", self.model_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.model_path) as f:
            self.model = json.load(f)
        self.checks = {c["id"]: c for c in self.model["mechanical"]["checks"]}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def plan(self, **kwargs):
        p = os.path.join(self.dir, "plan.json")
        with open(p, "w") as f:
            json.dump({"source_sha256": self.model["source_sha256"], **kwargs}, f)
        return p

    def original(self):
        with open(JEKYLL) as f:
            return f.read()

    def current(self):
        with open(self.post) as f:
            return f.read()

    def by_tag(self, tag):
        return [b for b in self.model["blocks"] if b["tag"] == tag]

    def test_detected_as_markdown_with_frontmatter(self):
        self.assertEqual(self.model["format"], "markdown")
        self.assertEqual(self.model["doc_kind"], "markdown")
        self.assertTrue(self.model["head"]["frontmatter_present"])
        self.assertEqual(self.model["head"]["title"]["text"], "Desert hikes")
        self.assertIn("tags", self.model["head"]["complex_keys"])

    def test_code_fence_protected(self):
        codes = self.by_tag("code")
        self.assertEqual(len(codes), 1)
        self.assertFalse(codes[0]["editable"])
        self.assertIn("curl -s", codes[0]["html"])
        # the fake heading inside the fence must not become a heading block
        self.assertFalse(any("fake heading" in b["text"] for b in self.model["blocks"]
                             if b["tag"].startswith("h")))
        # the fake link inside the fence must not join the link inventory
        self.assertNotIn("https://fake.example/x",
                         {l["href"] for l in self.model["links"]})
        self.assertIn("https://www.nps.gov/index.htm",
                      {l["href"] for l in self.model["links"]})

    def test_planted_issues_found(self):
        self.assertEqual(self.checks["title"]["status"], "warn")           # 12 chars
        self.assertEqual(self.checks["meta_description"]["status"], "fail")
        self.assertEqual(self.checks["heading_order"]["status"], "warn")   # h2 -> h4
        self.assertEqual(self.checks["img_alt"]["status"], "fail")
        self.assertEqual(self.checks["canonical"]["status"], "skipped")
        self.assertEqual(self.checks["jsonld"]["status"], "skipped")
        self.assertEqual(self.checks["h1_unique"]["status"], "pass")       # fm title = h1

    def test_protected_zones_non_editable(self):
        for tag in ("table", "html", "hr", "img", "code"):
            for b in self.by_tag(tag):
                self.assertFalse(b["editable"], "%s should be non-editable" % tag)
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": self.by_tag("html")[0]["id"],
                                        "new_content": "edited"}]), "--write")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.current(), self.original())

    def test_empty_plan_roundtrip_byte_identical(self):
        r = run("reassemble.py", self.post, self.plan(), "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.current(), self.original())

    def test_heading_edit_preserves_hash_prefix(self):
        h2 = next(b for b in self.by_tag("h2") if "water math" in b["text"])
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": h2["id"],
                                        "new_content": "Why water math matters on desert trails"}]),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("## Why water math matters on desert trails", self.current())
        expected = (self.original()[:h2["inner_span"][0]]
                    + "Why water math matters on desert trails"
                    + self.original()[h2["inner_span"][1]:])
        self.assertEqual(self.current(), expected)

    def test_meta_edits_update_frontmatter(self):
        r = run("reassemble.py", self.post,
                self.plan(meta_edits={
                    "title": "Desert Hiking Water Math: How Much to Carry",
                    "meta_description": "How much water desert hiking takes — the "
                                        "liter-per-two-miles rule, electrolytes, and gear."}),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cur = self.current()
        self.assertIn('title: "Desert Hiking Water Math: How Much to Carry"', cur)
        self.assertIn('description: "How much water desert hiking takes', cur)
        # description inserted inside the front matter, not the body
        self.assertLess(cur.index("description:"), cur.index("Desert hiking rewards"))
        rep = json.loads(r.stdout)
        self.assertGreater(rep["mechanical_after"], rep["mechanical_before"])

    def test_link_dropping_edit_rejected(self):
        b = next(b for b in self.by_tag("p") if "/blog/trail-nutrition" in b["html"])
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": b["id"],
                                        "new_content": "Plain water alone is not enough."}]),
                "--write")
        self.assertEqual(r.returncode, 6)
        self.assertIn("links lost", r.stdout)
        self.assertEqual(self.current(), self.original())

    def test_insertion_gets_blank_line_separation(self):
        b = self.by_tag("blockquote")[0]
        r = run("reassemble.py", self.post,
                self.plan(insertions=[{"after_block_id": b["id"],
                                       "html": "### Quick answer"}]),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("hikes early.\n\n### Quick answer\n\n", self.current())


class IndentedCodeTest(unittest.TestCase):
    """Classic 4-space indented code blocks must be non-editable, while
    indented lines directly after paragraph text remain lazy continuation."""

    MD = """# Indented code fixture

Intro paragraph explaining the setup steps below in enough words to matter.

    pip install requests
    python fetch.py --all
    # not a heading: [not a link](https://fake.example/y)

Text after the code block continues here
    with a lazily indented continuation line that stays part of the paragraph.

Closing paragraph so the document keeps more than one editable block.
"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.md")
        with open(self.post, "w") as f:
            f.write(self.MD)
        self.model_path = os.path.join(self.dir, "model.json")
        r = run("extract.py", self.post, "--out", self.model_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.model_path) as f:
            self.model = json.load(f)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_indented_block_is_protected_code(self):
        codes = [b for b in self.model["blocks"] if b["tag"] == "code"]
        self.assertEqual(len(codes), 1)
        self.assertFalse(codes[0]["editable"])
        self.assertIn("pip install requests", codes[0]["html"])
        self.assertFalse(any("not a heading" in b["text"] for b in self.model["blocks"]
                             if b["tag"].startswith("h")))
        self.assertNotIn("https://fake.example/y",
                         {l["href"] for l in self.model["links"]})

    def test_lazy_continuation_stays_paragraph(self):
        p = next(b for b in self.model["blocks"]
                 if b["tag"] == "p" and "Text after the code block" in b["text"])
        self.assertTrue(p["editable"])
        self.assertIn("lazily indented continuation", p["text"])

    def test_editing_indented_code_rejected(self):
        code = next(b for b in self.model["blocks"] if b["tag"] == "code")
        p = os.path.join(self.dir, "plan.json")
        with open(p, "w") as f:
            json.dump({"source_sha256": self.model["source_sha256"],
                       "block_edits": [{"block_id": code["id"], "new_content": "x"}]}, f)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "reassemble.py"),
                            self.post, p, "--write"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 5)
        with open(self.post) as f:
            self.assertEqual(f.read(), self.MD)


class PlainMarkdownTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.md")
        shutil.copy(PLAIN, self.post)
        self.model_path = os.path.join(self.dir, "model.json")
        r = run("extract.py", self.post, "--out", self.model_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.model_path) as f:
            self.model = json.load(f)
        self.checks = {c["id"]: c for c in self.model["mechanical"]["checks"]}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_no_frontmatter_head_checks_skipped(self):
        self.assertFalse(self.model["head"]["frontmatter_present"])
        self.assertEqual(self.checks["title"]["status"], "skipped")
        self.assertEqual(self.checks["meta_description"]["status"], "skipped")
        self.assertEqual(self.checks["h1_unique"]["status"], "pass")  # body h1, no fm title

    def test_meta_edits_rejected_without_frontmatter(self):
        p = os.path.join(self.dir, "plan.json")
        with open(p, "w") as f:
            json.dump({"source_sha256": self.model["source_sha256"],
                       "meta_edits": {"title": "New"}}, f)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "reassemble.py"),
                            self.post, p, "--write"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 5)
        self.assertIn("no front matter", r.stdout)


if __name__ == "__main__":
    unittest.main()
