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

## M008 - Team Builder Engine Runtime v1.0

- Runtime: `src/asc_orchestrator/tbe.py` implements deterministic registry-only selection, capacity and leadership decisions, exclusive ownership, assignment-level INPUT/RESOURCE dependencies, review/validator selection, escalation routes, and canonical `TEAM.md` rendering.
- CLI: `team-build` accepts explicit mission and classification JSON, writes the canonical manifest, supports controlled timestamps, and optionally binds it to PESE.
- PESE integration: manifest binding persists builder, review, and validator assignments with their prerequisite chain; Review Matrix/Validator Assignment work is authorized from canonical TEAM.md and gate status blocks milestone completion.
- Validation: 66 unit tests, Ruff, MyPy, formatting, compilation, documentation validation, controlled manifest reproducibility, and independent QA/conformance review passed.
- Boundary: TBE assembles and persists deterministic team plans only. It does not execute agents, run autonomous workflows, or orchestrate LLMs.

