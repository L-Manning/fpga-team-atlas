#!/usr/bin/env python3
"""Keep work content out of this public repository.

This repository is public, so anything committed and pushed here is published.
It holds the kit and a placeholder example roadmap, nothing from work. This guard
looks for signs of real work content and fails if it finds any:

  - a person in the example roadmap or library who isn't one of the placeholders
  - a protective, commercial or export-control marking
  - an e-mail address, a private IP address, an internal host name, a Windows
    network or drive path, or a link to a site that isn't on the list below
  - a spreadsheet, document, archive, image or FPGA design file outside the
    test fixtures

    python tests/content_guard.py            check every file Git would commit
    python tests/content_guard.py --staged   check only what is staged (the pre-commit hook runs this)

Exit code 0 when nothing was found, 1 when something needs a look, 2 when Git
couldn't be asked what is staged. If a finding is deliberate placeholder content,
extend the lists below in the same commit, so the reviewer sees the change.
Like the rest of tests/, this file is only for developing the kit and isn't
needed on the work network.
"""
from __future__ import annotations

import argparse
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "tools"))
import build_atlas as atlas  # noqa: E402  (the note reader, so frontmatter is read the same way)

# People in the example content. The placeholders run A, B, C... so a real name stands out.
PLACEHOLDER_NAMES = {"Avery", "Blake", "Casey", "Drew", "Ellis", "Frankie", "Gray", "Harper", "Indy", "Jordan"}
ROLES = {"Lead", "Team", "TBD", "Unassigned"}
PEOPLE_FIELDS = ("owner", "raised_by", "plus_ones", "reviewer", "approver", "assignee")
OWNER_LINE = re.compile(r"\*\*Owner:\*\*[ \t]*([^·*\n]+)")

# Sites that may be linked to (and their subdomains). Anything else could be a server at work.
PUBLIC_SITES = {"github.com", "gitlab.com", "scripts.sil.org", "openfontlicense.org", "example.com", "example.org",
                "example.net", "localhost", "python.org", "obsidian.md", "playwright.dev", "reproducible-builds.org",
                "claude.ai", "claude.com", "anthropic.com"}
PUBLIC_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
PUBLIC_EMAILS = {"git@github.com", "git@gitlab.com"}

# The only places that may hold the file types below: synthetic test data and the import template.
ALLOWED_FOLDERS = ("tests/fixtures/",)
ALLOWED_FILES = ("tools/roadmap_template.xlsx",)
BLOCKED_TYPES = {
    "spreadsheet or document": (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv", ".docx", ".doc", ".odt",
                                ".pptx", ".ppt", ".pdf", ".vsdx", ".mpp", ".msg", ".eml"),
    "archive": (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"),
    "image (a screenshot can show work content)": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
                                                    ".heic"),
    "FPGA design or build file": (".vhd", ".vhdl", ".v", ".sv", ".svh", ".xdc", ".sdc", ".ucf", ".tcl", ".xpr",
                                  ".xci", ".xcix", ".bd", ".bit", ".bin", ".mcs", ".prm", ".ltx", ".dcp", ".xsa",
                                  ".hdf", ".wcfg", ".wdb", ".coe", ".mem", ".elf"),
}

# The guard and its tests hold the patterns themselves, so their text isn't searched.
SELF = ("tests/content_guard.py", "tests/test_content_guard.py")

TEXT_RULES = [
    (re.compile(r"\b(?:OFFICIAL|SECRET|EYES ONLY|RESTRICTED|CONFIDENTIAL|NOFORN)\b"), "a protective marking"),
    (re.compile(r"\bPROPRIETARY\b"), "a commercial marking"),
    (re.compile(r"\bcommercial[- ]in[- ]confidence\b", re.I), "a commercial marking"),
    (re.compile(r"\b(?:ITAR|EAR99)\b"), "an export-control marking"),
    (re.compile(r"\bexport[- ]controlled\b", re.I), "an export-control marking"),
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "a private IP address"),
    (re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:local|corp|internal|intranet|intra|lan)\b", re.I),
     "an internal host name"),
    (re.compile(r"\\\\[A-Za-z0-9][A-Za-z0-9._-]*\\[A-Za-z0-9$._ -]+"), "a Windows network path"),
    (re.compile(r"\b[A-Za-z]:\\[A-Za-z0-9 ._-]+\\"), "a Windows drive path"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
URL = re.compile(r"\bhttps?://([A-Za-z0-9.-]+)", re.I)

HELP = ("This repository is public: anything pushed to it is published. Replace the content with a placeholder, "
        "or, if it is deliberate placeholder content, add it to the lists in tests/content_guard.py in the same "
        "commit. See CONTRIBUTING.md.")


def blocked_kind(path: str) -> str:
    if path.startswith(ALLOWED_FOLDERS) or path in ALLOWED_FILES:
        return ""
    ext = posixpath.splitext(path)[1].lower()
    return next((kind for kind, exts in BLOCKED_TYPES.items() if ext in exts), "")


def as_text(data: bytes):
    """The file's text, or None for a binary file. Markings are ASCII, so odd encodings still read well enough."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def is_public(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == site or host.endswith("." + site) for site in PUBLIC_SITES)


def known_person(name: str) -> bool:
    return name.strip().lower() in {n.lower() for n in PLACEHOLDER_NAMES | ROLES}


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def text_findings(path: str, text: str) -> list:
    found = []
    for rule, what in TEXT_RULES:
        for m in rule.finditer(text):
            found.append(f"{path}:{line_of(text, m.start())}: {what} ({m.group(0).strip()})")
    for m in EMAIL.finditer(text):
        address, domain = m.group(0), m.group(1).lower()
        if domain not in PUBLIC_EMAIL_DOMAINS and address.lower() not in PUBLIC_EMAILS:
            found.append(f"{path}:{line_of(text, m.start())}: an e-mail address ({address}). "
                         "Use a placeholder such as avery@example.org")
    for m in URL.finditer(text):
        if not is_public(m.group(1)):
            found.append(f"{path}:{line_of(text, m.start())}: a link to {m.group(1)}, which isn't on the list of "
                         "known public sites (PUBLIC_SITES)")
    return found


def people_findings(path: str, text: str) -> list:
    """People named in the example roadmap's frontmatter or on a library document's Owner line."""
    if not path.endswith(".md") or not path.startswith(("roadmap/", "library/")):
        return []
    found = []
    if path.startswith("roadmap/"):
        try:
            fm_text, _body, first = atlas.split_note(text)
            fm = atlas.parse_frontmatter(fm_text, first) if fm_text is not None else {}
        except atlas.FrontmatterError:
            fm = {}                 # build_atlas.py --check reports frontmatter it can't read
        for field in PEOPLE_FIELDS:
            for name in atlas.as_list(fm.get(field)):
                if not known_person(name):
                    found.append(f"{path}: {field} \"{name}\" isn't one of the placeholder names "
                                 f"({', '.join(sorted(PLACEHOLDER_NAMES))})")
    for m in OWNER_LINE.finditer(text):
        name = m.group(1).strip()
        if name and not name.startswith("<") and not known_person(name):
            found.append(f"{path}:{line_of(text, m.start())}: Owner \"{name}\" isn't one of the placeholder names")
    return found


def check(files: dict) -> list:
    """Findings for {repository-relative path: file contents as bytes}."""
    found = []
    for path in sorted(files):
        kind = blocked_kind(path)
        if kind:
            found.append(f"{path}: a {kind} can't go in this repository. Synthetic test data belongs in "
                         "tests/fixtures/")
            continue
        text = as_text(files[path])
        if text is None:
            continue
        if path not in SELF:
            found += text_findings(path, text)
        found += people_findings(path, text)
    return found


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def paths_from(out: bytes) -> list:
    return [p for p in out.decode("utf-8").split("\0") if p]


def staged_files(root: Path) -> dict:
    """What the next commit would contain, for every file it adds, copies, modifies or renames."""
    paths = paths_from(git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"))
    return {p: git(root, "show", f":{p}") for p in paths}


def working_files(root: Path) -> dict:
    """Every file Git would commit: tracked files and new ones that aren't ignored."""
    try:
        paths = paths_from(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"))
    except (OSError, subprocess.CalledProcessError):            # not a Git checkout: walk the folder instead
        skip = {".git", "public", "__pycache__", "shots", ".trash"}
        paths = []
        for top, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in skip)
            rel = Path(top).relative_to(root)
            paths += [(rel / n).as_posix() for n in sorted(names)]
    return {p: (root / p).read_bytes() for p in paths if (root / p).is_file()}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Look for work content before it reaches this public repository.")
    ap.add_argument("--staged", action="store_true", help="check only what is staged for the next commit")
    ap.add_argument("--root", type=Path, default=KIT, help="repository root (default: the folder above tests/)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        files = staged_files(root) if args.staged else working_files(root)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"Content guard: couldn't ask Git what is staged ({e}). Is Git installed and is this a clone?",
              file=sys.stderr)
        return 2
    found = check(files)
    if not found:
        print(f"Content guard: nothing found in {len(files)} file{'' if len(files) == 1 else 's'}.")
        return 0
    print(f"Content guard: {len(found)} thing{'' if len(found) == 1 else 's'} to look at before "
          f"{'this commit' if args.staged else 'committing'}:")
    for f in found:
        print("  " + f)
    print(HELP)
    return 1


if __name__ == "__main__":
    sys.exit(main())
