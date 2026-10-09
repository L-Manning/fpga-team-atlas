"""Tests for tests/content_guard.py, which keeps work content out of this public repository."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import content_guard as guard
from helpers import KIT


def joined(*parts: str) -> str:
    """Join the parts at run time, so this file never holds a finding itself."""
    return "".join(parts)


class RepositoryIsClean(unittest.TestCase):
    def test_every_file_git_would_commit_passes(self):
        found = guard.check(guard.working_files(KIT))
        self.assertEqual(found, [], "\n" + "\n".join(found))


class Rules(unittest.TestCase):
    def found(self, path: str, text: str) -> list:
        return guard.check({path: text.encode("utf-8")})

    def test_placeholder_people_and_roles_pass(self):
        note = "---\ntype: task\nid: X-1\nowner: Avery\nplus_ones: [Blake, Lead]\n---\nBody\n"
        self.assertEqual(self.found("roadmap/tasks/X-1 Thing.md", note), [])

    def test_other_people_are_found(self):
        note = "---\ntype: request\nid: REQ-9\nraised_by: Jane Smith\nplus_ones:\n  - Avery\n  - Sam\n---\n"
        found = self.found("roadmap/requests/REQ-9.md", note)
        self.assertEqual(len(found), 2, found)
        self.assertIn('raised_by "Jane Smith"', found[0])

    def test_library_owner_lines(self):
        self.assertEqual(self.found("library/guides/a.md", "**Owner:** Blake · **Last reviewed:** 2026-01-01\n"), [])
        self.assertEqual(self.found("library/templates/b.md", "**Owner:** <name> · **Last reviewed:** <date>\n"), [])
        self.assertEqual(len(self.found("library/guides/c.md", "**Owner:** Pat Jones · x\n")), 1)

    def test_markings_are_found(self):
        for text in (joined("OFFI", "CIAL-SENSITIVE"), joined("UK EYES", " ONLY"), joined("Commercial in ", "Confidence"),
                     joined("IT", "AR technical data"), joined("Export ", "Controlled")):
            found = self.found("README.md", "A heading\n\n" + text + "\n")
            self.assertEqual(len(found), 1, f"{text}: {found}")
            self.assertIn("README.md:3:", found[0])

    def test_ordinary_words_are_not_markings(self):
        text = "The official guide. A secret ballot. Restricted access. Proprietary fonts. Confidential? No."
        self.assertEqual(self.found("README.md", text), [])

    def test_addresses_hosts_and_links(self):
        cases = {
            joined("jane.smith@", "company.co.uk"): 1,
            "avery@example.org": 0,
            "git@github.com:L-Manning/fpga-team-atlas.git": 0,
            joined("10.20", ".30.40"): 1,
            joined("build01.", "corp"): 1,
            "https://github.com/L-Manning/fpga-team-atlas": 0,
            "https://help.obsidian.md/bases": 0,
            joined("https://gitlab.", "company.co.uk/fpga/atlas"): 1,
            joined("\\\\", "fileserver\\fpga"): 1,
            joined("S:", "\\Programmes\\"): 1,
            "Vivado 2024.2 and Python 3.8": 0,
        }
        for text, n in cases.items():
            self.assertEqual(len(self.found("library/guides/x.md", text)), n, text)

    def test_blocked_file_types(self):
        self.assertEqual(len(guard.check({"roadmap.xlsx": b"PK\x03\x04"})), 1)
        self.assertEqual(len(guard.check({"rtl/top.vhd": b"entity top is end entity;"})), 1)
        self.assertEqual(len(guard.check({"docs/atlas.PNG": b"\x89PNG"})), 1)
        self.assertEqual(guard.check({"tests/fixtures/new.xlsx": b"PK\x03\x04", "tools/roadmap_template.xlsx": b"PK"}), [])

    def test_staged_mode_reads_what_is_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = ["git", "-C", tmp, "-c", "user.name=Avery", "-c", "user.email=avery@example.org"]
            try:
                subprocess.run(git + ["init", "-q"], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError):
                self.skipTest("Git isn't available")
            (root / "notes.md").write_text(joined("Ask ", "ops@", "company.co.uk"), encoding="utf-8")
            (root / "plan.xlsx").write_bytes(b"PK\x03\x04")
            self.assertEqual(guard.check(guard.staged_files(root)), [])           # nothing staged yet
            subprocess.run(git + ["add", "notes.md", "plan.xlsx"], check=True, capture_output=True)
            found = guard.check(guard.staged_files(root))
            self.assertEqual(len(found), 2, found)


if __name__ == "__main__":
    unittest.main()
