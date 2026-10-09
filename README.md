# FPGA Team Atlas

The team roadmap drawn as a map. Every workstream, area, task, milestone and request is a Markdown note in this repository. A small script turns the notes into one web page: a chart of the workstreams, a close-up of each workstream's territory, a walled town plan of each area with its tasks in dependency order, a progress page, a flat list of every task, and a notice board where anyone can ask for a missing template, checklist or guide.

Nothing on the map is placed by hand. Positions, roads, rings and fog all come from the notes, so the atlas is exactly as current as the notes are.

- Edit in **Obsidian** (core features only; no community plugins).
- Build with **Python 3.8+**, standard library only. The build makes no network requests.
- View in any **browser**. The page is a single file with everything embedded.

Everything under `roadmap/` and `library/` is example content shaped like an FPGA team's set-up roadmap, with placeholder names (Avery, Blake, Casey…). Replace it with your own.

## Quick start

1. In Obsidian, choose **Open folder as vault** and pick this folder.
2. Build the atlas:
   ```
   python tools/build_atlas.py
   ```
3. Open `public/index.html` in a browser.

In GitLab, `.gitlab-ci.yml` checks the notes on every merge request and publishes the atlas from the default branch.

## Reading the map

The map has four levels: **chart → territory → town → task**. Click a territory or town on the chart to zoom into its territory, click a town there for its plan, and click a house for the task. The numbered steps in the toolbar show which level you are on, the page takes on the workstream's colour as you go deeper, and Esc goes back up a level.

| On the map | Means |
|---|---|
| Territory | A workstream. Click it to zoom in and see only its towns, with each task as a small house |
| Town | An area within a workstream. The ring shows its tasks by stage |
| West to east | Earlier to later in the order work unlocks |
| Track between towns | One area's tasks need another's first. Solid when the prerequisite is finished, dotted while it is open |
| Fog | An area with no tasks yet |
| Town plan | A walled town with one house per task, left to right in the order they can be done. Streets run from each task to the work it unlocks; a street with dashed edges is waiting on unfinished work. Gates lead to other areas |
| House | Survey stakes: planned. Scaffolding: in progress. Pennant: in review. Finished house: done. Lit windows and a smoking chimney: adopted |
| Ready | Planned, and everything it needs is done, so anyone can pick it up |
| Waiting | Started, but a prerequisite is still open |

There are also two small jokes in the sea. Hover over them.

The **Progress** tab is the plain view for updates: percentage built, progress by workstream and milestone, what's ready, what's holding up the most work, and a table of counts. **List** shows every task in one table you can sort and filter, with a button that copies it into a spreadsheet. **Checks** lists any problems the build found in the notes.

## The notes

There are five kinds of note, told apart by `type` in the frontmatter. Folders are only for tidiness: the build reads every note under `roadmap/` and ignores notes without a `type`, and anything in a folder starting with `_` or `.`.

| `type` | Folder | What it is | On the atlas |
|---|---|---|---|
| `workstream` | `roadmap/workstreams/` | One of the three or four big strands of work | A territory |
| `area` | `roadmap/areas/` | A group of related tasks | A town |
| `task` | `roadmap/tasks/` | One piece of work with a deliverable | A house |
| `milestone` | `roadmap/milestones/` | An outcome tasks count towards | A row on the progress page |
| `request` | `roadmap/requests/` | Someone asking for a template, checklist or guide | A card on the notice board |

### Task fields

```yaml
---
type: task
id: CI-03
parent: CI
kind: setup
status: in-progress
owner: Avery
milestone: M2
estimate: 5
dal: [A, B, C, D]
depends_on: [CI-01, VER-02]
deliverable: library/guides/nightly-regression.md
---
One or two sentences: what this delivers and why it matters.

## Subtasks
- [x] Choose the runner schedule
- [/] Publish pass/fail and coverage
- [ ] Alert on failure
```

| Field | Required | Values |
|---|---|---|
| `id` | Yes | Unique. Name the note after it: `CI-03 Nightly regression.md` |
| `parent` | Yes | The id of the task's area |
| `status` | Yes | `planned`, `in-progress`, `review`, `done`, `adopted` |
| `kind` | No | `template`, `checklist`, `guide`, `decision`, `setup`, `training`, `process` |
| `owner` | No | A name |
| `milestone` | No | The id of a milestone |
| `estimate` | No | A number of days (or hours or points, if the page is built with `--estimate-unit`). Totalled on the Progress page |
| `dal` | No | The DALs that need this task. Default: all. `[A, B]` marks work needed only at A and B |
| `depends_on` | No | Ids of tasks that must be done first |
| `deliverable` | No | Where the output lives: a path in this repository, a URL, or text such as `Document control: FPGA coding standard, issue 2` |
| `tracker` | No | Where detailed tracking lives once the team decides: a GitLab issue URL, a spreadsheet reference |
| `title` | No | Defaults to the file name without the id |

**Subtasks are the checkboxes in the task's note.** The owner adds them when they pick the task up: `- [ ]` to do, `- [/]` in progress, `- [x]` done, `- [-]` dropped.

**Done and adopted are different.** Done means the template, guide or decision is finished and published. Adopted means the team uses it routinely. Most of the value of this roadmap is in getting from the first to the second.

Other notes are simpler: workstreams and areas need `id` (and areas a `parent` workstream); milestones take an optional `target`; requests take `raised_by`, `raised`, `plus_ones`, `status` (`open`, `mapped`, `closed`) and `mapped_to`. Templates for each are in `_templates/`.

Lists can be written inline (`[A, B]`) or as `- item` lines, as Obsidian's Properties editor writes them. References can be ids, note names, or `[[wikilinks]]`.

## Importing a spreadsheet

If the roadmap already lives in Excel, `tools/import_roadmap.py` turns it into notes. It runs on your own machine with the standard library only, so the spreadsheet never leaves it.

```
python tools/import_roadmap.py roadmap.xlsx --dry-run    # see what it understood; nothing is written
python tools/import_roadmap.py roadmap.xlsx --fresh      # replace the example roadmap with yours
python tools/build_atlas.py                              # check the notes and build the page
```

It reads `.xlsx`, `.xlsm` and `.csv` files; save an old `.xls` as `.xlsx` first. `tools/roadmap_template.xlsx` shows the layout it likes best, but your own sheet will usually work as it is. It understands two layouts:

- **One task per row.** A sheet called Tasks, or the first sheet with a Task, Title or Name column. Columns give each task's workstream and area; an Epic column works as the area. Optional sheets called Workstreams, Areas (or Epics) and Milestones add IDs, descriptions, map hints and target dates.
- **An outline.** If there's a Level, Outline level or WBS column, the rows are read as a hierarchy: by default level 1 is a workstream, 2 an area, 3 a task, and anything deeper becomes a checklist item on the task above it. If you have an extra level, such as threads between epics and tasks, say what each level is: `--levels workstream,area,thread,task`. A level that isn't a workstream, area or task becomes a property on the notes below it. Format a WBS column as text, so Excel doesn't turn 1.10 into 1.1.

Headings are matched loosely; `--columns` lists them all. Task, Task name, Name or Summary work for the title; Depends on, Predecessors or Prerequisites for dependencies; Estimate, Effort or Duration for the estimate; Owner, Assignee or Resource names for the owner. If a heading isn't recognised, point at it: `--col area=Epic`. Any column it still doesn't know is kept on each task as an extra property (a Thread column becomes `thread:`), so nothing in the sheet is lost and Bases can filter on it.

What it does with the values:

- **IDs** in the sheet are kept. Rows without one get an ID made from their area's, such as CI-04. Plain numbers, as Microsoft Project exports have, are only used to match dependencies.
- **Blank and merged cells.** In a sheet grouped by workstream or area, a blank Workstream or Area cell means "same as the row above", and a merged cell counts for every row it covers. Hidden sheets, such as lists behind drop-downs, are skipped.
- **Dependencies** can give a task's ID or its exact name, separated by commas or semicolons. Microsoft Project's style (`12FS+2 days`) works too. If two tasks share a name it asks for the ID, and anything it can't match is listed for you to fix in the sheet. It never guesses.
- **Statuses** such as Not started, WIP, Complete or Closed are matched to the five the atlas uses. Anything else, such as Blocked, becomes planned and is kept as `sheet_status` so you can review it. A % Complete column works when there's no status.
- **Estimates** are stored as numbers in `estimate:`. A unit in the heading, such as `Estimate (hours)`, or in a cell, such as `4h` or a time like 7:30, is pointed out. If the team estimates in hours, add `--estimate-unit hours` to the build commands here and in `.gitlab-ci.yml`.
- **DAL** accepts letters in most forms (`A/B`, `A, B`, `B-D`). Blank, All, N/A or TBD means every DAL.

Running it again is safe. Without `--fresh` it only adds rows that aren't notes yet, matching them by ID or by name, and leaves existing notes alone. `--update` also writes the sheet's values into existing notes but keeps their text and checklists, and a blank cell never clears a value. `--fresh` deletes every workstream, area, task and milestone note, and the example requests (marked `example: true`), before it writes, including any edits made since; Git can bring them back. Requests your team has raised are kept. If the sheet turns out to have no tasks, nothing is deleted.

Once the team works in the notes, retire the spreadsheet. From then on the notes are the roadmap.

## Checks

| Severity | Examples | Effect |
|---|---|---|
| Error | Missing or duplicate id, unknown parent, a dependency on a task that doesn't exist, a dependency loop, an unknown status, kind or milestone, unreadable frontmatter | `--check` exits with 1, so the merge request pipeline fails |
| Warning | In progress with no owner or no subtasks, done with open subtasks, a finished template, checklist or guide with no deliverable, a deliverable file that doesn't exist, done while depending on unfinished work, an estimate that isn't a number | Shown on the Checks tab. `--strict` makes them fail too |
| Note | An area with no tasks yet (shown under fog) | Information only |

## Building

```
python tools/build_atlas.py [--check] [--strict] [--out FILE] [--vault-name NAME] [--title TEXT] [--estimate-unit UNIT] [--fragment] [--json FILE]
```

| Option | Does |
|---|---|
| `--check` | Check the notes only, without writing the page |
| `--strict` | Treat warnings as errors |
| `--out` | Output file. Default `public/index.html` |
| `--vault-name` | Obsidian vault name used by the "Open in Obsidian" links. Default: this folder's name |
| `--title` | Title shown on the page. Default `FPGA Team Atlas` |
| `--estimate-unit` | What estimates count: `days` (default), `hours`, `weeks` or `points` |
| `--fragment` | Write the page body without `<html>` and `<head>`, for hosts that add their own |
| `--json` | Also write the parsed data as JSON |

In CI the page also links each task to its file in GitLab and shows the commit it was built from.

Each workstream gets its own colour, in the order the notes are read. To pin a workstream to one side of the map, add `map_hint: west` (or `north`, `south`, `east`, `centre`, `northwest`, `northeast`, `southwest`, `southeast`) to its note. Otherwise workstreams are placed west to east by when their work unlocks.

## Obsidian set-up

- `.obsidian/app.json` makes Obsidian write standard Markdown links with relative paths instead of `[[wikilinks]]`, so links also work in GitLab's file view.
- Turn on the core **Templates** plugin; it is already pointed at `_templates/`.
- Columns the importer kept as extra properties show up in Obsidian's Properties panel and can be used in Bases views.
- `Roadmap.base` and `Requests.base` are table and card views for the core **Bases** plugin.
- No community plugins are needed.

## Changing the kit

[CONTRIBUTING.md](CONTRIBUTING.md) explains how a change gets in, and [REVIEW.md](REVIEW.md) explains what a reviewer checks. This repository is public, so `tests/content_guard.py` checks that nothing from work gets committed. Turn on its pre-commit hook once in each clone: `git config core.hooksPath .githooks`.

The tools have tests that need nothing beyond Python: `python -m unittest discover -s tests -t tests`. After changing the page template, `python tests/page_smoke.py --shots` opens the atlas in a headless browser, checks every view at desktop and phone widths and saves screenshots to look at (it needs Playwright: `pip install playwright`, then `python -m playwright install chromium`). `CLAUDE.md` explains how the kit fits together, for anyone changing it with Claude Code. `.claude/` holds two helper agents (a reviewer and a page checker) and a workflow skill for it.

## Bringing it onto the work network

Take a tagged release. `git archive --format=zip --output fpga-team-atlas.zip v1.2.0` makes a zip of the kit without the files that are only for developing it: `tests/`, `.github/`, `.githooks/`, `.claude/`, `CLAUDE.md`, `CONTRIBUTING.md` and `REVIEW.md`. `.gitattributes` lists them, and GitHub's source downloads leave them out too. Everything else is plain text except the import template (`tools/roadmap_template.xlsx`, an ordinary workbook with no macros) and the font files in `tools/fonts/` (Spectral and Atkinson Hyperlegible, both under the SIL Open Font License; licence texts included). Delete that folder if fonts are a problem; the page falls back to system fonts. The code has no third-party dependencies and the page makes no network requests.

The atlas is a planning aid for the team. Formal plans, standards and certification evidence stay in your controlled document system; tasks can point at them through `deliverable`.
