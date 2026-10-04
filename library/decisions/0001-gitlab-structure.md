# 0001 GitLab group and project structure

> [!note] Example content for the atlas prototype. Replace it with your own.

**Status:** Accepted · **Date:** 2026-09-15 · **Owner:** Blake

## Context
FPGA designs, shared IP and scripts are spread across personal folders and one large legacy repository, so nobody can tell which copy is current.

## Decision
- One GitLab group for the team.
- One project per FPGA design.
- Shared IP blocks and build scripts in their own projects, pulled in at a tagged version.
- This handbook (atlas, roadmap and library) in its own project.

## Consequences
- Each design has its own history, issues and permissions.
- Shared IP changes are versioned and adopted deliberately, instead of reaching every design at once.
