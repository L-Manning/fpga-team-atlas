# Contributing to the kit

This repository holds the FPGA Team Atlas kit (the tools, the page and the templates) and a placeholder example roadmap. It is how the kit is developed. The team's real roadmap lives on the work network, not here.

## The one rule: nothing from work

**This repository is public.** Anything committed and pushed to it is published at once, and deleting it afterwards doesn't take it back.

Never add anything from work:

- people's names (the examples use Avery, Blake, Casey and so on), customers, programmes, projects, part numbers or products;
- the real roadmap, a real spreadsheet, or anything copied from a controlled document;
- server names, internal addresses or links, network paths, or screenshots;
- anything with a protective, commercial or export-control marking.

`tests/content_guard.py` looks for signs of these. Turn on the pre-commit hook once in each clone so it checks every commit before it is made:

```
git config core.hooksPath .githooks
```

The guard also runs in CI, but by then the commit has already been pushed. If it raises a false alarm, change the content or extend the lists in `tests/content_guard.py` in the same commit, so the reviewer sees why. Don't skip it with `--no-verify`.

**If something from work does get pushed**, stop and tell the repository owner straight away. A new commit that deletes it isn't enough, because it stays in the history and in any clones. The owner takes the repository private, removes the content from the history, and asks GitHub to clear cached views. Follow your company's security incident process too: it may need reporting.

## How a change gets in

`main` always works. Every change reaches it through a pull request, never by pushing to `main` directly.

1. **Branch from the latest `main`.** Name the branch after the change: `fix/deliverable-paths`, `feature/print-view`, `docs/contributing`. Keep it short-lived: days, not weeks.
2. **Commit in small steps.** Each commit does one thing and leaves the tests passing. Write the subject in the imperative, under 72 characters ("Fix deliverable names with brackets"), then a blank line and a few lines on why.
3. **Run the checks before you push.**
   ```
   python -m unittest discover -s tests -t tests       # unit tests, on Python 3.8 and a current Python
   python tools/build_atlas.py --check                 # the example roadmap has no errors
   python tests/content_guard.py                       # nothing from work
   python tests/page_smoke.py --shots                  # if you changed the page: then look at the screenshots
   ```
4. **Open a pull request.** Say what changed, why, and how you checked it. If people will notice the change, update `README.md` in the same pull request.
5. **Review.** Someone other than the author reviews it against [REVIEW.md](REVIEW.md). Every comment is either fixed or answered, and CI is green.
6. **Merge.** Squash and merge by default, so each change is one commit on `main`. If a pull request holds several separate changes that each pass on their own, use rebase and merge to keep them apart. Delete the branch afterwards.

Never force-push `main` or a branch someone else is working on, and never commit `public/` or anything else the build generates.

## Definition of done for a kit change

- The unit tests pass on Python 3.8 and on a current Python.
- `build_atlas.py --check` reports no errors on the example roadmap.
- The content guard finds nothing.
- If `tools/atlas_template.html` changed: `page_smoke.py --shots` passes, and someone has looked at the screenshots in light and dark themes and at phone width.
- `README.md` covers anything users will notice. `CLAUDE.md` covers any change to the structure or conventions.

The conventions themselves are in [CLAUDE.md](CLAUDE.md): standard library only, Python 3.8, nothing fetched from the network, every note string escaped on the page, and messages in plain UK English that say what went wrong and what to do next.

## Releases, and bringing one onto the work network

When `main` has changes worth taking to work, tag it: `v1.2.0`. The first number goes up when existing notes need editing to keep working, the second for new features, the third for fixes. Write a few lines of release notes on what users will notice.

Make the bundle from the tag:

```
git archive --format=zip --output fpga-team-atlas-v1.2.0.zip v1.2.0
```

`.gitattributes` leaves the development-only files out of the archive: `tests/`, `.github/`, `.githooks/`, `.claude/`, `CLAUDE.md`, `CONTRIBUTING.md` and `REVIEW.md`. GitHub's source downloads leave them out too. Record the tag and the archive's SHA-256 checksum with the software import, so anyone can check that what's at work matches a tagged version.

## Working with Claude Code

`CLAUDE.md` tells Claude Code how the kit fits together and what it must never do. The rules above apply to Claude too:

- **Helper agents.** `.claude/agents/kit-reviewer.md` reviews a branch against REVIEW.md. `.claude/agents/page-checker.md` runs the browser checks and looks at the screenshots. Ask for them by name, for example: "use the kit-reviewer agent on this branch".
- **Workflow skill.** `.claude/skills/steward/SKILL.md` is the short version of this file for Claude: how to commit, push, open a pull request and respond to review and CI.
- **Claude never imports a real spreadsheet into this repository**, never pushes to `main`, and stops and tells you if the content guard finds anything.
