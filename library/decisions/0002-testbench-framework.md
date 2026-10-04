# 0002 Testbench framework

> [!note] Example content for the atlas prototype. Replace it with your own.

**Status:** Accepted · **Date:** 2026-08-28 · **Owner:** Avery

## Context
Every engineer writes testbenches differently, so logs, pass/fail reporting and coverage can't be compared or collected automatically.

## Decision
All new testbenches use OSVVM, starting from the team's testbench template (VER-02) once it is published.

## Consequences
- One way of writing tests, checking results and reporting coverage.
- Existing testbenches move over when they are next changed, not all at once.
