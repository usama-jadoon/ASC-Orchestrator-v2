"""Strict ACP v1.0 message framing and validation.

This module implements the local, host-independent message contract only.  It
does not implement transport, signing, encryption, replay protection, or agent
execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from types import MappingProxyType
from typing import Iterable, Mapping
from uuid import UUID


PROTOCOL = "ACP/v1.0"
HEADER_FIELDS = (
    "PROTOCOL",
    "TYPE",
    "FROM",
    "TO",
    "MISSION",
    "TIMESTAMP",
    "CORRELATION",
    "PAYLOAD-SHA256",
)

MESSAGE_TYPES = (
    "ASSIGNMENT",
    "STATUS_UPDATE",
    "PROGRESS",
    "EVIDENCE",
    "QUESTION",
    "ESCALATION",
    "WARNING",
    "FAILURE",
    "RECOVERY",
    "VALIDATION",
    "APPROVAL",
    "COMPLETION",
    "CANCELLATION",
    "REVIEW",
    "DECISION",
    "KNOWLEDGE_UPDATE",
    "MISSION_UPDATE",
    "HEARTBEAT",
)

# The source protocol explicitly marks only these fields as optional.  The
# order of all fields is normative, whether optional fields are present or not.
PAYLOAD_FIELD_REQUIREMENTS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ASSIGNMENT": (("OBJECTIVE", "BOUNDARIES", "AUTHORITY", "DELIVERABLES", "PRIORITY", "VALUE"), ()),
    "STATUS_UPDATE": (("STEP", "PROGRESS-PERCENT", "BLOCKERS", "RESOURCE-USAGE", "NEXT-EXPECTED-OUTCOME"), ()),
    "PROGRESS": (("COMPLETED-STEP", "EVIDENCE-REF", "OUTCOME", "NEXT-STEP"), ()),
    "EVIDENCE": (("TYPE", "REFERENCE", "HASH", "CONTEXT"), ("TIME-RANGE",)),
    "QUESTION": (("WHAT-IS-NEEDED", "WHY-NEEDED", "CONTEXT-REFERENCE"), ("RESPONSE-DEADLINE",)),
    "ESCALATION": (("ISSUE-TYPE", "DESCRIPTION", "EVIDENCE-REF", "IMPACT", "REQUESTED-ACTION", "TIME-BLOCKED"), ()),
    "WARNING": (("CONDITION", "POTENTIAL-IMPACT", "TIME-OBSERVED"), ("SUGGESTED-MITIGATION",)),
    "FAILURE": (("ERROR-CODE", "MESSAGE", "STACK-TRACE-or-LOG-REF", "ROOT-CAUSE-HYPOTHESIS", "RECOVERABLE", "SUGGECTED-NEXT-STEP"), ()),
    "RECOVERY": (("FAILURE-REF", "RECOVERY-POINT", "STATE-CORRECTIONS", "VALIDATION-REF", "READY-TO-RESUME"), ()),
    "VALIDATION": (("GATE", "RESULT", "FINDINGS", "EVIDENCE-REF", "REQUIRED-ACTIONS", "RETRY-ALLOWED"), ()),
    "APPROVAL": (("APPROVING-AGENT", "ITEM-APPROVED", "APPROVAL-TYPE", "CONDITIONS"), ("EFFECTIVE-UNTIL",)),
    "COMPLETION": (("ALL-GATES-PASSED", "DELIVERABLES-REF", "OUTCOME-VALUE", "HANDOFF-READY"), ("POST-COMPLETION-NOTES",)),
    "CANCELLATION": (("CANCELLING-AGENT", "REASON", "JUSTIFICATION", "PARTIAL-WORK-STATUS", "NOTIFICATION-REQ"), ()),
    "REVIEW": (("ITEM-UNDER-REVIEW", "REVIEW-TYPE", "FEEDBACK-REQUESTED", "CONTEXT"), ("DEADLINE",)),
    "DECISION": (("DECISION-ID", "CHOSEN-OPTION", "ALTERNATIVES-CONSIDERED", "EVIDENCE-BASIS", "EXPECTED-IMPACT", "REVERSIBLE", "REVERSIBILITY-CONDITIONS"), ()),
    "KNOWLEDGE_UPDATE": (("KNOWLEDGE-TYPE", "TITLE", "DESCRIPTION", "APPLICABLE-SCOPE", "EVIDENCE-REF", "ENTRY-TIME"), ()),
    "MISSION_UPDATE": (("FIELD-CHANGED", "OLD-VALUE", "NEW-VALUE", "CHANGE-REASON", "EFFECTIVE-IMMEDIATELY", "ACKNOWLEDGMENT-REQ"), ()),
    "HEARTBEAT": (("STATUS", "CURRENT-TASK", "RESOURCE-LOAD", "LAST-HEARTBEAT"), ("NOTES",)),
}

# Full on-wire field sequences.  It differs from the required/optional split
# for REVIEW, whose optional DEADLINE appears before required CONTEXT.
PAYLOAD_FIELD_ORDER: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        message_type: required + optional
        for message_type, (required, optional) in PAYLOAD_FIELD_REQUIREMENTS.items()
    }
    | {
        "WARNING": (
            "CONDITION",
            "POTENTIAL-IMPACT",
            "SUGGESTED-MITIGATION",
            "TIME-OBSERVED",
        ),
        "REVIEW": (
            "ITEM-UNDER-REVIEW",
            "REVIEW-TYPE",
            "FEEDBACK-REQUESTED",
            "DEADLINE",
            "CONTEXT",
        )
    }
)

# Kept as a direct, useful compatibility surface for callers that only need
# mandatory fields.
REQUIRED_PAYLOAD_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {message_type: requirement[0] for message_type, requirement in PAYLOAD_FIELD_REQUIREMENTS.items()}
)

_AGENT_TYPE_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
_HEX_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PAYLOAD_FIELD_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*\Z")
_UTC_MILLIS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")


class ACPError(ValueError):
    """Base error for ACP framing and validation failures."""


class ACPParseError(ACPError):
    """Raised when a message cannot be parsed as a strict ACP frame."""


class ACPValidationError(ACPError):
    """Raised when an ACP message fails protocol validation."""


def _is_uuid4(value: str) -> bool:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def validate_agent_id(value: str, *, allow_recipient_sentinels: bool = False) -> str:
    """Validate and return a canonical ACP agent identity."""
    if allow_recipient_sentinels and value in {"BROADCAST", "NONE"}:
        return value
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "AGENT" or not _AGENT_TYPE_RE.fullmatch(parts[1]):
        raise ACPValidationError("agent identity must be AGENT:<lowercase-type>:<uuidv4>")
    if not _is_uuid4(parts[2]):
        raise ACPValidationError("agent identity instance ID must be a canonical UUIDv4")
    return value


def _validate_timestamp(value: str) -> None:
    if not _UTC_MILLIS_RE.fullmatch(value):
        raise ACPValidationError("TIMESTAMP must be ISO-8601 UTC with millisecond precision")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ACPValidationError("TIMESTAMP is not a valid UTC timestamp") from exc
    if parsed.tzinfo is not None:  # Defensive: strptime above always returns naive.
        raise ACPValidationError("TIMESTAMP must be UTC")


def _normalise_payload(payload: Mapping[str, str] | Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    items = tuple(payload.items()) if isinstance(payload, Mapping) else tuple(payload)
    normalised: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ACPValidationError("payload entries must be (field, value) pairs")
        field, value = item
        if not isinstance(field, str) or not isinstance(value, str):
            raise ACPValidationError("payload fields and values must be text")
        normalised.append((field, value))
    return tuple(normalised)


@dataclass(frozen=True, slots=True)
class ACPMessage:
    """An immutable, validated ACP message.

    ``payload`` is a tuple rather than a dictionary so that the protocol's
    required wire ordering remains preserved and inspectable.
    """

    message_type: str
    sender: str
    recipient: str
    mission: str
    timestamp: str
    correlation: str
    payload: tuple[tuple[str, str], ...]
    payload_sha256: str
    protocol: str = PROTOCOL

    @classmethod
    def create(
        cls,
        message_type: str,
        sender: str,
        recipient: str,
        mission: str,
        timestamp: str,
        correlation: str,
        payload: Mapping[str, str] | Iterable[tuple[str, str]],
        *,
        protocol: str = PROTOCOL,
    ) -> "ACPMessage":
        payload_items = _normalise_payload(payload)
        payload_text = _payload_text(payload_items)
        message = cls(
            message_type=message_type,
            sender=sender,
            recipient=recipient,
            mission=mission,
            timestamp=timestamp,
            correlation=correlation,
            payload=payload_items,
            payload_sha256=hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
            protocol=protocol,
        )
        validate_message(message)
        return message

    @property
    def payload_fields(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.payload))

    def serialize(self) -> str:
        return serialize_message(self)


def _payload_text(payload: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{field}:{value}" for field, value in payload)


def _validate_payload(message_type: str, payload: tuple[tuple[str, str], ...]) -> None:
    if not payload:
        raise ACPValidationError("payload must contain required fields")
    required, optional = PAYLOAD_FIELD_REQUIREMENTS[message_type]
    expected = PAYLOAD_FIELD_ORDER[message_type]
    fields = tuple(field for field, _ in payload)
    if len(set(fields)) != len(fields):
        raise ACPValidationError("payload contains a duplicate field")
    if any(not _PAYLOAD_FIELD_RE.fullmatch(field) for field in fields):
        raise ACPValidationError("payload contains an invalid field name")
    if any(value == "" or "\r" in value or "\n" in value for _, value in payload):
        raise ACPValidationError("payload values must be non-empty single-line UTF-8 text")
    if any(field not in fields for field in required):
        raise ACPValidationError("payload contains a missing required field")
    positions = tuple(expected.index(field) if field in expected else -1 for field in fields)
    if -1 in positions:
        raise ACPValidationError("payload contains an unknown or out-of-order field")
    if positions != tuple(sorted(positions)):
        raise ACPValidationError("payload fields are out of order")
    values = dict(payload)
    _validate_payload_semantics(message_type, values)


def _require_enum(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ACPValidationError(f"{field} has an unsupported value: {value!r}")


def _validate_pipe_fields(field: str, value: str, count: int) -> None:
    if len(value.split("|")) != count or any(not item for item in value.split("|")):
        raise ACPValidationError(f"{field} must contain {count} non-empty pipe-delimited values")


def _validate_payload_semantics(message_type: str, values: Mapping[str, str]) -> None:
    """Apply the v1.0 field formats and closed value domains."""
    if message_type == "STATUS_UPDATE":
        step = values["STEP"]
        if step != "N/A":
            match = re.fullmatch(r"(\d+)/(\d+)", step)
            if not match or int(match.group(2)) == 0 or int(match.group(1)) > int(match.group(2)):
                raise ACPValidationError("STEP must be N/A or current-step/positive-total-steps")
        try:
            percent = int(values["PROGRESS-PERCENT"])
        except ValueError as exc:
            raise ACPValidationError("PROGRESS-PERCENT must be an integer from 0 to 100") from exc
        if not 0 <= percent <= 100 or str(percent) != values["PROGRESS-PERCENT"]:
            raise ACPValidationError("PROGRESS-PERCENT must be an integer from 0 to 100")
        _validate_pipe_fields("RESOURCE-USAGE", values["RESOURCE-USAGE"], 3)
    if message_type == "ASSIGNMENT":
        _validate_pipe_fields("BOUNDARIES", values["BOUNDARIES"], 4)
        _validate_pipe_fields("AUTHORITY", values["AUTHORITY"], 2)
    if message_type == "HEARTBEAT":
        _require_enum("STATUS", values["STATUS"], {"ready", "busy", "blocked", "failed"})
        _validate_pipe_fields("RESOURCE-LOAD", values["RESOURCE-LOAD"], 2)
    enum_fields = {
        "ASSIGNMENT": {"PRIORITY": {"Critical", "High", "Medium", "Low"}},
        "EVIDENCE": {"TYPE": {"test", "log", "scan", "artifact", "document"}},
        "ESCALATION": {"ISSUE-TYPE": {"blocker", "violation", "safety", "resource", "dependency"}},
        "VALIDATION": {
            "GATE": {"code-review", "security", "qa", "performance", "documentation", "contracts", "integrity", "readiness"},
            "RESULT": {"PASS", "FAIL", "BLOCKED"},
        },
        "APPROVAL": {"APPROVAL-TYPE": {"authority", "stakeholder", "gate"}},
        "CANCELLATION": {"REASON": {"business-priority", "constitutional", "blocked-impossible", "other"}},
        "REVIEW": {"REVIEW-TYPE": {"informal", "formal", "peer", "stakeholder"}},
        "KNOWLEDGE_UPDATE": {"KNOWLEDGE-TYPE": {"pattern", "lesson", "best-practice", "architecture-decision"}},
        "MISSION_UPDATE": {"FIELD-CHANGED": {"objective", "scope", "priority", "boundaries", "deliverables"}},
    }
    for field, allowed in enum_fields.get(message_type, {}).items():
        _require_enum(field, values[field], allowed)
    if message_type == "FAILURE":
        _require_enum(
            "SUGGECTED-NEXT-STEP",
            values["SUGGECTED-NEXT-STEP"],
            {"retry", "escalate", "abort", "investigate"},
        )
    if message_type == "CANCELLATION":
        _require_enum(
            "PARTIAL-WORK-STATUS",
            values["PARTIAL-WORK-STATUS"],
            {"preserve", "discard", "archive"},
        )
    for field in {
        "RECOVERABLE",
        "READY-TO-RESUME",
        "RETRY-ALLOWED",
        "ALL-GATES-PASSED",
        "HANDOFF-READY",
        "REVERSIBLE",
        "EFFECTIVE-IMMEDIATELY",
    } & values.keys():
        _require_enum(field, values[field], {"YES", "NO"})
    for field in {
        "RESPONSE-DEADLINE",
        "TIME-OBSERVED",
        "EFFECTIVE-UNTIL",
        "DEADLINE",
        "ENTRY-TIME",
        "LAST-HEARTBEAT",
    } & values.keys():
        if values[field] != "NONE":
            _validate_timestamp(values[field])
    if "TIME-RANGE" in values:
        parts = values["TIME-RANGE"].split("->")
        if len(parts) != 2:
            raise ACPValidationError("TIME-RANGE must be N/A or start->end timestamps")
        _validate_timestamp(parts[0])
        _validate_timestamp(parts[1])
    if message_type == "EVIDENCE" and not _HEX_SHA256_RE.fullmatch(values["HASH"]):
        raise ACPValidationError("HASH must be a 64 character lowercase SHA-256 hash")
    if message_type == "DECISION" and not _is_uuid4(values["DECISION-ID"]):
        raise ACPValidationError("DECISION-ID must be a canonical UUIDv4")
    for field in {"APPROVING-AGENT", "CANCELLING-AGENT"} & values.keys():
        validate_agent_id(values[field])


def validate_message(message: ACPMessage) -> ACPMessage:
    """Validate a message object and return it for convenient chaining."""
    if not isinstance(message, ACPMessage):
        raise ACPValidationError("value is not an ACPMessage")
    if message.protocol != PROTOCOL:
        raise ACPValidationError(f"unsupported protocol: {message.protocol!r}")
    if message.message_type not in MESSAGE_TYPES:
        raise ACPValidationError(f"unknown ACP message type: {message.message_type!r}")
    validate_agent_id(message.sender)
    validate_agent_id(message.recipient, allow_recipient_sentinels=True)
    if not isinstance(message.mission, str) or not message.mission:
        raise ACPValidationError("MISSION must be non-empty or MISSION:NONE")
    if "\r" in message.mission or "\n" in message.mission:
        raise ACPValidationError("MISSION must be a single line")
    _validate_timestamp(message.timestamp)
    if not _is_uuid4(message.correlation):
        raise ACPValidationError("CORRELATION must be a canonical UUIDv4")
    if not isinstance(message.payload_sha256, str) or not _HEX_SHA256_RE.fullmatch(message.payload_sha256):
        raise ACPValidationError("PAYLOAD-SHA256 must be 64 lowercase hexadecimal characters")
    payload = _normalise_payload(message.payload)
    _validate_payload(message.message_type, payload)
    try:
        actual_hash = hashlib.sha256(_payload_text(payload).encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ACPValidationError("payload is not valid UTF-8 text") from exc
    if actual_hash != message.payload_sha256:
        raise ACPValidationError("PAYLOAD-SHA256 does not match payload")
    return message


def serialize_message(message: ACPMessage) -> str:
    """Return the canonical ACP v1.0 UTF-8 text representation.

    The returned string contains LF line endings and no terminal newline.  Its
    bytes are therefore deterministic when encoded as UTF-8.
    """
    validate_message(message)
    headers = (
        f"PROTOCOL:{message.protocol}",
        f"TYPE:{message.message_type}",
        f"FROM:{message.sender}",
        f"TO:{message.recipient}",
        f"MISSION:{message.mission}",
        f"TIMESTAMP:{message.timestamp}",
        f"CORRELATION:{message.correlation}",
        f"PAYLOAD-SHA256:{message.payload_sha256}",
    )
    return "\n".join(headers + (_payload_text(message.payload),))


def parse_message(data: str | bytes) -> ACPMessage:
    """Parse a strict ACP v1.0 message, rejecting non-canonical framing."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ACPParseError("message is not valid UTF-8") from exc
    elif isinstance(data, str):
        try:
            data.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ACPParseError("message is not valid UTF-8") from exc
        text = data
    else:
        raise ACPParseError("message must be str or bytes")
    if not text or "\r" in text:
        raise ACPParseError("message must use canonical LF line endings")
    lines = text.split("\n")
    if len(lines) <= len(HEADER_FIELDS):
        raise ACPParseError("message is missing a payload")
    header_lines, payload_lines = lines[: len(HEADER_FIELDS)], lines[len(HEADER_FIELDS) :]
    headers: dict[str, str] = {}
    for expected, line in zip(HEADER_FIELDS, header_lines):
        if not line.startswith(expected + ":"):
            raise ACPParseError(f"expected header {expected!r} in its fixed position")
        value = line[len(expected) + 1 :]
        if value == "":
            raise ACPParseError(f"header {expected!r} must not be empty")
        headers[expected] = value
    payload: list[tuple[str, str]] = []
    for line in payload_lines:
        if not line or ":" not in line:
            raise ACPParseError("payload must be non-empty FIELD:value lines")
        field, value = line.split(":", 1)
        payload.append((field, value))
    message = ACPMessage(
        message_type=headers["TYPE"],
        sender=headers["FROM"],
        recipient=headers["TO"],
        mission=headers["MISSION"],
        timestamp=headers["TIMESTAMP"],
        correlation=headers["CORRELATION"],
        payload=tuple(payload),
        payload_sha256=headers["PAYLOAD-SHA256"],
        protocol=headers["PROTOCOL"],
    )
    try:
        return validate_message(message)
    except ACPValidationError as exc:
        raise ACPParseError(str(exc)) from exc


# Concise aliases make the module natural to use from transport adapters.
parse = parse_message
serialize = serialize_message
validate = validate_message
