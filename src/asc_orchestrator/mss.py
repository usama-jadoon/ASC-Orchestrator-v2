"""Mission Specification Standard (MSS v1.0) canonical mission-intake runtime.

MSS defines the deterministic JSON contract an operator submits to declare a
mission before the Team Builder Engine assembles a team and before PESE
persists any state.  This module implements the canonical intake layer only:
schema identity, mission vocabulary, structured parsing, and semantic
validation.  It deliberately does not plan, execute, orchestrate, or schedule
agents; those capabilities belong to later milestones.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

# --- Canonical vocabulary ---------------------------------------------------

MSS_SCHEMA = "MSS"
MSS_VERSION = "1.0"

MISSION_TYPES = frozenset(
    {
        "greenfield-project",
        "single-file-fix",
        "enhancement",
        "legacy-rescue",
        "multi-repo-orchestration",
        "spike",
        "compliance-audit",
    }
)

MISSION_CLASSES = frozenset({"bounded", "open-ended"})

PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})

VALIDATION_GATES = frozenset(
    {
        "GATE:qa",
        "GATE:security",
        "GATE:integrity",
        "GATE:release",
        "GATE:compliance",
    }
)

AUTHORITY_SCOPE_VOCABULARY = frozenset(
    {
        "Repository State: read-only access",
        "Repository State: read/write within owned paths",
        "Mission State: observation of assigned mission",
        "Mission State: update own mission facts",
        "Execution State: update own progress and step completion",
        "Validation State: read/write for security gate artifacts",
        "Validation State: read/write for owned gate artifacts",
        "Risk State: read/write for active risk registry",
    }
)

BASELINE_GATES: Mapping[str, frozenset[str]] = {
    "greenfield-project": frozenset({"GATE:qa", "GATE:release"}),
    "single-file-fix": frozenset({"GATE:qa"}),
    "enhancement": frozenset({"GATE:qa", "GATE:release"}),
    "legacy-rescue": frozenset({"GATE:qa", "GATE:security", "GATE:compliance"}),
    "multi-repo-orchestration": frozenset({"GATE:qa", "GATE:release"}),
    "spike": frozenset({"GATE:qa"}),
    "compliance-audit": frozenset({"GATE:compliance", "GATE:security"}),
}

_MISSION_ID_PATTERN = re.compile(r"MISSION:[A-Za-z0-9][A-Za-z0-9._-]*$")
_EXTENSION_KEY_PATTERN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9_-]+)+$", re.IGNORECASE)

_MISSION_KEYS = (
    "schema",
    "version",
    "mission_id",
    "mission_type",
    "mission_class",
    "priority",
    "objective",
    "acceptance_criteria",
    "constraints",
    "constraint_tags",
    "value_streams",
    "boundaries",
    "stakeholders",
    "validation_gates",
    "authority_scope",
    "created_at",
    "created_by",
    "source",
    "extensions",
)


class MSSError(ValueError):
    """A structural MSS v1.0 mission-intake failure.

    Structural failures (missing fields, wrong shapes, unreadable files) raise
    :class:`MSSError`; semantic problems (unknown mission type, unknown gate)
    are reported as findings on :class:`MissionValidationResult`.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class MissionFinding:
    """One structured MSS validation finding with a future severity model."""

    severity: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MissionValidationResult:
    """Outcome of a semantic MSS mission-specification validation."""

    ok: bool
    findings: tuple[MissionFinding, ...] = ()
    mission_id: str | None = None
    mission_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MissionSpec(Mapping[str, Any]):
    """Canonical, immutable MSS v1.0 mission-intake contract.

    ``MissionSpec`` implements :class:`collections.abc.Mapping` so the TBE
    ``MissionContract.from_mapping`` bridge consumes it directly: unknown keys
    raise ``KeyError`` (``Mapping.get`` then returns its default) while every
    canonical key is exposed verbatim.
    """

    schema: str
    version: str
    mission_id: str
    mission_type: str
    mission_class: str
    priority: str
    objective: str
    acceptance_criteria: tuple[Mapping[str, Any], ...]
    constraints: tuple[Mapping[str, Any], ...]
    constraint_tags: tuple[str, ...]
    value_streams: tuple[str, ...]
    boundaries: tuple[str, ...]
    stakeholders: tuple[str, ...]
    validation_gates: tuple[str, ...]
    authority_scope: tuple[str, ...]
    created_at: str
    created_by: str
    source: str
    extensions: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __getitem__(self, key: str) -> Any:
        if key not in _MISSION_KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(_MISSION_KEYS)

    def __len__(self) -> int:
        return len(_MISSION_KEYS)

    def to_mapping(self) -> dict[str, Any]:
        """Return a plain JSON-serializable mapping of this contract."""
        result: dict[str, Any] = {}
        for key in _MISSION_KEYS:
            value = getattr(self, key)
            if key == "extensions" and isinstance(value, Mapping):
                result[key] = dict(value)
            else:
                result[key] = value
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionSpec":
        """Parse a mission-intake JSON object into an immutable ``MissionSpec``.

        Structural problems (including a non-object input) raise
        :class:`MSSError`; semantic problems are left for
        :func:`validate_mission_spec`.
        """
        if not isinstance(value, Mapping):
            raise MSSError("INPUT_INVALID", "mission spec must be a JSON object")
        return cls(
            schema=_text(value.get("schema"), "schema"),
            version=_text(value.get("version"), "version"),
            mission_id=_text(value.get("mission_id"), "mission_id"),
            mission_type=_text(value.get("mission_type"), "mission_type"),
            mission_class=_text(value.get("mission_class"), "mission_class"),
            priority=_text(value.get("priority"), "priority"),
            objective=_text(value.get("objective"), "objective"),
            acceptance_criteria=_mappings(
                value.get("acceptance_criteria"), "acceptance_criteria"
            ),
            constraints=_mappings(value.get("constraints"), "constraints"),
            constraint_tags=_strings(value.get("constraint_tags"), "constraint_tags"),
            value_streams=_strings(value.get("value_streams"), "value_streams"),
            boundaries=_strings(value.get("boundaries"), "boundaries"),
            stakeholders=_strings(value.get("stakeholders"), "stakeholders"),
            validation_gates=_strings(
                value.get("validation_gates"), "validation_gates"
            ),
            authority_scope=_strings(value.get("authority_scope"), "authority_scope"),
            created_at=_text(value.get("created_at"), "created_at"),
            created_by=_text(value.get("created_by"), "created_by"),
            source=_text(value.get("source"), "source"),
            extensions=_extensions(value.get("extensions"), "extensions"),
        )


# --- Input helpers ----------------------------------------------------------


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MSSError("INPUT_INVALID", f"{field_name} must be a non-empty string")
    return value.strip()


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(x, str) for x in value
    ):
        raise MSSError("INPUT_INVALID", f"{field_name} must be a sequence of strings")
    return tuple(x.strip() for x in value)


def _mappings(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(x, Mapping) for x in value
    ):
        raise MSSError("INPUT_INVALID", f"{field_name} must be a sequence of objects")
    return tuple(x for x in value)


def _extensions(value: Any, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise MSSError("INPUT_INVALID", f"{field_name} must be an object")
    return MappingProxyType({str(key): item for key, item in value.items()})


# --- Validation --------------------------------------------------------------


def _is_iso_utc(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _severity_counts(findings: list[MissionFinding]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def validate_mission_spec(mission: MissionSpec) -> MissionValidationResult:
    """Semantically validate a parsed ``MissionSpec``.

    Returns a structured :class:`MissionValidationResult`; it never raises for
    a well-formed ``MissionSpec``.  ``ok`` is ``False`` only when at least one
    ``error``-severity finding exists.
    """
    findings: list[MissionFinding] = []

    if mission.schema != MSS_SCHEMA:
        findings.append(
            MissionFinding(
                "error",
                "SCHEMA_MISMATCH",
                f"schema must be {MSS_SCHEMA!r}",
            )
        )
    if mission.version != MSS_VERSION:
        findings.append(
            MissionFinding(
                "error",
                "VERSION_UNSUPPORTED",
                f"version must be {MSS_VERSION!r}",
            )
        )
    if mission.mission_type not in MISSION_TYPES:
        findings.append(
            MissionFinding(
                "error",
                "MISSION_TYPE_UNKNOWN",
                f"unknown mission_type {mission.mission_type!r}",
            )
        )
    if mission.mission_class not in MISSION_CLASSES:
        findings.append(
            MissionFinding(
                "error",
                "MISSION_CLASS_UNKNOWN",
                f"unknown mission_class {mission.mission_class!r}",
            )
        )
    if mission.priority not in PRIORITIES:
        findings.append(
            MissionFinding(
                "error",
                "PRIORITY_UNKNOWN",
                f"unknown priority {mission.priority!r}",
            )
        )
    if not _MISSION_ID_PATTERN.fullmatch(mission.mission_id):
        findings.append(
            MissionFinding(
                "error",
                "MISSION_ID_INVALID",
                f"mission_id {mission.mission_id!r} must match "
                "MISSION:[A-Za-z0-9][A-Za-z0-9._-]*",
            )
        )
    if not _is_iso_utc(mission.created_at):
        findings.append(
            MissionFinding(
                "error",
                "CREATED_AT_INVALID",
                f"created_at {mission.created_at!r} must be a UTC RFC 3339 timestamp",
            )
        )
    for gate in mission.validation_gates:
        if gate not in VALIDATION_GATES:
            findings.append(
                MissionFinding(
                    "error",
                    "GATE_UNKNOWN",
                    f"unknown validation gate {gate!r}",
                )
            )
    for scope in mission.authority_scope:
        if scope not in AUTHORITY_SCOPE_VOCABULARY:
            findings.append(
                MissionFinding(
                    "error",
                    "AUTHORITY_SCOPE_UNKNOWN",
                    f"unknown authority-scope phrase {scope!r}",
                )
            )

    missing = sorted(
        BASELINE_GATES.get(mission.mission_type, frozenset())
        - set(mission.validation_gates)
    )
    for gate in missing:
        findings.append(
            MissionFinding(
                "warning",
                "BASELINE_GATE_MISSING",
                f"{mission.mission_type} baseline gate {gate} is not declared",
            )
        )

    if not mission.acceptance_criteria:
        findings.append(
            MissionFinding(
                "warning",
                "NO_ACCEPTANCE_CRITERIA",
                "no acceptance criteria are declared",
            )
        )
    for index, criterion in enumerate(mission.acceptance_criteria, start=1):
        if "id" not in criterion or "description" not in criterion:
            findings.append(
                MissionFinding(
                    "warning",
                    "ACCEPTANCE_CRITERIA_INCOMPLETE",
                    f"criterion {index} must include id and description",
                )
            )
        criterion_gate = criterion.get("gate")
        if criterion_gate is not None and criterion_gate not in VALIDATION_GATES:
            findings.append(
                MissionFinding(
                    "warning",
                    "CRITERION_GATE_UNKNOWN",
                    f"criterion {index} gate {criterion_gate!r} is not canonical",
                )
            )
    for index, constraint in enumerate(mission.constraints, start=1):
        if "kind" not in constraint or "value" not in constraint:
            findings.append(
                MissionFinding(
                    "warning",
                    "CONSTRAINTS_INCOMPLETE",
                    f"constraint {index} must include kind and value",
                )
            )
    for key in mission.extensions:
        if not _EXTENSION_KEY_PATTERN.fullmatch(key):
            findings.append(
                MissionFinding(
                    "warning",
                    "EXTENSION_KEY_INVALID",
                    f"extension key {key!r} must be reverse-DNS",
                )
            )

    ok = not any(finding.severity == "error" for finding in findings)
    return MissionValidationResult(
        ok=ok,
        findings=tuple(findings),
        mission_id=mission.mission_id,
        mission_type=mission.mission_type,
        metadata={
            "schema": mission.schema,
            "version": mission.version,
            "severity_counts": _severity_counts(findings),
        },
    )


# --- File loading ------------------------------------------------------------


def load_mission_spec(path: Path) -> MissionSpec:
    """Load and structurally parse an MSS mission-specification JSON file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MSSError("LOAD_FAILED", f"cannot load mission spec: {error}") from error
    if not isinstance(raw, dict):
        raise MSSError("INPUT_INVALID", "mission spec must be a JSON object")
    return MissionSpec.from_mapping(raw)


def validate_mission_file(path: Path) -> MissionValidationResult:
    """Load a mission file and return its semantic validation result.

    Structural failures (missing file, invalid JSON, malformed fields) raise
    :class:`MSSError`; semantic problems are returned as findings.
    """
    return validate_mission_spec(load_mission_spec(path))
