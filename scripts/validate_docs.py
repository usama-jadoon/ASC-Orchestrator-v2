"""Validate the documentation that defines the shipped PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, RKM, AGC, REC, ETR, AWS, and REL contracts."""

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
AEX = ROOT / "docs" / "AEX_v1.0.md"
AHP = ROOT / "docs" / "AHP_v1.0.md"
VAL = ROOT / "docs" / "VAL_v1.0.md"
RKM = ROOT / "docs" / "RKM_v1.0.md"
AGC = ROOT / "docs" / "AGC_v1.0.md"
REC = ROOT / "docs" / "REC_v1.0.md"
ETR = ROOT / "docs" / "ETR_v1.0.md"
AWS = ROOT / "docs" / "AWS_v1.0.md"
REL = ROOT / "docs" / "REL_v1.0.md"

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

REQUIRED_AEX_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. ASSIGNMENT EXECUTION LIFECYCLE",
    "## 4. EXECUTION RESULT RECORD",
    "## 7. EEF EVENT INTEGRATION",
    "## 9. CLI REFERENCE",
    "## 10. ERROR HANDLING",
    "## 12. IMPLEMENTATION REQUIREMENTS",
    "## 13. IMPLEMENTATION GATES",
)

REQUIRED_AHP_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. HEARTBEAT RECORD",
    "## 4. AGENT HEALTH MODEL",
    "## 5. ON-DISK LAYOUT",
    "## 6. INTEGRITY AND VALIDATION",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 11. IMPLEMENTATION GATES",
)

REQUIRED_VAL_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. VALIDATION STATE AND GATES",
    "## 4. ARTIFACT RECORDS",
    "## 5. VERIFICATION",
    "## 6. INVALIDATION",
    "## 7. EVENT JOURNAL",
    "## 8. CLI REFERENCE",
    "## 9. ERROR HANDLING",
    "## 13. IMPLEMENTATION GATES",
)

REQUIRED_RKM_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. RISK RECORD SCHEMA",
    "## 4. HOLD MECHANISM — BLOCKING EVALUATION",
    "## 5. RISK LIFECYCLE",
    "## 6. EVENT JOURNAL",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 12. IMPLEMENTATION GATES",
)

REQUIRED_AGC_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 4. AGENT STATUS VOCABULARY",
    "## 5. AGENT LIFECYCLE",
    "## 6. EVENT JOURNAL",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 12. IMPLEMENTATION GATES",
)

REQUIRED_REC_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. RECOVERY RECORD SCHEMA",
    "## 4. TRIGGER MODEL",
    "## 5. RECOVERY LIFECYCLE",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 12. IMPLEMENTATION GATES",
)

REQUIRED_ETR_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. CHANNEL AND ENVELOPE SCHEMA",
    "## 4. AEAD ENVELOPE FORMAT",
    "## 5. LIFECYCLE",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 12. IMPLEMENTATION GATES",
)

REQUIRED_AWS_HEADINGS = (
    "## 2. ARCHITECTURE AND BOUNDARY",
    "## 3. SCHEDULER STATE AND CYCLE SCHEMA",
    "## 4. DECISION MODEL",
    "## 5. LIFECYCLE",
    "## 6. EVENT JOURNAL",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 9. ON-DISK LAYOUT",
    "## 10. COMPATIBILITY",
    "## 12. IMPLEMENTATION GATES",
)

REQUIRED_REL_HEADINGS = (
    "## 2. RELEASE CRITERIA",
    "## 3. VERSIONING",
    "## 4. RELEASE CONTRACT SCHEMA",
    "## 5. RELEASE VERIFICATION",
    "## 6. RELEASE GATES",
    "## 7. CLI REFERENCE",
    "## 8. ERROR HANDLING",
    "## 9. DISTRIBUTION",
    "## 10. COMPATIBILITY",
    "## 12. IMPLEMENTATION GATES",
)


def main() -> int:
    """Return nonzero when a canonical contract or CLI invariant is absent."""

    readme = README.read_text(encoding="utf-8")
    pese = PESE.read_text(encoding="utf-8")
    tbe = TBE.read_text(encoding="utf-8")
    mss = MSS.read_text(encoding="utf-8")
    eef = EEF.read_text(encoding="utf-8")
    cks = CKS.read_text(encoding="utf-8")
    aex = AEX.read_text(encoding="utf-8")
    ahp = AHP.read_text(encoding="utf-8")
    val = VAL.read_text(encoding="utf-8")
    rkm = RKM.read_text(encoding="utf-8")
    agc = AGC.read_text(encoding="utf-8")
    rec = REC.read_text(encoding="utf-8")
    etr = ETR.read_text(encoding="utf-8")
    aws = AWS.read_text(encoding="utf-8")
    rel = REL.read_text(encoding="utf-8")
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
        "aex-dispatch",
        "aex-complete",
        "aex-fail",
        "aex-block",
        "aex-unblock",
        "aex-status",
        "aex-result",
        "health-heartbeat",
        "health-status",
        "health-report",
        "health-check",
        "validation-gates",
        "validation-start",
        "validation-finish",
        "validation-verify",
        "validation-invalidate",
        "validation-report",
        "risk-open",
        "risk-list",
        "risk-status",
        "risk-mitigate",
        "risk-accept",
        "risk-resolve",
        "risk-halt",
        "risk-check",
        "risk-report",
        "agent-register",
        "agent-activate",
        "agent-dependency",
        "agent-ready",
        "agent-claim",
        "agent-complete",
        "agent-block",
        "agent-unblock",
        "agent-fail",
        "agent-quarantine",
        "agent-replace",
        "agent-release",
        "agent-heartbeat",
        "agent-checkpoint",
        "agent-list",
        "agent-status",
        "agent-report",
        "recovery-diagnose",
        "recovery-run",
        "recovery-status",
        "recovery-list",
        "recovery-report",
        "etr-bind-channel",
        "etr-revoke-channel",
        "etr-channel",
        "etr-list-channels",
        "etr-seal",
        "etr-open",
        "etr-list-envelopes",
        "etr-report",
        "scheduler-tick",
        "scheduler-enable",
        "scheduler-disable",
        "scheduler-status",
        "scheduler-cycle",
        "scheduler-list",
        "scheduler-report",
        "release",
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
    for heading in REQUIRED_AEX_HEADINGS:
        if heading not in aex:
            errors.append(f"AEX specification is missing: {heading}")
    for heading in REQUIRED_AHP_HEADINGS:
        if heading not in ahp:
            errors.append(f"AHP specification is missing: {heading}")
    for heading in REQUIRED_VAL_HEADINGS:
        if heading not in val:
            errors.append(f"VAL specification is missing: {heading}")
    for heading in REQUIRED_RKM_HEADINGS:
        if heading not in rkm:
            errors.append(f"RKM specification is missing: {heading}")
    for heading in REQUIRED_AGC_HEADINGS:
        if heading not in agc:
            errors.append(f"AGC specification is missing: {heading}")
    for heading in REQUIRED_REC_HEADINGS:
        if heading not in rec:
            errors.append(f"REC specification is missing: {heading}")
    for heading in REQUIRED_ETR_HEADINGS:
        if heading not in etr:
            errors.append(f"ETR specification is missing: {heading}")
    for heading in REQUIRED_AWS_HEADINGS:
        if heading not in aws:
            errors.append(f"AWS specification is missing: {heading}")
    for heading in REQUIRED_REL_HEADINGS:
        if heading not in rel:
            errors.append(f"REL specification is missing: {heading}")
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
    if "**END OF SPECIFICATION" not in aex:
        errors.append("AEX specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in ahp:
        errors.append("AHP specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in val:
        errors.append("VAL specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in rkm:
        errors.append("RKM specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in agc:
        errors.append("AGC specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in rec:
        errors.append("REC specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in etr:
        errors.append("ETR specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in aws:
        errors.append("AWS specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in rel:
        errors.append("REL specification does not contain its terminal marker")

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

    aex_fences = re.findall(r"```json\n(.*?)\n```", aex, flags=re.DOTALL)
    if not aex_fences:
        errors.append("AEX specification has no JSON examples")
    for index, document in enumerate(aex_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"AEX JSON example {index} is invalid: {error.msg}")

    ahp_fences = re.findall(r"```json\n(.*?)\n```", ahp, flags=re.DOTALL)
    if not ahp_fences:
        errors.append("AHP specification has no JSON examples")
    for index, document in enumerate(ahp_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"AHP JSON example {index} is invalid: {error.msg}")

    val_fences = re.findall(r"```json\n(.*?)\n```", val, flags=re.DOTALL)
    if not val_fences:
        errors.append("VAL specification has no JSON examples")
    for index, document in enumerate(val_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"VAL JSON example {index} is invalid: {error.msg}")

    rkm_fences = re.findall(r"```json\n(.*?)\n```", rkm, flags=re.DOTALL)
    if not rkm_fences:
        errors.append("RKM specification has no JSON examples")
    for index, document in enumerate(rkm_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"RKM JSON example {index} is invalid: {error.msg}")

    agc_fences = re.findall(r"```json\n(.*?)\n```", agc, flags=re.DOTALL)
    if not agc_fences:
        errors.append("AGC specification has no JSON examples")
    for index, document in enumerate(agc_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"AGC JSON example {index} is invalid: {error.msg}")

    rec_fences = re.findall(r"```json\n(.*?)\n```", rec, flags=re.DOTALL)
    if not rec_fences:
        errors.append("REC specification has no JSON examples")
    for index, document in enumerate(rec_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"REC JSON example {index} is invalid: {error.msg}")

    etr_fences = re.findall(r"```json\n(.*?)\n```", etr, flags=re.DOTALL)
    if not etr_fences:
        errors.append("ETR specification has no JSON examples")
    for index, document in enumerate(etr_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"ETR JSON example {index} is invalid: {error.msg}")

    aws_fences = re.findall(r"```json\n(.*?)\n```", aws, flags=re.DOTALL)
    if not aws_fences:
        errors.append("AWS specification has no JSON examples")
    for index, document in enumerate(aws_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"AWS JSON example {index} is invalid: {error.msg}")

    rel_fences = re.findall(r"```json\n(.*?)\n```", rel, flags=re.DOTALL)
    if not rel_fences:
        errors.append("REL specification has no JSON examples")
    for index, document in enumerate(rel_fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"REL JSON example {index} is invalid: {error.msg}")

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
    print(f"aex_required_headings={len(REQUIRED_AEX_HEADINGS)}")
    print(f"aex_json_examples={len(aex_fences)}")
    print(f"ahp_required_headings={len(REQUIRED_AHP_HEADINGS)}")
    print(f"ahp_json_examples={len(ahp_fences)}")
    print(f"val_required_headings={len(REQUIRED_VAL_HEADINGS)}")
    print(f"val_json_examples={len(val_fences)}")
    print(f"rkm_required_headings={len(REQUIRED_RKM_HEADINGS)}")
    print(f"rkm_json_examples={len(rkm_fences)}")
    print(f"agc_required_headings={len(REQUIRED_AGC_HEADINGS)}")
    print(f"agc_json_examples={len(agc_fences)}")
    print(f"rec_required_headings={len(REQUIRED_REC_HEADINGS)}")
    print(f"rec_json_examples={len(rec_fences)}")
    print(f"etr_required_headings={len(REQUIRED_ETR_HEADINGS)}")
    print(f"etr_json_examples={len(etr_fences)}")
    print(f"aws_required_headings={len(REQUIRED_AWS_HEADINGS)}")
    print(f"aws_json_examples={len(aws_fences)}")
    print(f"rel_required_headings={len(REQUIRED_REL_HEADINGS)}")
    print(f"rel_json_examples={len(rel_fences)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
