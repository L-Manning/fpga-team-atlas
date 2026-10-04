# Code review checklist (draft v0.1)

> [!note] Draft being trialled on merge requests. Example content for the atlas prototype.

Work down the list and comment on the merge request rather than fixing things yourself.

## Before you start
- [ ] The merge request links its task and says what changed and why.
- [ ] CI is green: lint clean, simulation passing.

## Design
- [ ] Follows the coding standard: naming, one entity per file, no inferred latches.
- [ ] Every clock domain crossing uses an approved synchroniser.
- [ ] Resets follow the reset strategy.
- [ ] Constants and generics are named; no magic numbers.

## Verification
- [ ] New or changed behaviour has a test.
- [ ] Tests check results automatically; nobody has to read a waveform to know it passed.

## Constraints and build
- [ ] New clocks and I/O are constrained.
- [ ] Every timing exception has a comment justifying it.

## Close out
- [ ] Every comment is resolved or answered.
- [ ] Documentation is updated where behaviour changed.
