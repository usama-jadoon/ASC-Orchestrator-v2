# Risks

| Risk | Type | Severity | Evidence | Mitigation | Status |
|---|---|---|---|---|---|
| ACP frames require canonical LF UTF-8 bytes; Windows text-mode writers can translate line endings. | Interoperability | Medium | ACP parser intentionally rejects CRLF; QA confirmed valid byte-mode flow. | Use `ACPMessage.serialize().encode("utf-8")` for persistence/transport adapters. | OPEN |
| Network/shared-filesystem locking semantics are not validated. | Operational | Medium | Local Windows process-locking and fsync tests pass. | Validate on target deployment filesystem before production transport work. | OPEN |
