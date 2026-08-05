# External Blockers

| Blocker | Why external | Independent work completed | Exact unblock action |
|---|---|---|---|
| No current release blocker. VAL v1.0 was defined and implemented in M014, adding gate verdicts and artifact verification on top of the completed local execution loop. | — | `docs/VAL_v1.0.md`, `src/asc_orchestrator/validation.py`, the GATE_* extension to the EEF `EVENT_TYPES` frozenset, six `validation-*` CLI commands, VAL unit and CLI suites, SHA-256 artifact binding, and the tamper-halt invalidation policy are complete and validated. | Preserve VAL as the canonical validation gate and artifact-verification contract; future work may extend encrypted transport and autonomous workflow scheduling. |
