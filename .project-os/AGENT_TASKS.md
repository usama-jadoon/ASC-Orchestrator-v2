# Agent Tasks and File Ownership

| Agent | Objective | Allowed scope | Exclusions | Status |
|---|---|---|---|---|
| Root / implementation lead | Establish Python packaging, configuration, CLI, durable state updates, and integration | `pyproject.toml`, `src/asc_orchestrator/__init__.py`, `src/asc_orchestrator/config.py`, `src/asc_orchestrator/cli.py`, `src/asc_orchestrator/errors.py`, `tests/test_config.py`, `.project-os/*.md` | ACP, audit, registry implementation and their tests | COMPLETE |
| ACP runtime worker | Implement ACP v1.0 parsing, serialization, validation, and local audit journaling | `src/asc_orchestrator/acp.py`, `src/asc_orchestrator/audit.py`, `tests/test_acp.py` | Package metadata, CLI, config, registry, project-state files | COMPLETE |
| Registry worker | Implement ACR v1.0 registry validation/loading and seed entries | `src/asc_orchestrator/registry.py`, `.project-os/COMPANY/DEPARTMENTS/*.json`, `tests/test_registry.py` | Package metadata, CLI, config, ACP/audit, project-state files | COMPLETE |
| PESE specification writer | Author the canonical PESE v1.0 normative contract compatible with ACP/ACR/TBE | `docs/PESE_v1.0.md` | Existing specifications, README, `.project-os` state, runtime code | COMPLETE |
| PESE runtime worker | Implement the canonical PESE v1.0 storage, integrity, lock, checkpoint, resume, recovery, and migration API | `src/asc_orchestrator/pese.py`, `tests/test_pese.py` | CLI, configuration, documentation, `.project-os` state, and all non-PESE runtime modules | COMPLETE |
| TBE runtime worker | Implement deterministic TBE v1.0 team selection, dependency resolution, ownership, and validation contracts | `src/asc_orchestrator/tbe.py`, `tests/test_tbe.py` | CLI, documentation, `.project-os` state, and ACP/ACR/PESE runtime modules | COMPLETE |
