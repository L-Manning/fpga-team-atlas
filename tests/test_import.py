"""Tests for tools/import_roadmap.py. Run with: python -m unittest discover tests"""
from __future__ import annotations

import unittest

from helpers import KitTestCase, atlas


class OneTaskPerRow(KitTestCase):
    def test_workbook_with_side_sheets(self):
        code, out = self.run_import("columns.xlsx", "--fresh")
        self.assertEqual(code, 0, out)
        self.assertIn("Created 3 workstreams, 5 areas, 3 milestones, 8 tasks", out)
        self.assertEqual(len(self.notes("tasks")), 8)
        # values from the side sheets
        self.assertEqual(self.fm("workstreams", "WOW")["map_hint"], "west")
        self.assertEqual(self.fm("milestones", "M1")["target"], "2026-12-18")
        # "M1 Foundations" in the sheet is milestone M1; M3 isn't in the Milestones sheet, so it's made
        self.assertEqual(self.fm("tasks", "CH-01")["milestone"], "M1")
        self.assertEqual(self.fm("milestones", "M3")["title"], "M3")
        # statuses, estimates and DALs as written
        self.assertEqual(self.fm("tasks", "CH-02")["status"], "in-progress")      # WIP
        self.assertEqual(self.fm("tasks", "GIT-02")["status"], "review")          # In review
        self.assertEqual(self.fm("tasks", "GIT-02")["estimate"], "4 h")           # kept, flagged by the checks
        ci = self.fm("tasks", "CI-01")
        self.assertEqual((ci["status"], ci["sheet_status"]), ("planned", "Blocked"))
        self.assertEqual(self.fm("tasks", "REV-02")["dal"], ["A", "B"])
        # a row with no ID gets one from its area
        self.assertEqual(self.fm("tasks", "PT-01")["title"], "Decide where we track tasks")
        # extra columns become properties
        self.assertEqual(self.fm("tasks", "CH-01")["thread"], "People")
        # dependencies: IDs resolve; a name shared by two tasks (rich-text cell) is reported, not guessed
        self.assertEqual(self.fm("tasks", "GIT-02")["depends_on"], ["GIT-01", "CH-02"])
        self.assertNotIn("depends_on", self.fm("tasks", "PT-01"))
        self.assertIn('which is the name of 2 tasks', out)
        self.assertIn('"Licence server upgrade", which isn\'t a task', out)

    def test_merged_cells_and_blank_cells_mean_same_as_above(self):
        code, out = self.run_import("merged_cells.xlsx", "--fresh")
        self.assertEqual(code, 0, out)
        tasks = {fm["title"]: fm for fm, _b, _p in self.notes("tasks").values()}
        self.assertEqual(tasks["Agree RACI"]["parent"], tasks["Write charter"]["parent"])
        self.assertEqual(tasks["Nightly regression"]["parent"], tasks["Runner"]["parent"])
        self.assertEqual(len(self.notes("workstreams")), 2)

    def test_multiline_cells(self):
        code, out = self.run_import("multiline_cells.csv", "--fresh")
        self.assertEqual(code, 0, out)
        (fm, body, _p), = self.notes("tasks").values()
        self.assertEqual(fm["deliverable"], "Document control: FPGA coding standard, issue 2")
        self.assertEqual(body.strip(), "Line one\nLine two")
        self.assertEqual(self.fm("workstreams", "SA")["title"], "S&A")

    def test_encodings_and_line_endings(self):
        for fixture, title in (("semicolon_cp1252.csv", "Café rota"), ("utf16_tabs.txt", "Write charter"),
                               ("old_mac_lines.csv", "Agree RACI"), ("apostrophes.csv", "Runner, licences and tools")):
            with self.subTest(fixture=fixture):
                code, out = self.run_import(fixture, "--fresh")
                self.assertEqual(code, 0, out)
                self.assertIn(title, [fm["title"] for fm, _b, _p in self.notes("tasks").values()])

    def test_apostrophes_are_not_quotes(self):
        self.run_import("apostrophes.csv", "--fresh")
        _fm, body, _p = self.notes("tasks")["CH-02"]
        self.assertEqual(body.strip(), "What 'done' means for a 'template' or a 'guide'")

    def test_dotted_ids_match_exactly(self):
        self.run_import("dotted_ids.csv", "--fresh")
        self.assertEqual(self.fm("tasks", "R-2")["depends_on"], ["R-1.1"])


class Outlines(KitTestCase):
    def test_microsoft_project_export(self):
        code, out = self.run_import("msproject_outline.xlsx", "--fresh")
        self.assertEqual(code, 0, out)
        self.assertIn("Created 2 workstreams, 2 areas, 4 tasks", out)
        roles = self.fm("tasks", "TC-02")
        self.assertEqual(roles["status"], "in-progress")                 # 50% complete
        self.assertEqual(roles["owner"], "Lead")                         # "Lead[50%]"
        self.assertEqual(roles["estimate"], "2")                         # the sum of its two 1-day subtasks
        self.assertIn("- [x] Draft RACI", self.notes("tasks")["TC-02"][1])
        self.assertEqual(self.fm("tasks", "CI-01")["depends_on"], ["TC-02"])   # "4FS+2 days" is row 4
        self.assertEqual(self.fm("tasks", "TC-01")["status"], "done")

    def test_extra_level(self):
        code, out = self.run_import("threads_outline.xlsx", "--fresh", "--levels", "workstream,area,thread,task")
        self.assertEqual(code, 0, out)
        charter = self.fm("tasks", "CHAR-01")
        self.assertEqual(charter["thread"], "People thread")
        self.assertEqual(self.fm("areas", "CI")["title"], "CI epic")    # "epic" is left out of the ID
        self.assertNotIn("thread", self.fm("tasks", "CI-01"))           # a new area clears the thread


class Values(KitTestCase):
    def test_milestone_names_that_are_not_id_plus_title(self):
        self.run_import("quarter_milestones.csv", "--fresh")
        ms = {fm["id"]: fm["title"] for fm, _b, _p in self.notes("milestones").values()}
        self.assertEqual(ms, {"Q1-2027": "Q1 2027", "Q3-2026": "Q3 2026", "Q3-2027": "Q3 2027"})
        self.run_import("fy_milestones.csv", "--fresh")
        self.assertIn("FY27-Q1", self.notes("milestones"))

    def test_time_formatted_estimates(self):
        code, out = self.run_import("hidden_sheet_hours.xlsx", "--fresh")
        self.assertIn('Skipped hidden sheets: "Lists"', out)
        self.assertIn("--estimate-unit hours", out)                       # the heading says (h:mm)
        (fm, _b, _p), = self.notes("tasks").values()
        self.assertEqual(fm["estimate"], "7.5")
        self.run_import("time_estimate.xlsx", "--fresh")
        (fm, _b, _p), = self.notes("tasks").values()
        self.assertEqual(fm["estimate"], "7.5 h")
        self.assertEqual(fm["start"], "2026-11-02")

    def test_estimate_heading_unit(self):
        self.run_import("hours_heading.csv", "--fresh")
        est = {fm["title"]: fm.get("estimate") for fm, _b, _p in self.notes("tasks").values()}
        self.assertEqual(est, {"Big job": "1200", "Small": "1.5"})
        self.assertFalse([i for i in self.check("hours").issues if i["code"] == "W109"])

    def test_1904_dates(self):
        self.run_import("dates_1904.xlsx", "--fresh")
        self.assertEqual(self.fm("milestones", "M1")["target"], "2026-12-18")


class Rerunning(KitTestCase):
    def test_add_then_update_then_nothing_to_do(self):
        self.run_import("semicolon_cp1252.csv", "--fresh")
        note = self.notes("tasks")["TC-02"][2]
        note.write_text(note.read_text(encoding="utf-8") + "\nWritten by hand.\n", encoding="utf-8")

        code, out = self.run_import("semicolon_cp1252_v2.csv")
        self.assertEqual(code, 0, out)
        self.assertIn("Created 1 task", out)
        self.assertEqual(self.fm("tasks", "TC-02")["status"], "in-progress")   # left alone without --update

        code, out = self.run_import("semicolon_cp1252_v2.csv", "--update")
        self.assertIn("Updated 1 task", out)
        self.assertEqual(self.fm("tasks", "TC-02")["status"], "done")
        self.assertIn("Written by hand.", note.read_text(encoding="utf-8"))
        self.assertEqual(self.fm("tasks", "TC-03")["depends_on"], ["TC-02"])

        code, out = self.run_import("semicolon_cp1252_v2.csv", "--update")
        self.assertIn("Unchanged: 1 workstream, 1 area, 3 tasks", out)

    def test_update_matches_repeated_names_in_order(self):
        self.run_import("same_names.csv", "--fresh")
        self.run_import("same_names_v2.csv", "--update")
        self.assertEqual(self.fm("tasks", "CS-01")["owner"], "Avery")
        third = self.fm("tasks", "CS-03")
        self.assertEqual((third["owner"], third["status"]), ("Casey", "in-progress"))

    def test_update_clears_sheet_status_once_known(self):
        self.run_import("blocked_status.csv", "--fresh")
        self.assertEqual(self.fm("tasks", "T-1")["sheet_status"], "Blocked")
        self.run_import("blocked_status_v2.csv", "--update")
        fm = self.fm("tasks", "T-1")
        self.assertEqual(fm["status"], "in-progress")
        self.assertNotIn("sheet_status", fm)

    def test_blank_status_never_overwrites(self):
        code, out = self.run_import("semicolon_cp1252_v2.csv")          # adds to the example roadmap
        self.assertEqual(code, 0, out)
        before = self.fm("tasks", "CH-01")["status"]
        self.run_import("semicolon_cp1252_v2.csv", "--update")
        self.assertEqual(self.fm("tasks", "CH-01")["status"], before)


class Safety(KitTestCase):
    def test_fresh_keeps_the_teams_own_requests(self):
        own = self.kit / "roadmap" / "requests" / "REQ-90 Ours.md"
        own.write_text("---\ntype: request\nid: REQ-90\ntitle: Ours\nstatus: open\n---\n", encoding="utf-8")
        examples = [p for p in (self.kit / "roadmap" / "requests").glob("*.md") if p != own]
        self.assertTrue(examples)
        code, out = self.run_import("columns.xlsx", "--fresh")
        self.assertEqual(code, 0, out)
        self.assertTrue(own.exists())
        self.assertFalse(any(p.exists() for p in examples))

    def test_a_sheet_with_no_tasks_changes_nothing(self):
        before = sorted(p.name for p in (self.kit / "roadmap").rglob("*.md"))
        code, out = self.run_import("headings_only.csv", "--fresh")
        self.assertEqual(code, 2)
        self.assertIn("nothing was changed", out)
        self.assertEqual(sorted(p.name for p in (self.kit / "roadmap").rglob("*.md")), before)

    def test_dry_run_writes_nothing(self):
        before = sorted(p.name for p in (self.kit / "roadmap").rglob("*.md"))
        code, out = self.run_import("columns.xlsx", "--fresh", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing was written", out)
        self.assertEqual(sorted(p.name for p in (self.kit / "roadmap").rglob("*.md")), before)

    def test_problems_stop_before_writing(self):
        for fixture, args, words in (("duplicate_ids.csv", (), "is used twice"),
                                     ("no_title.csv", (), "couldn't find a sheet"),
                                     ("no_title.csv", ("--col", "title=Nope"), 'no column is headed "Nope"'),
                                     ("no_title.csv", ("--col", "bogus=Thing"), "isn't a field")):
            with self.subTest(fixture=fixture, args=args):
                code, out = self.run_import(fixture, "--fresh", *args)
                self.assertEqual(code, 2)
                self.assertIn(words, out)
        self.assertTrue(any((self.kit / "roadmap" / "tasks").glob("*.md")))

    def test_imported_roadmap_builds_cleanly(self):
        for fixture in ("columns.xlsx", "msproject_outline.xlsx", "merged_cells.xlsx", "apostrophes.csv"):
            with self.subTest(fixture=fixture):
                self.run_import(fixture, "--fresh")
                self.assertEqual(self.check().count("error"), 0)


class Helpers(unittest.TestCase):
    def test_values(self):
        from import_roadmap import dal_of, estimate_of, status_of
        self.assertEqual(dal_of("A/B"), ["A", "B"])
        self.assertEqual(dal_of("B-D"), ["B", "C", "D"])
        self.assertEqual(dal_of("N/A"), [])
        self.assertIsNone(dal_of("Level 3"))
        self.assertEqual(estimate_of("1,200 h", "hours"), ("1200", "hours"))
        self.assertEqual(estimate_of("2,5"), ("2.5", ""))
        self.assertEqual(estimate_of("3d"), ("3", "days"))
        self.assertEqual(estimate_of("07:30"), ("7.5 h", "hours"))
        self.assertEqual(status_of("WIP", "")[0], "in-progress")
        self.assertEqual(status_of("", "100%")[0], "done")
        self.assertEqual(status_of("Blocked", ""), ("planned", False, "Blocked"))

    def test_generated_ids(self):
        from import_roadmap import Importer

        class Args:
            fresh = True
        imp = Importer.__new__(Importer)
        imp.taken, imp.args = set(), Args()
        self.assertEqual(imp.generated_id("Ways of Working"), "WW")
        self.assertEqual(imp.generated_id("Phase A"), "PA")
        self.assertEqual(imp.generated_id("S&A"), "SA")
        self.assertEqual(imp.generated_id("CI epic"), "CI")
        self.assertEqual(imp.generated_id("2027", "area"), "A2027")
        self.assertEqual(imp.generated_id("Phase A"), "PA2")              # taken, so numbered


if __name__ == "__main__":
    unittest.main()
