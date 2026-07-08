"""Round-trip and fail-closed tests for extract.py / reassemble.py.

Run with:  python3 -m unittest discover tests
Stdlib only — no third-party test dependencies.
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
SAMPLE = os.path.join(ROOT, "examples", "sample-post.html")


def run(script, *args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True)


class SpineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.html")
        shutil.copy(SAMPLE, self.post)
        self.model_path = os.path.join(self.dir, "model.json")
        r = run("extract.py", self.post, "--out", self.model_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.model_path) as f:
            self.model = json.load(f)
        self.sha = self.model["source_sha256"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def plan(self, **kwargs):
        p = os.path.join(self.dir, "plan.json")
        with open(p, "w") as f:
            json.dump({"source_sha256": self.sha, **kwargs}, f)
        return p

    def original(self):
        with open(SAMPLE) as f:
            return f.read()

    def current(self):
        with open(self.post) as f:
            return f.read()

    def block_with_link(self):
        return next(b for b in self.model["blocks"] if "<a " in b["html"])

    def test_extract_finds_planted_issues(self):
        failing = {c["id"] for c in self.model["mechanical"]["checks"]
                   if c["status"] != "pass"}
        for expected in ("title", "meta_description", "heading_order", "img_alt"):
            self.assertIn(expected, failing)
        self.assertEqual(self.model["doc_kind"], "document")
        self.assertGreater(self.model["stats"]["editable_count"], 5)

    def test_empty_plan_roundtrip_is_byte_identical(self):
        r = run("reassemble.py", self.post, self.plan(), "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.current(), self.original())
        self.assertTrue(json.loads(r.stdout)["identical"])

    def backup_dir(self):
        return os.path.join(self.dir, ".seo-optimizer", "backups")

    def test_single_edit_touches_only_that_span(self):
        b = next(b for b in self.model["blocks"]
                 if b["editable"] and "<a " not in b["html"] and b["tag"] == "p")
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": b["id"],
                                        "new_inner_html": "Replaced paragraph for the span test."}]),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        expected = (self.original()[:b["inner_span"][0]]
                    + "Replaced paragraph for the span test."
                    + self.original()[b["inner_span"][1]:])
        self.assertEqual(self.current(), expected)
        self.assertTrue(os.path.exists(os.path.join(self.backup_dir(), "post.html.original")))

    def test_double_run_never_loses_the_first_original(self):
        ps = [b for b in self.model["blocks"]
              if b["editable"] and "<a " not in b["html"] and b["tag"] == "p"]
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": ps[0]["id"],
                                        "new_content": "First optimization pass output."}]),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # second run against the new file state (fresh extract for a fresh sha)
        model2_path = os.path.join(self.dir, "model2.json")
        r = run("extract.py", self.post, "--out", model2_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(model2_path) as f:
            sha2 = json.load(f)["source_sha256"]
        plan2 = os.path.join(self.dir, "plan2.json")
        with open(plan2, "w") as f:
            json.dump({"source_sha256": sha2,
                       "block_edits": [{"block_id": ps[1]["id"],
                                        "new_content": "Second optimization pass output."}]}, f)
        r = run("reassemble.py", self.post, plan2, "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # the first-ever original must still be the untouched fixture bytes
        with open(os.path.join(self.backup_dir(), "post.html.original")) as f:
            self.assertEqual(f.read(), self.original())
        snapshots = [f for f in os.listdir(self.backup_dir())
                     if not f.endswith(".original")]
        self.assertGreaterEqual(len(snapshots), 2)
        self.assertIn("First optimization pass output.", self.current())
        self.assertIn("Second optimization pass output.", self.current())

    def test_unknown_block_id_rejected_file_untouched(self):
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": "b999", "new_inner_html": "x"}]),
                "--write")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.current(), self.original())

    def test_link_dropping_edit_rejected_file_untouched(self):
        b = self.block_with_link()
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": b["id"],
                                        "new_inner_html": "No more link here."}]),
                "--write")
        self.assertEqual(r.returncode, 6)
        self.assertIn("links lost", r.stdout)
        self.assertEqual(self.current(), self.original())

    def test_stale_sha_rejected(self):
        p = self.plan(block_edits=[])
        with open(self.post, "a") as f:
            f.write("\n<!-- drifted -->\n")
        r = run("reassemble.py", self.post, p, "--write")
        self.assertEqual(r.returncode, 4)

    def test_meta_description_insertion_and_score_improves(self):
        r = run("reassemble.py", self.post,
                self.plan(meta_edits={"meta_description":
                    "A practical camping packing list covering shelter, sleeping "
                    "gear, cooking, water, clothing and safety essentials."}),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = json.loads(r.stdout)
        self.assertGreater(rep["mechanical_after"], rep["mechanical_before"])
        self.assertIn('<meta name="description"', self.current())

    def test_uneditable_block_rejected(self):
        img = next(b for b in self.model["blocks"] if b["tag"] == "img")
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": img["id"], "new_inner_html": "x"}]),
                "--write")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.current(), self.original())


class NumberGuardTest(unittest.TestCase):
    """Fabrication guard: numbers a rewrite introduces must already exist in
    the original document; integers 0-10 are exempt (word-to-digit rewrites)."""

    HTML = """<!DOCTYPE html>
<html><head><title>Number guard fixture page for the engine tests</title>
<meta name="description" content="A fixture with real statistics so the number fabrication guard has something concrete to verify against.">
</head><body><article>
<h1>Our eight test campaigns, measured</h1>
<p>Across all campaigns we sent 1,533,399 messages and saw a 1.24% response rate overall.</p>
<p>The best campaign converted at 4.5% while the median stayed near the overall figure.</p>
<p>A closing paragraph so several editable blocks exist for the tests below.</p>
</article></body></html>
"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.html")
        with open(self.post, "w") as f:
            f.write(self.HTML)
        r = run("extract.py", self.post, "--out", os.path.join(self.dir, "m.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "m.json")) as f:
            self.model = json.load(f)
        self.paras = [b for b in self.model["blocks"] if b["tag"] == "p"]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def apply(self, **kwargs):
        p = os.path.join(self.dir, "plan.json")
        with open(p, "w") as f:
            json.dump({"source_sha256": self.model["source_sha256"], **kwargs}, f)
        return run("reassemble.py", self.post, p, "--write")

    def test_fabricated_number_refused(self):
        r = self.apply(block_edits=[{"block_id": self.paras[2]["id"],
                                     "new_content": "Studies show 95% of campaigns fail."}])
        self.assertEqual(r.returncode, 5)
        self.assertIn("fabricated or altered number '95'", r.stdout)
        with open(self.post) as f:
            self.assertEqual(f.read(), self.HTML)

    def test_digit_transposition_refused(self):
        r = self.apply(block_edits=[{"block_id": self.paras[0]["id"],
                                     "new_content": "We saw a 1.42% response rate overall."}])
        self.assertEqual(r.returncode, 5)
        self.assertIn("'1.42'", r.stdout)

    def test_restating_existing_numbers_across_blocks_passes(self):
        r = self.apply(block_edits=[{"block_id": self.paras[2]["id"],
                                     "new_content": "In short: 1,533,399 messages, a 1.24% response rate, and a 4.5% best case."}])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_comma_variant_of_existing_number_passes(self):
        r = self.apply(block_edits=[{"block_id": self.paras[2]["id"],
                                     "new_content": "That is 1533399 messages in total."}])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_small_integer_word_to_digit_passes(self):
        r = self.apply(block_edits=[{"block_id": self.paras[2]["id"],
                                     "new_content": "All 8 campaigns are covered above."}])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_fabricated_number_in_meta_refused(self):
        r = self.apply(meta_edits={"meta_description":
            "See how 72% of senders get replies with these campaign statistics."})
        self.assertEqual(r.returncode, 5)
        self.assertIn("'72'", r.stdout)


class CaptureRatioTest(unittest.TestCase):
    """Coverage honesty: content the parser cannot classify (e.g. <dl>) must
    surface as a capture warning instead of a silently partial diagnosis."""

    HALF_INVISIBLE = """<!DOCTYPE html>
<html><head><title>Capture ratio fixture page for engine tests</title></head>
<body><article>
<h1>Visible half</h1>
<p>Short visible paragraph.</p>
<dl>
<dt>Invisible term one</dt><dd>A long definition body that the parser has no rule for, so it never becomes a block and stays entirely outside the model's view of this article.</dd>
<dt>Invisible term two</dt><dd>Another long definition body, also unindexed, further inflating the amount of visible text that the block list fails to capture for this page.</dd>
</dl>
</article></body></html>
"""

    def _model_for(self, html):
        d = tempfile.mkdtemp()
        try:
            post = os.path.join(d, "post.html")
            with open(post, "w") as f:
                f.write(html)
            r = run("extract.py", post, "--out", os.path.join(d, "m.json"))
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(d, "m.json")) as f:
                return json.load(f)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_dl_heavy_page_warns(self):
        m = self._model_for(self.HALF_INVISIBLE)
        self.assertLess(m["stats"]["capture_ratio"], 0.7)
        checks = {c["id"]: c for c in m["mechanical"]["checks"]}
        self.assertEqual(checks["capture"]["status"], "warn")
        self.assertEqual(checks["capture"]["weight"], 0)

    def test_normal_page_passes(self):
        with open(SAMPLE) as f:
            m = self._model_for(f.read().replace("</body>", "</body>"))
        self.assertGreaterEqual(m["stats"]["capture_ratio"], 0.9)
        checks = {c["id"]: c for c in m["mechanical"]["checks"]}
        self.assertEqual(checks["capture"]["status"], "pass")


class ArticleHeaderTest(unittest.TestCase):
    """Regression: an <h1> inside <article><header> is post content, not site
    chrome (found on a real production page). A site-level <header> outside
    <article>/<main> must still be skipped."""

    HTML = """<!DOCTYPE html>
<html><head><title>Article header regression fixture page</title>
<meta name="description" content="A fixture proving article-scoped headers are indexed while site headers stay skipped for the engine.">
</head><body>
<header><nav><a href="/">Home</a></nav><p>site tagline — must stay invisible</p></header>
<article>
<header>
<h1>The Real Post Title Lives Here</h1>
<p>Posted on a Tuesday.</p>
</header>
<p>Body paragraph with enough words to count as content for the test.</p>
</article>
</body></html>
"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.html")
        with open(self.post, "w") as f:
            f.write(self.HTML)
        r = run("extract.py", self.post, "--out", os.path.join(self.dir, "m.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.dir, "m.json")) as f:
            self.model = json.load(f)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_article_header_h1_is_indexed(self):
        h1s = [b for b in self.model["blocks"] if b["tag"] == "h1"]
        self.assertEqual(len(h1s), 1)
        self.assertEqual(h1s[0]["text"], "The Real Post Title Lives Here")
        self.assertTrue(h1s[0]["editable"])
        checks = {c["id"]: c for c in self.model["mechanical"]["checks"]}
        self.assertEqual(checks["h1_unique"]["status"], "pass")

    def test_site_header_still_skipped(self):
        texts = " ".join(b["text"] for b in self.model["blocks"])
        self.assertNotIn("site tagline", texts)


if __name__ == "__main__":
    unittest.main()
