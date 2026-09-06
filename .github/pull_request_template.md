## Problem

<!-- What's broken, missing, or risky today? Link an issue if one exists. -->

## Design decision

<!-- What did you build, and why this approach over the alternatives? -->

## Failure modes considered

<!-- What can go wrong (bad input, concurrent access, partial failure,
     a client retry, a rollback) and how does this change behave? -->

## Tests added

<!-- New/changed tests, and what each one actually proves. -->

## Rollback impact

<!-- Schema migrations? New dependencies? What happens if this PR is
     reverted — is that safe, or does something need to happen first? -->

## Verification commands

```bash
cd backend
python -m pytest -q
python -m ruff check app tests loadtest
python -m mypy app
```

---

- [ ] `make check` passes locally (or CI is green on this PR)
- [ ] Docs updated if this changes behaviour someone would reasonably read about
      (`docs/architecture.md`, `docs/verification_matrix.md`,
      `docs/production_gap_register.md` — add a gap row for anything this
      *doesn't* actually solve, don't leave that implicit)
- [ ] No claim in this PR's description or in updated docs outruns what a
      test or a command in "Verification commands" actually proves
