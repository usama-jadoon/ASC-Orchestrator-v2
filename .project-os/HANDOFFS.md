# Specialist Handoffs

Record only distilled results and links to evidence. Do not paste private reasoning or huge logs.

## M006.5 — PESE v1.0 specification

- Canonical source: `docs/PESE_v1.0.md`.
- Compatibility: ACP audit remains logically separate; ACR remains the capability authority; TBE remains the team/recovery authority.
- Validation: JSON examples, required-topic coverage, and independent ACP/ACR/TBE compatibility review passed.
- Next: MISSION-007 implements PESE v1.0 without changing its state, checkpoint, resume, migration, locking, integrity, or recovery contracts.

## MISSION-007 - PESE Runtime v1.0

- Runtime: `src/asc_orchestrator/pese.py` implements the canonical `.project-os/PESE/` layout, immutable history, locks, audits, checkpoints, integrity checks, resume, recovery, and migrations.
- CLI: `state`, `resume`, `checkpoint`, and `validate-state` are wired through `src/asc_orchestrator/cli.py`.
- Validation: 44 unit tests, three repeated full-suite reliability runs, MyPy, Ruff, source compilation, documentation validation, Git lifecycle smoke tests, and independent QA/review passed.
- Boundary: PESE persists and validates facts; it does not implement mission, team-building, execution, or validation engines.

