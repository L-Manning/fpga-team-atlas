#!/usr/bin/env python3
"""FPGA Team Atlas: check the roadmap notes and build the atlas page.

Reads every Markdown note under roadmap/, checks its frontmatter (IDs, parents,
dependencies, statuses), then writes one self-contained HTML page with the data,
fonts and code embedded. It makes no network requests and needs nothing beyond
the Python 3.8+ standard library.

    python tools/build_atlas.py            build public/index.html
    python tools/build_atlas.py --check    check only: exit 1 if there are errors
    python tools/build_atlas.py --strict   exit 1 on warnings as well as errors

Notes without a `type` in their frontmatter are ignored, so free-form notes can
live alongside the roadmap. See README.md for the note format.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

TYPES = ("workstream", "area", "task", "milestone", "request")
STATUSES = ("planned", "in-progress", "review", "done", "adopted")
COMPLETE = ("done", "adopted")
KINDS = ("template", "checklist", "guide", "decision", "setup", "training", "process")
REQUEST_STATUSES = ("open", "mapped", "closed")
DALS = ("A", "B", "C", "D")
MAP_HINTS = ("west", "north", "south", "east", "centre", "center",
             "northwest", "northeast", "southwest", "southeast")
NEEDS_DELIVERABLE = ("template", "checklist", "guide")
# Short forms accepted after an estimate's number, by unit.
UNIT_WORDS = {"days": ("d", "day", "days"), "hours": ("h", "hr", "hrs", "hour", "hours"),
              "weeks": ("w", "wk", "wks", "week", "weeks"), "points": ("p", "pt", "pts", "point", "points", "sp")}

# Fonts embedded in the page (SIL Open Font License; see tools/fonts/).
FONT_FACES = [
    ("Spectral SC", "600", "normal", "spectral-sc-latin-600-normal.woff2"),
    ("Spectral", "400", "italic", "spectral-latin-400-italic.woff2"),
    ("Spectral", "600", "normal", "spectral-latin-600-normal.woff2"),
    ("Atkinson Hyperlegible Next", "200 800", "normal", "atkinson-hyperlegible-next-latin-wght-normal.woff2"),
    ("Atkinson Hyperlegible Mono", "200 800", "normal", "atkinson-hyperlegible-mono-latin-wght-normal.woff2"),
]

DOC_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{head}
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
</head>
<body>
{body}
</body>
</html>
"""


# --------------------------------------------------------------------------
# Frontmatter: the subset of YAML that Obsidian's Properties editor writes
# (key: value, inline [a, b] lists, block "- item" lists, quoted strings).
# --------------------------------------------------------------------------
class FrontmatterError(ValueError):
    def __init__(self, message: str, line: int):
        super().__init__(message)
        self.line = line


KEY_RE = re.compile(r"""^(?:"((?:[^"\\]|\\.)+)"|'((?:[^']|'')+)'|([^\s"'#\-\[\]{},&*!|>%@`?][^:]*?))[ \t]*:(?:[ \t]+(.*))?$""")


def key_of(m) -> str:
    """The key from a KEY_RE match, whether it was plain or quoted."""
    if m.group(1) is not None:
        return m.group(1).replace('\\"', '"').replace("\\\\", "\\")
    if m.group(2) is not None:
        return m.group(2).replace("''", "'")
    return m.group(3).strip()
ITEM_RE = re.compile(r"^\s*-(?:[ \t]+(.*))?$")


def _strip_comment(line: str) -> str:
    quote, escaped, prev = None, False, ""
    for i, ch in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote, prev = None, ch
            continue
        if ch in "\"'" and prev in ("", ":", "[", ",", "-"):
            quote = ch
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        if not ch.isspace():
            prev = ch
    return line


def _split_flow(s: str) -> list:
    items, cur, quote, escaped, depth = [], [], None, False, 0
    for ch in s:
        if quote:
            cur.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'" and not "".join(cur).strip():
            quote = ch
            cur.append(ch)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    items.append("".join(cur))
    return [i.strip() for i in items if i.strip()]


def _scalar(s: str):
    s = s.strip()
    if s == "":
        return ""
    if len(s) >= 2 and s[0] == s[-1] == '"':
        out, i, inner = [], 0, s[1:-1]
        while i < len(inner):
            c = inner[i]
            if c == "\\" and i + 1 < len(inner):
                n = inner[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(n, n))
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if s.startswith("[") and s.endswith("]"):
        return [_scalar(x) for x in _split_flow(s[1:-1])]
    if s in ("~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    return s


def parse_frontmatter(block: str, first_line: int) -> dict:
    data, key = {}, None
    for n, raw in enumerate(block.split("\n"), start=first_line):
        line = _strip_comment(raw.rstrip())
        if not line.strip():
            continue
        if not raw[:1].isspace() and not raw.startswith("-"):
            m = KEY_RE.match(line)
            if not m:
                raise FrontmatterError("expected 'key: value'", n)
            key, val = key_of(m), (m.group(4) or "").strip()
            data[key] = _scalar(val) if val else None
            continue
        m = ITEM_RE.match(line)
        if m and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            item = (m.group(1) or "").strip()
            if item:
                data[key].append(_scalar(item))
            continue
        raise FrontmatterError("can't read this line (multi-line values aren't supported)", n)
    return data


def split_note(text: str):
    """Return (frontmatter text or None, body, line number of first frontmatter line)."""
    if text.startswith("﻿"):
        text = text[1:]
    # Only real line ends split lines: a stray U+2028 or form feed inside a value is just a character.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, 0
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), 2
    raise FrontmatterError("the frontmatter has no closing ---", 1)


# --------------------------------------------------------------------------
# Body: subtasks are the note's checkboxes; the rest is the description.
# --------------------------------------------------------------------------
CHECK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX/\-])\]\s+(.*\S)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s")
SUBTASK_STATE = {"x": "done", "/": "doing", "-": "dropped"}


def split_body(body: str):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)      # HTML comments
    body = re.sub(r"%%.*?%%", "", body, flags=re.S)         # Obsidian comments
    subtasks, kept, in_code = [], [], False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else CHECK_RE.match(line)
        if m:
            subtasks.append({"text": m.group(2), "state": SUBTASK_STATE.get(m.group(1).lower(), "todo")})
        else:
            kept.append(line)
    out = []
    for i, line in enumerate(kept):
        if HEADING_RE.match(line):
            j = i + 1
            while j < len(kept) and not kept[j].strip():
                j += 1
            if j >= len(kept) or HEADING_RE.match(kept[j]):
                continue  # heading left empty once its checkboxes moved out
        out.append(line)
    return "\n".join(out).strip(), subtasks


def summary_of(desc: str, limit: int = 240) -> str:
    para = []
    for line in desc.splitlines():
        s = line.strip()
        if not s:
            if para:
                break
            continue
        if HEADING_RE.match(s) or s.startswith(">") or s.startswith("```") or s.startswith("|"):
            if para:
                break
            continue
        para.append(s)
    text = " ".join(para)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


# --------------------------------------------------------------------------
# Helpers for field values
# --------------------------------------------------------------------------
def as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        flat = flatten(v)
        return flat[0] if flat else ""
    return str(v).strip()


def flatten(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(flatten(x))
        return out
    s = str(v).strip()
    return [s] if s else []


def as_list(v) -> list:
    out = []
    for item in flatten(v):
        out.extend(p.strip() for p in item.split(",") if p.strip())
    return out


def clean_ref(s: str) -> str:
    s = s.strip()
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", s)
    if m:
        s = m.group(1)
    m = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", s)
    if m:
        s = urllib.parse.unquote(m.group(1))
    s = s.strip()
    if s.lower().endswith(".md"):
        s = s[:-3]
    return s


def is_url(s: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.\-]*://", s, re.I))


def is_web(s: str) -> bool:
    return bool(re.match(r"^https?://", s, re.I))


# --------------------------------------------------------------------------
# Build the model and check it
# --------------------------------------------------------------------------
class Checker:
    def __init__(self):
        self.issues = []

    def add(self, severity, code, path, nid, message):
        self.issues.append({"severity": severity, "code": code, "path": path, "id": nid, "message": message})

    def count(self, severity):
        return sum(1 for i in self.issues if i["severity"] == severity)


def collect_notes(root: Path, roadmap: Path, chk: Checker):
    notes = []
    if not roadmap.is_dir():
        chk.add("error", "E000", roadmap.as_posix(), None, "roadmap folder not found")
        return notes
    for path in sorted(roadmap.rglob("*.md")):
        parts = path.relative_to(roadmap).parts
        if any(p.startswith((".", "_")) for p in parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            chk.add("error", "E010", rel, None, "isn't valid UTF-8 text")
            continue
        try:
            fm_text, body, first = split_note(text)
            fm = parse_frontmatter(fm_text, first) if fm_text is not None else {}
        except FrontmatterError as e:
            chk.add("error", "E010", rel, None, f"frontmatter line {e.line}: {e}")
            continue
        notes.append((rel, path, fm, body))
    return notes


def find_cycles(graph: dict) -> list:
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in graph}
    stack, cycles, seen = [], [], set()

    def visit(n):
        colour[n] = GREY
        stack.append(n)
        for d in graph[n]:
            if d not in colour:
                continue
            if colour[d] == GREY:
                cyc = stack[stack.index(d):] + [d]
                key = frozenset(cyc)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cyc)
            elif colour[d] == WHITE:
                visit(d)
        stack.pop()
        colour[n] = BLACK

    for n in sorted(graph):
        if colour[n] == WHITE:
            visit(n)
    return cycles


def resolve_deliverable(value, note_path: Path, root: Path):
    s = as_str(value)
    if not s:
        return None
    label, target = s, s
    m = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", s)
    if m:
        label, target = m.group(1), m.group(2)
        if not is_url(target):
            target = urllib.parse.unquote(target)
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", s)
    if m:
        target, label = m.group(1), (m.group(2) or m.group(1))
    if is_web(target):
        return {"label": label, "url": target}
    if is_url(target):
        return {"label": label, "text": target}
    if re.match(r"^[^/\\]+?:\s", target):          # e.g. "Document control: FPGA coding standard"
        return {"label": label, "text": target}
    candidates = [root / target, note_path.parent / target]
    if not target.lower().endswith(".md"):
        candidates += [root / (target + ".md"), note_path.parent / (target + ".md")]
    for c in candidates:
        try:
            if c.is_file():
                return {"label": label, "path": c.resolve().relative_to(root.resolve()).as_posix(), "exists": True}
        except ValueError:
            continue
    base = Path(target).name
    if base and "/" not in target:              # Obsidian-style bare name: find it anywhere in the vault
        name = base if base.lower().endswith(".md") else base + ".md"
        for c in sorted(root.rglob(name)):
            if not any(p.startswith(".") for p in c.relative_to(root).parts):
                return {"label": label, "path": c.relative_to(root).as_posix(), "exists": True}
    return {"label": label, "path": target.lstrip("./"), "exists": False}


def unit_ok(word: str, unit: str) -> bool:
    word, unit = word.lower(), unit.lower()
    return not word or word in UNIT_WORDS.get(unit, ()) or unit.startswith(word)


def build_model(root: Path, roadmap: Path, chk: Checker, estimate_unit: str = "days") -> dict:
    raw = collect_notes(root, roadmap, chk)
    nodes, stem_to_id, order = {}, {}, []

    for rel, path, fm, body in raw:
        ntype = as_str(fm.get("type")).lower()
        if not ntype:
            continue
        nid = as_str(fm.get("id"))
        if ntype not in TYPES:
            chk.add("error", "E003", rel, nid or None, f"unknown type '{ntype}'; use one of: {', '.join(TYPES)}")
            continue
        if not nid:
            chk.add("error", "E001", rel, None, f"this {ntype} note has no id")
            continue
        if nid in nodes:
            chk.add("error", "E002", rel, nid, f"id {nid} is already used by {nodes[nid]['path']}")
            continue
        desc, subtasks = split_body(body)
        default_title = path.stem[len(nid):].strip(" -–—:") if path.stem.startswith(nid) else path.stem
        rec = {"type": ntype, "id": nid, "title": as_str(fm.get("title")) or default_title or path.stem,
               "path": rel, "summary": summary_of(desc), "description": desc}
        if ntype == "task":
            rec["subtasks"] = subtasks
        rec["_fm"], rec["_file"] = fm, path
        nodes[nid] = rec
        stem_to_id[path.stem] = nid
        order.append(rec)

    def resolve(value):
        ref = clean_ref(value)
        if ref in nodes:
            return ref
        base = ref.rsplit("/", 1)[-1]
        return stem_to_id.get(base, stem_to_id.get(ref, ref))

    def kind_of(nid):
        return nodes[nid]["type"] if nid in nodes else None

    def a_kind(nid):
        k = kind_of(nid) or "note"
        return ("an " if k[0] in "aeiou" else "a ") + k

    for rec in order:
        fm, nid, rel, t = rec["_fm"], rec["id"], rec["path"], rec["type"]
        if t == "workstream":
            hint = as_str(fm.get("map_hint")).lower()
            if hint and hint not in MAP_HINTS:
                chk.add("warning", "W108", rel, nid, f"map_hint '{hint}' isn't one of: {', '.join(MAP_HINTS)}")
                hint = ""
            rec["map_hint"] = hint
            rec["order"] = as_str(fm.get("order"))
        elif t == "area":
            parent = resolve(as_str(fm.get("parent"))) if fm.get("parent") else ""
            if not parent:
                chk.add("error", "E004", rel, nid, "has no parent; set it to the id of its workstream")
            elif kind_of(parent) != "workstream":
                what = "doesn't exist" if parent not in nodes else f"is {a_kind(parent)}, not a workstream"
                chk.add("error", "E004", rel, nid, f"parent {parent} {what}")
                parent = ""
            rec["parent"] = parent
        elif t == "task":
            parent = resolve(as_str(fm.get("parent"))) if fm.get("parent") else ""
            if not parent:
                chk.add("error", "E004", rel, nid, "has no parent; set it to the id of its area")
            elif kind_of(parent) != "area":
                what = "doesn't exist" if parent not in nodes else f"is {a_kind(parent)}, not an area"
                chk.add("error", "E004", rel, nid, f"parent {parent} {what}")
                parent = ""
            rec["parent"] = parent

            status = as_str(fm.get("status")).lower()
            if not status:
                chk.add("error", "E007", rel, nid, f"has no status; use one of: {', '.join(STATUSES)}")
                status = "planned"
            elif status not in STATUSES:
                chk.add("error", "E007", rel, nid, f"status '{status}' isn't one of: {', '.join(STATUSES)}")
                status = "planned"
            rec["status"] = status

            kind = as_str(fm.get("kind")).lower()
            if kind and kind not in KINDS:
                chk.add("error", "E007", rel, nid, f"kind '{kind}' isn't one of: {', '.join(KINDS)}")
                kind = ""
            rec["kind"] = kind
            rec["owner"] = as_str(fm.get("owner"))

            ms = resolve(as_str(fm.get("milestone"))) if fm.get("milestone") else ""
            if ms and kind_of(ms) != "milestone":
                chk.add("error", "E008", rel, nid, f"milestone {ms} doesn't exist")
                ms = ""
            rec["milestone"] = ms

            dal = [d.upper() for d in as_list(fm.get("dal"))]
            bad = [d for d in dal if d not in DALS]
            if bad:
                chk.add("error", "E007", rel, nid, f"dal {', '.join(bad)} isn't A, B, C or D")
            dal = [d for d in DALS if d in dal] or list(DALS)
            rec["dal"] = dal

            deps = []
            for ref in as_list(fm.get("depends_on")):
                did = resolve(ref)
                if did == nid:
                    chk.add("error", "E005", rel, nid, "depends on itself")
                elif did not in nodes:
                    chk.add("error", "E005", rel, nid, f"depends on {did}, which doesn't exist")
                elif kind_of(did) != "task":
                    chk.add("error", "E005", rel, nid, f"depends on {did}, which is {a_kind(did)}, not a task")
                elif did not in deps:
                    deps.append(did)
            rec["depends_on"] = deps
            est = as_str(fm.get("estimate"))
            rec["estimate"] = None
            if est:
                m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([A-Za-z]*)", est)
                if m and unit_ok(m.group(2), estimate_unit):
                    rec["estimate"] = float(m.group(1))
                else:
                    chk.add("warning", "W109", rel, nid, f"estimate '{est}' isn't a number of {estimate_unit}")
            rec["deliverable"] = resolve_deliverable(fm.get("deliverable"), rec["_file"], root)
            tracker = as_str(fm.get("tracker"))
            rec["tracker"] = ({"url": tracker} if is_web(tracker) else {"text": tracker}) if tracker else None
        elif t == "milestone":
            rec["target"] = as_str(fm.get("target"))
        elif t == "request":
            status = as_str(fm.get("status")).lower() or "open"
            if status not in REQUEST_STATUSES:
                chk.add("error", "E007", rel, nid, f"status '{status}' isn't one of: {', '.join(REQUEST_STATUSES)}")
                status = "open"
            rec["status"] = status
            rec["raised_by"] = as_str(fm.get("raised_by"))
            rec["raised"] = as_str(fm.get("raised"))
            rec["plus_ones"] = as_list(fm.get("plus_ones"))
            mapped = resolve(as_str(fm.get("mapped_to"))) if fm.get("mapped_to") else ""
            if mapped and kind_of(mapped) != "task":
                chk.add("error", "E009", rel, nid, f"mapped_to {mapped} isn't a task")
                mapped = ""
            if status == "mapped" and not mapped:
                chk.add("warning", "W107", rel, nid, "is marked mapped but has no mapped_to task")
            rec["mapped_to"] = mapped

    tasks = [r for r in order if r["type"] == "task"]
    graph = {r["id"]: r["depends_on"] for r in tasks}
    for cyc in find_cycles(graph):
        first = nodes[cyc[0]]
        chk.add("error", "E006", first["path"], first["id"], "dependency loop: " + " -> ".join(cyc))

    for r in tasks:
        nid, rel, st = r["id"], r["path"], r["status"]
        subs = r["subtasks"]
        live = [s for s in subs if s["state"] != "dropped"]
        if st in ("in-progress", "review") and not r["owner"]:
            chk.add("warning", "W101", rel, nid, f"{nid} is {st} but has no owner")
        if st == "in-progress" and not live:
            chk.add("warning", "W102", rel, nid, f"{nid} is in progress but has no subtasks yet")
        if st in COMPLETE and any(s["state"] in ("todo", "doing") for s in live):
            chk.add("warning", "W103", rel, nid, f"{nid} is {st} but still has open subtasks")
        deliv = r["deliverable"]
        if st in COMPLETE and r["kind"] in NEEDS_DELIVERABLE and not deliv:
            chk.add("warning", "W104", rel, nid, f"{nid} is {st} but doesn't say where its {r['kind']} lives (deliverable)")
        if deliv and deliv.get("path") and not deliv.get("exists") and st in ("review",) + COMPLETE:
            chk.add("warning", "W105", rel, nid, f"deliverable {deliv['path']} wasn't found in the repository")
        if st in COMPLETE:
            open_deps = [d for d in r["depends_on"] if nodes[d]["status"] not in COMPLETE]
            if open_deps:
                chk.add("warning", "W106", rel, nid, f"{nid} is {st} but depends on unfinished {', '.join(open_deps)}")

    has_task = {r["parent"] for r in tasks}
    has_area = {r["parent"] for r in order if r["type"] == "area"}
    for r in order:
        if r["type"] == "area" and r["id"] not in has_task:
            chk.add("info", "I201", r["path"], r["id"], f"{r['id']} has no tasks yet, so it shows under fog on the map")
        if r["type"] == "workstream" and r["id"] not in has_area:
            chk.add("info", "I202", r["path"], r["id"], f"{r['id']} has no areas yet, so it isn't drawn on the map")

    def clean(rec):
        return {k: v for k, v in rec.items() if not k.startswith("_")}

    groups = {t: [clean(r) for r in order if r["type"] == t] for t in TYPES}
    return {"workstreams": groups["workstream"], "areas": groups["area"], "tasks": groups["task"],
            "milestones": groups["milestone"], "requests": groups["request"]}


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------
def git_info(root: Path) -> dict:
    info = {"commit": os.environ.get("CI_COMMIT_SHORT_SHA", ""),
            "ref": os.environ.get("CI_COMMIT_REF_NAME", "") or os.environ.get("CI_DEFAULT_BRANCH", ""),
            "repo_url": os.environ.get("CI_PROJECT_URL", "")}
    if not info["commit"]:
        try:
            out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                info["commit"] = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def font_css(font_dir: Path) -> str:
    rules = []
    for family, weight, style, filename in FONT_FACES:
        f = font_dir / filename
        if not f.is_file():
            continue
        data = base64.b64encode(f.read_bytes()).decode("ascii")
        rules.append(f'@font-face{{font-family:"{family}";font-style:{style};font-weight:{weight};'
                     f'font-display:swap;src:url(data:font/woff2;base64,{data}) format("woff2")}}')
    return "\n".join(rules)


def as_document(fragment: str) -> str:
    head = []
    m = re.search(r"<title>.*?</title>", fragment, re.S)
    if m:
        head.append(m.group(0))
        fragment = fragment[: m.start()] + fragment[m.end():]
    styles = re.findall(r"<style>.*?</style>", fragment, re.S)
    for s in styles:
        head.append(s)
        fragment = fragment.replace(s, "", 1)
    return DOC_SHELL.format(head="\n".join(head), body=fragment.strip())


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Check the roadmap notes and build the FPGA Team Atlas.")
    ap.add_argument("--root", type=Path, default=here.parent, help="repository and vault root (default: the folder above tools/)")
    ap.add_argument("--roadmap", default="roadmap", help="folder of roadmap notes, relative to the root (default: roadmap)")
    ap.add_argument("--template", type=Path, default=here / "atlas_template.html")
    ap.add_argument("--fonts", type=Path, default=here / "fonts")
    ap.add_argument("--out", type=Path, default=None, help="output file (default: <root>/public/index.html)")
    ap.add_argument("--vault-name", default=None, help="Obsidian vault name for 'Open in Obsidian' links (default: the root folder's name)")
    ap.add_argument("--title", default="FPGA Team Atlas")
    ap.add_argument("--check", action="store_true", help="check the notes only; don't write the page")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--fragment", action="store_true", help="write the page without <html>/<head>, for hosts that add their own")
    ap.add_argument("--json", type=Path, default=None, help="also write the extracted data to this JSON file")
    ap.add_argument("--estimate-unit", default="days", help="what task estimates count: days (default), hours, weeks or points")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    chk = Checker()
    model = build_model(root, root / args.roadmap, chk, args.estimate_unit)
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    chk.issues.sort(key=lambda i: (sev_rank[i["severity"]], i["code"], i["path"]))

    counts = {k: len(model[k]) for k in ("workstreams", "areas", "tasks", "milestones", "requests")}
    def plural(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"
    print(f"{args.title}: " + ", ".join(plural(counts[k + 's'], k) for k in ("workstream", "area", "task", "milestone", "request")))
    for i in chk.issues:
        print(f"  {i['severity']:<7} {i['code']}  {i['path']}: {i['message']}")
    e, w, n = chk.count("error"), chk.count("warning"), chk.count("info")
    print(f"{e} error{'s' * (e != 1)}, {w} warning{'s' * (w != 1)}, {n} note{'s' * (n != 1)}")

    failed = e > 0 or (args.strict and w > 0)
    if args.check:
        return 1 if failed else 0

    info = git_info(root)
    meta = {"title": args.title, "vault": args.vault_name or root.name,
            "generated": dt.datetime.now().replace(microsecond=0).isoformat(),
            "commit": info["commit"], "ref": info["ref"], "repo_url": info["repo_url"], "counts": counts,
            "estimate_unit": args.estimate_unit}
    data = dict(meta=meta, issues=chk.issues, **model)
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
               .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))

    template = args.template.read_text(encoding="utf-8")
    if "__ATLAS_DATA__" not in template:
        print(f"error: {args.template} has no __ATLAS_DATA__ placeholder", file=sys.stderr)
        return 2
    page = template.replace("/*__ATLAS_FONTS__*/", font_css(args.fonts), 1).replace("__ATLAS_DATA__", payload, 1)
    page = re.sub(r"<title>.*?</title>", lambda _m: "<title>" + html.escape(args.title) + "</title>", page, count=1, flags=re.S)
    if not args.fragment:
        page = as_document(page)

    out = args.out or (root / "public" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
