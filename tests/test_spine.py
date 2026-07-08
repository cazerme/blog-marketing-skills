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
        self.assertTrue(os.path.exists(self.post + ".bak"))

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


if __name__ == "__main__":
    unittest.main()
