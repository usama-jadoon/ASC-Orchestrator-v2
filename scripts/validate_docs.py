"""Validate the documentation that defines the shipped PESE, TBE, MSS, EEF, and CKS contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PESE = ROOT / "docs" / "PESE_v1.0.md"
TBE = ROOT / "docs" / "TBE_v1.0.md"
MSS = ROOT / "docs" / "MSS_v1.0.md"
EEF = ROOT / "docs" / "EEF_v1.0.md"
CKS = ROOT / "docs" / "CKS_v1.0.md"

REQUIRED_PESE_HEADINGS = (
    "## 2. Canonical persistence model",
    "## 3. On-disk object encodings",
    "## 4. Top-level state schema",
    "## 5. State Manager",
    "## 6. Checkpoint Manager",
    "## 7. Resume Manager",
    "## 8. Integrity validation",
    "## 9. State locking",
    "## 10. Recovery Engine",
    "## 11. Version Manager and compatibility",
    "## 15. MISSION-007 implementation gates",
)

REQUIRED_TBE_HEADINGS = (
    "## 2. ORGANIZATION MODEL",
    "## 5. TEAM SELECTION ALGORITHM",
    "## 6. AGENT SELECTION RULES",
    "## 8. OWNERSHIP RULES",
    "## 11. DEPENDENCY RULES",
    "## 13. REVIEWER ASSIGNMENT",
    "## 14. VALIDATOR ASSIGNMENT",
    "## 15. ESCALATION HIERARCHY",
)

REQUIRED_MSS_HEADINGS = (
    "## 2. MISSION VOCABULARY — MISSION TYPES",
    "## 4. CANONICAL MISSION-INTAKE SCHEMA",
    "## 5. MISSION-TYPE BASELINE CAPABILITIES",
    "## 6. VALIDATION-GATE VOCABULARY",
    "## 7. AUTHORITY-SCOPE VOCABULARY",
    "## 9. CANONICAL JSON EXAMPLES",
)

REQUIRED_EEF_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. SESSION STATE MACHINE",
    "## 5. FIFO SCHEDULER SEMANTICS",
    "## 8. EVENT LOG SCHEMA",
    "## 9. `org.asc.eef` EXTENSION SHAPE",
    "## 10. CLI REFERENCE",
    "## 13. IMPLEMENTATION GATES",
)

REQUIRED_CKS_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. KEY TYPES AND RECORDS",
    "## 4. KEY LIFECYCLE",
    "## 5. SIGNING AND VERIFICATION",
    "## 6. SIGNING LEDGER",
    "## 7. ON-DISK LAYOUT",
    "## 10. CLI REFERENCE",
    "## 13. IMPLEMENTATION GATES",
)


def main() -> int:
    """Return nonzero when a canonical contract or CLI invariant is absent."""

    readme = README.read_text(encoding="utf-8")
    pese = PESE.read_text(encoding="utf-8")
    tbe = TBE.read_text(encoding="utf-8")
    mss = MSS.read_text(encoding="utf-8")
    eef = EEF.read_text(encoding="utf-8")
    cks = CKS.read_text(encoding="utf-8")
    errors: list[str] = []

    for command in (
        "state",
        "resume",
        "checkpoint",
        "validate-state",
        "team-build",
        "validate-mission",
        "execution-start",
        "execution-status",
        "execution-schedule",
        "execution-pause",
        "execution-resume",
        "execution-cancel",
        "execution-complete",
        "key-create",
        "key-list",
        "key-sign",
        "key-verify",
        "key-rotate",
        "key-revoke",
        "key-validate",
    ):
        if f" {command}" not in readme:
            errors.append(f"README does not document the `{command}` command")
    for heading in REQUIRED_PESE_HEADINGS:
        if heading not in pese:
            errors.append(f"PESE specification is missing: {heading}")
    for heading in REQUIRED_TBE_HEADINGS:
        if heading not in tbe:
            errors.append(f"TBE specification is missing: {heading}")
    for heading in REQUIRED_MSS_HEADINGS:
        if heading not in mss:
            errors.append(f"MSS specification is missing: {heading}")
    for heading in REQUIRED_EEF_HEADINGS:
        if heading not in eef:
            errors.append(f"EEF specification is missing: {heading}")
    for heading in REQUIRED_CKS_HEADINGS:
        if heading not in cks:
            errors.append(f"CKS specification is missing: {heading}")
    if "**END OF SPECIFICATION" not in pese:
        errors.append("PESE specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in tbe:
        errors.append("TBE specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in mss:
        errors.append("MSS specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in eef:
        errors.append("EEF specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in cks:
        errors.append("CKS specification does not contain its terminal marker")

    fences = re.findall(r"```json\n(.*?)\n```", pese, flags=re.DOTALL)
    if not fences:
        errors.append("PESE specification has no JSON encoding examples")
    for index, document in enumerate(fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"PESE JSON example {index} is invalid: {error.msg}")

    mss_fences = re.findall(r"```json\n(.*?)\n```", mss, flags=re.DOTALL)
    if not mss_fences:
        errors.append("MSS specification has no JSON examples")
    for index, document in enumerate(mss_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"MSS JSON example {index} is invalid: {error.msg}")

    eef_fences = re.findall(r"```json\n(.*?)\n```", eef, flags=re.DOTALL)
    if not eef_fences:
        errors.append("EEF specification has no JSON examples")
    for index, document in enumerate(eef_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"EEF JSON example {index} is invalid: {error.msg}")

    cks_fences = re.findall(r"```json\n(.*?)\n```", cks, flags=re.DOTALL)
    if not cks_fences:
        errors.append("CKS specification has no JSON examples")
    for index, document in enumerate(cks_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"CKS JSON example {index} is invalid: {error.msg}")

    if errors:
        print("documentation=FAIL")
        print("\\n".join(errors))
        return 1
    print("documentation=PASS")
    print(f"pese_json_examples={len(fences)}")
    print(f"tbe_required_headings={len(REQUIRED_TBE_HEADINGS)}")
    print(f"mss_required_headings={len(REQUIRED_MSS_HEADINGS)}")
    print(f"mss_json_examples={len(mss_fences)}")
    print(f"eef_required_headings={len(REQUIRED_EEF_HEADINGS)}")
    print(f"eef_json_examples={len(eef_fences)}")
    print(f"cks_required_headings={len(REQUIRED_CKS_HEADINGS)}")
    print(f"cks_json_examples={len(cks_fences)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
