#!/usr/bin/env python3
"""Turn a roadmap spreadsheet into FPGA Team Atlas notes.

Reads an Excel workbook (.xlsx or .xlsm) or a CSV file and writes one Markdown
note per workstream, area, task and milestone under roadmap/. It runs offline and
needs only the Python 3.8+ standard library, so the spreadsheet never leaves your
machine.

    python tools/import_roadmap.py plan.xlsx --dry-run   show what would happen
    python tools/import_roadmap.py plan.xlsx --fresh     replace the example roadmap
    python tools/import_roadmap.py plan.xlsx             add items that aren't notes yet
    python tools/import_roadmap.py plan.xlsx --update    also refresh existing notes
    python tools/import_roadmap.py --columns             list the headings it recognises

Two layouts are understood:

  one task per row   each row is a task; columns name its workstream and its area
                     (an "Epic" column works as the area)
  outline            a Level, Outline level or WBS column gives each row's depth.
                     By default 1 = workstream, 2 = area, 3 = task and anything
                     deeper is a subtask. Change this with --levels.

Headings are matched loosely, so "Task", "Task name", "Name" and "Summary" all
mean a task's title. Point a field at any other heading with --col, for example
--col area=Epic. Columns it doesn't recognise are kept as extra properties on each
task note, so nothing in the sheet is lost.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_atlas as atlas  # noqa: E402  (shares the note reader and the checks)


class ImportProblem(Exception):
    """A problem that stops the import before anything is written."""


# --------------------------------------------------------------------------
# Reading the spreadsheet
# --------------------------------------------------------------------------
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x85\u2028\u2029]")


def clean_text(s) -> str:
    """Cell text with Excel's _xHHHH_ escapes decoded, line ends as \\n and other control characters as spaces."""
    s = str(s if s is not None else "")
    s = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return CONTROL.sub(" ", s).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_of(el) -> str:
    """Text of a shared or inline string: plain <t> or rich-text runs, without phonetic hints."""
    if el is None:
        return ""
    out = []
    for c in el:
        name = _local(c.tag)
        if name == "t":
            out.append(c.text or "")
        elif name == "r":
            out.extend(t.text or "" for t in c if _local(t.tag) == "t")
    return "".join(out)


# Excel's built-in number formats for dates and for times of day.
BUILTIN_DATES = set(range(14, 18)) | {22} | set(range(27, 37)) | set(range(50, 59))
BUILTIN_TIMES = set(range(18, 22)) | set(range(45, 48))


def _format_kind(code: str) -> str:
    if re.search(r"\[(?:h+|m+|s+)\]", code or "", re.I):     # elapsed time such as [h]:mm
        return "time"
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "").lower()
    if re.search(r"[dy]", code):
        return "date"
    if "h" in code or "s" in code:
        return "time"
    return ""


def _num_text(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return "%.10g" % x


def _excel_date(x: float, date1904: bool) -> str:
    base = dt.datetime(1904, 1, 1) if date1904 else dt.datetime(1899, 12, 30)
    try:
        return (base + dt.timedelta(days=x)).date().isoformat()
    except (OverflowError, ValueError):
        return _num_text(x)


def _excel_time(x: float) -> str:
    minutes = int(round(x * 24 * 60))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _cell_ref(ref: str):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref or "")
    if not m:
        return None
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return col - 1, int(m.group(2))


def _sheet_rows(data: bytes, shared: list, styles: dict, date1904: bool) -> list:
    root = ET.fromstring(data)
    rows, last, merges = {}, 0, []
    for el in root.iter():
        name = _local(el.tag)
        if name == "mergeCell":
            a, _, b = (el.get("ref") or "").partition(":")
            ra, rb = _cell_ref(a), _cell_ref(b or a)
            if ra and rb:
                merges.append((ra, rb))
            continue
        if name != "row":
            continue
        r = int(el.get("r") or last + 1)
        last = r
        cells, nxt = {}, 0
        for c in el:
            if _local(c.tag) != "c":
                continue
            ref = _cell_ref(c.get("r") or "")
            col = ref[0] if ref else nxt
            nxt = col + 1
            kind = c.get("t") or "n"
            v = next((x.text for x in c if _local(x.tag) == "v"), None)
            if kind == "inlineStr":
                val = _text_of(next((x for x in c if _local(x.tag) == "is"), None))
            elif v is None or kind == "e":
                val = ""
            elif kind == "s":
                i = int(v)
                val = shared[i] if 0 <= i < len(shared) else ""
            elif kind == "b":
                val = "TRUE" if v.strip() == "1" else "FALSE"
            elif kind in ("str", "d"):
                val = v
            else:
                try:
                    x = float(v)
                except ValueError:
                    val = v
                else:
                    fmt = styles.get(int(c.get("s") or 0), "")
                    val = _excel_date(x, date1904) if fmt == "date" else _excel_time(x) if fmt == "time" else _num_text(x)
            val = clean_text(val)
            if val:
                cells[col] = val
        if cells:
            rows[r] = cells
    # A merged range shows its first cell's value across the whole range.
    for (c0, r0), (c1, r1) in merges:
        v = rows.get(r0, {}).get(c0, "")
        if not v:
            continue
        for r in range(r0, min(r1, r0 + 5000) + 1):
            for c in range(c0, min(c1, c0 + 200) + 1):
                rows.setdefault(r, {}).setdefault(c, v)
    out = []
    for r in range(1, max(rows) + 1 if rows else 1):
        cells = rows.get(r)
        out.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return out


def read_xlsx(path: Path) -> list:
    """[(sheet name, rows, hidden)], each row a list of cell texts."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        date1904 = any(_local(e.tag) == "workbookPr" and (e.get("date1904") or "").lower() in ("1", "true")
                       for e in wb.iter())
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                rels[r.get("Id")] = r.get("Target") or ""
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [_text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")) if _local(si.tag) == "si"]
        styles = {}
        if "xl/styles.xml" in names:
            st = ET.fromstring(z.read("xl/styles.xml"))
            custom = {int(e.get("numFmtId")): e.get("formatCode") or ""
                      for e in st.iter() if _local(e.tag) == "numFmt" and (e.get("numFmtId") or "").isdigit()}
            for xfs in st.iter():
                if _local(xfs.tag) != "cellXfs":
                    continue
                for i, xf in enumerate(x for x in xfs if _local(x.tag) == "xf"):
                    fid = int(xf.get("numFmtId") or 0)
                    kind = "date" if fid in BUILTIN_DATES else "time" if fid in BUILTIN_TIMES else _format_kind(custom.get(fid, ""))
                    if kind:
                        styles[i] = kind
        out = []
        for sh in wb.iter():
            if _local(sh.tag) != "sheet":
                continue
            rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
            target = rels.get(rid, "")
            if not target:
                continue
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            if part in names:
                hidden = (sh.get("state") or "visible") != "visible"
                out.append((sh.get("name") or part, _sheet_rows(z.read(part), shared, styles, date1904), hidden))
        return out


def read_csv(path: Path) -> list:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    first = next((ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()), "")
    delim = max(("\t", ";", ","), key=lambda d: (first.count(d), d == ","))
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim, quotechar='"', doublequote=True)
        rows = [[clean_text(c) for c in row] for row in reader]
    except csv.Error as e:
        raise ImportProblem(f"couldn't read {path.name} as CSV ({e})")
    return [(path.stem, rows, False)]


def read_book(path: Path) -> list:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            return read_xlsx(path)
        except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError) as e:
            raise ImportProblem(f"couldn't read {path.name} as an Excel workbook ({e})")
    if ext in (".csv", ".tsv", ".txt"):
        return read_csv(path)
    if ext == ".xls":
        raise ImportProblem(f"{path.name} is an old-style .xls file. In Excel, use File > Save As and choose "
                            "Excel Workbook (.xlsx) or CSV, then import that.")
    raise ImportProblem(f"{path.name}: expected an .xlsx, .xlsm or .csv file")


# --------------------------------------------------------------------------
# Recognising columns
# --------------------------------------------------------------------------
def _norm(s) -> str:
    """For matching headings: case, spaces and punctuation ignored."""
    return re.sub(r"[^a-z0-9%#]+", "", str(s).lower())


def _key(s) -> str:
    """For matching names and IDs: case and repeated spaces ignored, punctuation kept."""
    return " ".join(str(s or "").lower().split())


def _heading_keys(heading: str) -> list:
    """A heading as written, and without a bracketed unit such as '(days)'."""
    keys = [_norm(heading)]
    bare = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", heading).strip()
    if bare and _norm(bare) not in keys:
        keys.append(_norm(bare))
    return [k for k in keys if k]


TASK_FIELDS = {
    "id": ["ID", "Ref", "Reference", "Key", "Code", "Task ID", "Item ID", "Unique ID", "No", "Number", "#"],
    "title": ["Title", "Task", "Task name", "Name", "Summary", "Item", "Activity", "Action"],
    "workstream": ["Workstream", "Work stream", "Stream", "Programme", "Program", "Theme", "Pillar"],
    "area": ["Area", "Epic", "Town", "Feature", "Work package", "Package", "Group"],
    "status": ["Status", "State"],
    "complete": ["% Complete", "Percent complete", "Complete", "% done", "Progress", "Pct complete"],
    "owner": ["Owner", "Assignee", "Assigned to", "Who", "Lead", "Responsible", "Resource names", "Resource"],
    "milestone": ["Milestone", "Target milestone", "Phase"],
    "depends_on": ["Depends on", "Dependencies", "Dependency", "Depends", "Predecessors", "Predecessor",
                   "Prerequisites", "Prereqs", "Needs", "Blocked by", "After"],
    "estimate": ["Estimate", "Estimates", "Effort", "Est", "Estimated effort", "Estimate days", "Days", "Man days",
                 "Person days", "Duration", "Work", "Size", "Points", "Story points"],
    "kind": ["Kind", "Type", "Task type", "Output type"],
    "dal": ["DAL", "DALs", "DAL level", "DAL levels", "Applies to"],
    "deliverable": ["Deliverable", "Output", "Artefact", "Artifact", "Document", "Link", "Location"],
    "tracker": ["Tracker", "Issue", "Ticket", "GitLab issue", "Jira", "URL"],
    "description": ["Description", "Details", "Detail", "Notes", "Note", "Comments", "Comment", "Scope", "Why"],
    "subtasks": ["Subtasks", "Sub tasks", "Sub-tasks", "Steps", "Checklist", "Actions"],
    "level": ["Level", "Outline level", "WBS", "Outline", "Hierarchy", "Indent"],
}
WS_FIELDS = {
    "id": ["ID", "Ref", "Key", "Code"],
    "title": ["Title", "Name", "Workstream", "Work stream", "Stream"],
    "description": ["Description", "Summary", "Details", "Notes", "Purpose", "Goal", "Scope"],
    "map_hint": ["Map hint", "Map_hint", "Position", "Side"],
    "order": ["Order", "Sort", "Sequence"],
}
AREA_FIELDS = {
    "id": ["ID", "Ref", "Key", "Code"],
    "title": ["Title", "Name", "Area", "Epic", "Town"],
    "workstream": ["Workstream", "Work stream", "Stream", "Parent"],
    "description": ["Description", "Summary", "Details", "Notes", "Scope"],
}
MS_FIELDS = {
    "id": ["ID", "Ref", "Key", "Code"],
    "title": ["Title", "Name", "Milestone"],
    "target": ["Target", "Target date", "Date", "Due", "Due date", "Finish", "End", "Deadline"],
    "description": ["Description", "Summary", "Details", "Notes", "Exit criteria", "Criteria"],
}
SHEET_ROLES = {
    "workstreams": ["Workstreams", "Workstream", "Streams"],
    "areas": ["Areas", "Area", "Epics", "Epic", "Towns"],
    "milestones": ["Milestones", "Milestone"],
    "tasks": ["Tasks", "Task", "Task list", "Backlog", "Roadmap", "Plan", "Work", "Items", "Actions"],
}

STATUS_WORDS = {
    "planned": ["planned", "not started", "not yet started", "to do", "todo", "backlog", "open", "new",
                "proposed", "pending", "queued", "ready"],
    "in-progress": ["in progress", "in-progress", "wip", "doing", "started", "active", "ongoing", "underway",
                    "under way", "in work", "working", "in hand"],
    "review": ["review", "in review", "reviewing", "for review", "awaiting review", "peer review", "under review",
               "awaiting approval", "in approval"],
    "done": ["done", "complete", "completed", "closed", "finished", "resolved", "delivered", "published", "released"],
    "adopted": ["adopted", "in use", "embedded", "bau", "business as usual", "live", "routine", "in routine use"],
}
STATUS_INDEX = {_norm(w): s for s, words in STATUS_WORDS.items() for w in words}
YES = {"true", "yes", "y", "x", "✓", "✔", "1"}
NO = {"false", "no", "n", "0"}
KIND_INDEX = {}
for _k in atlas.KINDS:
    KIND_INDEX[_norm(_k)] = _k
    KIND_INDEX[_norm(_k + "s")] = _k
STOP_WORDS = {"a", "an", "and", "of", "the", "for", "to", "in", "on", "with", "by"}
GENERIC_WORDS = {"epic", "epics", "area", "workstream", "stream", "thread", "theme"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
RESERVED_KEYS = {"type", "id", "title", "parent", "kind", "status", "owner", "milestone", "estimate", "dal",
                 "depends_on", "deliverable", "tracker", "map_hint", "order", "target", "raised_by", "raised",
                 "plus_ones", "mapped_to", "aliases", "cssclasses", "example", "sheet_status", "task_type"}


def alias_index(fields: dict) -> dict:
    idx = {}
    for field, names in fields.items():
        for n in names:
            idx.setdefault(_norm(n), field)
    return idx


def find_header(rows: list, fields: dict, overrides: dict, need: str = "title"):
    """The row (within the first 20) that looks most like a heading row: (index, columns, extras, notes)."""
    idx = alias_index(fields)
    over = {_norm(h): f for f, h in overrides.items()}
    best = None
    for r, row in enumerate(rows[:20]):
        heads = [(c, str(h).strip()) for c, h in enumerate(row) if str(h).strip()]
        cols, extras, notes = {}, [], []
        for c, h in heads:                       # --col first, so it wins over any alias
            f = next((over[k] for k in _heading_keys(h) if k in over), None)
            if f and f not in cols:
                cols[f] = c
        for c, h in heads:
            if c in cols.values():
                continue
            f = next((idx[k] for k in _heading_keys(h) if k in idx), None)
            if f and f not in cols:
                cols[f] = c
            else:
                if f:
                    notes.append(f'"{h}" also looks like the {f} column; kept as an extra property instead')
                extras.append((h, c))
        if need in cols and (best is None or len(cols) > len(best[1])):
            best = (r, cols, extras, list(dict.fromkeys(notes)))
    return best


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def cell(row: list, col) -> str:
    if col is None or col >= len(row):
        return ""
    return str(row[col]).strip()


def one_line(s: str) -> str:
    return " ".join(str(s).split())


def prop_key(heading: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(heading).lower()).strip("_") or "column"
    if key[0].isdigit():
        key = "c_" + key
    if key in RESERVED_KEYS:
        key += "_sheet"
    return key


def unique_keys(headings: list) -> list:
    """A property name for each extra heading, numbered when two headings come out the same."""
    out, seen = [], set()
    for h in headings:
        base = prop_key(h)
        key, n = base, 2
        while key in seen:
            key, n = f"{base}_{n}", n + 1
        seen.add(key)
        out.append(key)
    return out


# --------------------------------------------------------------------------
# Interpreting cell values
# --------------------------------------------------------------------------
def fraction_of(raw: str):
    s = str(raw or "").strip()
    if not s:
        return None
    if s.lower() in YES:
        return 1.0
    if s.lower() in NO:
        return 0.0
    pct = s.endswith("%")
    try:
        x = float(s.rstrip("%").strip())
    except ValueError:
        return None
    if pct or x > 1:
        x /= 100.0
    return max(0.0, min(1.0, x))


def status_of(raw: str, complete: str):
    """(atlas status, whether the sheet said so, the sheet's own word if it wasn't one the atlas uses)."""
    s = raw.strip()
    if s:
        st = STATUS_INDEX.get(_norm(s))
        if st:
            return st, True, ""
    frac = fraction_of(complete)
    if frac is not None:
        st = "planned" if frac <= 0 else "done" if frac >= 1 else "in-progress"
        return st, True, s
    if not s and complete.strip():
        st = STATUS_INDEX.get(_norm(complete))
        if st:
            return st, True, ""
        return "planned", False, complete.strip()
    return "planned", False, s


def dal_of(raw: str):
    """DAL letters, [] for every DAL, or None if the cell can't be read."""
    s = one_line(raw).upper()
    if not s or s in ("ALL", "ANY", "ALL DALS", "N/A", "NA", "-", "–", "TBD", "TBC", "NONE", "?"):
        return []
    s = re.sub(r"\bDALS?\b", " ", s).strip()
    m = re.fullmatch(r"([A-D])\s*(?:-|–|TO)\s*([A-D])", s)
    if m:
        lo, hi = sorted((m.group(1), m.group(2)))
        letters = [d for d in atlas.DALS if lo <= d <= hi]
    else:
        letters = []
        for tok in re.split(r"[\s,/;&+]+|\bAND\b|\bOR\b", s):
            if not tok:
                continue
            if not re.fullmatch(r"[A-D]{1,4}", tok):
                return None
            letters.extend(tok)
        letters = [d for d in atlas.DALS if d in letters]
    return [] if len(letters) == 4 else letters


UNIT_NAMES = (("hour", "hours"), ("hr", "hours"), ("week", "weeks"), ("wk", "weeks"), ("point", "points"),
              ("pt", "points"), ("sp", "points"), ("day", "days"))


def unit_of(text: str) -> str:
    t = text.lower()
    if re.fullmatch(r"\s*\[?h+\]?:mm(?::ss)?\s*", t):
        return "hours"
    for word, unit in UNIT_NAMES:
        if word in t:
            return unit
    return {"h": "hours", "w": "weeks", "d": "days", "p": "points"}.get(t.strip(), "")


def estimate_of(raw: str, base: str = "days"):
    """(value to store, unit written in the cell or ''). A number in the base unit is stored bare."""
    s = one_line(raw).rstrip("?").strip()
    if not s:
        return "", ""
    hm = re.fullmatch(r"(\d+):([0-5]\d)(?::[0-5]\d)?", s)                # 07:30 from a time-formatted cell
    if hm:
        s = _num_text(int(hm.group(1)) + int(hm.group(2)) / 60.0) + " h"
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*([A-Za-z\-]*)\.?", s)
    if not m:
        return s, ""
    num = m.group(1)
    num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", num) else num.replace(",", ".")
    num = _num_text(float(num))
    unit = unit_of(m.group(2)) if m.group(2) else ""
    return (num if unit in ("", base) else f"{num} {m.group(2)}"), unit


def lines_of(raw: str) -> list:
    return [ln.strip() for ln in str(raw or "").split("\n") if ln.strip()]


def subtask_of(text: str):
    """(mark, text) from a line such as '- [x] Draft it' or '• Draft it'."""
    m = re.match(r"^(?:[-*+•▪◦]\s*)?(?:\[([ xX/\-])\]\s*)?(.*)$", text)
    mark, body = (m.group(1) or " "), m.group(2).strip()
    return {"x": "x", "X": "x", "/": "/", "-": "-"}.get(mark, " "), body


def split_refs(raw: str) -> list:
    return [p.strip() for p in re.split(r"[,;\n]+", raw or "") if p.strip()]


# --------------------------------------------------------------------------
# Writing notes
# --------------------------------------------------------------------------
SAFE_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-/()+]*$")


def yaml_scalar(v) -> str:
    s = CONTROL.sub(" ", one_line(v) if "\n" in str(v) else str(v))
    if s and SAFE_SCALAR.match(s) and s == s.strip() and s.lower() not in (
            "true", "false", "null", "yes", "no", "on", "off", "~"):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t") + '"'


INLINE_LISTS = ("depends_on", "dal", "plus_ones")


def fm_lines(k: str, v) -> list:
    if isinstance(v, list):
        if k in INLINE_LISTS or not v:
            return [f"{k}: [{', '.join(yaml_scalar(x) for x in v)}]"]
        return [f"{k}:"] + [f"  - {yaml_scalar(x)}" for x in v]
    if isinstance(v, bool):
        return [f"{k}: {'true' if v else 'false'}"]
    if v is None or v == "":
        return [f"{k}:"]
    return [f"{k}: {yaml_scalar(v)}"]


def frontmatter_text(fm: dict) -> str:
    out = ["---"]
    for k, v in fm.items():
        out.extend(fm_lines(k, v))
    out.append("---")
    return "\n".join(out) + "\n"


def edit_note(text: str, changes: dict, remove: set, add_body: str) -> str:
    """Change some frontmatter keys of an existing note and leave every other line as it was."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return frontmatter_text(changes) + text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        raise ImportProblem("a note's frontmatter has no closing ---")
    blocks, cur = [], None
    for line in lines[1:end]:
        bare = atlas._strip_comment(line.rstrip())
        m = None
        if bare.strip() and not line[:1].isspace() and not line.startswith("-"):
            m = atlas.KEY_RE.match(bare)
        if m:
            cur = [atlas.key_of(m), [line]]
            blocks.append(cur)
        elif cur is not None:
            cur[1].append(line)
        else:
            blocks.append([None, [line]])
    out, done = [], set()
    for key, blines in blocks:
        if key in remove:
            continue
        if key in changes:
            out.extend(fm_lines(key, changes[key]))
            done.add(key)
        else:
            out.extend(blines)
    for key, v in changes.items():
        if key not in done:
            out.extend(fm_lines(key, v))
    rest = lines[end:]
    if add_body:
        while rest and rest[-1] == "":
            rest.pop()
        rest += [add_body, ""]
    return "\n".join(["---"] + out + rest)


BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')


def safe_name(s: str, limit: int = 90) -> str:
    s = re.sub(r"\s+", " ", BAD_NAME.sub("-", s)).strip().lstrip("._ ").rstrip(". ")
    if len(s) > limit:
        s = s[:limit].rstrip(" .-")
    if s.upper() in WINDOWS_RESERVED:
        s = "_" + s
    return s or "Untitled"


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# --------------------------------------------------------------------------
# The import
# --------------------------------------------------------------------------
class Item:
    def __init__(self, kind: str, title: str, where: str):
        self.kind, self.title, self.where = kind, one_line(title), where
        self.id = ""
        self.raw_id = ""
        self.parent = None          # Item
        self.fields = {}            # frontmatter values from the sheet
        self.props = {}             # extra columns
        self.description = ""
        self.subtasks = []          # [(mark, text)]
        self.deps_raw = []          # references as written
        self.ms_raw = ""
        self.est_parts = []         # estimates from subtask rows, used if the task has none
        self.defaults = set()       # fields filled with a default rather than read from the sheet
        self.status_known = False   # the sheet gave a status the atlas recognises


class Importer:
    def __init__(self, args, existing: dict):
        self.args = args
        self.existing = existing        # id (lower) -> note record (see scan_existing)
        self.problems = []              # things to look at, with sheet rows
        self.info = []                  # what was understood
        self.workstreams, self.areas, self.tasks, self.milestones = [], [], [], []
        self.taken = set() if args.fresh else set(existing)
        self.claimed = set()            # existing note IDs already matched to a sheet item
        self.units = {}                 # units written in estimate cells, e.g. {"hours": 3}
        self.heading_unit = ""          # unit named in the estimate heading
        self.said = set()
        self.sub_numbers = {}           # row numbers of subtask rows -> their task
        self.extra_keys = []            # [(heading, column, property name)]

    # -- helpers ---------------------------------------------------------
    def base_unit(self) -> str:
        """The unit a bare estimate is in: the one the estimate heading names, else days."""
        return self.heading_unit or "days"

    def problem(self, where: str, msg: str):
        self.problems.append(f"{where}: {msg}" if where else msg)

    def once(self, key: str, msg: str):
        if key not in self.said:
            self.said.add(key)
            self.info.append(msg)

    @staticmethod
    def find(items: list, ref: str, titles: bool = True):
        """The item whose ID, or else whose name, is exactly ref (ignoring case)."""
        k = _key(ref)
        if not k:
            return None
        for it in items:
            if k in (_key(it.id), _key(it.raw_id)):
                return it
        if titles:
            for it in items:
                if _key(it.title) == k:
                    return it
        return None

    def ws_for(self, ref: str, where: str):
        name = one_line(ref) or "Unassigned"
        if not one_line(ref):
            self.once("unassigned", "Tasks with no workstream went into one called Unassigned")
        it = self.find(self.workstreams, name)
        if not it:
            it = Item("workstream", name, where)
            self.workstreams.append(it)
        return it

    def area_for(self, ref: str, ws, where: str):
        k = _key(ref)
        for by_title in (False, True):
            for it in self.areas:
                names = (_key(it.title),) if by_title else (_key(it.id), _key(it.raw_id))
                if k and k in names and (ws is None or it.parent is ws or it.parent is None):
                    if it.parent is None:
                        it.parent = ws
                    return it
        it = Item("area", one_line(ref) or "General", where)
        it.parent = ws
        self.areas.append(it)
        return it

    def existing_like(self, kind: str, ref: str, titles: bool = True):
        if self.args.fresh or not ref:
            return None
        k = _key(ref)
        for rec in self.existing.values():
            if rec["kind"] == kind and rec["id"].lower() not in self.claimed and (
                    _key(rec["id"]) == k or (titles and _key(rec["title"]) == k)):
                return rec
        return None

    # -- reading the sheets ------------------------------------------------
    def run(self, book: list):
        overrides = dict(self.args.col)
        hidden = [n for n, _r, h in book if h and n != self.args.sheet]
        if hidden:
            self.info.append("Skipped hidden sheets: " + ", ".join(f'"{n}"' for n in hidden))
        sheets = [(n, rows) for n, rows, h in book
                  if (not h or n == self.args.sheet) and any(any(str(c).strip() for c in r) for r in rows)]
        if not sheets:
            raise ImportProblem("the spreadsheet is empty")
        for field, heading in overrides.items():
            if not any(_norm(heading) in {_norm(c) for r in rows[:20] for c in r} for _n, rows in sheets):
                raise ImportProblem(f'--col {field}={heading}: no column is headed "{heading}"')
        role_of = {}
        for name, _rows in sheets:
            for role, names in SHEET_ROLES.items():
                if _norm(name) in {_norm(n) for n in names}:
                    role_of.setdefault(role, name)
        task_sheet = self.args.sheet or role_of.get("tasks")
        if task_sheet and task_sheet not in {n for n, _ in sheets}:
            raise ImportProblem(f'there is no sheet called "{task_sheet}". Sheets: ' + ", ".join(n for n, _ in sheets))
        if not task_sheet:
            others = {role_of.get(r) for r in ("workstreams", "areas", "milestones")}
            for name, rows in sheets:
                if name not in others and find_header(rows, TASK_FIELDS, overrides):
                    task_sheet = name
                    break
        if not task_sheet:
            raise ImportProblem("couldn't find a sheet with a Task, Title or Name column. Name the sheet with --sheet "
                                "and the title column with --col title=HEADING")
        book_d = dict(sheets)
        for role, fields in (("workstreams", WS_FIELDS), ("areas", AREA_FIELDS), ("milestones", MS_FIELDS)):
            name = role_of.get(role)
            if name and name != task_sheet:
                self.read_side_sheet(role, name, book_d[name], fields)
        rows = book_d[task_sheet]
        if self.args.header_row is not None:
            hr = self.args.header_row - 1
            if not 0 <= hr < len(rows):
                raise ImportProblem(f"--header-row {self.args.header_row} is outside the sheet")
            found = find_header([rows[hr]], TASK_FIELDS, overrides)
            if found:
                found = (hr,) + found[1:]
        else:
            found = find_header(rows, TASK_FIELDS, overrides)
        if not found:
            raise ImportProblem(f'couldn\'t find the heading row in "{task_sheet}": it needs a column such as Task, '
                                "Title or Name. Use --col title=HEADING to name it")
        hr, cols, extras, notes = found
        for n in notes:
            self.info.append(f"{task_sheet}: {n}")
        for field, heading in overrides.items():
            if field not in cols:
                raise ImportProblem(f'--col {field}={heading}: no column headed "{heading}" in "{task_sheet}"')
        self.info.append(f'Read "{task_sheet}": headings on row {hr + 1}; ' + ", ".join(
            f"{f} = {rows[hr][c]}" for f, c in sorted(cols.items(), key=lambda kv: kv[1])))
        outline = "level" in cols and not self.args.flat
        if "level" in cols and not outline:
            extras.append((rows[hr][cols["level"]], cols.pop("level")))
        keys = unique_keys([h for h, _c in extras])
        self.extra_keys = [(h, c, k) for (h, c), k in zip(extras, keys)]
        if self.extra_keys:
            self.info.append("Kept as extra properties: " + ", ".join(f'"{h}" as {k}' for h, _c, k in self.extra_keys))
        if "estimate" in cols:
            m = re.search(r"[\(\[]([^\)\]]+)", rows[hr][cols["estimate"]])
            self.heading_unit = unit_of(m.group(1)) if m else ""
        if outline:
            self.read_outline(task_sheet, rows, hr, cols)
        else:
            self.read_rows(task_sheet, rows, hr, cols)

    def read_side_sheet(self, role: str, name: str, rows: list, fields: dict):
        found = find_header(rows, fields, {})
        if not found:
            self.info.append(f'Skipped "{name}": no Name or Title column')
            return
        hr, cols, _extras, _notes = found
        n = 0
        for r in range(hr + 1, len(rows)):
            row, where = rows[r], f"{name} row {r + 1}"
            title = one_line(cell(row, cols.get("title")))
            if not title:
                continue
            n += 1
            if role == "workstreams":
                it = Item("workstream", title, where)
                hint = cell(row, cols.get("map_hint")).lower()
                if hint and hint not in atlas.MAP_HINTS:
                    self.problem(where, f'map hint "{hint}" isn\'t one of: {", ".join(atlas.MAP_HINTS)}; left out')
                    hint = ""
                it.fields.update(map_hint=hint, order=cell(row, cols.get("order")))
                self.workstreams.append(it)
            elif role == "areas":
                ws_ref = cell(row, cols.get("workstream"))
                it = Item("area", title, where)
                it.parent = self.ws_for(ws_ref, where) if ws_ref else None
                self.areas.append(it)
            else:
                it = Item("milestone", title, where)
                it.fields["target"] = one_line(cell(row, cols.get("target")))
                self.milestones.append(it)
            it.raw_id = one_line(cell(row, cols.get("id")))
            it.description = cell(row, cols.get("description"))
        self.info.append(f'Read "{name}": {plural(n, role[:-1])}')

    def task_from_row(self, row: list, cols: dict, where: str, area):
        t = Item("task", cell(row, cols.get("title")), where)
        t.parent = area
        t.raw_id = one_line(cell(row, cols.get("id")))
        status, known, raw_status = status_of(cell(row, cols.get("status")), cell(row, cols.get("complete")))
        t.status_known = known
        if not known:
            t.defaults.add("status")
        if raw_status:
            self.problem(where, f'status "{raw_status}" isn\'t one the atlas uses; set to {status} and kept as sheet_status')
            t.props["sheet_status"] = one_line(raw_status)
        kind_raw = one_line(cell(row, cols.get("kind")))
        kind = KIND_INDEX.get(_norm(kind_raw), "")
        if kind_raw and not kind:
            t.props["task_type"] = kind_raw
        owner = one_line(re.sub(r"\[[^\]]*\]", "", cell(row, cols.get("owner")))).strip(" ,;")
        est, unit = estimate_of(cell(row, cols.get("estimate")), self.base_unit())
        if unit and unit != self.base_unit():
            self.units[unit] = self.units.get(unit, 0) + 1
        dal_raw = cell(row, cols.get("dal"))
        dal = dal_of(dal_raw)
        if dal is None:
            self.problem(where, f'DAL "{one_line(dal_raw)}" isn\'t a list of A, B, C or D; left blank, which means every DAL')
            dal = []
        t.fields.update(kind=kind, status=status, owner=owner, estimate=est, dal=dal,
                        deliverable=one_line(cell(row, cols.get("deliverable"))),
                        tracker=one_line(cell(row, cols.get("tracker"))))
        t.ms_raw = one_line(cell(row, cols.get("milestone")))
        t.deps_raw = split_refs(cell(row, cols.get("depends_on")))
        t.description = cell(row, cols.get("description"))
        t.subtasks = [subtask_of(x) for x in lines_of(cell(row, cols.get("subtasks")))]
        for _heading, c, key in self.extra_keys:
            v = cell(row, c)
            if v:
                t.props[key] = [x.strip().replace(" ", "-") for x in split_refs(v)] if key == "tags" else one_line(v)
        self.tasks.append(t)
        return t

    def read_rows(self, sheet: str, rows: list, hr: int, cols: dict):
        if "area" not in cols and "workstream" not in cols and not self.areas:
            raise ImportProblem(f'"{sheet}" has no Area (or Epic) and no Workstream column, so tasks can\'t be placed. '
                                "Add them, use --col area=HEADING, or use an outline with a Level or WBS column")
        if "area" not in cols:
            self.info.append("No Area or Epic column: each workstream gets one area called General")
        n, last_ws, last_area, fill_ws, fill_area = 0, "", "", 0, 0
        for r in range(hr + 1, len(rows)):
            row, where = rows[r], f"{sheet} row {r + 1}"
            if not cell(row, cols.get("title")):
                if any(str(c).strip() for c in row):
                    self.problem(where, "no task name, so the row was skipped")
                continue
            ws_ref, area_ref = one_line(cell(row, cols.get("workstream"))), one_line(cell(row, cols.get("area")))
            # Blank cells under a filled one mean "same as above", as in a sheet grouped by workstream.
            if not ws_ref and last_ws and "workstream" in cols:
                ws_ref, fill_ws = last_ws, fill_ws + 1
            if not area_ref and last_area and "area" in cols and ws_ref == last_ws:
                area_ref, fill_area = last_area, fill_area + 1
            last_ws, last_area = ws_ref, area_ref
            if area_ref:
                known = self.find(self.areas, area_ref)
                if known and known.parent is not None and not ws_ref:
                    area = known
                else:
                    area = self.area_for(area_ref, self.ws_for(ws_ref, where), where)
            else:
                area = self.area_for("General", self.ws_for(ws_ref, where), where)
            self.task_from_row(row, cols, where, area)
            n += 1
        if fill_ws or fill_area:
            parts = [plural(fill_ws, "row") + " with a blank workstream" if fill_ws else "",
                     plural(fill_area, "row") + " with a blank area" if fill_area else ""]
            self.info.append("Took the value from the row above for " + " and ".join(p for p in parts if p))
        self.info.append(f"One task per row: {plural(n, 'task')}")

    def depth_of(self, raw: str, wbs: bool):
        s = raw.strip()
        if not wbs and re.fullmatch(r"\d+(?:\.0+)?", s):
            return int(float(s))
        if re.fullmatch(r"\d+(?:\.\d+)*\.?", s):
            parts = [p for p in s.strip(".").split(".") if p != ""]
            while len(parts) > 1 and re.fullmatch(r"0+", parts[-1]):
                parts.pop()
            return len(parts)
        return None

    def read_outline(self, sheet: str, rows: list, hr: int, cols: dict):
        levels = [one_line(x).lower() for x in self.args.levels.split(",") if x.strip()]
        for need in ("workstream", "area", "task"):
            if need not in levels:
                raise ImportProblem(f"--levels must include {need}")
        wi, ai, ti = levels.index("workstream"), levels.index("area"), levels.index("task")
        if not wi < ai < ti:
            raise ImportProblem("--levels must list workstream, then area, then task")
        names = {i: prop_key(x) for i, x in enumerate(levels) if x not in ("workstream", "area", "task")}
        self.info.append("Outline: " + ", ".join(f"level {i + 1} = {x}" for i, x in enumerate(levels[:ti + 1]))
                         + ", deeper = subtask" + "".join(f'; "{levels[i]}" kept as {k}' for i, k in names.items()))
        wbs = _norm(sheet_heading(rows, hr, cols, "level")) == "wbs"
        ws = area = task = None
        props = {}                       # level index -> (property name, value)
        n = 0
        for r in range(hr + 1, len(rows)):
            row, where = rows[r], f"{sheet} row {r + 1}"
            title = one_line(cell(row, cols.get("title")))
            if not title:
                if any(str(c).strip() for c in row):
                    self.problem(where, "no name, so the row was skipped")
                continue
            lv = cell(row, cols.get("level"))
            depth = self.depth_of(lv, wbs)
            if not depth:
                self.problem(where, f'level "{lv}" isn\'t a number or a WBS code such as 1.2.3, so the row was skipped')
                continue
            i = depth - 1
            role = "subtask" if i > ti else levels[i]
            if role != "subtask":
                # A row at one level closes everything at that level and below it.
                props = {j: v for j, v in props.items() if j < i}
                if i <= wi:
                    ws = None
                if i <= ai:
                    area = None
                task = None
            above = lambda limit: {k: v for j, (k, v) in props.items() if j < limit}  # noqa: E731
            if role == "workstream":
                ws = self.find(self.workstreams, title) or Item("workstream", title, where)
                if ws not in self.workstreams:
                    self.workstreams.append(ws)
                ws.raw_id = ws.raw_id or one_line(cell(row, cols.get("id")))
                ws.description = ws.description or cell(row, cols.get("description"))
            elif role == "area":
                area = self.area_for(title, ws or self.ws_for("", where), where)
                area.raw_id = area.raw_id or one_line(cell(row, cols.get("id")))
                area.description = area.description or cell(row, cols.get("description"))
                area.props.update(above(ai))
            elif role == "task":
                if area is None:
                    area = self.area_for("General", ws or self.ws_for("", where), where)
                task = self.task_from_row(row, cols, where, area)
                for k, v in above(ti).items():
                    task.props.setdefault(k, v)
                n += 1
            elif role == "subtask":
                if task is None:
                    self.problem(where, "a subtask with no task above it, so the row was skipped")
                    continue
                st, _known, _raw = status_of(cell(row, cols.get("status")), cell(row, cols.get("complete")))
                task.subtasks.append(("x" if st in atlas.COMPLETE else "/" if st in ("in-progress", "review") else " ", title))
                if re.fullmatch(r"\d+", cell(row, cols.get("id"))):
                    self.sub_numbers[cell(row, cols.get("id"))] = task
                est, _unit = estimate_of(cell(row, cols.get("estimate")), self.base_unit())
                if est:
                    task.est_parts.append(est)
            else:
                props[i] = (names[i], title)
        for t in self.tasks:
            if not t.fields.get("estimate") and t.est_parts:
                try:
                    t.fields["estimate"] = _num_text(sum(float(x) for x in t.est_parts))
                    self.info.append(f"{t.where}: no estimate, so used the sum of its subtasks ({t.fields['estimate']})")
                except ValueError:
                    pass
        self.info.append(plural(n, "task"))

    # -- IDs and references -------------------------------------------------
    def clean_id(self, raw: str, where: str) -> str:
        cid = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.strip()).strip("-.")
        if cid and cid != raw.strip():
            self.problem(where, f'ID "{raw}" changed to "{cid}" so it works in file names and links')
        return cid

    def generated_id(self, title: str, kind: str = "") -> str:
        every = re.findall(r"[A-Za-z0-9]+", title)
        # "of" in "Ways of Working" is skipped; the "A" in "Phase A" is a label, so it stays.
        words = [w for i, w in enumerate(every)
                 if w.lower() not in STOP_WORDS or (w != w.lower() and i > 0)] or every
        words = [w for w in words if w.lower() not in GENERIC_WORDS] or words      # "CI epic" -> CI
        if len(words) == 1 and len(words[0]) < 2 and len(every) > 1:
            words = every                                                          # "S&A" -> SA
        if not words:
            base = "X"
        elif len(words) == 1:
            base = words[0][:4].upper()
        else:
            base = "".join(w[0] for w in words)[:4].upper()
        if len(base) < 2 and words:
            base = words[0][:3].upper()
        if base.isdigit():                       # plain numbers are kept for Microsoft Project row numbers
            base = (kind[:1] or "X").upper() + base
        cand, n = base, 2
        while cand.lower() in self.taken:
            cand, n = f"{base}{n}", n + 1
        self.taken.add(cand.lower())
        return cand

    def reuse_existing(self, it) -> str:
        """Without --fresh, an item with no ID in the sheet takes the ID of an unclaimed note with its type and name."""
        if self.args.fresh:
            return ""
        for key in sorted(self.existing):
            rec = self.existing[key]
            if key in self.claimed or rec["kind"] != it.kind or _key(rec["title"]) != _key(it.title):
                continue
            if it.parent is not None and rec["parent"] and rec["parent"].lower() != it.parent.id.lower():
                continue
            self.claimed.add(key)
            return rec["id"]
        return ""

    def assign_ids(self):
        groups = (self.workstreams, self.areas, self.milestones, self.tasks)
        if any(re.fullmatch(r"\d+", it.raw_id or "") for items in groups for it in items):
            self.info.append("IDs that are plain numbers (as Microsoft Project exports have) are used to match "
                             "dependencies; those items get IDs made from their names instead")
        seen = {}
        for items in groups:
            for it in items:
                if it.raw_id and not re.fullmatch(r"\d+", it.raw_id):
                    cid = self.clean_id(it.raw_id, it.where)
                    if not cid:
                        continue
                    if cid.lower() in seen:
                        raise ImportProblem(f"ID {cid} is used twice: {seen[cid.lower()]} and {it.where}")
                    seen[cid.lower()] = it.where
                    rec = None if self.args.fresh else self.existing.get(cid.lower())
                    if rec and rec["kind"] == it.kind:
                        cid = rec["id"]                 # the note's own spelling of its ID
                        self.claimed.add(cid.lower())
                    it.id = cid
                    self.taken.add(cid.lower())
        for items in groups[:3]:
            for it in items:
                if not it.id:
                    it.id = self.reuse_existing(it) or self.generated_id(it.title, it.kind)
                    self.taken.add(it.id.lower())
        counters = {}
        for t in self.tasks:
            if t.id:
                continue
            t.id = self.reuse_existing(t)
            if t.id:
                continue
            prefix = t.parent.id
            n = counters.get(prefix, 0)
            while True:
                n += 1
                cand = f"{prefix}-{n:02d}"
                if cand.lower() not in self.taken:
                    break
            counters[prefix] = n
            t.id = cand
            self.taken.add(cand.lower())

    def milestone_for(self, label: str, where: str, prefix_count: dict):
        ms = self.find(self.milestones, label)
        if ms:
            return ms
        # "M1 Foundations" is milestone M1, called Foundations. "Q1 2027" and "FY27 Q1" are names as they stand.
        m = re.match(r"^([A-Za-z]{1,4}\d+(?:\.\d+)*)\s*[:\-–]?\s+(\S.*)$", label)
        if m and not re.search(r"[A-Za-z]{3,}", m.group(2)):
            m = None
        if m:
            ms = self.find(self.milestones, m.group(1), titles=False)
            if ms:
                return ms
        rec = self.existing_like("milestone", label) or (self.existing_like("milestone", m.group(1), titles=False) if m else None)
        if rec:
            ms = Item("milestone", rec["title"], where)
            ms.id = rec["id"]
            self.claimed.add(rec["id"].lower())
            self.milestones.append(ms)
            return ms
        ms = Item("milestone", label, where)
        if re.fullmatch(r"[A-Za-z0-9._-]+", label) and label.lower() not in self.taken:
            ms.id = label
        elif m and prefix_count.get(m.group(1).lower(), 0) == 1 and m.group(1).lower() not in self.taken:
            ms.id, ms.title = m.group(1), m.group(2)
        else:
            base = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.") or "M"
            cand, n = base, 2
            while cand.lower() in self.taken:
                cand, n = f"{base}-{n}", n + 1
            ms.id = cand
        self.taken.add(ms.id.lower())
        self.milestones.append(ms)
        return ms

    def find_task(self, ref: str):
        """(task, problem) for a dependency reference: an exact ID, else one task with exactly that name."""
        k = _key(ref)
        for t in self.tasks:
            if k in (_key(t.id), _key(t.raw_id)):
                return t, ""
        named = [t for t in self.tasks if _key(t.title) == k]
        if len(named) == 1:
            return named[0], ""
        if len(named) > 1:
            return None, (f'depends on "{ref}", which is the name of {len(named)} tasks '
                          f'({", ".join(t.id for t in named)}), so that link was left out; use the ID')
        head = re.split(r"[\s:]+", ref.strip(), maxsplit=1)[0]
        if head != ref.strip():
            for t in self.tasks:
                if _key(head) in (_key(t.id), _key(t.raw_id)):
                    return t, ""
        return None, f'depends on "{ref}", which isn\'t a task in the sheet, so that link was left out'

    def resolve(self):
        labels = []
        for t in self.tasks:
            if t.ms_raw and t.ms_raw not in labels:
                labels.append(t.ms_raw)
        prefix_count = {}
        for lab in labels:
            m = re.match(r"^([A-Za-z]{1,4}\d+(?:\.\d+)*)(?:\s*[:\-–]?\s+\S.*)?$", lab)
            if m:
                prefix_count[m.group(1).lower()] = prefix_count.get(m.group(1).lower(), 0) + 1
        by_label = {}
        for lab in sorted(labels, key=lambda s: " " in s):    # bare IDs such as "M1" first
            by_label[lab] = self.milestone_for(lab, "", prefix_count)
        by_number = {}
        for it in self.tasks + self.areas + self.workstreams:
            if re.fullmatch(r"\d+", it.raw_id or ""):
                by_number.setdefault(it.raw_id, it)
        for k, v in self.sub_numbers.items():
            by_number.setdefault(k, v)
        for t in self.tasks:
            if t.ms_raw:
                t.fields["milestone"] = by_label[t.ms_raw].id
            deps = []
            for ref in t.deps_raw:
                target, why = None, ""
                m = re.fullmatch(r"(\d+)\s*(?:FS|SS|FF|SF)?\s*(?:[+-].*)?", ref, re.I)
                if m and m.group(1) in by_number:
                    hit = by_number[m.group(1)]
                    if hit.kind == "area":
                        for x in self.tasks:
                            if x.parent is hit and x is not t and x.id not in deps:
                                deps.append(x.id)
                        self.info.append(f"{t.where}: depends on {hit.title}, so on every task in it")
                        continue
                    if hit.kind == "workstream":
                        self.problem(t.where, f"depends on the whole of {hit.title}; that link was left out, so point "
                                              "it at the tasks it needs")
                        continue
                    target = hit
                else:
                    target, why = self.find_task(ref)
                if target is None:
                    self.problem(t.where, why)
                elif target is t:
                    self.problem(t.where, "depends on itself, so that link was left out")
                elif target.id not in deps:
                    deps.append(target.id)
            t.fields["depends_on"] = deps

    # -- notes ----------------------------------------------------------------
    def notes(self):
        """(item, frontmatter dict, body) for everything to write."""
        out = []
        for w in self.workstreams:
            fm = {"type": "workstream", "id": w.id, "title": w.title}
            if w.fields.get("map_hint"):
                fm["map_hint"] = w.fields["map_hint"]
            if w.fields.get("order"):
                fm["order"] = w.fields["order"]
            out.append((w, fm, w.description))
        for a in self.areas:
            fm = {"type": "area", "id": a.id, "title": a.title, "parent": a.parent.id if a.parent else ""}
            fm.update(a.props)
            out.append((a, fm, a.description))
        for m in self.milestones:
            fm = {"type": "milestone", "id": m.id, "title": m.title}
            if m.fields.get("target"):
                fm["target"] = m.fields["target"]
            out.append((m, fm, m.description))
        for t in self.tasks:
            f = t.fields
            fm = {"type": "task", "id": t.id, "title": t.title, "parent": t.parent.id}
            for k in ("kind", "status", "owner", "milestone", "estimate", "dal", "depends_on", "deliverable", "tracker"):
                v = f.get(k)
                if k == "status" or v:
                    fm[k] = v
            fm.update(t.props)
            body = t.description
            if t.subtasks:
                body = (body + "\n\n" if body else "") + "## Subtasks\n" + "\n".join(f"- [{mk}] {tx}" for mk, tx in t.subtasks)
            out.append((t, fm, body))
        return out


FOLDERS = {"workstream": "workstreams", "area": "areas", "task": "tasks", "milestone": "milestones"}


def scan_existing(roadmap: Path) -> dict:
    """id (lower) -> {path, kind, title, parent (an ID), id, example} for every typed note under roadmap/."""
    found, stems = {}, {}
    if not roadmap.is_dir():
        return found
    for path in sorted(roadmap.rglob("*.md")):
        if any(p.startswith((".", "_")) for p in path.relative_to(roadmap).parts):
            continue
        try:
            fm_text, _body, first = atlas.split_note(path.read_text(encoding="utf-8"))
            fm = atlas.parse_frontmatter(fm_text, first) if fm_text is not None else {}
        except (atlas.FrontmatterError, UnicodeDecodeError):
            continue
        kind, nid = atlas.as_str(fm.get("type")).lower(), atlas.as_str(fm.get("id"))
        if kind in atlas.TYPES and nid:
            title = atlas.as_str(fm.get("title"))
            if not title:
                title = path.stem[len(nid):].strip(" -–—:") if path.stem.startswith(nid) else path.stem
            found[nid.lower()] = {"path": path, "kind": kind, "title": title, "id": nid,
                                  "parent": atlas.clean_ref(atlas.as_str(fm.get("parent"))),
                                  "example": atlas.as_str(fm.get("example")).lower() in ("true", "yes", "1")}
            stems[path.stem.lower()] = nid
    titles = {}
    for rec in found.values():
        titles.setdefault(_key(rec["title"]), rec["id"])
    for rec in found.values():                  # parent written as an ID, a [[link]], a file name or a title
        p = rec["parent"]
        if p and p.lower() not in found:
            base = p.rsplit("/", 1)[-1].lower()
            rec["parent"] = stems.get(base) or titles.get(_key(p)) or p
    return found


def plan_writes(imp: Importer, roadmap: Path, existing: dict, args):
    """[(action, path, text, item)] where action is create, update, same or keep."""
    plan, used, names = [], set(), {}
    removing = {rec["path"].resolve() for rec in existing.values()
                if rec["kind"] in FOLDERS or rec["example"]} if args.fresh else set()

    def taken_name(folder: Path, name: str) -> bool:
        if folder not in names:
            names[folder] = {p.name.lower() for p in folder.glob("*.md") if p.resolve() not in removing} if folder.is_dir() else set()
        return name.lower() in names[folder] or str(folder / name).lower() in used

    for it, fm, body in imp.notes():
        rec = None if args.fresh else existing.get(it.id.lower())
        if rec and rec["kind"] == it.kind:
            path = rec["path"]
            used.add(str(path).lower())
            if not args.update:
                plan.append(("keep", path, None, it))
                continue
            text = path.read_text(encoding="utf-8")
            fm_text, old_body, first = atlas.split_note(text)
            old = atlas.parse_frontmatter(fm_text, first) if fm_text is not None else {}
            changes = {}
            for k, v in fm.items():
                if k in ("id", "type") or k in it.defaults or v in (None, "", []):
                    continue
                if k == "title" and _key(v) == _key(rec["title"]):
                    continue
                if old.get(k) != v:
                    changes[k] = v
            remove = {"sheet_status"} if it.status_known and "sheet_status" in old and "sheet_status" not in fm else set()
            add_body = body.strip() if body and body.strip() and not old_body.strip() else ""
            if not changes and not remove and not add_body:
                plan.append(("same", path, None, it))
            else:
                plan.append(("update", path, edit_note(text, changes, remove, add_body), it))
            continue
        folder = roadmap / FOLDERS[it.kind]
        if it.kind in ("workstream", "area"):
            stem = safe_name(it.title)
        elif re.sub(r"[^a-z0-9]", "", it.title.lower()) == re.sub(r"[^a-z0-9]", "", it.id.lower()):
            stem = safe_name(it.title)              # "Q3 2026", not "Q3-2026 Q3 2026"
        else:
            stem = safe_name(f"{it.id} {it.title}")
        name = f"{stem}.md"
        if taken_name(folder, name):
            name = f"{safe_name(it.id + ' ' + it.title)}.md"
        n = 2
        while taken_name(folder, name):
            name = f"{safe_name(it.id + ' ' + it.title)} ({n}).md"
            n += 1
        path = folder / name
        used.add(str(path).lower())
        plan.append(("create", path, frontmatter_text(fm) + (body.strip() + "\n" if body and body.strip() else ""), it))
    return plan, sorted(removing)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Turn a roadmap spreadsheet into FPGA Team Atlas notes.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Headings it recognises: run with --columns. Full guide: README.md")
    ap.add_argument("spreadsheet", nargs="?", type=Path, help=".xlsx, .xlsm or .csv file")
    ap.add_argument("--root", type=Path, default=HERE.parent, help="repository and vault root (default: the folder above tools/)")
    ap.add_argument("--roadmap", default="roadmap", help="folder of roadmap notes, relative to the root")
    ap.add_argument("--sheet", help="the sheet with the tasks (default: one called Tasks, or the first that fits)")
    ap.add_argument("--header-row", type=int, help="row number of the headings, if it can't be found")
    ap.add_argument("--col", action="append", default=[], metavar="FIELD=HEADING",
                    help="use the column with this heading for a field, e.g. --col area=Epic (repeatable)")
    ap.add_argument("--levels", default="workstream,area,task",
                    help="outline layout: what each level is, top first (default: workstream,area,task). Other "
                         "names become a property on everything below, e.g. workstream,area,thread,task")
    ap.add_argument("--flat", action="store_true", help="ignore a Level or WBS column and read one task per row")
    ap.add_argument("--fresh", action="store_true",
                    help="remove every workstream, area, task and milestone note, and the example requests, first; "
                         "then write the roadmap from the sheet alone. Your own requests stay")
    ap.add_argument("--update", action="store_true",
                    help="also write the sheet's values into notes that already exist (their text and checklists are kept)")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen without writing anything")
    ap.add_argument("--columns", action="store_true", help="list the headings that are recognised, then stop")
    args = ap.parse_args(argv)

    if args.columns:
        for title, fields in (("Tasks sheet", TASK_FIELDS), ("Workstreams sheet", WS_FIELDS),
                              ("Areas sheet", AREA_FIELDS), ("Milestones sheet", MS_FIELDS)):
            print(title)
            for f, names in fields.items():
                print(f"  {f:<12} {', '.join(names)}")
        return 0
    if not args.spreadsheet:
        ap.error("give the spreadsheet to import, or --columns")
    pairs = []
    for c in args.col:
        if "=" not in c:
            ap.error(f"--col {c}: write it as FIELD=HEADING, e.g. --col area=Epic")
        f, h = c.split("=", 1)
        f = f.strip().lower().replace("-", "_").replace(" ", "_")
        if f not in TASK_FIELDS:
            ap.error(f"--col {c}: {f} isn't a field. Fields: {', '.join(TASK_FIELDS)}")
        pairs.append((f, h.strip()))
    args.col = pairs

    root = args.root.resolve()
    roadmap = (root / args.roadmap).resolve()
    if not args.spreadsheet.is_file():
        print(f"error: {args.spreadsheet} not found", file=sys.stderr)
        return 2

    def shown(p: Path) -> str:
        try:
            return p.resolve().relative_to(root).as_posix()
        except ValueError:
            return str(p)

    try:
        existing = scan_existing(roadmap)
        book = read_book(args.spreadsheet)
        imp = Importer(args, existing)
        imp.run(book)
        if not imp.tasks:
            raise ImportProblem("found no tasks under the headings, so nothing was changed"
                                + ("" if not imp.problems else ":\n  " + "\n  ".join(imp.problems[:10])))
        imp.assign_ids()
        imp.resolve()
        plan, removed = plan_writes(imp, roadmap, existing, args)
    except ImportProblem as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"Importing {args.spreadsheet.name}" + (" (dry run: nothing will be written)" if args.dry_run else ""))
    for line in imp.info:
        print("  " + line)
    if imp.heading_unit and imp.heading_unit != "days":
        print(f"  The estimate heading says {imp.heading_unit}. Build with --estimate-unit {imp.heading_unit} (and add "
              "it to both build lines in .gitlab-ci.yml); otherwise the atlas reads estimates as days")
    if imp.units:
        odd = ", ".join(f"{u} ({n})" for u, n in sorted(imp.units.items(), key=lambda kv: -kv[1]))
        print(f"  Some estimates are written in a unit other than {imp.base_unit()}: {odd}. They were kept as written; "
              "the checks point them out so they can be converted")

    if removed and not args.dry_run:
        for path in removed:
            path.unlink()
    counts = {}
    for action, path, text, it in plan:
        counts.setdefault(action, {}).setdefault(it.kind, 0)
        counts[action][it.kind] += 1
        if not args.dry_run and action in ("create", "update"):
            write_text(path, text)

    def summary(action):
        c = counts.get(action, {})
        return ", ".join(plural(c[k], k) for k in ("workstream", "area", "milestone", "task") if c.get(k))

    verb = "Would " if args.dry_run else ""
    if removed:
        print(f"{verb}{'remove' if args.dry_run else 'Removed'} {plural(len(removed), 'existing note')} (--fresh)")
    for action, label in (("create", "create" if args.dry_run else "Created"), ("update", "update" if args.dry_run else "Updated")):
        if counts.get(action):
            print(f"{verb}{label} {summary(action)}")
    if args.dry_run:
        for p in [p for a, p, _t, _i in plan if a == "create"][:6]:
            print(f"  e.g. {shown(p)}")
    if counts.get("same"):
        print(f"Unchanged: {summary('same')}")
    if counts.get("keep"):
        print(f"Already notes, left as they are: {summary('keep')} (use --update to refresh them from the sheet)")
    if not args.fresh:
        in_sheet = {it.id.lower() for _a, _p, _t, it in plan}
        stray = [rec for k, rec in existing.items() if k not in in_sheet and rec["kind"] in FOLDERS]
        if stray:
            print(f"{plural(len(stray), 'note')} in {args.roadmap}/ aren't in the sheet and were left alone")

    if imp.problems:
        print(f"\nNeeds a look ({len(imp.problems)}):")
        for p in imp.problems[:60]:
            print("  " + p)
        if len(imp.problems) > 60:
            print(f"  ...and {len(imp.problems) - 60} more")

    if args.dry_run:
        print("\nNothing was written. Run again without --dry-run to import.")
        return 0
    chk = atlas.Checker()
    atlas.build_model(root, roadmap, chk)
    e, w, n = chk.count("error"), chk.count("warning"), chk.count("info")
    print(f"\nChecks: {plural(e, 'error')}, {plural(w, 'warning')}, {plural(n, 'note')}. "
          "Run python tools/build_atlas.py to see them and build the page.")
    return 1 if e else 0


def sheet_heading(rows: list, hr: int, cols: dict, field: str) -> str:
    c = cols.get(field)
    return str(rows[hr][c]) if c is not None and c < len(rows[hr]) else ""


if __name__ == "__main__":
    sys.exit(main())
