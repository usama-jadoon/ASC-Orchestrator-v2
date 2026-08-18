#!/usr/bin/env python3
"""Audit harness: generate correct deterministic v1.0.1 fixture chain.

RC-003: the synthetic v1.0.1 fixture generator produced an incorrect
rev2 -> rev1 SHA relationship.  Real InboxShield history does NOT contain
this defect.  This script regenerates the v1.0.1 history with a valid
prev_state_sha256 that chains to the actual v1.0.0 state.

Usage:
    python audit/build_fixtures.py --generate-v101

The script also provides a chain-validation guard that MUST pass before any
fixture enters the compatibility corpus (used by deep audit re-runs).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "audit_fixtures"


def canonical_json(value: Any) -> bytes:
    """Serialize JSON using sorted keys and ECMAScript-compatible numbers."""
    import numbers

    def encode(obj: Any) -> str:
        if isinstance(obj, str):
            return json.dumps(obj, ensure_ascii=False)
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if obj is None:
            return "null"
        if isinstance(obj, numbers.Integral) and not isinstance(obj, bool):
            return str(obj)
        if isinstance(obj, float):
            if obj != obj or obj in (float("inf"), float("-inf")):
                raise ValueError("non-finite float")
            # repr() gives shortest round-tripping representation.
            return repr(obj)
        if isinstance(obj, list):
            return "[" + ",".join(encode(item) for item in obj) + "]"
        if isinstance(obj, dict):
            items = sorted(obj.items())
            return "{" + ",".join(encode(k) + ":" + encode(v) for k, v in items) + "}"
        raise TypeError(f"unserializable: {type(obj)}")

    return encode(value).encode("utf-8")


def canonical_sha256(value: Any, omit: str | None = None) -> str:
    """SHA-256 of canonical JSON, optionally omitting one key."""
    if omit is not None and isinstance(value, dict):
        value = {k: v for k, v in value.items() if k != omit}
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_envelope(path: Path) -> dict[str, Any]:
    """Load a PESE envelope JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_envelope(path: Path, envelope: dict[str, Any]) -> None:
    """Write envelope as pretty JSON (not canonical; envelope metadata is not hashed)."""
    path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def validate_chain(rev1_path: Path, rev2_path: Path) -> tuple[bool, str]:
    """Validate that rev2.previous_state_sha256 == rev1.state_sha256.

    Returns (ok, detail).  If ok is False, detail describes the mismatch.
    """
    rev1 = load_envelope(rev1_path)
    rev2 = load_envelope(rev2_path)

    expected = rev1["state_sha256"]
    actual = rev2["previous_state_sha256"]

    if expected != actual:
        return (
            False,
            f"chain broken: rev2.previous_state_sha256={actual[:16]}... "
            f"!= rev1.state_sha256={expected[:16]}...",
        )
    return True, "chain valid: rev2.previous_state_sha256 == rev1.state_sha256"


def generate_v101_fixture() -> int:
    """Generate the corrected v1.0.1 history revision 2.

    Reads audit_fixtures/v1.0.0/history_1.json (rev1),
    reads audit_fixtures/v1.0.1/history_2.json (rev2 with broken chain),
    patches rev2.previous_state_sha256 to rev1.state_sha256,
    recomputes rev2.file_sha256 and rev2.state_sha256 (state content unchanged),
    writes corrected rev2 to audit_fixtures/v1.0.1/history_2.json.
    """
    rev1_path = FIXTURES_DIR / "v1.0.0" / "history_1.json"
    rev2_path = FIXTURES_DIR / "v1.0.1" / "history_2.json"

    if not rev1_path.exists():
        print(f"ERROR: rev1 not found at {rev1_path}", file=sys.stderr)
        return 1
    if not rev2_path.exists():
        print(f"ERROR: rev2 not found at {rev2_path}", file=sys.stderr)
        return 1

    rev1 = load_envelope(rev1_path)
    rev2 = load_envelope(rev2_path)

    # Verify rev1 is revision 1
    if rev1["revision"] != 1:
        print(
            f"ERROR: expected rev1 revision=1, got {rev1['revision']}", file=sys.stderr
        )
        return 1

    # Verify rev2 is revision 2 pointing to rev1
    if rev2["revision"] != 2:
        print(
            f"ERROR: expected rev2 revision=2, got {rev2['revision']}", file=sys.stderr
        )
        return 1
    if rev2["previous_revision"] != 1:
        print(
            f"ERROR: expected rev2 previous_revision=1, got {rev2['previous_revision']}",
            file=sys.stderr,
        )
        return 1

    # The fix: set previous_state_sha256 to rev1's state_sha256
    correct_prev = rev1["state_sha256"]
    rev2["previous_state_sha256"] = correct_prev

    # Recompute file_sha256 (hash of the whole envelope without file_sha256)
    rev2["file_sha256"] = canonical_sha256(rev2, omit="file_sha256")

    # state_sha256 is the hash of the state payload only.
    # The state content is UNCHANGED; we just recompute to be safe.
    rev2["state_sha256"] = canonical_sha256(rev2["state"])

    # Write corrected rev2
    write_envelope(rev2_path, rev2)

    # Also update live.json to match (it mirrors history_2.json)
    live_path = FIXTURES_DIR / "v1.0.1" / "live.json"
    if live_path.exists():
        live = load_envelope(live_path)
        live["previous_state_sha256"] = correct_prev
        live["file_sha256"] = canonical_sha256(live, omit="file_sha256")
        live["state_sha256"] = canonical_sha256(live["state"])
        write_envelope(live_path, live)

    # Verify the chain now passes
    ok, detail = validate_chain(rev1_path, rev2_path)
    if not ok:
        print(f"ERROR: chain validation failed after fix: {detail}", file=sys.stderr)
        return 1

    print(f"OK: {detail}")
    print(f"  rev1.state_sha256 = {correct_prev}")
    print(f"  rev2.previous_state_sha256 = {correct_prev}")
    return 0


def validate_corpus_entry() -> int:
    """Guard: validate all historical chains in the compatibility corpus.

    This MUST pass before any fixture enters the deep-audit compatibility
    corpus.  Currently checks v1.0.0 -> v1.0.1 chain integrity.
    """
    rev1_path = FIXTURES_DIR / "v1.0.0" / "history_1.json"
    rev2_path = FIXTURES_DIR / "v1.0.1" / "history_2.json"

    ok, detail = validate_chain(rev1_path, rev2_path)
    if ok:
        print(f"CORPUS GUARD PASS: {detail}")
        return 0
    else:
        print(f"CORPUS GUARD FAIL: {detail}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit fixture chain builder")
    parser.add_argument(
        "--generate-v101",
        action="store_true",
        help="Regenerate v1.0.1 revision 2 with correct chain",
    )
    parser.add_argument(
        "--validate-corpus",
        action="store_true",
        help="Validate historical chains before compatibility corpus entry",
    )
    args = parser.parse_args(argv)

    if args.generate_v101:
        return generate_v101_fixture()
    if args.validate_corpus:
        return validate_corpus_entry()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
