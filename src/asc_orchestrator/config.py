"""Local, deterministic runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .errors import ConfigurationError


DEFAULT_CONFIG_NAME = "asc-orchestrator.toml"
REQUIRED_RUNTIME_KEYS = {
    "project_os_dir",
    "registry_dir",
    "audit_dir",
    "protocol_version",
}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Resolved local paths and protocol version for a repository runtime."""

    repository_root: Path
    project_os_dir: Path
    registry_dir: Path
    audit_dir: Path
    protocol_version: str


def _resolve_relative(repository_root: Path, value: object, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"runtime.{key} must be a non-empty string")
    path = Path(value)
    return path if path.is_absolute() else repository_root / path


def load_config(
    repository_root: str | Path = ".", config_name: str = DEFAULT_CONFIG_NAME
) -> RuntimeConfig:
    """Load and validate the repository-local TOML configuration."""

    root = Path(repository_root).resolve()
    config_path = root / config_name
    if not config_path.is_file():
        raise ConfigurationError(f"configuration file does not exist: {config_path}")

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML configuration: {error}") from error

    runtime = raw.get("runtime")
    if not isinstance(runtime, dict):
        raise ConfigurationError("configuration must contain a [runtime] table")
    missing = REQUIRED_RUNTIME_KEYS.difference(runtime)
    if missing:
        raise ConfigurationError(
            "runtime configuration is missing required keys: " + ", ".join(sorted(missing))
        )
    unknown = set(runtime).difference(REQUIRED_RUNTIME_KEYS)
    if unknown:
        raise ConfigurationError(
            "runtime configuration contains unsupported keys: " + ", ".join(sorted(unknown))
        )

    protocol_version = runtime["protocol_version"]
    if protocol_version != "ACP/v1.0":
        raise ConfigurationError("runtime.protocol_version must be ACP/v1.0")

    return RuntimeConfig(
        repository_root=root,
        project_os_dir=_resolve_relative(root, runtime["project_os_dir"], "project_os_dir"),
        registry_dir=_resolve_relative(root, runtime["registry_dir"], "registry_dir"),
        audit_dir=_resolve_relative(root, runtime["audit_dir"], "audit_dir"),
        protocol_version=protocol_version,
    )
