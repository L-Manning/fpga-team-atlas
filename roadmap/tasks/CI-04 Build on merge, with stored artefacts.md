---
type: task
id: CI-04
title: "Build on merge, with stored artefacts"
parent: CI
kind: setup
status: planned
owner: Ellis
milestone: M2
dal: [A, B, C, D]
depends_on: [CI-01, BLD-01]
---
Every merge to main produces a build whose outputs are stored against the commit.
