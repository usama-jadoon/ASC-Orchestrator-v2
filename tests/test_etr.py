"""Unit tests for Encrypted Transport (ETR) v1.0."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main
from asc_orchestrator.etr import (
    ETR_CIPHER,
    ETR_FORMAT,
    EtrError,
    SealedEnvelope,
    TransportChannel,
    TransportReport,
    UnsealedPayload,
    _aead_open,
    _aead_seal,
    _chacha20_block,
    _chacha20_xor,
    _pad16,
    _poly1305,
)
from asc_orchestrator.keys import KeyStore

# ---------------------------------------------------------------------------
# RFC 8439 test vectors
# ---------------------------------------------------------------------------

# §2.3.2 ChaCha20 block test vector.
_CHACHA20_KEY_232 = bytes(range(0x00, 0x20))  # 00 01 ... 1f
_CHACHA20_NONCE_232 = bytes([0, 0, 0, 0x09, 0, 0, 0, 0x4A, 0, 0, 0, 0])
_CHACHA20_COUNTER_232 = 1
_CHACHA20_BLOCK_232 = bytes.fromhex(
    "10f1e7e4d13b5915500fdd1fa32071c4"
    "c7d1f4c733c068030422aa9ac3d46c4e"
    "d2826446079faa0914c2d705d98b02a2"
    "b5129cd1de164eb9cbd083e8a2503c4e"
)

# §2.5.2 Poly1305 test vector 1.
_POLY1305_KEY_V1 = bytes.fromhex(
    "85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b"
)
_POLY1305_MSG_V1 = b"Cryptographic Forum Research Group"
_POLY1305_TAG_V1 = bytes.fromhex("a8061dc1305136c6c22b8baf0c0127a9")

# §2.5.2 Poly1305 test vector 2: all-zero key + 200 zero bytes.
_POLY1305_KEY_V2 = bytes(32)
_POLY1305_MSG_V2 = bytes(200)
_POLY1305_TAG_V2 = bytes(16)

# §2.8.2 AEAD test vector 1: "Ladies and Gentlemen..."
_AEAD_KEY_V1 = bytes(range(0x80, 0xA0))
# The RFC expresses the nonce as an 8-byte IV (40..47) plus a 32-bit
# fixed-common part (07 00 00 00); nonce = constant | iv.
_AEAD_NONCE_V1 = bytes.fromhex("070000004041424344454647")
_AEAD_AAD_V1 = bytes(
    [0x50, 0x51, 0x52, 0x53, 0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7]
)
_AEAD_PT_V1 = (
    b"Ladies and Gentlemen of the class of '99: "
    b"If I could offer you only one tip for the future, "
    b"sunscreen would be it."
)
_AEAD_CT_V1 = bytes.fromhex(
    "d31a8d34648e60db7b86afbc53ef7ec2"
    "a4aded51296e08fea9e2b5a736ee62d6"
    "3dbea45e8ca9671282fafb69da92728b"
    "1a71de0a9e060b2905d6a5b67ecd3b36"
    "92ddbd7f2d778b8c9803aee328091b58"
    "fab324e4fad675945585808b4831d7bc"
    "3ff4def08e4b7a9de576d26586cec64b"
    "6116"
)
_AEAD_TAG_V1 = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")

# Appendix A.5 AEAD decryption test vector (full key/nonce/aad/plaintext).
_AEAD_KEY_A5 = bytes.fromhex(
    "1c9240a5eb55d38af333888604f6b5f0473917c1402b80099dca5cbc207075c0"
)
_AEAD_NONCE_A5 = bytes.fromhex("000000000102030405060708")
_AEAD_AAD_A5 = bytes.fromhex("f33388860000000000004e91")
_AEAD_CT_A5 = bytes.fromhex(
    "64a0861575861af460f062c79be643bd"
    "5e805cfd345cf389f108670ac76c8cb2"
    "4c6cfc18755d43eea09ee94e382d26b0"
    "bdb7b73c321b0100d4f03b7f355894cf"
    "332f830e710b97ce98c8a84abd0b9481"
    "14ad176e008d33bd60f982b1ff37c855"
    "9797a06ef4f0ef61c186324e2b350638"
    "3606907b6a7c02b0f9f6157b53c867e4"
    "b9166c767b804d46a59b5216cde7a4e9"
    "9040c5a40433225ee282a1b0a06c523e"
    "af4534d7f83fa1155b0047718cbc546a"
    "0d072b04b3564eea1b422273f548271a"
    "0bb2316053fa76991955ebd63159434e"
    "cebb4e466dae5a1073a6727627097a10"
    "49e617d91d361094fa68f0ff77987130"
    "305beaba2eda04df997b714d6c6f2c29"
    "a6ad5cb4022b02709b"
)
_AEAD_PT_A5 = bytes.fromhex(
    "496e7465726e65742d44726166747320"
    "61726520647261667420646f63756d65"
    "6e74732076616c696420666f72206120"
    "6d6178696d756d206f6620736978206d"
    "6f6e74687320616e64206d6179206265"
    "20757064617465642c207265706c6163"
    "65642c206f72206f62736f6c65746564"
    "206279206f7468657220646f63756d65"
    "6e747320617420616e792074696d652e"
    "20497420697320696e617070726f7072"
    "6961746520746f2075736520496e7465"
    "726e65742d4472616674732061732072"
    "65666572656e6365206d617465726961"
    "6c206f7220746f206369746520746865"
    "6d206f74686572207468616e20617320"
    "2fe2809c776f726b20696e2070726f67"
    "726573732e2fe2809d"
)
_AEAD_TAG_A5 = bytes.fromhex("eead9d67890cbb22392336fea1851f38")

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

MISSION = {
    "mission_id": "MISSION:etr",
    "mission_type": "enhancement",
    "objective": "Add a deterministic encrypted-transport capability.",
    "demands": [
        {
            "id": "ASSIGNMENT:build",
            "capability": "developer",
            "project": "app",
            "criterion": "works",
            "paths": ["src/feature.py"],
            "validation_gates": ["functional"],
        }
    ],
}
CLASSIFICATION = [
    {
        "type": "python-package",
        "root": "app",
        "languages": ["python"],
        "frameworks": [],
        "platform": "linux",
        "test_surface": "unittest",
    }
]


def _valid_entry(agent_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent-id": agent_id,
        "version": "1.0.0",
        "display-name": agent_id,
        "description": f"{agent_id} for ETR tests.",
        "purpose": {
            "mission-types": ["enhancement"],
            "value-streams": ["delivery"],
            "strategic-objectives": ["reliability"],
        },
        "responsibilities": {
            "primary-duties": ["complete assigned work"],
            "excluded-duties": ["unrelated work"],
        },
        "authority": {
            "autonomous-decisions": ["choose implementation details"],
            "escalation-decisions": ["change mission scope"],
            "authority-scope": ["assigned mission"],
        },
        "decision-rights": {
            "decision-types": ["implementation"],
            "decision-criteria": {"implementation": ["mission criterion"]},
            "reversibility": {"implementation": "reversible"},
        },
        "escalation-rights": {
            "escalation-triggers": ["blocked"],
            "escalation-paths": {"blocked": "orchestrator"},
            "escalation-timeout": "30",
        },
        "required-skills": {
            "competencies": [agent_id],
            "proficiency-levels": {agent_id: "intermediate"},
            "skill-validators": {agent_id: "test evidence"},
        },
        "allowed-tools": {
            "tool-categories": ["development"],
            "specific-tools": ["python"],
            "tool-restrictions": ["no network"],
            "tool-validation": ["approved"],
        },
        "allowed-mcp-servers": {
            "mcp-server-types": ["filesystem"],
            "specific-servers": ["filesystem:local"],
            "mcp-restrictions": ["no network"],
        },
        "owned-artifacts": {
            "artifact-types": ["evidence"],
            "artifact-locations": {"evidence": "artifacts/"},
            "artifact-ownership": {"evidence": "exclusive"},
            "artifact-retention": {"evidence": "mission"},
        },
        "owned-repository-areas": {
            "owned-paths": ["src/**"],
            "writable-paths": ["src/**"],
            "path-restrictions": ["/.git/", "/.project-os/"],
            "path-validation": ["paths are checked"],
        },
        "communication-rights": {
            "message-types-sent": ["PROGRESS"],
            "message-types-received": ["ASSIGNMENT"],
            "communication-restrictions": ["mission scope only"],
            "correlation-rules": ["retain mission correlation"],
        },
        "validation-duties": {
            "validation-gates": ["functional"],
            "validation-criteria": {"functional": ["criterion"]},
            "evidence-requirements": {"functional": ["evidence"]},
            "validation-automation": {"functional": "automated"},
        },
        "recovery-duties": {
            "recovery-scenarios": ["agent failure"],
            "recovery-procedures": {"agent failure": ["reassign"]},
            "state-checkpoints": {"before work": ["execution-state"]},
            "recovery-validation": {"agent failure": "state restored"},
        },
        "kpis-and-success-metrics": {
            "kpi-definitions": {"completion": {"target": "100%"}},
            "metric-collection-method": {"completion": "assignment state"},
            "success-thresholds": {"completion": "green"},
            "metric-reporting-frequency": {"completion": "per mission"},
        },
        "parallel-execution-rules": {
            "can-run-concurrently": "yes",
            "shared-resources": "none",
            "conflict-resolution": "deterministic order",
            "resource-limits": "max: 3",
        },
        "dependencies": {
            "agent-dependencies": "none",
            "tool-dependencies": ["python"],
            "environment-dependencies": ["temporary directory"],
            "dependency-validation": ["versions checked"],
        },
        "input-contracts": {
            "input-message-types": ["EVIDENCE", "REVIEW"],
            "input-schema": {
                m: {"required": ["REFERENCE"]} for m in ("EVIDENCE", "REVIEW")
            },
            "input-validation": ["reference is valid"],
            "input-state-requirements": ["active mission"],
        },
        "output-contracts": {
            "output-message-types": ["EVIDENCE", "REVIEW"],
            "output-schema": {
                m: {"required": ["REFERENCE"]} for m in ("EVIDENCE", "REVIEW")
            },
            "output-state-changes": ["assignment progress"],
            "output-validation": ["reference is valid"],
        },
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


# ---------------------------------------------------------------------------
# RFC 8439 primitive tests
# ---------------------------------------------------------------------------


class TestRFC8439Primitives(unittest.TestCase):
    """Verify ChaCha20, Poly1305, and AEAD against published test vectors."""

    def test_chacha20_block_vector(self) -> None:
        block = _chacha20_block(
            _CHACHA20_KEY_232, _CHACHA20_COUNTER_232, _CHACHA20_NONCE_232
        )
        self.assertEqual(block, _CHACHA20_BLOCK_232)

    def test_chacha20_block_key_length(self) -> None:
        with self.assertRaises(EtrError) as ctx:
            _chacha20_block(b"\x00" * 16, 0, b"\x00" * 12)
        self.assertEqual(ctx.exception.code, "BAD_KEY")

    def test_chacha20_block_nonce_length(self) -> None:
        with self.assertRaises(EtrError) as ctx:
            _chacha20_block(b"\x00" * 32, 0, b"\x00" * 8)
        self.assertEqual(ctx.exception.code, "BAD_NONCE")

    def test_chacha20_xor_empty(self) -> None:
        result = _chacha20_xor(b"\x00" * 32, 0, b"\x00" * 12, b"")
        self.assertEqual(result, b"")

    def test_chacha20_xor_length_preserved(self) -> None:
        plaintext = b"\x42" * 128
        ct = _chacha20_xor(b"\x00" * 32, 0, b"\x00" * 12, plaintext)
        self.assertEqual(len(ct), len(plaintext))
        # XOR is its own inverse.
        self.assertEqual(_chacha20_xor(b"\x00" * 32, 0, b"\x00" * 12, ct), plaintext)

    def test_poly1305_vector_1(self) -> None:
        tag = _poly1305(_POLY1305_KEY_V1, _POLY1305_MSG_V1)
        self.assertEqual(tag, _POLY1305_TAG_V1)

    def test_poly1305_vector_2_zero_key_zero_msg(self) -> None:
        tag = _poly1305(_POLY1305_KEY_V2, _POLY1305_MSG_V2)
        self.assertEqual(tag, _POLY1305_TAG_V2)

    def test_poly1305_key_length(self) -> None:
        with self.assertRaises(EtrError) as ctx:
            _poly1305(b"\x00" * 16, b"\x00")
        self.assertEqual(ctx.exception.code, "BAD_KEY")

    def test_pad16_partial_block(self) -> None:
        data = b"\x01\x02\x03"
        padded = _pad16(data)
        self.assertEqual(len(padded), 16)
        self.assertEqual(padded[:3], data)

    def test_pad16_exact_boundary(self) -> None:
        data = b"\x01" * 16
        self.assertIs(_pad16(data), data)

    def test_aead_vector_1_114_bytes(self) -> None:
        ct, tag = _aead_seal(_AEAD_KEY_V1, _AEAD_NONCE_V1, _AEAD_AAD_V1, _AEAD_PT_V1)
        self.assertEqual(ct, _AEAD_CT_V1)
        self.assertEqual(tag, _AEAD_TAG_V1)
        # Round-trip.
        pt = _aead_open(_AEAD_KEY_V1, _AEAD_NONCE_V1, _AEAD_AAD_V1, ct, tag)
        self.assertEqual(pt, _AEAD_PT_V1)

    def test_aead_vector_a5_appendix(self) -> None:
        """Appendix A.5 AEAD decryption vector; verify seal and open round-trip."""
        ct, tag = _aead_seal(_AEAD_KEY_A5, _AEAD_NONCE_A5, _AEAD_AAD_A5, _AEAD_PT_A5)
        self.assertEqual(ct, _AEAD_CT_A5)
        self.assertEqual(tag, _AEAD_TAG_A5)
        pt = _aead_open(_AEAD_KEY_A5, _AEAD_NONCE_A5, _AEAD_AAD_A5, ct, tag)
        self.assertEqual(pt, _AEAD_PT_A5)

    def test_aead_tag_mismatch_returns_none(self) -> None:
        result = _aead_open(
            _AEAD_KEY_V1,
            _AEAD_NONCE_V1,
            _AEAD_AAD_V1,
            _AEAD_CT_V1,
            b"\x00" * 16,
        )
        self.assertIsNone(result)

    def test_aead_determinism(self) -> None:
        key = b"\x00" * 32
        nonce = b"\x00" * 12
        aad = b"\xaa\xbb"
        plaintext = b"hello world"
        ct1, tag1 = _aead_seal(key, nonce, aad, plaintext)
        ct2, tag2 = _aead_seal(key, nonce, aad, plaintext)
        self.assertEqual(ct1, ct2)
        self.assertEqual(tag1, tag2)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses(unittest.TestCase):
    """Verify frozen dataclass field shapes."""

    def test_transport_channel(self) -> None:
        ch = TransportChannel(
            channel_id="CHANNEL:test",
            format=ETR_FORMAT,
            from_id="AGENT:a:local",
            to_id="AGENT:b:local",
            key_id="KEY-test",
            status="ACTIVE",
            created_at="2026-08-07T00:00:00Z",
            updated_at=None,
            revoked_at=None,
        )
        self.assertEqual(ch.status, "ACTIVE")
        self.assertEqual(ch.format, ETR_FORMAT)

    def test_sealed_envelope(self) -> None:
        env = SealedEnvelope(
            envelope_id="ENVELOPE:test",
            format=ETR_FORMAT,
            cipher=ETR_CIPHER,
            key_id="KEY-test",
            nonce="aa",
            aad="bb",
            ciphertext="cc",
            tag="dd",
            plaintext_sha256="ee",
            message_type=None,
            from_id=None,
            to_id=None,
            mission_id=None,
            correlation_id=None,
            status="SEALED",
            created_at="2026-08-07T00:00:00Z",
            opened_at=None,
        )
        self.assertEqual(env.status, "SEALED")
        self.assertIsNone(env.message_type)

    def test_unsealed_payload(self) -> None:
        up = UnsealedPayload(
            payload=b"hello",
            envelope_id="ENVELOPE:x",
            key_id="KEY:x",
            plaintext_sha256="abc",
        )
        self.assertEqual(up.payload, b"hello")

    def test_transport_report(self) -> None:
        tr = TransportReport(
            channels_total=0,
            channels_active=0,
            channels_revoked=0,
            envelopes_total=0,
            envelopes_sealed=0,
            envelopes_opened=0,
            envelopes_auth_failed=0,
        )
        self.assertEqual(tr.channels_total, 0)


# ---------------------------------------------------------------------------
# EtrError tests
# ---------------------------------------------------------------------------


class TestEtrError(unittest.TestCase):
    def test_code_and_detail(self) -> None:
        err = EtrError("CODE", "detail")
        self.assertEqual(err.code, "CODE")
        self.assertEqual(err.detail, "detail")
        self.assertIn("CODE: detail", str(err))


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestEncryptedTransport(unittest.TestCase):
    """EncryptedTransport unit tests over a temp git repo."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._dir = self._tmp.__enter__()
        self._root = self._setup_repo(self._dir)

    def tearDown(self) -> None:
        self._tmp.__exit__(None, None, None)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(root), *arguments])
        return code, output.getvalue()

    @staticmethod
    def _git(root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _setup_repo(self, directory: str) -> Path:
        root = Path(directory)
        registry_dir = root / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        # A reviewer is required by team-build --bind-state (independent ACR
        # reviewer for the builder's demand). The developer does the build.
        for name, agent in [
            ("developer", _valid_entry("developer")),
            ("reviewer", _valid_entry("reviewer")),
        ]:
            (registry_dir / f"{name}.json").write_text(
                json.dumps(agent), encoding="utf-8"
            )
        config = (
            '[runtime]\nproject_os_dir = ".project-os"\n'
            'registry_dir = "registry"\n'
            'audit_dir = ".project-os/AUDIT"\n'
            'protocol_version = "ACP/v1.0"\n'
        )
        (root / "asc-orchestrator.toml").write_text(config, encoding="utf-8")
        (root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
        (root / "classification.json").write_text(
            json.dumps(CLASSIFICATION), encoding="utf-8"
        )
        self._git(root, "init")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "ETR Tests")
        (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", "initial")
        code, output = self._run(root, "state", "--initialize")
        self.assertEqual(code, 0, output)
        code, output = self._run(
            root,
            "team-build",
            "--mission",
            "mission.json",
            "--classification",
            "classification.json",
            "--bind-state",
        )
        self.assertEqual(code, 0, output)
        return root

    def _engine(self) -> "EncryptedTransport":  # noqa: F821
        from asc_orchestrator.etr import EncryptedTransport

        return EncryptedTransport(self._root)

    def _actor(self) -> str:
        return "AGENT:orchestrator:local"

    def _create_key(self) -> str:
        ks = KeyStore(self._root)
        record = ks.create_key(self._actor(), purpose="etr-test")
        return record.key_id

    # --- channel tests -----------------------------------------------------

    def test_bind_channel_returns_active(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:sender:local", "AGENT:receiver:local", key_id, self._actor()
        )
        self.assertEqual(ch.status, "ACTIVE")
        self.assertEqual(ch.key_id, key_id)
        self.assertTrue(ch.channel_id.startswith("CHANNEL:"))

    def test_bind_channel_missing_key(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.bind_channel(
                "AGENT:a:local", "AGENT:b:local", "KEY-nonexistent", self._actor()
            )
        self.assertEqual(ctx.exception.code, "KEY_NOT_FOUND")

    def test_revoke_channel(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        revoked = engine.revoke_channel(ch.channel_id, self._actor())
        self.assertEqual(revoked.status, "REVOKED")
        self.assertIsNotNone(revoked.revoked_at)

    def test_revoke_channel_not_active(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        engine.revoke_channel(ch.channel_id, self._actor())
        with self.assertRaises(EtrError) as ctx:
            engine.revoke_channel(ch.channel_id, self._actor())
        self.assertEqual(ctx.exception.code, "CHANNEL_NOT_ACTIVE")

    def test_channel_read(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        fetched = engine.channel(ch.channel_id, self._actor())
        self.assertEqual(fetched.status, "ACTIVE")

    def test_channel_not_found(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.channel("CHANNEL:nonexistent", self._actor())
        self.assertEqual(ctx.exception.code, "CHANNEL_NOT_FOUND")

    # --- envelope tests ----------------------------------------------------

    def test_seal_and_open_round_trip(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        payload = b"Hello ETR v1.0!"
        env = engine.seal(
            payload,
            key_id=key_id,
            message_type="STATUS_UPDATE",
            from_id="AGENT:sender:local",
            to_id="AGENT:receiver:local",
            mission_id="MISSION:test",
            correlation_id="9f1e2d3c-4b5a-6d7e-8f9a-0b1c2d3e4f5a",
            actor=self._actor(),
        )
        self.assertEqual(env.status, "SEALED")
        self.assertEqual(env.key_id, key_id)
        self.assertEqual(env.cipher, ETR_CIPHER)
        self.assertEqual(env.format, ETR_FORMAT)
        self.assertEqual(env.plaintext_sha256, hashlib.sha256(payload).hexdigest())
        # Open.
        unsealed = engine.open(env.envelope_id, actor=self._actor())
        self.assertEqual(unsealed.payload, payload)
        self.assertEqual(unsealed.envelope_id, env.envelope_id)
        self.assertEqual(unsealed.key_id, key_id)
        self.assertEqual(unsealed.plaintext_sha256, env.plaintext_sha256)

    def test_seal_empty_payload(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.seal(b"", key_id=key_id, actor=self._actor())
        self.assertEqual(ctx.exception.code, "EMPTY_PAYLOAD")

    def test_seal_requires_exactly_one_key_or_channel(self) -> None:
        self._create_key()
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.seal(b"x", actor=self._actor())
        self.assertEqual(ctx.exception.code, "KEY_REQUIRED")

    def test_seal_via_channel_id(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        payload = b"sealed via channel"
        env = engine.seal(payload, channel_id=ch.channel_id, actor=self._actor())
        self.assertEqual(env.key_id, key_id)
        unsealed = engine.open(env.envelope_id, actor=self._actor())
        self.assertEqual(unsealed.payload, payload)

    def test_seal_active_channel_resolves_defaults(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:sender:local", "AGENT:receiver:local", key_id, self._actor()
        )
        env = engine.seal(b"data", channel_id=ch.channel_id, actor=self._actor())
        self.assertEqual(env.from_id, "AGENT:sender:local")
        self.assertEqual(env.to_id, "AGENT:receiver:local")

    def test_seal_revoked_channel_fails(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        engine.revoke_channel(ch.channel_id, self._actor())
        with self.assertRaises(EtrError) as ctx:
            engine.seal(b"x", channel_id=ch.channel_id, actor=self._actor())
        self.assertEqual(ctx.exception.code, "CHANNEL_NOT_ACTIVE")

    def test_seal_unknown_channel_fails(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.seal(b"x", channel_id="CHANNEL:nonexistent", actor=self._actor())
        self.assertEqual(ctx.exception.code, "CHANNEL_NOT_FOUND")

    def test_open_record_mapping(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(b"mapping test", key_id=key_id, actor=self._actor())
        record = {
            "envelope_id": env.envelope_id,
            "format": env.format,
            "cipher": env.cipher,
            "key_id": env.key_id,
            "nonce": env.nonce,
            "aad": env.aad,
            "ciphertext": env.ciphertext,
            "tag": env.tag,
            "plaintext_sha256": env.plaintext_sha256,
            "message_type": env.message_type,
            "from": env.from_id,
            "to": env.to_id,
            "mission_id": env.mission_id,
            "correlation_id": env.correlation_id,
            "status": env.status,
            "created_at": env.created_at,
            "opened_at": env.opened_at,
        }
        unsealed = engine.open(record, actor=self._actor())
        self.assertEqual(unsealed.payload, b"mapping test")

    def test_tamper_header_field_auth_failed(self) -> None:
        """Tampering message_type (a header field) fails the tag check."""
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(
            b"tamper test",
            key_id=key_id,
            message_type="ORIGINAL",
            actor=self._actor(),
        )
        # Load record from state and tamper message_type.
        state, _, _ = engine._load_state(self._actor())
        rec = dict(engine._envelopes(state)[env.envelope_id])
        rec["message_type"] = "TAMPERED"
        with self.assertRaises(EtrError) as ctx:
            engine.open(rec, actor=self._actor())
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")

    def test_tamper_ciphertext_auth_failed(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(b"ct tamper", key_id=key_id, actor=self._actor())
        state, _, _ = engine._load_state(self._actor())
        rec = dict(engine._envelopes(state)[env.envelope_id])
        # Flip a byte in the ciphertext.
        ct_bytes = bytes.fromhex(rec["ciphertext"])
        ct_bad = bytes([ct_bytes[0] ^ 0xFF]) + ct_bytes[1:]
        rec["ciphertext"] = ct_bad.hex()
        with self.assertRaises(EtrError) as ctx:
            engine.open(rec, actor=self._actor())
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")

    def test_tamper_tag_auth_failed(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(b"tag tamper", key_id=key_id, actor=self._actor())
        state, _, _ = engine._load_state(self._actor())
        rec = dict(engine._envelopes(state)[env.envelope_id])
        # Flip one hex nibble so the tag is a valid hex string but wrong.
        first = rec["tag"][0]
        rec["tag"] = ("1" if first != "1" else "0") + rec["tag"][1:]
        with self.assertRaises(EtrError) as ctx:
            engine.open(rec, actor=self._actor())
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")

    def test_open_wrong_key(self) -> None:
        """Change key_id to a different valid key → AAD changes → auth fails."""
        key_a = self._create_key()
        key_b = self._create_key()
        engine = self._engine()
        env = engine.seal(b"wrong key", key_id=key_a, actor=self._actor())
        state, _, _ = engine._load_state(self._actor())
        rec = dict(engine._envelopes(state)[env.envelope_id])
        rec["key_id"] = key_b  # point to different key
        with self.assertRaises(EtrError) as ctx:
            engine.open(rec, actor=self._actor())
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")

    def test_open_missing_envelope(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.open("ENVELOPE:nonexistent", actor=self._actor())
        self.assertEqual(ctx.exception.code, "ENVELOPE_NOT_FOUND")

    def test_open_envelope_already_opened(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(b"once", key_id=key_id, actor=self._actor())
        engine.open(env.envelope_id, actor=self._actor())
        with self.assertRaises(EtrError) as ctx:
            engine.open(env.envelope_id, actor=self._actor())
        self.assertEqual(ctx.exception.code, "ENVELOPE_NOT_OPENABLE")

    def test_open_bad_format(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.open(
                {"format": "WRONG/v1", "status": "SEALED", "key_id": "x"},
                actor=self._actor(),
            )
        self.assertEqual(ctx.exception.code, "BAD_ENVELOPE")

    def test_open_bad_envelope_type(self) -> None:
        engine = self._engine()
        with self.assertRaises(EtrError) as ctx:
            engine.open(123, actor=self._actor())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "BAD_ENVELOPE")

    def test_determinism(self) -> None:
        """Same key+nonce+plaintext+aad → same ciphertext+tag."""
        key = _AEAD_KEY_V1
        nonce = _AEAD_NONCE_V1
        aad = _AEAD_AAD_V1
        plaintext = _AEAD_PT_V1
        ct1, tag1 = _aead_seal(key, nonce, aad, plaintext)
        ct2, tag2 = _aead_seal(key, nonce, aad, plaintext)
        self.assertEqual(ct1, ct2)
        self.assertEqual(tag1, tag2)

    # --- list and report tests ---------------------------------------------

    def test_list_channels(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        engine.bind_channel("AGENT:a:local", "AGENT:b:local", key_id, self._actor())
        engine.bind_channel("AGENT:b:local", "AGENT:c:local", key_id, self._actor())
        all_ch = engine.list_channels(actor=self._actor())
        self.assertEqual(len(all_ch), 2)
        filtered = engine.list_channels(from_id="AGENT:a:local", actor=self._actor())
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].from_id, "AGENT:a:local")

    def test_list_channels_by_status(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        engine.revoke_channel(ch.channel_id, self._actor())
        active = engine.list_channels(status="ACTIVE", actor=self._actor())
        self.assertEqual(len(active), 0)
        revoked = engine.list_channels(status="REVOKED", actor=self._actor())
        self.assertEqual(len(revoked), 1)

    def test_list_envelopes(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        engine.seal(b"e1", key_id=key_id, message_type="STATUS", actor=self._actor())
        engine.seal(b"e2", key_id=key_id, message_type="COMMAND", actor=self._actor())
        all_env = engine.list_envelopes(actor=self._actor())
        self.assertEqual(len(all_env), 2)
        status_filtered = engine.list_envelopes(status="SEALED", actor=self._actor())
        self.assertEqual(len(status_filtered), 2)

    def test_report(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        engine.bind_channel("AGENT:a:local", "AGENT:b:local", key_id, self._actor())
        engine.seal(b"payload", key_id=key_id, actor=self._actor())
        report = engine.report(actor=self._actor())
        self.assertEqual(report.channels_total, 1)
        self.assertEqual(report.channels_active, 1)
        self.assertEqual(report.channels_revoked, 0)
        self.assertEqual(report.envelopes_total, 1)
        self.assertEqual(report.envelopes_sealed, 1)
        self.assertEqual(report.envelopes_opened, 0)
        self.assertEqual(report.envelopes_auth_failed, 0)

    # --- file transport tests -----------------------------------------------

    def test_seal_file_and_open_file(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        source = Path(self._root) / "secret.txt"
        source.write_bytes(b"file content v1")
        engine.seal_file(source, key_id=key_id, actor=self._actor())
        self.assertTrue((Path(self._root) / "secret.txt.etr").exists())
        payload = engine.open_file(
            str(Path(self._root) / "secret.txt.etr"),
            output=str(Path(self._root) / "decrypted.txt"),
            actor=self._actor(),
        )
        self.assertEqual(payload, b"file content v1")
        self.assertEqual(
            Path(self._root) / "decrypted.txt", Path(self._root) / "decrypted.txt"
        )
        self.assertEqual(
            Path(self._root).joinpath("decrypted.txt").read_bytes(),
            b"file content v1",
        )

    def test_seal_file_custom_output(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        source = Path(self._root) / "data.bin"
        source.write_bytes(b"binary")
        output_path = Path(self._root) / "out.encrypted"
        engine.seal_file(
            source, key_id=key_id, output=str(output_path), actor=self._actor()
        )
        self.assertTrue(output_path.exists())

    # --- EEF event journal integrity ----------------------------------------

    def test_eef_event_chain(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:a:local", "AGENT:b:local", key_id, self._actor()
        )
        env = engine.seal(
            b"chain test", key_id=key_id, message_type="STATUS", actor=self._actor()
        )
        engine.open(env.envelope_id, actor=self._actor())
        engine.revoke_channel(ch.channel_id, self._actor())
        from asc_orchestrator.execution import EEFEventJournal

        journal = EEFEventJournal(self._root)
        events = journal.events()
        event_types = [e.get("event_type") for e in events]
        self.assertIn("ETR_CHANNEL_BOUND", event_types)
        self.assertIn("ETR_SEALED", event_types)
        self.assertIn("ETR_UNSEALED", event_types)
        self.assertIn("ETR_CHANNEL_REVOKED", event_types)

    def test_auth_failed_event_emitted(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        env = engine.seal(b"auth", key_id=key_id, actor=self._actor())
        state, _, _ = engine._load_state(self._actor())
        rec = dict(engine._envelopes(state)[env.envelope_id])
        first = rec["tag"][0]
        rec["tag"] = ("1" if first != "1" else "0") + rec["tag"][1:]
        with self.assertRaises(EtrError):
            engine.open(rec, actor=self._actor())
        from asc_orchestrator.execution import EEFEventJournal

        journal = EEFEventJournal(self._root)
        events = journal.events()
        event_types = [e.get("event_type") for e in events]
        self.assertIn("ETR_AUTH_FAILED", event_types)

    # --- backward-compat smoke ----------------------------------------------

    def test_existing_pese_state_has_transport_state(self) -> None:
        """Fresh state includes transport_state after M018 pese change."""
        from asc_orchestrator.pese import PESEStore

        store = PESEStore(self._root)
        loaded = store.load(actor=self._actor())
        state = loaded.data["envelope"]["state"]
        self.assertIn("transport_state", state)
        self.assertIn("channels", state["transport_state"])
        self.assertIn("envelopes", state["transport_state"])

    def test_bind_and_list_via_engine_directly(self) -> None:
        key_id = self._create_key()
        engine = self._engine()
        ch = engine.bind_channel(
            "AGENT:x:local", "AGENT:y:local", key_id, self._actor()
        )
        self.assertTrue(ch.channel_id.startswith("CHANNEL:"))
        listed = engine.list_channels(actor=self._actor())
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].channel_id, ch.channel_id)
