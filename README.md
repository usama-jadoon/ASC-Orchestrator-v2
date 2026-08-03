# ASC Orchestrator v2

Autonomous Software Company Orchestrator - Version 2

A professional open-source repository serving as the permanent Global Software Company Operating System.

## Mission

To establish a foundation for autonomous software company operations through a modular, extensible CLI-based orchestration system.

## Repository Structure

This repository serves as the foundation for the ASC Orchestrator v2, containing:

- Python runtime foundation for ACP v1.0 and ACR v1.0 validation
- Canonical PESE v1.0 specification for persistent mission, execution, validation, risk, agent, repository, and checkpoint state
- PESE v1.0 runtime for atomic state history, checkpoints, integrity validation, deterministic resume, locking, recovery, and migration records
- Local configuration and CLI validation commands
- JSON ACR department registry entries and deterministic registry loading
- Standard-library automated tests
- GitHub community files (CONTRIBUTING, ISSUE_TEMPLATES, etc.)

## Local development

Python 3.11 or later is required. No third-party runtime dependencies are needed.

```powershell
python -m unittest discover -s tests -t . -v
$env:PYTHONPATH = "src"
python -m asc_orchestrator --root . config
python -m asc_orchestrator --root . registry
python -m asc_orchestrator --root . state --initialize
python -m asc_orchestrator --root . state
python -m asc_orchestrator --root . validate-state
python -m asc_orchestrator --root . resume
python -m asc_orchestrator --root . checkpoint --mission-id MISSION:example
```

`asc-orchestrator.toml` is the canonical local runtime configuration. ACP audit records are written beneath `.project-os/AUDIT/`; ACR entries are loaded from `.project-os/COMPANY/DEPARTMENTS/`.

PESE persists only beneath `.project-os/PESE/`. `state --initialize` creates the required layout and revision 1; all normal state changes belong to the typed PESE runtime API, so the CLI `checkpoint` command deliberately creates only a `MANUAL` checkpoint. `resume` is read-only. Every state command emits a structured outcome, including its operation ID and non-secret integrity findings.

PESE is specified in [PESE v1.0](./docs/PESE_v1.0.md), which remains the canonical contract. Validate a checkout with:

```powershell
python -m unittest discover -s tests -t . -v
python -m mypy
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/validate_docs.py
```

## Documentation

See the [docs](./docs) directory for detailed documentation.

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Security Policy

See our [security policy](SECURITY.md) for details on reporting security vulnerabilities.

## Acknowledgments

- Built as part of the Autonomous Software Company initiative
