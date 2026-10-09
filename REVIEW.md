# Reviewing a change to the kit

How to review a pull request to this repository, for people and for Claude's automated code review. [CLAUDE.md](CLAUDE.md) explains how the kit fits together. [CONTRIBUTING.md](CONTRIBUTING.md) explains how a change gets in.

Sort each finding into one of three groups, and give it a file and line, what goes wrong and when, and what to do instead.

## Blocking: fix before merging

1. **Anything from work.** This repository is public. Real names, programmes, customers, server names, internal links, spreadsheets, screenshots or marked material must not be committed. The content guard (`tests/content_guard.py`) catches some of this, but not all. Read the example content as well as the code. A leak is also a security incident: see CONTRIBUTING.md.
2. **Note content reaching the page unescaped.** Note text is untrusted. Every string the page builds into HTML goes through `esc()`, or through `md()` and `inline()`, which escape it themselves. Only `http(s)` and `obsidian://` addresses may become an `href`. Any other scheme stays as plain text. The build must keep escaping `<`, `>` and `&` in the embedded JSON, so a note can't close the `<script>` element.
3. **Anything fetched over the network**, at build time or view time: scripts, stylesheets, fonts, images, `fetch()`, or a CDN. The page must work offline from a single file.
4. **Python that won't run on 3.8 or needs a package.** The tools use the standard library only. Watch for `match`, `str.removeprefix` and `str.removesuffix`, `dict | dict`, `list[str]` or `X | None` evaluated at run time (annotations are fine with `from __future__ import annotations`), `zoneinfo`, `functools.cache`, `Path.is_relative_to`, `zip(strict=...)`, `Path.write_text(newline=...)` and parenthesised `with` statements.
5. **The importer guessing.** If a name matches two tasks, or a value is unknown, the importer reports it with the sheet row and keeps the raw value. It must never pick one silently, drop a value, or delete notes when the sheet turned out to have no tasks.
6. **A layout that changes between builds of the same notes.** Layout randomness comes from generators seeded from IDs. `Math.random()`, the date, or the order of a `Set` or object built from unsorted input mustn't affect where things are drawn.
7. **A check that changes meaning silently.** If a check code is added, removed, renumbered, or moved between error, warning and note, the README's Checks table and the tests change with it. Errors fail CI, so downgrading one is a decision, not a tidy-up.
8. **Tests weakened to get green.** No test is skipped, deleted or loosened without a reason the reviewer agrees with.

## Should fix

- **Messages** are plain UK English for engineers. They name the note path or sheet row, say what is wrong, and say what to do next.
- **Accessibility.** Every control works from the keyboard. After navigating, focus moves to the new view's heading (`takeFocus()`). Motion stops under `prefers-reduced-motion`. Colours come from the CSS tokens, with dark variants. Nothing scrolls sideways at 390 px.
- **Navigation** goes through `location.hash` and `route()`. A zoom that another navigation overtakes is dropped (`navSeq`).
- **Tests** cover new behaviour, including what goes wrong: a bad value, a missing file, an odd encoding.
- **Docs.** README.md covers anything users will notice. CLAUDE.md covers changes to the structure or conventions.

## Nits (optional)

Naming, comment wording, and small simplifications that don't change behaviour. Mark them as optional so they don't hold up a merge.

## Don't flag

- The page template's compact JavaScript style (one-line helpers, template strings): it is the house style.
- The two easter eggs, Mt Timing Closure and the sea serpent. They are original artwork and meant to be there.
- The example roadmap's one warning (OUT-02 has no subtasks yet) and one note (Integration Support is under fog). They are expected, and they show the Checks tab and fog in use.

## Checking a change yourself

```
python -m unittest discover -s tests -t tests       # on Python 3.8 and a current Python
python tools/build_atlas.py --check
python tests/content_guard.py
python tests/page_smoke.py --shots                  # after a page change: then look at tests/shots/
```
