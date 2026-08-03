"""ACR v1.0 agent capability registry loading and validation.

The registry is deliberately a small, dependency-free boundary: entries are
JSON documents and are validated before any caller can use them for staffing
or agent spawning.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_DIRECTORY = Path(".project-os/COMPANY/DEPARTMENTS")

_AGENT_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_OWNERSHIP = re.compile(
    r"^(?:exclusive|shared|shared-with-[a-z][a-z0-9]*(?:-[a-z0-9]+)*)$"
)


class RegistryError(ValueError):
    """Base exception for ACR registry loading and validation failures."""


class RegistryValidationError(RegistryError):
    """An entry does not meet the mandatory ACR v1.0 contract."""


class DuplicateAgentIdError(RegistryError):
    """Two registry files declare the same ``agent-id``."""


class RegistryLoadError(RegistryError):
    """A registry document cannot be read as a JSON object."""


# All ACR 2.1--2.19 sections and their mandatory fields.  Only
# responsibilities.secondary-duties is marked optional in ACR v1.0.
_SECTIONS: dict[str, tuple[str, ...]] = {
    "purpose": ("mission-types", "value-streams", "strategic-objectives"),
    "responsibilities": ("primary-duties", "excluded-duties"),
    "authority": ("autonomous-decisions", "escalation-decisions", "authority-scope"),
    "decision-rights": ("decision-types", "decision-criteria", "reversibility"),
    "escalation-rights": (
        "escalation-triggers",
        "escalation-paths",
        "escalation-timeout",
    ),
    "required-skills": ("competencies", "proficiency-levels", "skill-validators"),
    "allowed-tools": (
        "tool-categories",
        "specific-tools",
        "tool-restrictions",
        "tool-validation",
    ),
    "allowed-mcp-servers": ("mcp-server-types", "specific-servers", "mcp-restrictions"),
    "owned-artifacts": (
        "artifact-types",
        "artifact-locations",
        "artifact-ownership",
        "artifact-retention",
    ),
    "owned-repository-areas": (
        "owned-paths",
        "writable-paths",
        "path-restrictions",
        "path-validation",
    ),
    "communication-rights": (
        "message-types-sent",
        "message-types-received",
        "communication-restrictions",
        "correlation-rules",
    ),
    "validation-duties": (
        "validation-gates",
        "validation-criteria",
        "evidence-requirements",
        "validation-automation",
    ),
    "recovery-duties": (
        "recovery-scenarios",
        "recovery-procedures",
        "state-checkpoints",
        "recovery-validation",
    ),
    "kpis-and-success-metrics": (
        "kpi-definitions",
        "metric-collection-method",
        "success-thresholds",
        "metric-reporting-frequency",
    ),
    "parallel-execution-rules": (
        "can-run-concurrently",
        "shared-resources",
        "conflict-resolution",
        "resource-limits",
    ),
    "dependencies": (
        "agent-dependencies",
        "tool-dependencies",
        "environment-dependencies",
        "dependency-validation",
    ),
    "input-contracts": (
        "input-message-types",
        "input-schema",
        "input-validation",
        "input-state-requirements",
    ),
    "output-contracts": (
        "output-message-types",
        "output-schema",
        "output-state-changes",
        "output-validation",
    ),
}

_IDENTITY = ("agent-id", "version", "display-name", "description")
_OPTIONAL_FIELDS = {("responsibilities", "secondary-duties")}
_EMPTY_LISTS_ALLOWED = {
    ("owned-repository-areas", "owned-paths"),
    ("owned-repository-areas", "writable-paths"),
}

_LIST_FIELDS = {
    ("purpose", "mission-types"),
    ("purpose", "value-streams"),
    ("purpose", "strategic-objectives"),
    ("responsibilities", "primary-duties"),
    ("responsibilities", "secondary-duties"),
    ("responsibilities", "excluded-duties"),
    ("authority", "autonomous-decisions"),
    ("authority", "escalation-decisions"),
    ("authority", "authority-scope"),
    ("decision-rights", "decision-types"),
    ("escalation-rights", "escalation-triggers"),
    ("required-skills", "competencies"),
    ("allowed-tools", "tool-categories"),
    ("allowed-tools", "specific-tools"),
    ("allowed-tools", "tool-restrictions"),
    ("allowed-tools", "tool-validation"),
    ("allowed-mcp-servers", "mcp-server-types"),
    ("allowed-mcp-servers", "specific-servers"),
    ("allowed-mcp-servers", "mcp-restrictions"),
    ("owned-artifacts", "artifact-types"),
    ("owned-repository-areas", "owned-paths"),
    ("owned-repository-areas", "writable-paths"),
    ("owned-repository-areas", "path-restrictions"),
    ("owned-repository-areas", "path-validation"),
    ("communication-rights", "message-types-sent"),
    ("communication-rights", "message-types-received"),
    ("communication-rights", "communication-restrictions"),
    ("communication-rights", "correlation-rules"),
    ("validation-duties", "validation-gates"),
    ("recovery-duties", "recovery-scenarios"),
    ("dependencies", "tool-dependencies"),
    ("dependencies", "environment-dependencies"),
    ("dependencies", "dependency-validation"),
    ("input-contracts", "input-message-types"),
    ("input-contracts", "input-validation"),
    ("input-contracts", "input-state-requirements"),
    ("output-contracts", "output-message-types"),
    ("output-contracts", "output-state-changes"),
    ("output-contracts", "output-validation"),
}

_MAPPING_FIELDS = {
    ("decision-rights", "decision-criteria"),
    ("decision-rights", "reversibility"),
    ("escalation-rights", "escalation-paths"),
    ("required-skills", "proficiency-levels"),
    ("required-skills", "skill-validators"),
    ("owned-artifacts", "artifact-locations"),
    ("owned-artifacts", "artifact-ownership"),
    ("owned-artifacts", "artifact-retention"),
    ("validation-duties", "validation-criteria"),
    ("validation-duties", "evidence-requirements"),
    ("validation-duties", "validation-automation"),
    ("recovery-duties", "recovery-procedures"),
    ("recovery-duties", "state-checkpoints"),
    ("recovery-duties", "recovery-validation"),
    ("kpis-and-success-metrics", "kpi-definitions"),
    ("kpis-and-success-metrics", "metric-collection-method"),
    ("kpis-and-success-metrics", "success-thresholds"),
    ("kpis-and-success-metrics", "metric-reporting-frequency"),
    ("input-contracts", "input-schema"),
    ("output-contracts", "output-schema"),
}


def _context(source: str | Path | None, field: str) -> str:
    return f"{source}: {field}" if source is not None else field


def _fail(source: str | Path | None, field: str, message: str) -> None:
    raise RegistryValidationError(f"{_context(source, field)} {message}")


def _require_nonempty_string(value: Any, source: str | Path | None, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(source, field, "must be a non-empty string")


def _require_nonempty_list(
    value: Any, source: str | Path | None, field: str, *, allow_empty: bool = False
) -> None:
    if not isinstance(value, list):
        _fail(source, field, "must be a list")
    if not value and not allow_empty:
        _fail(source, field, "must not be empty")
    for index, item in enumerate(value):
        _require_nonempty_string(item, source, f"{field}[{index}]")


def _require_mapping(
    value: Any, source: str | Path | None, field: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        _fail(source, field, "must be a non-empty object")
    for key in value:
        _require_nonempty_string(key, source, f"{field} key")
    return value


def _validate_mapping_values(
    value: Mapping[str, Any], source: str | Path | None, field: str
) -> None:
    """Validate the nested ACR data maps without over-constraining their prose."""
    for key, child in value.items():
        child_field = f"{field}.{key}"
        if isinstance(child, str):
            _require_nonempty_string(child, source, child_field)
        elif isinstance(child, list):
            _require_nonempty_list(child, source, child_field)
        elif isinstance(child, Mapping):
            nested = _require_mapping(child, source, child_field)
            _validate_mapping_values(nested, source, child_field)
        else:
            _fail(source, child_field, "must be a non-empty string, list, or object")


def validate_entry(
    entry: Mapping[str, Any],
    *,
    source: str | Path | None = None,
    expected_agent_id: str | None = None,
) -> None:
    """Validate one JSON-decoded ACR v1.0 entry.

    ``expected_agent_id`` is normally derived from the filename and prevents a
    registry document from silently being stored under the wrong agent type.
    """
    if not isinstance(entry, Mapping):
        _fail(source, "entry", "must be a JSON object")

    for field in _IDENTITY:
        if field not in entry:
            _fail(source, field, "is required")
        _require_nonempty_string(entry[field], source, field)

    agent_id = entry["agent-id"]
    if not _AGENT_ID.fullmatch(agent_id):
        _fail(source, "agent-id", "must be lowercase kebab-case")
    if expected_agent_id is not None and agent_id != expected_agent_id:
        _fail(source, "agent-id", f"must match filename agent id {expected_agent_id!r}")
    if not _SEMVER.fullmatch(entry["version"]):
        _fail(source, "version", "must be semantic version MAJOR.MINOR.PATCH")

    for section, fields in _SECTIONS.items():
        if section not in entry:
            _fail(source, section, "section is required")
        section_value = _require_mapping(entry[section], source, section)
        for field in fields:
            if field not in section_value:
                _fail(source, f"{section}.{field}", "is required")
            value = section_value[field]
            if (section, field) in _LIST_FIELDS:
                _require_nonempty_list(
                    value,
                    source,
                    f"{section}.{field}",
                    allow_empty=(section, field) in _EMPTY_LISTS_ALLOWED,
                )
            elif (section, field) in _MAPPING_FIELDS:
                nested = _require_mapping(value, source, f"{section}.{field}")
                _validate_mapping_values(nested, source, f"{section}.{field}")
            else:
                _require_nonempty_string(value, source, f"{section}.{field}")

        if section == "responsibilities" and "secondary-duties" in section_value:
            _require_nonempty_list(
                section_value["secondary-duties"], source, f"{section}.secondary-duties"
            )

    ownership = entry["owned-artifacts"]["artifact-ownership"]
    if not isinstance(ownership, Mapping):
        _fail(source, "owned-artifacts.artifact-ownership", "must be an object")
    for artifact, ownership_class in ownership.items():
        _require_nonempty_string(
            ownership_class, source, f"owned-artifacts.artifact-ownership.{artifact}"
        )
        if not _OWNERSHIP.fullmatch(ownership_class):
            _fail(
                source,
                f"owned-artifacts.artifact-ownership.{artifact}",
                "must be exclusive, shared, or shared-with-<owner>",
            )

    artifact_types = set(entry["owned-artifacts"]["artifact-types"])
    for metadata_field in (
        "artifact-locations",
        "artifact-ownership",
        "artifact-retention",
    ):
        metadata = entry["owned-artifacts"][metadata_field]
        metadata_types = set(metadata)
        missing = sorted(artifact_types - metadata_types)
        extraneous = sorted(metadata_types - artifact_types)
        if missing:
            _fail(
                source,
                f"owned-artifacts.{metadata_field}",
                f"is missing metadata for artifact type(s): {', '.join(missing)}",
            )
        if extraneous:
            _fail(
                source,
                f"owned-artifacts.{metadata_field}",
                f"has metadata for undeclared artifact type(s): {', '.join(extraneous)}",
            )


def load_registry(
    directory: str | Path = DEFAULT_REGISTRY_DIRECTORY,
) -> dict[str, dict[str, Any]]:
    """Load a directory of ACR JSON entries in deterministic filename order.

    A missing directory, malformed JSON, duplicate IDs, or an entry whose ID
    does not correspond to its filename raises a specific ``RegistryError``.
    """
    registry_directory = Path(directory)
    if not registry_directory.is_dir():
        raise RegistryLoadError(
            f"registry directory does not exist: {registry_directory}"
        )

    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(
        registry_directory.glob("*.json"), key=lambda candidate: candidate.name
    ):
        expected_agent_id = path.stem
        if not _AGENT_ID.fullmatch(expected_agent_id):
            raise RegistryLoadError(
                f"registry filename must be lowercase kebab-case: {path.name}"
            )
        try:
            with path.open("r", encoding="utf-8") as document:
                entry = json.load(document)
        except OSError as error:
            raise RegistryLoadError(
                f"cannot read registry entry {path}: {error}"
            ) from error
        except json.JSONDecodeError as error:
            raise RegistryLoadError(
                f"malformed JSON in registry entry {path}: {error.msg}"
            ) from error

        validate_entry(entry, source=path)
        agent_id = entry["agent-id"]
        if agent_id in entries:
            raise DuplicateAgentIdError(f"duplicate agent-id {agent_id!r} in {path}")
        if agent_id != expected_agent_id:
            raise RegistryValidationError(
                f"{path}: agent-id must match filename agent id {expected_agent_id!r}"
            )
        entries[agent_id] = dict(entry)
    return entries


def load_project_registry(project_root: str | Path = ".") -> dict[str, dict[str, Any]]:
    """Load the ACR registry from a project root's canonical directory."""
    return load_registry(Path(project_root) / DEFAULT_REGISTRY_DIRECTORY)
