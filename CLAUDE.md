# FPGA Team Atlas: notes for Claude

## What this is

A roadmap kit for an FPGA team in a UK aerospace and defence company. The team works to DO-254, usually at DAL C or D and sometimes up to A or B, and writes VHDL-1993 for AMD devices. The kit sets up the team's ways of working: standards, GitLab, CI, reviews and releases.

- **Notes are the source of truth.** The roadmap is a set of Markdown notes in an Obsidian vault (this folder): workstreams, areas, tasks, milestones and requests.
- **One page is built from them.** `tools/build_atlas.py` reads the notes, checks them and writes a single self-contained HTML page. The page is an Admiralty-style chart with four zoom levels (chart → territory → walled town → task), plus Progress, List, Notice board and Checks views.
- **Nothing on the map is placed by hand.** Layout is generated from the notes and is deterministic: it uses random number generators seeded from IDs, so the chart doesn't jump between builds. With `SOURCE_DATE_EPOCH` set, the whole page is the same byte for byte.
- **It must work offline at work.** There are no network requests at build or view time and no Obsidian community plugins, because plugins need a long approval and must run offline. The Python is 3.8+ and uses only the standard library. Fonts are embedded.
- **GitLab CI does the checking and publishing at work.** `.gitlab-ci.yml` runs `--check` on merge requests and publishes the page through Pages.

**This repository holds the kit and a placeholder example roadmap only.** Never add a real roadmap, real names, programme details or anything from work. The example people are Avery, Blake, Casey and so on.

**The repository is public, so anything pushed is published.** `tests/content_guard.py` looks for work content: names that aren't placeholders, markings, e-mail addresses, internal hosts and links, and spreadsheets, documents, images or design files outside `tests/fixtures/`. The pre-commit hook in `.githooks/` runs it on every commit. Turn the hook on at the start of a session with `git config core.hooksPath .githooks`. If the guard finds anything, stop and tell the user. Never commit with `--no-verify`, and never import a real spreadsheet here.

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
| `tests/` | Unit tests (stdlib `unittest`) with spreadsheet fixtures, `page_smoke.py` (Playwright), and `content_guard.py` (keeps work content out of this public repository) |
| `.githooks/pre-commit` | Runs the content guard on what is staged |
| `README.md` | The user guide. Keep it in step with any change people will notice |
| `CONTRIBUTING.md` | How a change gets in: the git workflow, the definition of done, releases |
| `REVIEW.md` | What a reviewer checks, sorted into blocking, should fix and nits |
| `.claude/agents/` | Helper agents: `kit-reviewer` (reviews a branch against REVIEW.md) and `page-checker` (browser checks and screenshots) |
| `.claude/skills/steward/` | The workflow for commits, pull requests, review comments and CI |
| `.gitattributes` | Leaves the development-only files above out of `git archive` bundles for the work network |

## Commands

```
python tools/build_atlas.py --check                 # check the notes
python tools/build_atlas.py                         # build public/index.html
python -m unittest discover -s tests -t tests       # unit tests (fast, no dependencies)
python tests/page_smoke.py --shots                  # browser checks + screenshots in tests/shots/
python tests/content_guard.py                       # nothing from work (--staged: only what is staged)
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

1. Run the unit tests (on Python 3.8 too if `uv` is available), and check that `build_atlas.py --check` has no errors on the example roadmap.
2. If you changed `atlas_template.html`, run `tests/page_smoke.py --shots` and look at the screenshots in light, dark and phone widths. The `page-checker` agent can do this.
3. Run `tests/content_guard.py`.
4. Update `README.md` for anything users will notice, and `CLAUDE.md` if the structure or conventions changed.
5. Commit and open pull requests as `CONTRIBUTING.md` and the `steward` skill describe. The `kit-reviewer` agent can review the branch first.
