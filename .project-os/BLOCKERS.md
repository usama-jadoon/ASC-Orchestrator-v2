# External Blockers

| Blocker | Why external | Independent work completed | Exact unblock action |
|---|---|---|---|
| No current release blocker. RKM v1.0 was defined and implemented in M015, adding the risk ledger and hold mechanism that gate autonomous execution on HALT / unresolved CRITICAL / declared HIGH block conditions. | — | `docs/RKM_v1.0.md`, `src/asc_orchestrator/risk.py`, the RISK_* extension to the EEF `EVENT_TYPES` frozenset, nine `risk-*` CLI commands, RKM unit and CLI suites, `org.asc.rkm` block-condition storage, and the `risk-check` hold-mechanism gate are complete and validated. | Preserve RKM as the canonical risk-management and hold-mechanism contract; future work may extend encrypted transport and autonomous workflow scheduling. |
