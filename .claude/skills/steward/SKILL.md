---
name: steward
description: How to take a change to this repository from branch to merged pull request. Covers commits, the checks to run before pushing, the public-repository rule, pull request descriptions, and how to respond to review comments and CI. Use it when committing, pushing, opening or updating a pull request, or acting on review or CI for one.
---

# Steward: getting a change merged here

This repository is public. [CONTRIBUTING.md](../../../CONTRIBUTING.md) is the full process; this is the short version for Claude.

## Before every commit

- At the start of a session, turn on the hook: `git config core.hooksPath .githooks`. It runs `python tests/content_guard.py --staged` before each commit.
- If the guard finds anything, stop. Don't commit, don't work round it, and never use `--no-verify`. Tell the user what it found.
- Never import a real spreadsheet into this repository. Never add real names, programmes, customers, server names, internal links, screenshots or marked material. The example people are Avery, Blake, Casey, Drew, Ellis and Frankie.

## Commits

- Each commit does one thing and leaves the tests passing.
- Write the subject in the imperative, under 72 characters. Wrap the body at 72 characters and say what changed and why.

## Before pushing

Run these and confirm they pass:

- `python -m unittest discover -s tests -t tests`, and on Python 3.8 as well when `uv` is available: `uv run --no-project --python 3.8 -- python -m unittest discover -s tests -t tests`
- `python tools/build_atlas.py --check`, which must report no errors
- `python tests/content_guard.py`
- After any change to `tools/atlas_template.html`: `python tests/page_smoke.py --shots`, then look at the screenshots, or ask the page-checker agent to.

Update `README.md` for anything users will notice, and `CLAUDE.md` for any change to the structure or conventions.

## Pull requests

- Work on the branch the session was given. Otherwise branch from the latest `main` as `fix/…`, `feature/…` or `docs/…`.
- Open a pull request only when the user asks for one. Its title says what it does, in the imperative. Its body has these sections:
  - **What changed**
  - **Why**
  - **How it was checked**: the commands and their results
  - **What users will notice**: including README changes
  - **Where to look first**
- Never push to `main`. Never force-push a branch someone else works on.

## Review comments and CI

- The `tests` workflow runs the content guard, the unit tests on Python 3.8 and 3.13, a page build and the browser smoke test. Red CI is work to do now; don't wait it out.
- A content-guard failure on a commit that has been pushed means work content may already be public. Stop and tell the user at once (CONTRIBUTING.md, "If something from work does get pushed"). Pushing a commit that deletes it doesn't fix it.
- Judge findings with [REVIEW.md](../../../REVIEW.md):
  - Always fix blocking findings.
  - Fix small, clear asks and push.
  - For a larger ask, or a finding you disagree with, reply with your reasoning and let the author decide.
  - Optional nits go into the next push that touches the same files.
- Merging is the user's decision. The default is squash and merge. Use rebase and merge when the pull request holds separate commits that each pass on their own.
