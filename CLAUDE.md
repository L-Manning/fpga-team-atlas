# FPGA Team Atlas: notes for Claude

## What this is

A roadmap kit for an FPGA team in a UK aerospace and defence company. The team works to DO-254, usually at DAL C or D and sometimes up to A or B, and writes VHDL-1993 for AMD devices. The kit sets up the team's ways of working: standards, GitLab, CI, reviews and releases.

- **Notes are the source of truth.** The roadmap is a set of Markdown notes in an Obsidian vault (this folder): workstreams, areas, tasks, milestones and requests.
- **One page is built from them.** `tools/build_atlas.py` reads the notes, checks them and writes a single self-contained HTML page. The page is an Admiralty-style chart with four zoom levels (chart → territory → walled town → task), plus Progress, List, Notice board and Checks views.
- **Nothing on the map is placed by hand.** Layout is generated from the notes and is deterministic: it uses random number generators seeded from IDs, so the chart doesn't jump between builds.
- **It must work offline at work.** There are no network requests at build or view time and no Obsidian community plugins, because plugins need a long approval and must run offline. The Python is 3.8+ and uses only the standard library. Fonts are embedded.
- **GitLab CI does the checking and publishing at work.** `.gitlab-ci.yml` runs `--check` on merge requests and publishes the page through Pages.

**This repository holds the kit and a placeholder example roadmap only.** Never add a real roadmap, real names, programme details or anything from work. The example people are Avery, Blake, Casey and so on.

## Layout

| Path | What |
|---|---|
| `roadmap/` | The example roadmap notes. Example requests carry `example: true` |
| `library/` | Templates, checklists, guides and decision records that tasks deliver |
| `_templates/` | Obsidian note templates |
| `tools/build_atlas.py` | Notes → checks → page. It has a hand-written frontmatter parser (no PyYAML). Check codes: E0xx errors (fail CI), W1xx warnings, I2xx notes |
| `tools/atlas_template.html` | The page. Vanilla JS in one IIFE, SVG and canvas, no libraries. The build fills in `__ATLAS_DATA__` and `/*__ATLAS_FONTS__*/` |
| `tools/import_roadmap.py` | Spreadsheet (.xlsx/.xlsm/.csv) → notes, offline. It reads xlsx with zipfile and ElementTree |
| `tools/roadmap_template.xlsx` | The sheet layout the importer likes best |
| `tools/fonts/` | woff2 fonts (OFL) that are embedded in the page |
| `tests/` | Unit tests (stdlib `unittest`) with spreadsheet fixtures, and `page_smoke.py` (Playwright) |
| `README.md` | The user guide. Keep it in step with any change people will notice |

## Commands

```
python tools/build_atlas.py --check                 # check the notes
python tools/build_atlas.py                         # build public/index.html
python -m unittest discover -s tests -t tests       # unit tests (fast, no dependencies)
python tests/page_smoke.py --shots                  # browser checks + screenshots in tests/shots/
python tools/import_roadmap.py tests/fixtures/columns.xlsx --dry-run
```

`page_smoke.py` needs `pip install playwright` and `python -m playwright install chromium`. It builds the example roadmap and a generated one about six times bigger. It then checks for script errors, sideways scrolling at 390 px, overlaps in every territory view, and Esc and Back behaviour.

## Conventions

- **Python.** Use only the standard library and keep it 3.8-compatible: no `match`, no `str.removeprefix`, and use `from __future__ import annotations` for modern type hints. The tools must keep running on a locked-down Windows PC as well as on Linux CI.
- **Messages and docs.** Write plain UK English for engineers, not programmers. Say what went wrong and what to do next. Messages name the sheet row or note path.
- **The importer never guesses.** If a dependency name matches two tasks, or a value is unknown, it reports it and keeps the raw value (`sheet_status`, `task_type`). A run that would delete notes but finds no tasks changes nothing.
- **The page treats note content as untrusted.** Escape every string with `esc()`. Links only become `href`s for `http(s)` or `obsidian://`.
- **Page styling.**
  - Colours are CSS tokens on `:root`, with dark variants under `prefers-color-scheme` and `[data-theme]`.
  - Nothing may scroll sideways at 390 px.
  - Honour `prefers-reduced-motion`.
  - Every control works from the keyboard.
- **Navigation goes through `location.hash` → `route()`.** The routes are `#map`, `#region.ID`, `#area.ID`, `#task.ID`, `#progress`, `#list`, `#board` and `#checks`. A zoom animation that another navigation overtakes is dropped (`navSeq`). Focus moves to the new view's heading via `takeFocus()`.
- **The two easter eggs are original artwork:** Mt Timing Closure and the "Here be metastability" sea serpent. Don't add characters or artwork from existing franchises.

## Before finishing a change

1. Run the unit tests, and check that `build_atlas.py --check` has no errors on the example roadmap.
2. If you changed `atlas_template.html`, run `tests/page_smoke.py --shots` and look at the screenshots in light, dark and phone widths.
3. Update `README.md` for anything users will notice, and `CLAUDE.md` if the structure or conventions changed.
