#!/usr/bin/env python3
"""Performance benchmarks for ASC Orchestrator v1.0.0.

Standalone script — no external dependencies.  Uses ``time.perf_counter``
for micro-benchmarking core operations.

Usage::

    python benchmarks/run_benchmarks.py
"""

from __future__ import annotations

import hashlib  # noqa: F401 - used by HMAC benchmarking
import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure local source is on sys.path so we benchmark the working tree,
# not an installed package.
_src = (Path(__file__).resolve().parents[1] / "src").as_posix()
if _src not in sys.path:
    sys.path.insert(0, _src)


def _bench(label: str, fn, *, iterations: int = 500, warmup: int = 20) -> dict:
    """Run *fn* for *warmup* + *iterations* rounds and return timing stats."""
    for _ in range(warmup):
        fn()
    times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    times.sort()
    n = len(times)
    return {
        "label": label,
        "iterations": n,
        "total_ms": round(sum(times) * 1000, 2),
        "mean_ms": round(sum(times) / n * 1000, 3),
        "median_ms": round(times[n // 2] * 1000, 3),
        "p95_ms": round(times[int(n * 0.95)] * 1000, 3),
        "min_ms": round(times[0] * 1000, 3),
        "max_ms": round(times[-1] * 1000, 3),
    }


def bench_hash_chaining() -> list[dict]:
    """Benchmark hash-chain operations (PESE journal append pattern)."""
    from asc_orchestrator.pese import canonical_json, canonical_sha256

    results = []
    state = {
        "schema_version": "1.0.0",
        "company_state": {"company_id": "test", "status": "ACTIVE"},
        "mission_state": {"missions": {}},
    }
    results.append(_bench("pese.canonical_json (1KB)", lambda: canonical_json(state)))
    results.append(
        _bench("pese.canonical_sha256 (1KB)", lambda: canonical_sha256(state))
    )
    return results


def bench_key_operations() -> list[dict]:
    """Benchmark CKS key lifecycle operations."""
    from asc_orchestrator.keys import KeyStore

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = KeyStore(root)
        rec = store.create_key("AGENT:bench:test")
        key_id = rec.key_id
        payload = b"benchmark payload " * 10

        results.append(
            _bench("cks.create_key", lambda: store.create_key("AGENT:bench:test"))
        )
        results.append(_bench("cks.load_key", lambda: store.load_key(key_id)))
        results.append(
            _bench(
                "cks.sign (180B)",
                lambda: store.sign(key_id, payload, "AGENT:bench:test"),
            )
        )
        sig = store.sign(key_id, payload, "AGENT:bench:test")
        results.append(
            _bench(
                "cks.verify", lambda: store.verify(key_id, payload, sig.signature_hex)
            )
        )
        results.append(_bench("cks.status", lambda: store.status(key_id)))
    return results


def bench_health_operations() -> list[dict]:
    """Benchmark AHP health store operations."""
    from asc_orchestrator.health import HealthStore

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = HealthStore(root)
        results.append(
            _bench("ahp.heartbeat", lambda: store.heartbeat("AGENT:bench:local"))
        )
        store.heartbeat("AGENT:bench:local")
        results.append(
            _bench(
                "ahp.agent_health",
                lambda: store.agent_health("AGENT:bench:local", timeout=300),
            )
        )
    return results


def bench_pese_lifecycle() -> list[dict]:
    """Benchmark PESE state load/save cycle."""
    from asc_orchestrator.pese import PESEStore

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = PESEStore(root)
        store.initialize("AGENT:orchestrator:bench")
        # initialize() rewrites the journal each call — use few iterations.
        results.append(
            _bench(
                "pese.initialize",
                lambda: store.initialize("AGENT:orchestrator:bench"),
                iterations=50,
            )
        )
        results.append(
            _bench("pese.load", lambda: store.load(actor="AGENT:orchestrator:bench"))
        )
    return results


def bench_hmac_operations() -> list[dict]:
    """Benchmark raw HMAC-SHA256 for throughput baseline."""
    import hmac

    results = []
    key = b"0" * 32
    payload_1k = b"x" * 1024
    payload_64k = b"y" * 65536
    results.append(
        _bench("hmac-sha256 (1KB)", lambda: hmac.new(key, payload_1k, "sha256"))
    )
    results.append(
        _bench("hmac-sha256 (64KB)", lambda: hmac.new(key, payload_64k, "sha256"))
    )
    return results


def bench_risk_operations() -> list[dict]:
    """Benchmark RKM risk engine operations."""
    from asc_orchestrator.pese import PESEStore
    from asc_orchestrator.risk import RiskEngine

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # PESE state must exist before RiskEngine can load it.
        PESEStore(root).initialize("AGENT:orchestrator:bench")
        engine = RiskEngine(root)
        actor = "AGENT:orchestrator:bench"
        for i in range(5):
            engine.open(f"RISK:bench-{i}", "LOW", f"bench-{i}", None, actor)

        def _open_and_mitigate():
            risk_id = f"RISK:bench-extra-{time.monotonic_ns()}"
            engine.open(risk_id, "LOW", "perf-test", None, actor)
            engine.mitigate(risk_id, actor)

        results.append(
            _bench("rkm.open+mitigate cycle", _open_and_mitigate, iterations=100)
        )
        results.append(
            _bench("rkm.check (5 risks)", lambda: engine.check("MISSION:bench"))
        )
    return results


def main() -> None:
    print("=" * 72)
    print("ASC Orchestrator v1.0.0 — Performance Benchmarks")
    print("=" * 72)
    all_results: list[dict] = []

    for section_fn in [
        bench_hmac_operations,
        bench_hash_chaining,
        bench_key_operations,
        bench_health_operations,
        bench_pese_lifecycle,
        bench_risk_operations,
    ]:
        section_name = (
            section_fn.__name__.replace("bench_", "")
            .replace("_operations", "")
            .replace("_", " ")
            .title()
        )
        print(f"\n--- {section_name} ---")
        results = section_fn()
        all_results.extend(results)
        for r in results:
            print(
                f"  {r['label']:.<45s} "
                f"mean={r['mean_ms']:>7.3f}ms  "
                f"p95={r['p95_ms']:>7.3f}ms  "
                f"({r['iterations']} iters)"
            )

    print("\n" + "=" * 72)
    print(f"Total benchmarks: {len(all_results)}")
    print(f"Total time: {sum(r['total_ms'] for r in all_results):.0f}ms")
    print("=" * 72)

    # Write machine-readable results
    out_path = Path(__file__).parent / "results.json"
    out_path.write_text(json.dumps(all_results, indent=2) + "\n", encoding="utf-8")
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
