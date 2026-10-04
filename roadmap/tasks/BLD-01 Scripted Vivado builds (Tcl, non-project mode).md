---
type: task
id: BLD-01
title: "Scripted Vivado builds (Tcl, non-project mode)"
parent: BLD
kind: setup
status: in-progress
owner: Ellis
milestone: M2
dal: [A, B, C, D]
depends_on: [GIT-02]
---
One command builds a design from a clean checkout, with no clicks and no local state.

## Subtasks
- [x] Build script for the pilot design
- [/] Parameterise it for other designs
- [ ] Document how to use it
- [ ] Run it in CI
