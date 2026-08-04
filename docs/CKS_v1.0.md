# CRYPTOGRAPHIC KEY SERVICE (CKS v1.0) SPECIFICATION

## Canonical Key Management and Audit-Signing Contract for ASC Orchestrator v2

---

## 1. PURPOSE, SCOPE, AND NORMATIVE CONVENTIONS

### 1.1 Purpose

Cryptographic Key Service (CKS) v1.0 defines the deterministic, stdlib-only key-management and signing contract for ASC Orchestrator v2. CKS generates cryptographically secure symmetric keys, stores them as immutable records, supports rotation and revocation, and provides HMAC-SHA256 signing and constant-time signature verification. The signing ledger — a hash-chained JSON-lines journal mirroring the `AuditJournal` pattern — provides append-only evidence of every signature produced.

CKS is designed to enable production audit signing of PESE, ACP, TBE, MSS, and EEF records, giving operators a deterministic, auditable mechanism to attest file integrity with a verifiable key identity.

CKS SHALL be deterministic: given the same key material and the same payload bytes, signing SHALL produce the same HMAC output. Key generation is the only non-deterministic operation (CSPRNG via `secrets`); all other operations are deterministic and append-only.

### 1.2 Principles

1. **Immutable key records.** A key record, once written, SHALL NEVER be modified. Rotation and revocation are expressed as status-transition entries in a separate hash-chained journal, not by mutating the key record.
2. **PESE is the state authority.** CKS does not write PESE state. CKS writes exclusively under its own canonical layout at `.project-os/KEYS/`.
3. **Deterministic signing.** HMAC-SHA256 is deterministic: the same key material and the same payload always produce the same signature.
4. **Constant-time verification.** Signature verification SHALL use `hmac.compare_digest` to prevent timing attacks.
5. **Append-only evidence.** Every key creation, signing, rotation, and revocation is recorded in a hash-chained journal. Journals are immutable once appended.
6. **Audit signing is a consumer pattern.** CKS defines how to sign any file and produce a signed attestation record. CKS does not modify PESE, ACP, audit, or EEF internals to add signing — it is an additive layer.
7. **No network, HSM, or external services.** All operations are local, stdlib-only (`secrets`, `hmac`, `hashlib`, `json`, `hmac`).

### 1.3 Non-goals and boundaries

CKS v1.0 (this specification) SHALL NOT:

- read, write, or mutate PESE, ACP, TBE, MSS, or EEF state directly;
- provide asymmetric cryptography (RSA, ECDSA, Ed25519), X.509 certificates, or TLS;
- interact with hardware security modules (HSMs), external key vaults, or cloud KMS;
- define agent identity, authentication, authorization, or session tokens;
- store, transport, or manage password credentials, API tokens, or secrets beyond symmetric HMAC keys.

CKS v1.0 is a symmetric key management and signing service. It enables audit signing but does not replace or modify the contracts it signs.

### 1.4 Normative language

The terms **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative. A `key_id` is an ASCII string matching `KEY-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}-[A-Z0-9]{13,}` (UUIDv4 + compact timestamp segment). All times are UTC RFC 3339 timestamps with millisecond precision (`YYYY-MM-DDTHH:mm:ss.sssZ`). All hex-encoded values use lowercase hex. A "key record" is the immutable CKS file documenting a key's creation metadata. A "signing ledger" is the append-only, hash-chained JSONL journal of signatures produced by a specific key.

---

## 2. ARCHITECTURE AND BOUNDARY

### 2.1 Layering

```
+-----------------------------------------------+
| Operators / Agents (CLI, future drivers)       |
+-----------------------------------------------+
| CKS v1.0  KeyStore (this contract)             |
|   - key generation, rotation, revocation       |
|   - HMAC-SHA256 signing and verification       |
|   - hash-chained signing ledger                |
+-----------------------------------------------+
| AuditJournal / PESE / ACP / EEF (consumers)    |
|   - signed artifacts and attestations          |
+-----------------------------------------------+
```

CKS sits between operators and the signing-consumer layer. It writes exclusively to `.project-os/KEYS/`; it never reads PESE state (beyond optionally verifying that an artifact file exists) and never mutates any existing contract.

### 2.2 KeyStore

`KeyStore` is the primary CKS API. It is instantiated per-repository:

```python
KeyStore(root: Path)
```

`KeyStore` operates under `<root>/.project-os/KEYS/` and exposes: `create_key`, `load_key`, `list_keys`, `sign`, `verify`, `rotate`, `revoke`, `status`, and `validate`. All methods that mutate state (create, sign, rotate, revoke) acquire a per-keystore process lock before writing.

`KeyStore` has no dependency on `PESEStore` or any other runtime module. It is independently testable and usable in any project.

---

## 3. KEY TYPES AND RECORDS

### 3.1 Supported key types

| `key_type` | Algorithm | Key size | Signing function |
|---|---|---|---|
| `HMAC-SHA256` | HMAC with SHA-256 | 256 bits (32 bytes) | `hmac.new(key, msg, "sha256")` |

CKS v1.0 supports only `HMAC-SHA256`. The key type is recorded in the key record and verified at signing time. Signing with a key whose `key_type` does not match `HMAC-SHA256` SHALL raise an error.

### 3.2 Immutable key record schema

Each key record is written once and never modified. The file at `keys/<key_id>.json` is a single JSON object:

| Field | Type | Required | Description |
|---|---|---|---|
| `format` | `"CKS/v1.0"` | yes | Canonical format marker |
| `kind` | `"key"` | yes | Object kind |
| `key_id` | string | yes | Unique identifier (`KEY-<uuid4>-<ts13>`) |
| `key_type` | `"HMAC-SHA256"` | yes | Algorithm |
| `purpose` | string \| null | no | Human-readable description of the key's role |
| `created_at` | RFC 3339 | yes | Creation timestamp |
| `created_by` | string | yes | Actor who generated the key |
| `material_hex` | 64-char hex | yes | The 256-bit key material, hex-encoded |
| `fingerprint_hex` | 64-char hex | yes | SHA-256 of `material_hex` (canonical UTF-8 bytes) |
| `file_sha256` | 64-char hex | yes | SHA-256 of the canonical JSON of this record **excluding** the `file_sha256` field |

The key material is stored in plaintext hex. This is appropriate for a local development, auditing, and attestation tool. Production HSM-backed key storage is out of scope.

---

## 4. KEY LIFECYCLE

### 4.1 Key generation

`create_key(writer, purpose=None)` performs:

1. Generate 32 random bytes via `secrets.token_hex(32)` → 64 hex characters.
2. Compute `fingerprint_hex` as SHA-256 of the `material_hex` UTF-8 bytes.
3. Build the canonical key record JSON (excluding `file_sha256`).
4. Compute `file_sha256` as SHA-256 of the canonical JSON.
5. Write the record atomically to `keys/<key_id>.json` (no overwrite).
6. Create the status journal `status/<key_id>.jsonl` with the initial `ACTIVE` entry.

The `key_id` is `KEY-<uuid4>-<compact_ts13>` where `uuid4` is a random UUIDv4 and `compact_ts13` is a 13-character UTC compact timestamp. Key IDs are unique and collision-resistant.

Returns a `KeyRecord` dataclass.

### 4.2 Key rotation

`rotate(writer, old_key_id, reason="ROTATION")` performs:

1. Verify the old key exists and its current status is `ACTIVE`.
2. Append a `ROTATED` status entry to `status/<old_key_id>.jsonl`.
3. Create a new key (same as `create_key`).

Returns the new `KeyRecord`. The old key's `material_hex` is preserved in its immutable key record for historical verification, but the key is no longer valid for new signing operations.

### 4.3 Key revocation

`revoke(writer, key_id, reason="REVOCATION")` performs:

1. Verify the key exists and its current status is `ACTIVE`.
2. Append a `REVOKED` status entry to `status/<key_id>.jsonl`.

Returns the revocation entry. Revoked keys SHALL NOT produce valid signatures.

---

## 5. SIGNING AND VERIFICATION

### 5.1 HMAC-SHA256 signing

`sign(key_id, payload: bytes, actor, purpose=None)` performs:

1. Load the key record for `key_id`; verify its resolved status is `ACTIVE`.
2. Verify `key_type == "HMAC-SHA256"`.
3. Compute `signature_hex = hmac.new(material_hex_bytes, payload, "sha256").hexdigest()` where `material_hex_bytes` is the UTF-8 encoding of `material_hex` (the hex string itself, not the decoded bytes — HMAC key is the hex-encoded string).
4. Compute `payload_sha256 = sha256(payload).hexdigest()`.
5. Append a `signature` entry to `signatures/<key_id>.jsonl` (hash-chained).
6. Return a `SignatureRecord` dataclass.

The `payload` is `bytes`. To sign JSON, serialize to canonical JSON first: `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",",":")).encode("utf-8")`.

**Signing material**: The HMAC key is the UTF-8 encoding of the `material_hex` string (64 ASCII bytes). This means: `hmac.new(material_hex.encode("utf-8"), payload, "sha256")`. The `material_hex` is 64 hex characters representing 256 bits of entropy, but the HMAC key is 64 bytes of ASCII hex text. This is a deliberate choice for deterministic hex-based interoperability and does not reduce the effective key space below 256 bits of entropy.

### 5.2 Signature record schema

Each entry in the signing ledger (`signatures/<key_id>.jsonl`) is:

| Field | Type | Required | Description |
|---|---|---|---|
| `format` | `"CKS/v1.0"` | yes | Canonical format marker |
| `kind` | `"signature"` | yes | Object kind |
| `key_id` | string | yes | Signing key identifier |
| `payload_sha256` | 64-char hex | yes | SHA-256 of the original payload bytes |
| `signature_hex` | 64-char hex | yes | HMAC-SHA256 signature |
| `signed_at` | RFC 3339 | yes | Signing timestamp |
| `actor` | string | yes | Signing actor |
| `purpose` | string \| null | no | Optional context |
| `previous_hash` | 64-char hex \| null | yes | `entry_hash` of the prior line (null for first line) |
| `entry_hash` | 64-char hex | yes | SHA-256 of canonical JSON of this record excluding `entry_hash` |

### 5.3 Verification protocol

`verify(key_id, payload: bytes, signature_hex: str)` performs:

1. Load the key record for `key_id`.
2. Recompute `hmac.new(material_hex.encode("utf-8"), payload, "sha256").hexdigest()`.
3. Compare using `hmac.compare_digest(computed, signature_hex)` — constant-time.
4. Return `True` if and only if the comparison succeeds and the key status is `ACTIVE`.

Verification is read-only and side-effect-free. It does NOT record to the signing ledger.

---

## 6. SIGNING LEDGER

### 6.1 Hash-chained JSONL

The signing ledger at `signatures/<key_id>.jsonl` is an append-only, hash-chained JSONL file. It mirrors the `AuditJournal` pattern (section 2.1 of `docs/ACP_v1.0.md`):

- One JSON object per line, compact canonical encoding (`sort_keys=True`, `separators=(",",":")`).
- Each entry's `previous_hash` equals the `entry_hash` of the preceding line (`null` for the first entry).
- `entry_hash` is SHA-256 of the canonical JSON of all fields except `entry_hash` itself.
- A new entry SHALL NOT be appended if `verify_chain()` returns `False`.
- Appends are protected by an exclusive process lock (`.signatures.<key_id>.lock`).

### 6.2 Chain verification

`verify_chain(key_id) -> bool` iterates every line in `signatures/<key_id>.jsonl` and verifies:

1. `previous_hash` matches the preceding entry's `entry_hash`.
2. `entry_hash` matches the recompute of the record's `entry_hash`.

Returns `True` only if the entire chain is valid.

---

## 7. ON-DISK LAYOUT

### 7.1 Canonical KEYS directory structure

```
.project-os/KEYS/
  keys/
    KEY-<id>.json               # immutable key record (one per key)
  status/
    KEY-<id>.jsonl              # status transition journal (per key, hash-chained)
  signatures/
    KEY-<id>.jsonl              # signing ledger (per key, hash-chained)
  .signatures.<key_id>.lock     # process lock for ledger appends
```

### 7.2 Key record files

Each key record is a standalone JSON file at `keys/<key_id>.json`. The file is written once and never rewritten. The filename IS the key ID (with `:` replaced by `-` for Windows filesystem compatibility).

### 7.3 Status journal files

Status transitions for a key are written to `status/<key_id>.jsonl`. Each line is a status-entry record following the hash-chained format (fields: `format`, `kind: "key-status"`, `key_id`, `status`, `reason`, `actor`, `at`, `previous_hash`, `entry_hash`).

If no status journal exists for a key, its effective status is `ACTIVE` (the default from key creation).

Status values: `ACTIVE`, `ROTATED`, `REVOKED`. A key can transition `ACTIVE → ROTATED` or `ACTIVE → REVOKED` only. `ROTATED` and `REVOKED` are terminal.

### 7.4 Signature ledger files

Signature ledgers are at `signatures/<key_id>.jsonl` (section 6). One ledger per key. A key with no signing ledger is valid but has produced no signatures.

---

## 8. AUDIT-SIGNING INTEGRATION

### 8.1 Signing PESE/ACP/EEF artifacts

Any file in the repository can be signed by CKS. To sign a PESE checkpoint, audit entry, EEF event, or ACP message:

1. Read the file's raw bytes (or compute canonical JSON for structured objects).
2. Call `store.sign(key_id, payload_bytes, actor, purpose="<description>")`.
3. Optionally write a signed attestation record next to the artifact.

CKS does NOT modify the artifact file. Signing is purely additive — it produces a verifiable signature and records it in the signing ledger.

### 8.2 Signed attestation records

A signed attestation is an optional JSON file written alongside an artifact to document that a specific key signed a specific file at a specific time:

```json
{
  "format": "CKS/v1.0",
  "kind": "attestation",
  "key_id": "KEY-...",
  "artifact_path": "path/to/artifact.json",
  "artifact_sha256": "<sha256 of artifact file bytes>",
  "signature_hex": "<HMAC-SHA256 signature>",
  "signed_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local"
}
```

Attestation files are NOT part of the core signing ledger — they are an optional convenience. The canonical signing evidence is always the signing ledger.

---

## 9. KEYS EXTENSION

CKS MAY persist a minimal summary in PESE state under the extension key `org.asc.cks`:

```json
{
  "org.asc.cks": {
    "keys": {
      "KEY-...": {
        "status": "ACTIVE",
        "key_type": "HMAC-SHA256",
        "created_at": "...",
        "purpose": "..."
      }
    }
  }
}
```

This extension is informational only. The authoritative key state is the CKS layout under `.project-os/KEYS/`. CKS SHALL NOT write PESE state — the extension is defined here for future consumers that may wish to cross-reference key status with PESE state.

---

## 10. CLI REFERENCE

CKS exposes seven CLI subcommands:

| Command | Exit 0 outcome | Exit 2 condition |
|---|---|---|
| `key-create` | `key_id=<id>` | Internal error |
| `key-list` | `key_count=N` then `key_id` lines | Internal error |
| `key-sign --key-id <id> --file <path>` | `signature=<hex>` | Key not found or inactive |
| `key-verify --key-id <id> --file <path> --signature <hex>` | `valid=true` or `valid=false` | Key not found |
| `key-rotate --key-id <id>` | `new_key_id=<id>` | Key not found or inactive |
| `key-revoke --key-id <id>` | `key_id=<id> status=REVOKED` | Key not found or not active |
| `key-validate` | `outcome=VALID` | Ledger integrity failure |

All commands accept `--root <path>` (default: `.`) and `--actor` (default: `AGENT:orchestrator:local`).

---

## 11. ERROR HANDLING

CKS errors are `CKSError(RuntimeError)` with a structured `code` and `detail`:

| Code | Meaning |
|---|---|
| `KEY_NOT_FOUND` | `key_id` does not match any key record |
| `KEY_NOT_ACTIVE` | Key status is ROTATED or REVOKED |
| `KEY_TYPE_UNSUPPORTED` | Key type is not HMAC-SHA256 |
| `LEDGER_BROKEN` | Signing ledger chain verification failed |
| `LEDGER_APPEND_FAILED` | Could not append to the signing ledger (lock timeout) |
| `FILE_READ_FAILED` | Could not read the artifact for signing |
| `ATTESTATION_WRITE_FAILED` | Could not write the attestation file |

---

## 12. COMPATIBILITY

- CKS operates exclusively under `.project-os/KEYS/` and does not interfere with PESE, ACP, TBE, MSS, or EEF layouts.
- CKS depends only on Python 3.11+ stdlib: `secrets`, `hmac`, `hashlib`, `json`, `pathlib`, `threading`.
- CKS keys are a natural extension of the PESE `org.asc.cks` extension namespace.
- Existing PESE, ACP, TBE, MSS, and EEF contracts are unaffected by CKS.

---

## 13. IMPLEMENTATION GATES

CKS v1.0 is complete when:

1. `docs/CKS_v1.0.md` is ratified with all required sections (purpose, architecture, key types, lifecycle, signing/verification, ledger, layout, audit integration, CLI reference, error handling, compatibility, implementation gates, and terminal marker).
2. `src/asc_orchestrator/keys.py` implements `KeyStore` and `CKSError` using only stdlib, with no external dependencies.
3. All key lifecycle operations (create, rotate, revoke, validate) persist correct, immutable records.
4. Signing is deterministic and verifiable; constant-time comparison is used.
5. Signing ledger chain verification detects tampering and broken chains.
6. Seven `key-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
7. `tests/test_keys.py` exercises all key operations, signing/verification, rotation, revocation, and ledger integrity.
8. `tests/test_keys_cli.py` exercises the CLI lifecycle.
9. `python -m mypy` passes on `src`.
10. `python -m ruff check src tests scripts` and `ruff format --check` pass.
11. `python scripts/validate_docs.py` passes with CKS spec coverage.
12. `python -m unittest discover -s tests -t .` passes (existing + new CKS tests).

**END OF SPECIFICATION — CKS v1.0**
