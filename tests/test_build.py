"""Tests for tools/build_atlas.py. Run with: python -m unittest discover tests"""
from __future__ import annotations

import json
import re
import unittest

from helpers import KitTestCase, atlas


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:      # Path.write_text has no newline= before 3.10
        f.write(text)


class ExampleRoadmap(KitTestCase):
    def test_example_has_no_errors(self):
        chk = self.check()
        self.assertEqual(chk.count("error"), 0, [i for i in chk.issues if i["severity"] == "error"])

    def test_page_is_one_self_contained_file(self):
        out = self.kit / "public" / "index.html"
        code, log = self.run_build("--out", str(out), "--title", "Avionics & Atlas")
        self.assertEqual(code, 0, log)
        page = out.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!doctype html>") or page.lower().startswith("<!doctype html>"))
        self.assertIn("<title>Avionics &amp; Atlas</title>", page)
        self.assertNotIn("__ATLAS_DATA__", page)
        self.assertNotIn("/*__ATLAS_FONTS__*/", page)
        self.assertIsNone(re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', page), "the page must not load anything from the network")
        data = json.loads(re.search(r'<script id="atlas-data" type="application/json">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(data["meta"]["title"], "Avionics & Atlas")
        self.assertEqual(len(data["tasks"]), len(self.notes("tasks")))

    def test_fragment_for_hosts_that_add_their_own_head(self):
        out = self.kit / "public" / "fragment.html"
        self.run_build("--out", str(out), "--fragment")
        self.assertTrue(out.read_text(encoding="utf-8").startswith("<title>"))

    def test_check_only_writes_nothing(self):
        code, log = self.run_build("--check")
        self.assertEqual(code, 0, log)
        self.assertFalse((self.kit / "public" / "index.html").exists())


class Checks(KitTestCase):
    def codes(self, **kw):
        return {i["code"] for i in self.check(**kw).issues}

    def test_broken_references_are_errors(self):
        tasks = self.kit / "roadmap" / "tasks"
        write(tasks / "ZZ-01 Orphan.md", "---\ntype: task\nid: ZZ-01\ntitle: Orphan\nparent: NOPE\nstatus: planned\n"
                                         "depends_on: [ZZ-01, GONE]\nmilestone: M99\n---\n")
        codes = self.codes()
        self.assertTrue({"E004", "E005", "E008"} <= codes, codes)
        code, log = self.run_build("--check")
        self.assertEqual(code, 1)

    def test_duplicate_ids_and_bad_values(self):
        tasks = self.kit / "roadmap" / "tasks"
        write(tasks / "Dup.md", "---\ntype: task\nid: CI-01\ntitle: Dup\nparent: CI\nstatus: planned\n---\n")
        write(tasks / "Odd.md", "---\ntype: task\nid: ODD-1\ntitle: Odd\nparent: CI\nstatus: blocked\ndal: [E]\n---\n")
        codes = self.codes()
        self.assertIn("E002", codes)
        self.assertIn("E007", codes)

    def test_dependency_loop(self):
        tasks = self.kit / "roadmap" / "tasks"
        write(tasks / "L1.md", "---\ntype: task\nid: L-1\ntitle: L1\nparent: CI\nstatus: planned\ndepends_on: [L-2]\n---\n")
        write(tasks / "L2.md", "---\ntype: task\nid: L-2\ntitle: L2\nparent: CI\nstatus: planned\ndepends_on: [L-1]\n---\n")
        self.assertIn("E006", self.codes())

    def test_estimate_units(self):
        tasks = self.kit / "roadmap" / "tasks"
        write(tasks / "E1.md", "---\ntype: task\nid: E-1\ntitle: E1\nparent: CI\nstatus: planned\nestimate: 4 h\n---\n")
        self.assertIn("W109", self.codes())
        self.assertNotIn("W109", self.codes(estimate_unit="hours"))

    def test_strict_fails_on_warnings(self):
        code, _log = self.run_build("--check", "--strict")
        self.assertEqual(code, 1 if self.check().count("warning") else 0)


class Frontmatter(unittest.TestCase):
    def parse(self, text):
        fm_text, body, first = atlas.split_note(text)
        return atlas.parse_frontmatter(fm_text, first), body

    def test_values(self):
        fm, body = self.parse('---\nid: X-1\nestimate: 2\ndal: [A, B]\ntitle: "Café \\"rota\\""\nexample: true\n'
                              'list:\n  - one\n  - two  # a comment\nempty:\n"key with spaces": v\nkey two: w\n---\nBody\n')
        self.assertEqual(fm["dal"], ["A", "B"])
        self.assertEqual(fm["title"], 'Café "rota"')
        self.assertIs(fm["example"], True)
        self.assertEqual(fm["list"], ["one", "two"])
        self.assertIsNone(fm["empty"])
        self.assertEqual((fm["key with spaces"], fm["key two"]), ("v", "w"))
        self.assertEqual(body.strip(), "Body")

    def test_windows_line_endings_and_bom(self):
        fm, body = self.parse("﻿---\r\nid: X-2\r\ntitle: T\r\n---\r\nLine\r\n")
        self.assertEqual((fm["id"], fm["title"]), ("X-2", "T"))
        self.assertEqual(body.strip(), "Line")

    def test_unicode_line_separator_is_not_a_line_break(self):
        fm, _body = self.parse("---\nid: X-3\ntitle: one two\n---\n")
        self.assertEqual(fm["title"], "one two")

    def test_links(self):
        self.assertEqual(atlas.clean_ref("[[CI-01 Runner|CI-01]]"), "CI-01 Runner")
        self.assertTrue(atlas.is_web("https://example.org"))
        self.assertFalse(atlas.is_web("javascript://x"))


if __name__ == "__main__":
    unittest.main()
