"""Tests for tools/build_atlas.py. Run with: python -m unittest discover tests"""
from __future__ import annotations

import json
import os
import re
import unittest
from unittest import mock

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

    def page_data(self, page: str) -> dict:
        return json.loads(re.search(r'<script id="atlas-data" type="application/json">(.*?)</script>', page, re.S).group(1))

    def test_note_text_cannot_end_the_data_script(self):
        nasty = 'Close </script><script>alert("x")</script> & <b>bold</b>'
        task = self.kit / "roadmap" / "tasks" / "CI-03 Nightly regression.md"
        write(task, task.read_text(encoding="utf-8").replace("Run the full", nasty + " Run the full"))
        out, js = self.kit / "public" / "index.html", self.kit / "public" / "atlas.json"
        code, log = self.run_build("--out", str(out), "--json", str(js))
        self.assertEqual(code, 0, log)
        page = out.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", page)
        data = self.page_data(page)
        self.assertIn(nasty, next(t for t in data["tasks"] if t["id"] == "CI-03")["description"])
        self.assertEqual(json.loads(js.read_text(encoding="utf-8"))["tasks"], data["tasks"])

    def test_source_date_epoch_makes_builds_identical(self):
        a, b = self.kit / "public" / "a.html", self.kit / "public" / "b.html"
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            codes = (self.run_build("--out", str(a))[0], self.run_build("--out", str(b))[0])
        self.assertEqual(codes, (0, 0))
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(self.page_data(a.read_text(encoding="utf-8"))["meta"]["generated"], "2023-11-14T22:13:20")
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "yesterday"}):
            code, log = self.run_build("--out", str(a))
        self.assertEqual(code, 2)
        self.assertIn("SOURCE_DATE_EPOCH", log)


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

    def test_warnings_and_notes(self):
        road = self.kit / "roadmap"
        write(road / "workstreams" / "Empty.md", "---\ntype: workstream\nid: EMPTY\nmap_hint: up\n---\n")      # W108, I202
        write(road / "tasks" / "W-1.md", "---\ntype: task\nid: W-1\nparent: CI\nstatus: in-progress\n---\n")    # W101, W102
        write(road / "tasks" / "W-2.md", "---\ntype: task\nid: W-2\nparent: CI\nstatus: done\nkind: template\n"
                                         "depends_on: [CI-03]\n---\n- [ ] Still open\n")                       # W103, W104, W106
        write(road / "tasks" / "W-3.md", "---\ntype: task\nid: W-3\nparent: CI\nstatus: review\nowner: Avery\n"
                                         "deliverable: library/guides/not-written-yet.md\n---\n- [x] Draft\n")  # W105
        write(road / "requests" / "REQ-90.md", "---\ntype: request\nid: REQ-90\nstatus: mapped\n---\n")         # W107
        codes = self.codes()
        expected = {"W101", "W102", "W103", "W104", "W105", "W106", "W107", "W108", "I201", "I202"}
        self.assertTrue(expected <= codes, sorted(expected - codes))

    def test_unreadable_notes_and_missing_ids(self):
        tasks = self.kit / "roadmap" / "tasks"
        write(tasks / "No id.md", "---\ntype: task\nparent: CI\nstatus: planned\n---\n")                      # E001
        write(tasks / "Odd type.md", "---\ntype: epic\nid: EP-1\n---\n")                                       # E003
        write(tasks / "Broken.md", "---\ntype: task\nthis line has no colon\n---\n")                          # E010
        (tasks / "Latin-1.md").write_bytes("---\ntype: task\nid: L-1\ntitle: Café\n---\n".encode("latin-1"))  # E010
        issues = self.check().issues
        codes = [i["code"] for i in issues]
        self.assertTrue({"E001", "E003"} <= set(codes), codes)
        self.assertEqual(codes.count("E010"), 2, issues)
        self.assertTrue(all(i["path"].startswith("roadmap/") for i in issues))

    def test_a_reference_to_the_wrong_kind_of_note_says_what_it_is(self):
        road = self.kit / "roadmap"
        write(road / "tasks" / "M-1.md", "---\ntype: task\nid: M-1\nparent: CI\nstatus: planned\nmilestone: CI-01\n---\n")
        write(road / "requests" / "REQ-91.md", "---\ntype: request\nid: REQ-91\nstatus: mapped\nmapped_to: CI\n---\n")
        messages = {i["code"]: i["message"] for i in self.check().issues if i["code"] in ("E008", "E009")}
        self.assertEqual(messages, {"E008": "milestone CI-01 is a task, not a milestone",
                                    "E009": "mapped_to CI is an area, not a task"})


class Deliverables(KitTestCase):
    def resolve(self, value):
        return atlas.resolve_deliverable(value, self.kit / "roadmap" / "tasks" / "X-1 Example.md", self.kit)

    def test_files_that_exist(self):
        write(self.kit / "library" / "guides" / "Spec [draft] v2.md", "Placeholder.\n")
        charter = "library/guides/team-charter.md"
        for value, path in {
            charter: charter,
            "team-charter": charter,                                    # a bare name is found anywhere in the vault
            "[[team-charter]]": charter,
            "[The charter](library/guides/team-charter.md)": charter,
            "../../library/guides/team-charter.md": charter,            # relative to the note
            "library\\guides\\team-charter.md": charter,                # written on Windows: the same on Linux CI
            "Spec [draft] v2": "library/guides/Spec [draft] v2.md",     # brackets are just characters
        }.items():
            d = self.resolve(value)
            self.assertEqual((d.get("path"), d.get("exists")), (path, True), value)

    def test_files_that_dont_exist_yet(self):
        for value, path in {
            "*": "*",                                                   # not a pattern: it matches no file
            "./library/not-yet.md": "library/not-yet.md",
            "../library/not-yet.md": "roadmap/library/not-yet.md",      # where that is, from the note's folder
            ".config/not-yet.md": ".config/not-yet.md",
        }.items():
            d = self.resolve(value)
            self.assertEqual((d.get("path"), d.get("exists")), (path, False), value)

    def test_links_and_text(self):
        self.assertEqual(self.resolve("https://example.org/guide")["url"], "https://example.org/guide")
        text = "Document control: FPGA coding standard, issue 2"
        self.assertEqual(self.resolve(text), {"label": text, "text": text})


class Body(unittest.TestCase):
    def test_checkboxes_in_code_blocks_are_only_examples(self):
        body = ("Intro.\n\n```markdown\n- [ ] In a backtick block\n~~~\n- [ ] Still in it: a tilde line doesn't close it\n"
                "```\n~~~~\n- [ ] In a tilde block\n~~~\n- [ ] Still in it: a shorter fence doesn't close it\n~~~~\n"
                "- [x] Real one\n- [/] Another\n")
        _desc, subs = atlas.split_body(body)
        self.assertEqual([(s["text"], s["state"]) for s in subs], [("Real one", "done"), ("Another", "doing")])


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
