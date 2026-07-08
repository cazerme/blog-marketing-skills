"""Fragment-mode tests: body-only HTML (no <head>), as produced by
template-driven blogs (server-rendered or SSG).

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
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "fragment-post.html")

HEAD_LEVEL_CHECKS = {"title", "meta_description", "canonical", "jsonld",
                     "h1_unique", "kw_title", "kw_h1"}


def run(script, *args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True)


class FragmentTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.post = os.path.join(self.dir, "post.html")
        shutil.copy(FIXTURE, self.post)
        self.model_path = os.path.join(self.dir, "model.json")
        r = run("extract.py", self.post, "--out", self.model_path,
                "--keyword", "desert hiking water")
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
        with open(FIXTURE) as f:
            return f.read()

    def current(self):
        with open(self.post) as f:
            return f.read()

    def test_detected_as_fragment(self):
        self.assertEqual(self.model["doc_kind"], "fragment")

    def test_head_level_checks_skipped_and_unweighted(self):
        for cid in HEAD_LEVEL_CHECKS & set(self.checks):
            self.assertEqual(self.checks[cid]["status"], "skipped", cid)
            self.assertEqual(self.checks[cid]["weight"], 0, cid)

    def test_body_checks_still_scored(self):
        self.assertEqual(self.checks["img_alt"]["status"], "pass")
        self.assertIn(self.checks["kw_opening"]["status"], ("pass", "fail"))
        self.assertNotEqual(self.checks["word_count"]["status"], "skipped")
        self.assertGreater(self.model["mechanical"]["score"], 0)

    def test_blocks_indexed_like_documents(self):
        tags = [b["tag"] for b in self.model["blocks"]]
        for expected in ("p", "h2", "h3", "h4", "ol", "ul", "img"):
            self.assertIn(expected, tags)
        self.assertTrue(all(not b["editable"] for b in self.model["blocks"]
                            if b["tag"] == "img"))

    def test_fragment_block_edit_is_byte_exact(self):
        b = next(b for b in self.model["blocks"]
                 if b["editable"] and b["tag"] == "p" and "<a " not in b["html"])
        r = run("reassemble.py", self.post,
                self.plan(block_edits=[{"block_id": b["id"],
                                        "new_inner_html": "Rewritten fragment paragraph."}]),
                "--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        expected = (self.original()[:b["inner_span"][0]]
                    + "Rewritten fragment paragraph."
                    + self.original()[b["inner_span"][1]:])
        self.assertEqual(self.current(), expected)

    def test_meta_edits_rejected_on_fragment(self):
        r = run("reassemble.py", self.post,
                self.plan(meta_edits={"title": "New Title",
                                      "meta_description": "New description."}),
                "--write")
        self.assertEqual(r.returncode, 5)
        self.assertIn("no <title>", r.stdout)
        self.assertIn("no <head>", r.stdout)
        self.assertEqual(self.current(), self.original())


if __name__ == "__main__":
    unittest.main()
