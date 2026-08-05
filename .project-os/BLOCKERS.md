# External Blockers

| Blocker | Why external | Independent work completed | Exact unblock action |
|---|---|---|---|
| No current release blocker. AHP v1.0 was defined and implemented in M013, adding agent liveness observation on top of the completed local execution loop. | — | `docs/AHP_v1.0.md`, `src/asc_orchestrator/health.py`, four `health-*` CLI commands, AHP unit and CLI suites, hash-chained heartbeat journals, and the ALIVE/STALLED/UNKNOWN liveness model are complete and validated. | Preserve AHP as the canonical agent-health and liveness-observation contract; future work may extend encrypted transport and autonomous workflow scheduling. |
