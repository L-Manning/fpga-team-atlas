"""Shared helpers for the tests: a scratch copy of the kit, and running the tools inside it."""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(KIT / "tools"))

import build_atlas as atlas  # noqa: E402
import import_roadmap as importer  # noqa: E402

SKIP = shutil.ignore_patterns(".git", ".github", "public", "tests", "__pycache__", "*.pyc")


class KitTestCase(unittest.TestCase):
    """Each test gets its own copy of the kit, so the tools can write notes freely."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.kit = Path(self._tmp.name) / "kit"
        shutil.copytree(KIT, self.kit, ignore=SKIP)

    def tearDown(self):
        self._tmp.cleanup()

    # -- running the tools ---------------------------------------------------
    def run_import(self, fixture: str, *args: str):
        """(exit code, everything printed) for import_roadmap.py on a fixture."""
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            try:
                code = importer.main([str(FIXTURES / fixture), "--root", str(self.kit), *args])
            except SystemExit as e:          # argparse errors
                code = e.code
        return code, out.getvalue()

    def run_build(self, *args: str):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = atlas.main(["--root", str(self.kit), *args])
        return code, out.getvalue()

    def check(self, estimate_unit: str = "days"):
        chk = atlas.Checker()
        atlas.build_model(self.kit, self.kit / "roadmap", chk, estimate_unit)
        return chk

    # -- reading what was written --------------------------------------------
    def notes(self, folder: str) -> dict:
        """id -> (frontmatter, body, path) for every note in roadmap/<folder>."""
        found = {}
        for path in sorted((self.kit / "roadmap" / folder).glob("*.md")):
            fm_text, body, first = atlas.split_note(path.read_text(encoding="utf-8"))
            fm = atlas.parse_frontmatter(fm_text, first) if fm_text is not None else {}
            found[atlas.as_str(fm.get("id"))] = (fm, body, path)
        return found

    def fm(self, folder: str, nid: str) -> dict:
        notes = self.notes(folder)
        self.assertIn(nid, notes, f"no {folder} note with id {nid}; have {sorted(notes)}")
        return notes[nid][0]
