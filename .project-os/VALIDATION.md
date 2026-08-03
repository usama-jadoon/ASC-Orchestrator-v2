# Validation

| Date | Gate / command | Result | Evidence or failure summary |
|---|---|---|---|
| 2026-08-04 | `python -m unittest discover -s tests -t . -v` | PASS | 20 tests passed, including separate-process audit-chain test. |
| 2026-08-04 | CLI smoke | PASS | `config` resolved ACP/v1.0 and `registry` loaded two deterministic ACR entries. |
| 2026-08-04 | JSON validation | PASS | Both registry entries parsed with `python -m json.tool`. |
| 2026-08-04 | Package build | PASS | Dependency-free wheel build produced `asc_orchestrator-0.1.0-py3-none-any.whl`. |
| 2026-08-04 | Independent QA and review | PASS | QA verified custom audit path and concurrent CLI writes; review found no remaining actionable M006 findings. |
| 2026-08-04 | PESE v1.0 structural validation | PASS | JSON examples parse; Markdown fences balance; required-topic checks pass. |
| 2026-08-04 | PESE v1.0 compatibility review | PASS | Independent review verified ACP, ACR, and TBE integration, bounded replacement lineage, and team-directory mission-record archival. |
| 2026-08-04 | PESE runtime unit suite | PASS | 44 `unittest` cases passed, including state/history integrity, checkpoints, recovery, migration, manifest authority, and separate-process audit-chain tests. |
| 2026-08-04 | PESE runtime reliability | PASS | Three consecutive full-suite passes and repeated eight-process audit-chain stress runs passed on Windows. |
| 2026-08-04 | Type and lint gates | PASS | `python -m mypy` and `python -m ruff check src tests scripts` passed. |
| 2026-08-04 | Documentation and runtime integrity | PASS | `python scripts/validate_docs.py`, source compilation, temporary-Git `state`/`validate-state`/`resume` lifecycle, and independent QA/conformance review passed. |
