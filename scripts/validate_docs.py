"""Validate the documentation that defines the shipped PESE and TBE contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PESE = ROOT / "docs" / "PESE_v1.0.md"
TBE = ROOT / "docs" / "TBE_v1.0.md"

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


def main() -> int:
    """Return nonzero when a canonical contract or CLI invariant is absent."""

    readme = README.read_text(encoding="utf-8")
    pese = PESE.read_text(encoding="utf-8")
    tbe = TBE.read_text(encoding="utf-8")
    errors: list[str] = []

    for command in ("state", "resume", "checkpoint", "validate-state", "team-build"):
        if f" {command}" not in readme:
            errors.append(f"README does not document the `{command}` command")
    for heading in REQUIRED_PESE_HEADINGS:
        if heading not in pese:
            errors.append(f"PESE specification is missing: {heading}")
    for heading in REQUIRED_TBE_HEADINGS:
        if heading not in tbe:
            errors.append(f"TBE specification is missing: {heading}")
    if "**END OF SPECIFICATION" not in pese:
        errors.append("PESE specification does not contain its terminal marker")
    if "**END OF SPECIFICATION" not in tbe:
        errors.append("TBE specification does not contain its terminal marker")

    fences = re.findall(r"```json\n(.*?)\n```", pese, flags=re.DOTALL)
    if not fences:
        errors.append("PESE specification has no JSON encoding examples")
    for index, document in enumerate(fences, start=1):
        try:
            json.loads(document)
        except json.JSONDecodeError as error:
            errors.append(f"PESE JSON example {index} is invalid: {error.msg}")

    if errors:
        print("documentation=FAIL")
        print("\\n".join(errors))
        return 1
    print("documentation=PASS")
    print(f"pese_json_examples={len(fences)}")
    print(f"tbe_required_headings={len(REQUIRED_TBE_HEADINGS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
