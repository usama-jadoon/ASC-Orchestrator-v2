"""Deterministic Team Builder Engine (TBE v1.0) planning boundary.

TBE consumes a mission, repository classification, and *already validated* ACR
registry entries.  It deliberately does not activate agents, write TEAM.md, or
mutate PESE.  The caller can persist :meth:`TeamManifest.to_markdown` at the
canonical TEAM.md location after validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from .acp import validate_agent_id


class TBEError(ValueError):
    """A TBE v1.0 assembly or manifest-validation failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


PHASES = (
    "INVESTIGATION",
    "PLANNING",
    "BUILD",
    "TEST",
    "SECURITY",
    "STAGING/INTEGRATION",
    "RELEASE-VALIDATION",
    "RELEASE",
)
DEPARTMENTS = (
    "ENGINEERING",
    "QUALITY",
    "SECURITY",
    "OPERATIONS",
    "PRODUCT",
    "DESIGN",
    "DATA",
    "RESEARCH",
)
_GATE_DEFAULTS = {
    "functional": "qa-validator",
    "acceptance": "qa-validator",
    "security": "security-auditor",
    "compliance": "compliance-validator",
    "release": "release-manager",
}


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TBEError("INPUT_INVALID", f"{field_name} must be a non-empty string")
    return value.strip()


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(x, str) or not x.strip() for x in value
    ):
        raise TBEError(
            "INPUT_INVALID", f"{field_name} must be a sequence of non-empty strings"
        )
    return tuple(sorted(dict.fromkeys(x.strip() for x in value)))


@dataclass(frozen=True, slots=True)
class ProjectClassification:
    type: str
    root_path: str
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    platform: str = "unknown"
    test_surface: str = ""
    deployment_surface: str = ""
    constraint_tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProjectClassification":
        return cls(
            _text(value.get("type"), "project.type"),
            _text(value.get("root_path", value.get("root")), "project.root_path"),
            _strings(value.get("languages", ()), "project.languages"),
            _strings(value.get("frameworks", ()), "project.frameworks"),
            str(value.get("platform", "unknown")),
            str(value.get("test_surface", value.get("test-surface", ""))),
            str(value.get("deployment_surface", value.get("deployment-surface", ""))),
            _strings(
                value.get("constraint_tags", value.get("constraint-tags", ())),
                "project.constraint_tags",
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityDemand:
    demand_id: str
    capability: str
    source_project: str
    source_criterion: str
    mutable_paths: tuple[str, ...] = ()
    validation_gates: tuple[str, ...] = ()
    role: str = "builder"
    depends_on: tuple[str, ...] = ()
    handoff_message_type: str = "EVIDENCE"
    artifact_class: str | None = None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], index: int = 1
    ) -> "CapabilityDemand":
        capability = _text(value.get("capability"), "demand.capability")
        raw_paths = value.get("mutable_paths", value.get("paths", ()))
        role = str(
            value.get(
                "role",
                "validator"
                if value.get("validation_gates") and not raw_paths
                else "builder",
            )
        ).lower()
        if role not in {"builder", "reviewer", "validator", "investigator", "support"}:
            raise TBEError("INPUT_INVALID", f"demand.role is unsupported: {role}")
        return cls(
            str(value.get("demand_id", value.get("id", f"DEMAND:{index:03d}"))),
            capability,
            str(value.get("source_project", value.get("project", "."))),
            str(value.get("source_criterion", value.get("criterion", capability))),
            _strings(
                value.get("mutable_paths", value.get("paths", ())),
                "demand.mutable_paths",
            ),
            _strings(
                value.get("validation_gates", value.get("gates", ())),
                "demand.validation_gates",
            ),
            role,
            _strings(value.get("depends_on", ()), "demand.depends_on"),
            str(value.get("handoff_message_type", "EVIDENCE")).upper(),
            _optional_text(
                value.get("artifact_class", value.get("artifact-class")),
                "demand.artifact_class",
            ),
        )


@dataclass(frozen=True, slots=True)
class MissionContract:
    mission_id: str
    mission_type: str
    objective: str
    acceptance_criteria: tuple[Mapping[str, Any], ...] = ()
    demands: tuple[CapabilityDemand, ...] = ()
    constraint_tags: tuple[str, ...] = ()
    project_class: str = "small"
    sequence: int = 1

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionContract":
        criteria = value.get(
            "acceptance_criteria", value.get("acceptance-criteria", ())
        )
        if not isinstance(criteria, (list, tuple)) or any(
            not isinstance(x, Mapping) for x in criteria
        ):
            raise TBEError(
                "INPUT_INVALID", "mission.acceptance_criteria must be mappings"
            )
        raw_demands = value.get("demands", ())
        if not isinstance(raw_demands, (list, tuple)):
            raise TBEError("INPUT_INVALID", "mission.demands must be a sequence")
        return cls(
            _text(value.get("mission_id", value.get("id")), "mission.mission_id"),
            _text(value.get("mission_type", value.get("type")), "mission.mission_type"),
            _text(value.get("objective"), "mission.objective"),
            tuple(criteria),
            tuple(
                CapabilityDemand.from_mapping(x, i + 1)
                if isinstance(x, Mapping)
                else _raise("INPUT_INVALID", "mission.demands contains non-mapping")
                for i, x in enumerate(raw_demands)
            ),
            _strings(
                value.get("constraint_tags", value.get("constraint-tags", ())),
                "mission.constraint_tags",
            ),
            str(value.get("project_class", "small")).lower(),
            int(value.get("sequence", 1)),
        )


def _raise(code: str, detail: str) -> Any:
    raise TBEError(code, detail)


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


@dataclass(frozen=True, slots=True)
class TeamMember:
    agent_id: str
    agent_type: str
    role: str
    department: str
    registry_reference: str
    capacity: int | None
    headroom: int | None


@dataclass(frozen=True, slots=True)
class OwnershipEntry:
    assignment_id: str
    area: str
    owner_agent_id: str
    ownership_class: str = "exclusive"
    restrictions: tuple[str, ...] = ()
    artifact_class: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source: str
    target: str
    edge_type: str


@dataclass(frozen=True, slots=True)
class TeamManifest:
    team_id: str
    mission_id: str
    version: int
    assembled_at: str
    operating_mode: str
    objective: str
    classifications: tuple[ProjectClassification, ...]
    members: tuple[TeamMember, ...]
    ownership: tuple[OwnershipEntry, ...]
    dependencies: tuple[DependencyEdge, ...]
    parallel_groups: tuple[tuple[str, tuple[str, ...]], ...]
    phases: tuple[tuple[str, int], ...]
    reviews: tuple[tuple[str, str, str, str], ...]
    validators: tuple[tuple[str, str, str | None], ...]
    escalation_routes: tuple[tuple[str, tuple[str, ...]], ...]
    policies: tuple[tuple[str, str], ...]
    selection_records: tuple[tuple[str, str, tuple[str, ...], str], ...] = ()

    def to_markdown(self) -> str:
        """Return canonical LF-terminated TEAM.md text in TBE §2.4 order."""
        lines = [
            "# TEAM.md",
            "",
            "## TEAM IDENTITY",
            f"Team ID: {self.team_id}",
            f"Mission ID: {self.mission_id}",
            f"Manifest Version: {self.version}",
            f"Assembly Timestamp: {self.assembled_at}",
            f"Operating Mode: {self.operating_mode}",
            f"Objective: {self.objective}",
            "",
            "## PROJECT CLASSIFICATION",
            "| Root | Type | Languages | Frameworks | Platform | Test surface | Deployment surface | Constraint tags |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {x.root_path} | {x.type} | {', '.join(x.languages) or '-'} | {', '.join(x.frameworks) or '-'} | {x.platform} | {x.test_surface or '-'} | {x.deployment_surface or '-'} | {', '.join(x.constraint_tags) or '-'} |"
            for x in self.classifications
        ]
        lines += [
            "",
            "## MEMBERSHIP TABLE",
            "| Agent ID | Role | Department | ACR registry reference |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {m.agent_id} | {m.role.title()} | {m.department} | {m.registry_reference} |"
            for m in self.members
        ]
        lines += [
            "",
            "## OWNERSHIP MATRIX",
            "| Assignment | Mutable area or artifact | Owner | Ownership class | Artifact class | Path restrictions |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {o.assignment_id} | {o.area} | {o.owner_agent_id} | {o.ownership_class} | {o.artifact_class or '-'} | {', '.join(o.restrictions) or '-'} |"
            for o in self.ownership
        ]
        lines += [
            "",
            "## EXECUTION GRAPH",
            "### Phase index",
            "| Agent | Phase |",
            "| --- | --- |",
        ]
        lines += [f"| {agent} | {phase} |" for agent, phase in self.phases]
        lines += ["", "### Parallel groups", "| Group | Members |", "| --- | --- |"]
        lines += [
            f"| {group} | {', '.join(members)} |"
            for group, members in self.parallel_groups
        ]
        lines += [
            "",
            "### Dependency graph",
            "| From | To | Type |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {edge.source} | {edge.target} | {edge.edge_type} |"
            for edge in self.dependencies
        ]
        lines += [
            "",
            "## REVIEW MATRIX",
            "| Deliverable type | Owning builder | Assigned reviewer | Rotation state |",
            "| --- | --- | --- | --- |",
        ]
        lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in self.reviews]
        lines += [
            "",
            "## VALIDATOR ASSIGNMENT",
            "| Gate | Validator | Fallback validator |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {gate} | {validator} | {fallback or '-'} |"
            for gate, validator, fallback in self.validators
        ]
        lines += [
            "",
            "## ESCALATION ROUTES",
            "| Member | Route (L0→L4) |",
            "| --- | --- |",
        ]
        lines += [
            f"| {agent} | {' → '.join(route)} |"
            for agent, route in self.escalation_routes
        ]
        lines += [
            "",
            "## CAPACITY RECORD",
            "| Agent | Declared capacity | Headroom |",
            "| --- | --- | --- |",
        ]
        lines += [
            f"| {m.agent_id} | {m.capacity if m.capacity is not None else 'unbounded'} | {m.headroom if m.headroom is not None else 'unbounded'} |"
            for m in self.members
        ]
        lines += [
            "",
            "## ACTIVE POLICIES",
            "| Policy | Evidence reference |",
            "| --- | --- |",
        ]
        lines += [f"| {policy} | {evidence} |" for policy, evidence in self.policies]
        lines += [
            "",
            "### Selection records",
            "| Demand | Chosen agent type | Rejected candidates | Justification |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {demand} | {chosen} | {', '.join(rejected) or '-'} | {justification} |"
            for demand, chosen, rejected, justification in self.selection_records
        ]
        return "\n".join(lines) + "\n"


def derive_demands(
    mission: MissionContract | Mapping[str, Any],
    classifications: Sequence[ProjectClassification | Mapping[str, Any]],
) -> tuple[CapabilityDemand, ...]:
    """Derive explicit mission, criterion, and constraint demands (TBE §5.3)."""
    contract = (
        mission
        if isinstance(mission, MissionContract)
        else MissionContract.from_mapping(mission)
    )
    projects = _classifications(classifications)
    demands = list(contract.demands)
    n = len(demands)
    for criterion in contract.acceptance_criteria:
        capabilities = criterion.get("capabilities", ())
        if not isinstance(capabilities, (list, tuple)):
            raise TBEError("INPUT_INVALID", "criterion.capabilities must be a sequence")
        for capability in capabilities:
            n += 1
            demands.append(
                CapabilityDemand.from_mapping(
                    {
                        "demand_id": f"CRITERION:{n:03d}",
                        "capability": capability,
                        "source_project": criterion.get(
                            "project", projects[0].root_path if projects else "."
                        ),
                        "source_criterion": criterion.get(
                            "id", criterion.get("text", capability)
                        ),
                        "mutable_paths": criterion.get("mutable_paths", ()),
                        "validation_gates": criterion.get("validation_gates", ()),
                        "role": criterion.get("role", "builder"),
                        "depends_on": criterion.get("depends_on", ()),
                        "artifact_class": criterion.get("artifact_class"),
                    },
                    n,
                )
            )
    tags = set(contract.constraint_tags)
    for project in projects:
        tags.update(project.constraint_tags)
    injected: list[tuple[str, str, str]] = []
    if any(tag.startswith("regulated:") for tag in tags):
        injected += [
            ("security-auditor", "security", "validator"),
            ("compliance-validator", "compliance", "validator"),
        ]
    if "security" in tags or "payments" in tags or "public-api" in tags:
        injected.append(("security-auditor", "security", "validator"))
    if "public-api" in tags:
        injected.append(("technical-writer", "documentation", "builder"))
    for capability, gate, role in injected:
        if not any(
            d.capability == capability and gate in d.validation_gates for d in demands
        ):
            n += 1
            demands.append(
                CapabilityDemand(
                    f"CONSTRAINT:{n:03d}",
                    capability,
                    ".",
                    f"constraint:{gate}",
                    (),
                    (gate,),
                    role,
                )
            )
    return tuple(sorted(demands, key=lambda d: d.demand_id))


def build_team(
    mission: MissionContract | Mapping[str, Any],
    classifications: Sequence[ProjectClassification | Mapping[str, Any]],
    registry: Mapping[str, Mapping[str, Any]],
    *,
    assembled_at: str | None = None,
    registry_reference: str = ".project-os/COMPANY/DEPARTMENTS",
    operating_mode: str = "ASSEMBLY",
) -> TeamManifest:
    """Assemble and validate a deterministic TBE v1.0 team manifest."""
    contract = (
        mission
        if isinstance(mission, MissionContract)
        else MissionContract.from_mapping(mission)
    )
    projects, demands = (
        _classifications(classifications),
        derive_demands(contract, classifications),
    )
    if not registry:
        raise TBEError("CAPABILITY_GAP", "ACR registry is empty")
    selected: list[tuple[CapabilityDemand, str]] = []
    selection_records: list[tuple[str, str, tuple[str, ...], str]] = []
    for demand in demands:
        candidate, rejected = _select(
            demand, contract, projects, registry, selected, demands
        )
        selected.append((demand, candidate))
        selection_records.append(
            (
                demand.demand_id,
                candidate,
                rejected,
                "TBE v1.0 section 6 deterministic selection",
            )
        )
    # Review and validation are mandatory selection products, not incidental
    # properties of builders.  Synthesize positions only where mission demands
    # did not already name an independent registered specialist.
    selected, generated_records = _add_gate_positions(
        selected, contract, projects, registry
    )
    selection_records.extend(generated_records)
    members, demand_owners = _members(selected, registry, registry_reference)
    members = _add_leadership_members(
        members, registry, contract.mission_type, registry_reference
    )
    ownership = _ownership(selected, demand_owners, registry)
    _validate_ownership(ownership, demands, members)
    input_edges = _dependencies(demands, selected, demand_owners, registry)
    explicit_edges = tuple(
        sorted(
            set(
                input_edges
                + _resource_edges(selected, ownership, registry, input_edges)
            ),
            key=lambda edge: (edge.source, edge.target, edge.edge_type),
        )
    )
    reviews = _reviews(selected, demand_owners, members, registry, projects)
    validators = _validators(demands, demand_owners, members, registry, projects)
    phases = _phases(
        selected, demand_owners, members, validators, reviews, explicit_edges
    )
    parallel = _parallel_groups(members, ownership, explicit_edges, phases, registry)
    routes = _routes(members)
    policies = _policies(contract, projects, members)
    if len({record[0] for record in selection_records}) != len(selection_records):
        raise TBEError(
            "MANIFEST_INVALID", "selection records must be unique per demand"
        )
    timestamp = assembled_at or datetime.now(UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    manifest = TeamManifest(
        f"TEAM:{contract.mission_id}:{contract.sequence}",
        contract.mission_id,
        1,
        timestamp,
        operating_mode,
        contract.objective,
        projects,
        members,
        ownership,
        explicit_edges,
        parallel,
        phases,
        reviews,
        validators,
        routes,
        policies,
        tuple(sorted(selection_records)),
    )
    validate_manifest(manifest, registry=registry)
    return manifest


assemble_team = build_team


def validate_manifest(
    manifest: TeamManifest, *, registry: Mapping[str, Mapping[str, Any]] | None = None
) -> TeamManifest:
    """Validate the TBE §2.4/§8--§15 assembly invariants without side effects."""
    if not manifest.team_id.startswith(f"TEAM:{manifest.mission_id}:"):
        raise TBEError(
            "MANIFEST_INVALID", "team id must be TEAM:<mission-id>:<sequence>"
        )
    agents = {m.agent_id for m in manifest.members}
    if len(agents) != len(manifest.members):
        raise TBEError("MANIFEST_INVALID", "duplicate member identity")
    for member in manifest.members:
        validate_agent_id(member.agent_id)
    selection_demands = [record[0] for record in manifest.selection_records]
    if len(selection_demands) != len(set(selection_demands)):
        raise TBEError(
            "MANIFEST_INVALID", "selection records must be unique per demand"
        )
    _validate_ownership(manifest.ownership, (), manifest.members)
    _validate_dag(manifest.dependencies)
    assignments = {item.assignment_id for item in manifest.ownership}
    for edge in manifest.dependencies:
        if edge.edge_type not in {"INPUT", "RESOURCE", "PHASE", "GATE"}:
            raise TBEError(
                "MANIFEST_INVALID", f"invalid dependency edge type {edge.edge_type}"
            )
        if edge.source not in assignments or edge.target not in assignments:
            raise TBEError(
                "DEPENDENCY_INVALID", "dependency endpoint is not an assignment"
            )
    phase_map = dict(manifest.phases)
    if set(phase_map) != agents or len(phase_map) != len(manifest.phases):
        raise TBEError("PHASE_INVALID", "every member must have exactly one phase")
    if any(not isinstance(index, int) or index < 0 for index in phase_map.values()):
        raise TBEError("PHASE_INVALID", "phase indexes must be non-negative integers")
    assignment_owners = {
        item.assignment_id: item.owner_agent_id for item in manifest.ownership
    }
    for edge in manifest.dependencies:
        source_owner, target_owner = (
            assignment_owners[edge.source],
            assignment_owners[edge.target],
        )
        if (
            source_owner != target_owner
            and phase_map[source_owner] >= phase_map[target_owner]
        ):
            raise TBEError(
                "PARALLEL_GROUP_INVALID",
                "dependency-connected members cannot share a parallel phase",
            )
    grouped_members = [
        member for _, group in manifest.parallel_groups for member in group
    ]
    if set(grouped_members) != agents or len(grouped_members) != len(
        set(grouped_members)
    ):
        raise TBEError(
            "PARALLEL_GROUP_INVALID", "parallel groups must partition members"
        )
    for group_id, group in manifest.parallel_groups:
        if not group_id.startswith("PHASE-") or not group:
            raise TBEError("PARALLEL_GROUP_INVALID", "parallel group is malformed")
        try:
            phase = int(group_id.removeprefix("PHASE-"))
        except ValueError as exc:
            raise TBEError(
                "PARALLEL_GROUP_INVALID", "parallel group phase is invalid"
            ) from exc
        if any(phase_map[member] != phase for member in group):
            raise TBEError("PARALLEL_GROUP_INVALID", "group member phase mismatch")
    builder_ids = {m.agent_id for m in manifest.members if m.role == "builder"}
    for _, owner, reviewer, _ in manifest.reviews:
        if owner == reviewer or reviewer not in agents:
            raise TBEError("REVIEW_INVALID", "reviewer must be a distinct member")
    reviewed = {owner for _, owner, _, _ in manifest.reviews}
    if builder_ids - reviewed:
        raise TBEError("REVIEW_INVALID", "every builder needs a reviewer")
    reviewed_ids = {r[2] for r in manifest.reviews}
    for _, validator, fallback in manifest.validators:
        if (
            validator not in agents
            or validator in builder_ids
            or validator in reviewed_ids
        ):
            raise TBEError(
                "VALIDATOR_INVALID",
                "validator must be independent of builders and reviewers",
            )
        if fallback is not None and (
            fallback not in agents
            or fallback in builder_ids
            or fallback in reviewed_ids
        ):
            raise TBEError("VALIDATOR_INVALID", "fallback validator is not independent")
    if set(x[0] for x in manifest.escalation_routes) != agents:
        raise TBEError(
            "ESCALATION_INVALID", "every member requires an escalation route"
        )
    for member_id, route in manifest.escalation_routes:
        if (
            not 3 <= len(route) <= 5
            or route[0] != member_id
            or route[-2:] != ("ORCHESTRATOR", "HUMAN-STAKEHOLDER")
            or len(route) != len(set(route))
            or any(
                endpoint not in agents | {"ORCHESTRATOR", "HUMAN-STAKEHOLDER"}
                for endpoint in route
            )
        ):
            raise TBEError("ESCALATION_INVALID", "invalid or cyclic escalation route")
    if registry is not None:
        member_by_id = {member.agent_id: member for member in manifest.members}
        for member in manifest.members:
            if member.agent_type not in registry:
                raise TBEError(
                    "REGISTRY_INVALID",
                    f"{member.agent_type} is not in the ACR registry",
                )
        for item in manifest.ownership:
            if item.artifact_class is None:
                continue
            declared = (
                registry[member_by_id[item.owner_agent_id].agent_type]
                .get("owned-artifacts", {})
                .get("artifact-ownership", {})
            )
            if declared.get(item.artifact_class) != item.ownership_class:
                raise TBEError(
                    "ARTIFACT_OWNERSHIP_INVALID",
                    f"registry ownership does not authorize {item.artifact_class}",
                )
        for _, owner, reviewer, _ in manifest.reviews:
            if not _contract_compatible(
                registry[member_by_id[owner].agent_type],
                registry[member_by_id[reviewer].agent_type],
                "EVIDENCE",
            ):
                raise TBEError(
                    "CONTRACT_INCOMPATIBLE",
                    f"review handoff {owner} to {reviewer} is incompatible",
                )
        for _, validator, _ in manifest.validators:
            validator_entry = registry[member_by_id[validator].agent_type]
            for _, owner, reviewer, _ in manifest.reviews:
                if not _contract_compatible(
                    registry[member_by_id[owner].agent_type],
                    validator_entry,
                    "EVIDENCE",
                ) or not _contract_compatible(
                    registry[member_by_id[reviewer].agent_type],
                    validator_entry,
                    "REVIEW",
                ):
                    raise TBEError(
                        "CONTRACT_INCOMPATIBLE",
                        f"validation handoff to {validator} is incompatible",
                    )
    return manifest


def bind_manifest_to_pese(
    manifest: TeamManifest,
    pese_store: Any,
    *,
    manifest_ref: str,
    actor: str,
    priority: str = "MEDIUM",
    dependencies_verified: bool = False,
    registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> Any:
    """Bind a pre-written, validated TEAM.md to PESE through its public API.

    This is intentionally a handoff, not execution: it registers the mission,
    PENDING builder assignments, active agent facts, and PENDING gate facts in
    one audited PESE revision.  The TEAM.md must already exist and match TBE's
    canonical serialization exactly, preventing PESE from being bound to a
    different human-readable authority record.
    """
    if not actor.startswith("AGENT:orchestrator:"):
        raise TBEError(
            "UNAUTHORIZED",
            "bind_manifest_to_pese requires orchestrator authority",
        )
    if registry is None and any(item.artifact_class for item in manifest.ownership):
        raise TBEError(
            "PESE_BIND_INVALID",
            "registry is required to bind artifact ownership",
        )
    validate_manifest(manifest, registry=registry)
    reference = Path(manifest_ref)
    if reference.is_absolute() or ".." in reference.parts:
        raise TBEError(
            "PESE_BIND_INVALID", "manifest_ref must be a safe repository-relative path"
        )
    path = Path(pese_store.root) / reference
    try:
        if (
            path.read_text(encoding="utf-8").replace("\r\n", "\n")
            != manifest.to_markdown()
        ):
            raise TBEError(
                "PESE_BIND_INVALID", "written TEAM.md does not match canonical manifest"
            )
    except OSError as exc:
        raise TBEError(
            "PESE_BIND_INVALID", "canonical TEAM.md is not readable"
        ) from exc
    loaded = pese_store.load(actor=actor)
    if getattr(loaded, "code", None) != "STATE_LOADED":
        return loaded
    state = loaded.data["envelope"]["state"]
    if manifest.mission_id in state["mission_state"]["missions"]:
        raise TBEError(
            "PESE_BIND_INVALID", f"mission already exists: {manifest.mission_id}"
        )
    assignment_owner = {
        item.assignment_id: item.owner_agent_id for item in manifest.ownership
    }
    review_assignment_owner: dict[str, str] = {}
    review_dependencies: dict[str, tuple[str, ...]] = {}
    for reviewed_assignment, _, reviewer, _ in manifest.reviews:
        assignment = _pese_assignment_id("review", reviewed_assignment)
        review_assignment_owner[assignment] = reviewer
        review_dependencies[assignment] = (reviewed_assignment,)
    validator_assignment_owner: dict[str, str] = {}
    validator_dependencies: dict[str, tuple[str, ...]] = {}
    all_review_assignments = tuple(sorted(review_assignment_owner))
    for gate, validator, _ in manifest.validators:
        assignment = _pese_assignment_id("validate", gate)
        validator_assignment_owner[assignment] = validator
        validator_dependencies[assignment] = all_review_assignments
    if len(
        set(assignment_owner)
        | set(review_assignment_owner)
        | set(validator_assignment_owner)
    ) != (
        len(assignment_owner)
        + len(review_assignment_owner)
        + len(validator_assignment_owner)
    ):
        raise TBEError("PESE_BIND_INVALID", "derived PESE assignment id collision")
    assignment_owner.update(review_assignment_owner)
    assignment_owner.update(validator_assignment_owner)
    assignment_dependencies = {
        assignment: tuple(
            sorted(
                edge.source
                for edge in manifest.dependencies
                if edge.target == assignment and edge.edge_type in {"INPUT", "RESOURCE"}
            )
        )
        for assignment in {item.assignment_id for item in manifest.ownership}
    }
    assignment_dependencies.update(review_dependencies)
    assignment_dependencies.update(validator_dependencies)
    member_phase = dict(manifest.phases)
    assignment_phase = {
        assignment: member_phase[owner]
        for assignment, owner in assignment_owner.items()
    }
    for _ in range(len(assignment_phase) + 1):
        changed = False
        for assignment, dependencies in assignment_dependencies.items():
            for prerequisite in dependencies:
                if assignment_phase[assignment] <= assignment_phase[prerequisite]:
                    assignment_phase[assignment] = assignment_phase[prerequisite] + 1
                    changed = True
        if not changed:
            break
    gate_rows = tuple(manifest.validators)

    def mutate(target: dict[str, Any]) -> None:
        target["mission_state"]["missions"][manifest.mission_id] = {
            "status": "PLANNED",
            "priority": priority,
            "manifest_ref": manifest_ref.replace("\\", "/"),
            "manifest_version": manifest.version,
            "assigned_agent_ids": [member.agent_id for member in manifest.members],
            "started_at": None,
            "completed_at": None,
            "last_checkpoint_id": None,
            "acceptance_evidence_refs": [],
            "dissolution_record": None,
        }
        target["mission_state"]["active_mission_id"] = manifest.mission_id
        phase_ids = {
            phase: f"TBE:{manifest.mission_id}:PHASE:{phase}"
            for phase in sorted(set(assignment_phase.values()))
        }
        target["execution_state"]["milestones"].extend(
            {
                "id": phase_ids[phase],
                "order": phase,
                "status": "PENDING",
            }
            for phase in sorted(phase_ids)
        )
        target["execution_state"]["current_milestone_id"] = (
            phase_ids[min(phase_ids)] if phase_ids else None
        )
        for assignment, owner in assignment_owner.items():
            target["execution_state"]["assignments"][assignment] = {
                "mission_id": manifest.mission_id,
                "milestone_id": phase_ids[assignment_phase[assignment]],
                "status": "PENDING",
                "assigned_agent_id": owner,
                "manifest_version": manifest.version,
                "depends_on": list(assignment_dependencies[assignment]),
                "input_refs": [],
                "output_refs": [],
                "started_at": None,
                "completed_at": None,
                "last_checkpoint_id": None,
                "position_id": f"POSITION:{assignment.removeprefix('ASSIGNMENT:')}",
                "replacement_count": 0,
                "replacement_lineage": [],
                "interruption": None,
            }
        target["execution_state"]["next_task_candidates"] = sorted(
            assignment
            for assignment, dependencies in assignment_dependencies.items()
            if not dependencies
        )
        for member in manifest.members:
            target["agent_state"]["agents"][member.agent_id] = {
                "agent_id": member.agent_id,
                "status": "READY",
                "mission_id": manifest.mission_id,
                "assignment_id": next(
                    (
                        aid
                        for aid, owner in assignment_owner.items()
                        if owner == member.agent_id
                    ),
                    None,
                ),
                "manifest_version": manifest.version,
                "last_heartbeat_at": None,
                "last_checkpoint_id": None,
                "acr_ref": member.registry_reference,
                "dependency_environment_state": {
                    "status": "VERIFIED" if dependencies_verified else "UNKNOWN",
                    "verified_at": None,
                    "tool_dependencies": [],
                    "environment_dependencies": [],
                },
                "interruption": None,
            }
        for gate, validator, _ in gate_rows:
            target["validation_state"]["gates"][
                f"GATE:{manifest.mission_id}:{gate}"
            ] = {
                "mission_id": manifest.mission_id,
                "status": "PENDING",
                "validator_agent_id": validator,
                "manifest_version": manifest.version,
                "criteria_refs": [f"{manifest_ref}#validation-gate-{gate}"],
                "artifact_ids": [],
                "last_checkpoint_id": None,
                "verdict_at": None,
            }
        target["extensions"].setdefault("org.asc.tbe", {})[manifest.mission_id] = {
            "dependency_edges": [
                {"source": edge.source, "target": edge.target, "type": edge.edge_type}
                for edge in manifest.dependencies
            ],
            "review_matrix": [
                {
                    "deliverable_type": deliverable,
                    "owner": owner,
                    "reviewer": reviewer,
                    "rotation": rotation,
                }
                for deliverable, owner, reviewer, rotation in manifest.reviews
            ],
        }

    return pese_store.update(
        expected_revision=loaded.state_revision,
        actor=actor,
        transition_type="TEAM_MANIFEST_BIND",
        subject=manifest.mission_id,
        from_value=None,
        to_value=manifest_ref,
        mutate=mutate,
    )


def team_manifest_relative_path(manifest: TeamManifest) -> str:
    """Return a reversible Windows-safe canonical TEAM.md storage reference.

    TBE identifiers intentionally contain ``:``.  The standard's conceptual
    `<team-id>` directory therefore needs percent encoding on Windows; the
    literal Team ID remains authoritative inside TEAM.md.
    """
    return (
        ".project-os/COMPANY/TEAMS/" + manifest.team_id.replace(":", "%3A") + "/TEAM.md"
    )


def _pese_assignment_id(kind: str, label: str) -> str:
    """Create a deterministic PESE-safe ID for derived control work."""
    token = label.removeprefix("ASSIGNMENT:")
    safe = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._-")
        else "-"
        for character in token
    ).strip("-")
    if not safe:
        raise TBEError("PESE_BIND_INVALID", "derived PESE assignment has no safe label")
    return f"ASSIGNMENT:{kind}-{safe}"


def _classifications(
    values: Sequence[ProjectClassification | Mapping[str, Any]],
) -> tuple[ProjectClassification, ...]:
    result = tuple(
        x
        if isinstance(x, ProjectClassification)
        else ProjectClassification.from_mapping(x)
        for x in values
    )
    if not result:
        raise TBEError(
            "INPUT_INVALID", "at least one project classification is required"
        )
    return tuple(sorted(result, key=lambda x: x.root_path))


def _entry_active(entry: Mapping[str, Any]) -> bool:
    return (
        str(entry.get("lifecycle-status", entry.get("status", "active"))).lower()
        == "active"
    )


def _mission_authorized(entry: Mapping[str, Any], mission_type: str) -> bool:
    values = entry.get("purpose", {}).get("mission-types", ())
    return any(str(x).lower() in {"*", mission_type.lower()} for x in values)


def _path_right(entry: Mapping[str, Any], paths: tuple[str, ...]) -> bool:
    writable = tuple(entry.get("owned-repository-areas", {}).get("writable-paths", ()))
    if not paths:
        return True
    if not writable:
        return False
    return all(any(_overlaps(path, allowed) for allowed in writable) for path in paths)


def _select(
    demand: CapabilityDemand,
    mission: MissionContract,
    projects: tuple[ProjectClassification, ...],
    registry: Mapping[str, Mapping[str, Any]],
    selected: list[tuple[CapabilityDemand, str]],
    demand_pool: Sequence[CapabilityDemand] = (),
) -> tuple[str, tuple[str, ...]]:
    candidates: list[tuple[tuple[Any, ...], str]] = []
    rejected: list[str] = []
    terms = {x.lower() for p in projects for x in p.languages + p.frameworks}
    tags = {x for p in projects for x in p.constraint_tags} | set(
        mission.constraint_tags
    )
    for agent_type, entry in sorted(registry.items()):
        if not _entry_active(entry):
            rejected.append(f"{agent_type}: Rule 6.1 inactive registry entry")
            continue
        if not _mission_authorized(entry, mission.mission_type):
            rejected.append(f"{agent_type}: Rule 6.1 mission authorization")
            continue
        if not _path_right(entry, demand.mutable_paths):
            rejected.append(f"{agent_type}: Rule 6.1 writable-path mismatch")
            continue
        competencies = {
            str(x).lower()
            for x in entry.get("required-skills", {}).get("competencies", ())
        }
        exact = int(agent_type == demand.capability)
        capability_match = exact or demand.capability.lower() in competencies
        if not capability_match:
            rejected.append(f"{agent_type}: Rule 6.1 capability mismatch")
            continue
        role_ok = demand.role != "validator" or bool(
            entry.get("validation-duties", {}).get("validation-gates")
        )
        if not role_ok:
            rejected.append(f"{agent_type}: Rule 6.1 validator-gate mismatch")
            continue
        coverage = sum(
            1
            for other in demand_pool
            if (
                agent_type == other.capability
                or other.capability.lower() in competencies
            )
            and _path_right(entry, other.mutable_paths)
        )
        precision = len(competencies & terms)
        qualification = int(
            any(tag.startswith("regulated:") for tag in tags)
            and bool(entry.get("validation-duties", {}).get("evidence-requirements"))
        )
        version = tuple(int(x) for x in str(entry.get("version", "0.0.0")).split("."))
        candidates.append(
            (
                (
                    -coverage,
                    -exact,
                    -precision,
                    -qualification,
                    tuple(-x for x in version),
                    agent_type,
                ),
                agent_type,
            )
        )
    if not candidates:
        raise TBEError(
            "CAPABILITY_GAP",
            f"no active ACR specialist can satisfy {demand.demand_id} ({demand.capability})",
        )
    chosen = min(candidates)[1]
    rejected.extend(
        f"{agent_type}: Rule 6.2 deterministic tie-break"
        for _, agent_type in candidates
        if agent_type != chosen
    )
    return chosen, tuple(sorted(rejected))


def _capacity(entry: Mapping[str, Any]) -> int | None:
    value = str(
        entry.get("parallel-execution-rules", {}).get("resource-limits", "unbounded")
    ).lower()
    if "unbounded" in value:
        return None
    import re

    found = re.search(r"max:\s*(\d+)", value)
    return int(found.group(1)) if found else 1


def _department(agent_type: str, role: str, entry: Mapping[str, Any]) -> str:
    if role in {"reviewer", "validator"}:
        gates = {
            str(x).lower()
            for x in entry.get("validation-duties", {}).get("validation-gates", ())
        }
        return "SECURITY" if gates & {"security", "compliance"} else "QUALITY"
    mapping = {
        "investigator": "RESEARCH",
        "security-auditor": "SECURITY",
        "compliance-validator": "SECURITY",
        "database-engineer": "DATA",
        "data-engineer": "DATA",
        "ai-ml-engineer": "DATA",
        "devops-engineer": "OPERATIONS",
        "infrastructure-engineer": "OPERATIONS",
        "release-manager": "OPERATIONS",
        "ui-ux-designer": "DESIGN",
        "technical-writer": "PRODUCT",
        "product-analyst": "PRODUCT",
    }
    return mapping.get(agent_type, "ENGINEERING")


def _members(
    selected: list[tuple[CapabilityDemand, str]],
    registry: Mapping[str, Mapping[str, Any]],
    reference: str,
) -> tuple[tuple[TeamMember, ...], dict[str, str]]:
    members: list[TeamMember] = []
    owners: dict[str, str] = {}
    counts: dict[str, int] = {}
    instances: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for demand, agent_type in selected:
        key = (agent_type, demand.role)
        entry = registry[agent_type]
        cap = _capacity(entry)
        # Consolidate while declared parallel capacity permits; otherwise the
        # same registered type receives a new ACP instance with disjoint work.
        available = next(
            (item for item in instances.get(key, ()) if cap is None or item[1] < cap),
            None,
        )
        if available is None:
            counts[agent_type] = counts.get(agent_type, 0) + 1
            aid = f"AGENT:{agent_type}:{_instance_id(agent_type, counts[agent_type])}"
            members.append(
                TeamMember(
                    aid,
                    agent_type,
                    demand.role,
                    _department(agent_type, demand.role, entry),
                    f"{reference}/{agent_type}.json",
                    cap,
                    cap,
                )
            )
            instances.setdefault(key, []).append((aid, 0))
            available = instances[key][-1]
        aid, used = available
        slots = instances[key]
        slots[slots.index(available)] = (aid, used + 1)
        owners[demand.demand_id] = aid
    usage = {
        agent: sum(1 for owner in owners.values() if owner == agent)
        for agent in {m.agent_id for m in members}
    }
    finalized = tuple(
        TeamMember(
            member.agent_id,
            member.agent_type,
            member.role,
            member.department,
            member.registry_reference,
            member.capacity,
            None
            if member.capacity is None
            else max(0, member.capacity - usage[member.agent_id]),
        )
        for member in sorted(members, key=lambda m: m.agent_id)
    )
    return finalized, owners


def _instance_id(agent_type: str, ordinal: int) -> str:
    """Deterministic UUIDv4-shaped ACP instance id; no random selection input."""
    import hashlib

    raw = bytearray(
        hashlib.sha256(f"tbe:{agent_type}:{ordinal}".encode()).digest()[:16]
    )
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


def _add_leadership_members(
    members: tuple[TeamMember, ...],
    registry: Mapping[str, Mapping[str, Any]],
    mission_type: str,
    reference: str,
) -> tuple[TeamMember, ...]:
    """Materialize §2.2.3/§3.2.3 leadership as real ACP members."""
    execution = [
        member
        for member in members
        if member.role not in {"team-lead", "department-lead"}
    ]
    result = list(members)
    if len(execution) > 5:
        result.append(
            _lead_member(
                "team-lead", "LEADERSHIP", result, registry, mission_type, reference
            )
        )
    by_department: dict[str, int] = {}
    for member in execution:
        by_department[member.department] = by_department.get(member.department, 0) + 1
    for department, count in sorted(by_department.items()):
        if count >= 3:
            result.append(
                _lead_member(
                    "department-lead",
                    department,
                    result,
                    registry,
                    mission_type,
                    reference,
                )
            )
    return tuple(sorted(result, key=lambda member: member.agent_id))


def _lead_member(
    agent_type: str,
    department: str,
    existing: Sequence[TeamMember],
    registry: Mapping[str, Mapping[str, Any]],
    mission_type: str,
    reference: str,
) -> TeamMember:
    entry = registry.get(agent_type)
    if (
        entry is None
        or not _entry_active(entry)
        or not _mission_authorized(entry, mission_type)
    ):
        raise TBEError(
            "LEADERSHIP_GAP",
            f"{agent_type} must be an active ACR specialist for a leadership-required team",
        )
    ordinal = 1 + sum(member.agent_type == agent_type for member in existing)
    agent_id = f"AGENT:{agent_type}:{_instance_id(agent_type, ordinal)}"
    capacity = _capacity(entry)
    return TeamMember(
        agent_id,
        agent_type,
        agent_type,
        department,
        f"{reference}/{agent_type}.json",
        capacity,
        capacity,
    )


def _add_gate_positions(
    selected: list[tuple[CapabilityDemand, str]],
    mission: MissionContract,
    projects: Sequence[ProjectClassification],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[
    list[tuple[CapabilityDemand, str]],
    list[tuple[str, str, tuple[str, ...], str]],
]:
    """Fill mandatory reviewer/validator positions from the ACR, deterministically."""
    result = list(selected)
    records: list[tuple[str, str, tuple[str, ...], str]] = []
    builders = [(d, agent) for d, agent in result if d.role == "builder"]
    known_reviewer = {agent for d, agent in result if d.role == "reviewer"}
    for index, (builder, builder_type) in enumerate(builders, 1):
        if known_reviewer - {builder_type}:
            continue
        candidate = _independent_candidate(
            registry,
            mission.mission_type,
            exclude={builder_type},
            need_message="REVIEW",
        )
        if candidate is None:
            raise TBEError(
                "REVIEWER_GAP", f"no independent ACR reviewer for {builder.demand_id}"
            )
        demand = CapabilityDemand(
            f"REVIEW:{index:03d}",
            candidate,
            builder.source_project,
            builder.demand_id,
            (),
            (),
            "reviewer",
        )
        result.append((demand, candidate))
        records.append(
            _independent_selection_record(
                demand.demand_id,
                candidate,
                registry,
                mission.mission_type,
                exclude={builder_type},
                need_message="REVIEW",
            )
        )
        known_reviewer.add(candidate)
    gates = sorted({gate.lower() for d, _ in result for gate in d.validation_gates})
    for index, gate in enumerate(gates, 1):
        if any(
            d.role == "validator" and gate in {x.lower() for x in d.validation_gates}
            for d, _ in result
        ):
            continue
        preferred = _GATE_DEFAULTS.get(gate)
        preferred_candidate: str | None = None
        if (
            preferred is not None
            and preferred in registry
            and _valid_gate_candidate(registry[preferred], mission.mission_type, gate)
        ):
            preferred_candidate = preferred
        candidate = preferred_candidate or _independent_candidate(
            registry,
            mission.mission_type,
            exclude={agent for _, agent in builders},
            gate=gate,
        )
        if candidate is None:
            raise TBEError("VALIDATOR_GAP", f"no independent ACR validator for {gate}")
        demand = CapabilityDemand(
            f"VALIDATE:{index:03d}",
            candidate,
            ".",
            f"gate:{gate}",
            (),
            (gate,),
            "validator",
        )
        result.append((demand, candidate))
        records.append(
            _independent_selection_record(
                demand.demand_id,
                candidate,
                registry,
                mission.mission_type,
                exclude={agent for _, agent in builders},
                gate=gate,
                preferred=preferred_candidate is not None,
            )
        )
    regulated = any(
        tag.startswith("regulated:")
        for project in projects
        for tag in project.constraint_tags
    ) or any(tag.startswith("regulated:") for tag in mission.constraint_tags)
    if regulated and "compliance" in gates:
        existing = {
            agent
            for demand, agent in result
            if demand.role == "validator"
            and "compliance" in {x.lower() for x in demand.validation_gates}
        }
        fallback = _independent_candidate(
            registry,
            mission.mission_type,
            exclude=existing | {agent for _, agent in builders},
            gate="compliance",
        )
        if fallback is None:
            raise TBEError(
                "VALIDATOR_GAP",
                "regulated compliance gate requires a named independent fallback",
            )
        demand = CapabilityDemand(
            "VALIDATE:FALLBACK-COMPLIANCE",
            fallback,
            ".",
            "regulated-fallback",
            (),
            ("compliance",),
            "validator",
        )
        result.append((demand, fallback))
        records.append(
            _independent_selection_record(
                demand.demand_id,
                fallback,
                registry,
                mission.mission_type,
                exclude=existing | {agent for _, agent in builders},
                gate="compliance",
            )
        )
    return result, records


def _valid_gate_candidate(
    entry: Mapping[str, Any], mission_type: str, gate: str
) -> bool:
    return (
        _entry_active(entry)
        and _mission_authorized(entry, mission_type)
        and gate
        in {
            str(x).lower()
            for x in entry.get("validation-duties", {}).get("validation-gates", ())
        }
    )


def _independent_candidate(
    registry: Mapping[str, Mapping[str, Any]],
    mission_type: str,
    *,
    exclude: set[str],
    need_message: str | None = None,
    gate: str | None = None,
) -> str | None:
    candidates = []
    for agent_type, entry in sorted(registry.items()):
        if (
            agent_type in exclude
            or not _entry_active(entry)
            or not _mission_authorized(entry, mission_type)
        ):
            continue
        if gate is not None and gate not in {
            str(x).lower()
            for x in entry.get("validation-duties", {}).get("validation-gates", ())
        }:
            continue
        if need_message is not None and need_message not in set(
            entry.get("output-contracts", {}).get("output-message-types", ())
        ):
            continue
        candidates.append(agent_type)
    return candidates[0] if candidates else None


def _independent_selection_record(
    demand_id: str,
    chosen: str,
    registry: Mapping[str, Mapping[str, Any]],
    mission_type: str,
    *,
    exclude: set[str],
    need_message: str | None = None,
    gate: str | None = None,
    preferred: bool = False,
) -> tuple[str, str, tuple[str, ...], str]:
    """Record every deterministic rejection for a synthesized gate position."""
    rejected: list[str] = []
    for agent_type, entry in sorted(registry.items()):
        if agent_type == chosen:
            continue
        if agent_type in exclude:
            reason = "Rule 6.1 independence exclusion"
        elif not _entry_active(entry):
            reason = "Rule 6.1 inactive registry entry"
        elif not _mission_authorized(entry, mission_type):
            reason = "Rule 6.1 mission authorization"
        elif gate is not None and not _valid_gate_candidate(entry, mission_type, gate):
            reason = "Rule 6.1 validation-gate mismatch"
        elif need_message is not None and need_message not in set(
            entry.get("output-contracts", {}).get("output-message-types", ())
        ):
            reason = "Rule 6.1 output-message mismatch"
        elif preferred:
            reason = "Rule 6.2 default gate specialist precedence"
        else:
            reason = "Rule 6.2 deterministic lexical tie-break"
        rejected.append(f"{agent_type}: {reason}")
    return (
        demand_id,
        chosen,
        tuple(rejected),
        "TBE v1.0 section 6 deterministic independent selection",
    )


def _ownership(
    selected: list[tuple[CapabilityDemand, str]],
    owners: Mapping[str, str],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[OwnershipEntry, ...]:
    result: list[OwnershipEntry] = []
    for demand, agent_type in selected:
        if demand.role != "builder":
            continue
        restrictions = tuple(
            sorted(
                set(
                    registry[agent_type]
                    .get("owned-repository-areas", {})
                    .get("path-restrictions", ())
                )
                | {"/.git/", "/.project-os/"}
            )
        )
        ownership_map = (
            registry[agent_type]
            .get("owned-artifacts", {})
            .get("artifact-ownership", {})
        )
        artifact_class = demand.artifact_class
        if artifact_class is not None and artifact_class not in ownership_map:
            raise TBEError(
                "ARTIFACT_OWNERSHIP_INVALID",
                f"{agent_type} does not declare artifact class {artifact_class}",
            )
        ownership_class = str(ownership_map.get(artifact_class, "exclusive"))
        if ownership_class not in {"exclusive", "shared-with-validator"}:
            raise TBEError(
                "ARTIFACT_OWNERSHIP_INVALID",
                f"unsupported artifact ownership class {ownership_class}",
            )
        owned_areas = demand.mutable_paths or (
            (f"artifact:{artifact_class}",) if artifact_class is not None else ()
        )
        for path in owned_areas:
            result.append(
                OwnershipEntry(
                    demand.demand_id,
                    path,
                    owners[demand.demand_id],
                    ownership_class,
                    restrictions,
                    artifact_class,
                )
            )
    return tuple(sorted(result, key=lambda x: (x.area, x.assignment_id)))


def _overlaps(left: str, right: str) -> bool:
    a, b = left.rstrip("/"), right.rstrip("/")
    if a == b:
        return True
    if any(c in a for c in "*?"):
        return fnmatchcase(b, a) or b.startswith(a.split("*", 1)[0])
    if any(c in b for c in "*?"):
        return fnmatchcase(a, b) or a.startswith(b.split("*", 1)[0])
    return a.startswith(b + "/") or b.startswith(a + "/")


def _validate_ownership(
    ownership: Sequence[OwnershipEntry],
    demands: Sequence[CapabilityDemand],
    members: Sequence[TeamMember],
) -> None:
    owner_ids = {m.agent_id for m in members}
    paths = {o.assignment_id for o in ownership}
    for demand in demands:
        if (
            demand.role == "builder"
            and demand.mutable_paths
            and demand.demand_id not in paths
        ):
            raise TBEError(
                "OWNERSHIP_INVALID", f"unowned mutable paths for {demand.demand_id}"
            )
    for i, item in enumerate(ownership):
        if item.owner_agent_id not in owner_ids:
            raise TBEError("OWNERSHIP_INVALID", "ownership references a non-member")
        if item.ownership_class not in {"exclusive", "shared-with-validator"}:
            raise TBEError(
                "ARTIFACT_OWNERSHIP_INVALID",
                f"invalid ownership class {item.ownership_class}",
            )
        for other in ownership[i + 1 :]:
            if item.owner_agent_id != other.owner_agent_id and _overlaps(
                item.area, other.area
            ):
                raise TBEError(
                    "OWNERSHIP_CONFLICT", f"{item.area} conflicts with {other.area}"
                )
            if (
                item.artifact_class is not None
                and item.artifact_class == other.artifact_class
                and item.owner_agent_id != other.owner_agent_id
            ):
                raise TBEError(
                    "OWNERSHIP_CONFLICT",
                    f"artifact class {item.artifact_class} has multiple owners",
                )


def _validate_dag(edges: Sequence[DependencyEdge]) -> None:
    """Kahn traversal for TBE §11.2.2, including self-edge rejection."""
    nodes = {edge.source for edge in edges} | {edge.target for edge in edges}
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        if edge.source == edge.target:
            raise TBEError("DEPENDENCY_CYCLE", f"self dependency for {edge.source}")
        if edge.target not in successors[edge.source]:
            successors[edge.source].add(edge.target)
            indegree[edge.target] += 1
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node = ready.pop(0)
        visited += 1
        for target in sorted(successors[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(nodes):
        raise TBEError("DEPENDENCY_CYCLE", "execution graph contains a cycle")


def _dependencies(
    demands: Sequence[CapabilityDemand],
    selected: Sequence[tuple[CapabilityDemand, str]],
    owners: Mapping[str, str],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[DependencyEdge, ...]:
    by_id = {d.demand_id: (d, agent) for d, agent in selected}
    edges: list[DependencyEdge] = []
    for demand in demands:
        for parent in demand.depends_on:
            if parent not in by_id:
                raise TBEError(
                    "DEPENDENCY_INVALID",
                    f"{demand.demand_id} depends on unknown {parent}",
                )
            _, upstream_type = by_id[parent]
            downstream_type = by_id[demand.demand_id][1]
            if not _contract_compatible(
                registry[upstream_type],
                registry[downstream_type],
                demand.handoff_message_type,
            ):
                raise TBEError(
                    "CONTRACT_INCOMPATIBLE",
                    f"{parent} → {demand.demand_id} lacks {demand.handoff_message_type} contract compatibility",
                )
            # Edges are assignment-level.  Two sequential assignments may be
            # owned by the same member, which is valid and must not become a
            # synthetic self-cycle in the team graph or PESE `depends_on`.
            edges.append(DependencyEdge(parent, demand.demand_id, "INPUT"))
    return tuple(sorted(set(edges), key=lambda x: (x.source, x.target, x.edge_type)))


def _resource_edges(
    selected: Sequence[tuple[CapabilityDemand, str]],
    ownership: Sequence[OwnershipEntry],
    registry: Mapping[str, Mapping[str, Any]],
    input_edges: Sequence[DependencyEdge],
) -> tuple[DependencyEdge, ...]:
    """Serialize shared non-partitioned ACR resources at assignment level."""
    buckets: dict[str, list[str]] = {}
    owned_assignments = {item.assignment_id for item in ownership}
    selected_types = {
        demand.demand_id: agent_type
        for demand, agent_type in selected
        if demand.demand_id in owned_assignments
    }
    order = _topological_assignment_order(owned_assignments, input_edges)
    order_index = {assignment: index for index, assignment in enumerate(order)}
    for assignment, agent_type in selected_types.items():
        resources = (
            str(
                registry[agent_type]
                .get("parallel-execution-rules", {})
                .get("shared-resources", "none")
            )
            .strip()
            .lower()
        )
        if resources and resources not in {"none", "read-only"}:
            buckets.setdefault(resources, []).append(assignment)
    edges: list[DependencyEdge] = []
    for assignments in buckets.values():
        ordered = sorted(assignments, key=lambda item: (order_index[item], item))
        for left, right in zip(ordered, ordered[1:]):
            edges.append(DependencyEdge(left, right, "RESOURCE"))
    return tuple(edges)


def _topological_assignment_order(
    assignments: set[str], edges: Sequence[DependencyEdge]
) -> tuple[str, ...]:
    """Return a stable assignment order that cannot oppose an INPUT edge."""
    successors: dict[str, set[str]] = {assignment: set() for assignment in assignments}
    indegree = {assignment: 0 for assignment in assignments}
    for edge in edges:
        if (
            edge.edge_type == "INPUT"
            and edge.source in successors
            and edge.target in successors
            and edge.target not in successors[edge.source]
        ):
            successors[edge.source].add(edge.target)
            indegree[edge.target] += 1
    ready = sorted(assignment for assignment, degree in indegree.items() if degree == 0)
    result: list[str] = []
    while ready:
        assignment = ready.pop(0)
        result.append(assignment)
        for target in sorted(successors[assignment]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(result) != len(assignments):
        raise TBEError("DEPENDENCY_CYCLE", "resource scheduling input graph is cyclic")
    return tuple(result)


def _contract_compatible(
    upstream: Mapping[str, Any], downstream: Mapping[str, Any], message_type: str
) -> bool:
    """Validate ACP message type and the ACR-declared required schema fields."""
    outputs = upstream.get("output-contracts", {})
    inputs = downstream.get("input-contracts", {})
    if message_type not in set(outputs.get("output-message-types", ())):
        return False
    if message_type not in set(inputs.get("input-message-types", ())):
        return False
    output_schema = outputs.get("output-schema", {}).get(message_type)
    input_schema = inputs.get("input-schema", {}).get(message_type)
    if not isinstance(output_schema, Mapping) or not isinstance(input_schema, Mapping):
        return False
    output_required = output_schema.get("required", ())
    input_required = input_schema.get("required", ())
    if not isinstance(output_required, (list, tuple)) or not isinstance(
        input_required, (list, tuple)
    ):
        return False
    return set(input_required).issubset(set(output_required))


def _reviews(
    selected: Sequence[tuple[CapabilityDemand, str]],
    owners: Mapping[str, str],
    members: Sequence[TeamMember],
    registry: Mapping[str, Mapping[str, Any]],
    projects: Sequence[ProjectClassification],
) -> tuple[tuple[str, str, str, str], ...]:
    rows = []
    terms = {x.lower() for p in projects for x in p.languages + p.frameworks}
    for demand, _ in selected:
        if demand.role != "builder":
            continue
        owner = owners[demand.demand_id]
        owner_department = next(m.department for m in members if m.agent_id == owner)
        candidates = [
            m
            for m in members
            if m.agent_id != owner
            and m.role == "reviewer"
            and (
                not terms
                or bool(
                    terms
                    & {
                        str(x).lower()
                        for x in registry[m.agent_type]
                        .get("required-skills", {})
                        .get("competencies", ())
                    }
                )
            )
        ]
        if not candidates:
            candidates = [
                m for m in members if m.agent_id != owner and m.role == "reviewer"
            ]
        if not candidates:
            raise TBEError(
                "REVIEWER_GAP", f"no independent reviewer for {demand.demand_id}"
            )
        candidates.sort(key=lambda m: (m.department == owner_department, m.agent_id))
        reviewer = candidates[0]
        builder_type = next(
            agent_type
            for candidate_demand, agent_type in selected
            if candidate_demand.demand_id == demand.demand_id
        )
        if not _contract_compatible(
            registry[builder_type], registry[reviewer.agent_type], "EVIDENCE"
        ):
            raise TBEError(
                "CONTRACT_INCOMPATIBLE",
                f"{demand.demand_id} cannot hand EVIDENCE to reviewer {reviewer.agent_id}",
            )
        rows.append((demand.demand_id, owner, reviewer.agent_id, "R0"))
    return tuple(sorted(rows))


def _validators(
    demands: Sequence[CapabilityDemand],
    owners: Mapping[str, str],
    members: Sequence[TeamMember],
    registry: Mapping[str, Mapping[str, Any]],
    projects: Sequence[ProjectClassification],
) -> tuple[tuple[str, str, str | None], ...]:
    gates = sorted({g.lower() for d in demands for g in d.validation_gates})
    builder = {m.agent_id for m in members if m.role == "builder"}
    reviewer = {m.agent_id for m in members if m.role == "reviewer"}
    regulated = any(
        t.startswith("regulated:") for p in projects for t in p.constraint_tags
    ) or any(
        d.source_criterion.startswith("constraint:")
        and "compliance" in d.validation_gates
        for d in demands
    )
    rows = []
    for gate in gates:
        candidates = [
            m
            for m in members
            if m.agent_id not in builder | reviewer
            and gate
            in {
                str(x).lower()
                for x in registry[m.agent_type]
                .get("validation-duties", {})
                .get("validation-gates", ())
            }
        ]
        if not candidates:
            raise TBEError("VALIDATOR_GAP", f"no independent validator for {gate}")
        candidates.sort(
            key=lambda m: (m.agent_type != _GATE_DEFAULTS.get(gate, ""), m.agent_id)
        )
        fallback = None
        if regulated and gate == "compliance":
            options = [
                m.agent_id for m in candidates if m.agent_id != candidates[0].agent_id
            ]
            if not options:
                raise TBEError(
                    "VALIDATOR_GAP",
                    "regulated compliance gate requires a named independent fallback",
                )
            fallback = options[0]
        validator = candidates[0]
        for member in members:
            if member.role == "builder" and not _contract_compatible(
                registry[member.agent_type], registry[validator.agent_type], "EVIDENCE"
            ):
                raise TBEError(
                    "CONTRACT_INCOMPATIBLE",
                    f"validator {validator.agent_id} cannot consume builder EVIDENCE",
                )
            if member.role == "reviewer" and not _contract_compatible(
                registry[member.agent_type], registry[validator.agent_type], "REVIEW"
            ):
                raise TBEError(
                    "CONTRACT_INCOMPATIBLE",
                    f"validator {validator.agent_id} cannot consume reviewer REVIEW",
                )
        rows.append((gate, validator.agent_id, fallback))
    return tuple(rows)


def _phases(
    selected: Sequence[tuple[CapabilityDemand, str]],
    owners: Mapping[str, str],
    members: Sequence[TeamMember],
    validators: Sequence[tuple[str, str, str | None]],
    reviews: Sequence[tuple[str, str, str, str]],
    dependencies: Sequence[DependencyEdge],
) -> tuple[tuple[str, int], ...]:
    assignment_phase = {
        demand.demand_id: 2
        if demand.role in {"builder", "investigator", "support"}
        else 4
        for demand, _ in selected
    }
    for _ in range(len(assignment_phase) + 1):
        changed = False
        for edge in dependencies:
            if (
                edge.edge_type in {"INPUT", "RESOURCE"}
                and assignment_phase[edge.target] <= assignment_phase[edge.source]
            ):
                assignment_phase[edge.target] = assignment_phase[edge.source] + 1
                changed = True
        if not changed:
            break
    phase = {member.agent_id: 1 for member in members}
    for assignment, value in assignment_phase.items():
        owner = owners.get(assignment)
        if owner is not None:
            phase[owner] = max(phase[owner], value)
    for _, _, reviewer, _ in reviews:
        phase[reviewer] = 3
    for gate, validator, _ in validators:
        phase[validator] = 5 if gate == "security" else 7
    for _ in range(len(phase) + 1):
        changed = False
        for edge in dependencies:
            if edge.edge_type not in {"INPUT", "RESOURCE"}:
                continue
            source, target = owners.get(edge.source), owners.get(edge.target)
            if source is not None and target is not None and source != target:
                if phase[target] <= phase[source]:
                    phase[target] = phase[source] + 1
                    changed = True
        if not changed:
            break
    else:
        raise TBEError("DEPENDENCY_CYCLE", "member phase scheduling did not converge")
    return tuple(sorted(phase.items()))


def _dependency_phase_adjust(
    phases: Sequence[tuple[str, int]], edges: Sequence[DependencyEdge]
) -> tuple[tuple[str, int], ...]:
    """Ensure an INPUT edge cannot leave two assignments in one group."""
    result = dict(phases)
    for _ in range(len(result) + 1):
        changed = False
        for edge in edges:
            if result[edge.target] <= result[edge.source]:
                result[edge.target] = result[edge.source] + 1
                changed = True
        if not changed:
            return tuple(sorted(result.items()))
    raise TBEError("DEPENDENCY_CYCLE", "dependency scheduling did not converge")


def _parallel_groups(
    members: Sequence[TeamMember],
    ownership: Sequence[OwnershipEntry],
    edges: Sequence[DependencyEdge],
    phases: Sequence[tuple[str, int]],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    phase_map = dict(phases)
    groups = []
    for phase in sorted(set(phase_map.values())):
        ids = sorted(x for x, v in phase_map.items() if v == phase)
        groups.append((f"PHASE-{phase}", tuple(ids)))
    return tuple(groups)


def _routes(members: Sequence[TeamMember]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    team_leads = sorted(
        member.agent_id for member in members if member.role == "team-lead"
    )
    department_leads = {
        member.department: member.agent_id
        for member in members
        if member.role == "department-lead"
    }
    routes: list[tuple[str, tuple[str, ...]]] = []
    for member in members:
        route = [member.agent_id]
        team_lead = team_leads[0] if team_leads else None
        department_lead = department_leads.get(member.department)
        if member.role not in {"team-lead", "department-lead"}:
            if team_lead is not None and team_lead != member.agent_id:
                route.append(team_lead)
            if department_lead is not None and department_lead not in route:
                route.append(department_lead)
        elif member.role == "department-lead":
            if team_lead is not None and team_lead != member.agent_id:
                route.append(team_lead)
        route.extend(("ORCHESTRATOR", "HUMAN-STAKEHOLDER"))
        routes.append((member.agent_id, tuple(route)))
    return tuple(routes)


def _policies(
    mission: MissionContract,
    projects: Sequence[ProjectClassification],
    members: Sequence[TeamMember],
) -> tuple[tuple[str, str], ...]:
    tags = set(mission.constraint_tags) | {
        t for p in projects for t in p.constraint_tags
    }
    values = [
        ("registry-only-selection", "TBE v1.0 §4.4.1"),
        ("exclusive-ownership", "TBE v1.0 §8"),
    ]
    if any(x.startswith("regulated:") for x in tags):
        values.append(("regulated-validator-independence", "TBE v1.0 §14.2"))
    return tuple(values)
