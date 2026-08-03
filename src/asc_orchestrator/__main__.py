"""Allow `python -m asc_orchestrator`."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
