# AGENT COMMUNICATION PROTOCOL (ACP v1.0)  
## Official Communication Standard for ASC Orchestrator v2  

---  

### 1. PROTOCOL PURPOSE  
ACP v1.0 provides a deterministic, auditable, and machine-readable communication layer for all agents within the ASC Orchestrator v2 ecosystem. It ensures that every interaction—task assignment, status reporting, evidence exchange, validation, escalation, handoff, and recovery—follows a strictly defined format independent of underlying AI hosts, repositories, or project types. The protocol enables seamless collaboration, clear accountability, and deterministic recovery from interruptions while maintaining a complete audit trail of all agent activities.  

---  

### 2. COMMUNICATION PRINCIPLES  
- **Deterministic**: Given identical inputs and state, the protocol produces identical message sequences.  
- **Auditable**: Every message is immutable, timestamped, and traceable to a specific agent and mission.  
- **Machine-Readable**: Messages are structured for automated parsing without reliance on natural language understanding.  
- **Explicit Ownership**: Each message clearly identifies the sender, recipient (if any), and associated mission or task.  
- **Minimal Redundancy**: Messages contain only essential information; repetition is avoided through correlation and sequencing.  
- **Failure-Tolerant**: The protocol defines clear behaviors for message loss, duplication, reordering, and agent crashes.  
- **Security-Aware**: Message integrity and origin authentication are mandatory; confidentiality is enforced where required.  
- **Version-Compatible**: Backward and forward compatibility are built into the message structure to allow gradual evolution.  
- **Host-Independent**: The protocol does not depend on specific AI host features, APIs, or internal mechanisms.  

---  

### 3. AGENT IDENTITY  
Every agent in the system possesses a globally unique, immutable identifier formatted as:  
`AGENT:<agent-type>:<instance-id>`  
- `<agent-type>`: A concise, lowercase string denoting the agent’s functional role (e.g., `investigator`, `developer`, `validator`, `orchestrator`).  
- `<instance-id>`: A UUIDv4 ensuring uniqueness across all instances of that agent type, generated at agent instantiation and never reused.  

Examples:  
- `AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0`  
- `AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8`  

Agent identity is included in every message header and is cryptographically verifiable via the agent’s registered public key in the company state.  

---  

### 4. MESSAGE TYPES  
ACP defines the following message types. Each message type carries a specific semantic meaning and expected handling behavior.  

**ASSIGNMENT**  
Sent by an orchestrator or delegating agent to assign a bounded task or mission to a recipient agent. Contains the mission specification, objectives, boundaries, and authority limits.  

**STATUS_UPDATE**  
Sent periodically by an executing agent to report current state, progress metrics, resource utilization, and any impediments. Does not imply completion.  

**PROGRESS**  
Sent upon completion of a discrete work unit within a mission (e.g., a step in an execution queue). Includes evidence of completion and updates to the execution state.  

**EVIDENCE**  
Sent to submit verifiable artifacts supporting a claim, validation gate, or mission milestone. Includes references to files, test outputs, logs, or cryptographic hashes.  

**QUESTION**  
Sent when an agent requires clarification or information outside its authority to proceed. Must specify the exact information needed and why it is required.  

**ESCALATION**  
Sent when an agent encounters a blocker that cannot be resolved within its authority, a constitutional violation, or a safety concern. Includes evidence of the issue and the specific assistance requested.  

**WARNING**  
Sent to notify of a potential issue that does not yet block progress but may lead to future problems (e.g., resource depletion, degrading performance).  

**FAILURE**  
Sent when an agent cannot complete an assigned task due to an internal error, violated precondition, or unsolvable problem within its domain. Includes diagnostic information and root cause hypothesis.  

**RECOVERY**  
Sent after a failure or interruption to indicate that the agent has restored state and is ready to resume work. Includes the recovery point and any state corrections applied.  

**VALIDATION**  
Sent by a validation gate agent to report the outcome of a specific validation check (code review, security, QA, etc.). Includes pass/fail status, detailed findings, and required actions if applicable.  

**APPROVAL**  
Sent by an authorized agent (e.g., stakeholder, gate keeper) to authorize a proposed action, mission progression, or decision. References the item being approved.  

**COMPLETION**  
Sent by the assigned agent when all mission objectives have been met, all validation gates passed, and deliverables are ready for handoff.  

**CANCELLATION**  
Sent by an orchestrator or authorized stakeholder to terminate a mission before completion. Includes justification and instructions for partial work preservation.  

**REVIEW**  
Sent to request feedback on a work product (e.g., design document, code change) from a peer or stakeholder. Unlike validation, review is advisory and does not gate progression unless specified by mission rules.  

**DECISION**  
Sent to record a consequential choice made by an agent with authority (e.g., architectural pivot, technology selection). Includes alternatives considered, evidence basis, and expected impact.  

**KNOWLEDGE_UPDATE**  
Sent to submit newly acquired organizational knowledge (lessons learned, best practices, patterns) for inclusion in the knowledge state.  

**MISSION_UPDATE**  
Sent by an orchestrator to modify an active mission’s scope, objectives, priority, or boundaries. Requires acknowledgment from assigned agents.  

**HEARTBEAT**  
Sent periodically by every agent to indicate liveness and readiness. Includes current operational status and resource utilization snapshot.  

---  

### 5. STANDARD MESSAGE STRUCTURE  
Every ACP message consists of a fixed header followed by a type-specific payload. The header is mandatory and identical across all message types.  

**HEADER (8 fields, order fixed):**  
1. `PROTOCOL:ACP/v1.0`  
2. `TYPE:<message-type>` (one of the types listed in Section 4)  
3. `FROM:<sender-agent-id>`  
4. `TO:<recipient-agent-id>` (or `TO:BROADCAST` for announcements, `TO:NONE` for logs)  
5. `MISSION:<mission-id>` (or `MISSION:NONE` if not mission-specific)  
6. `TIMESTAMP:<ISO-8601 UTC>` (precision to milliseconds)  
7. `CORRELATION:<uuidv4>` (unique per message thread; replies retain parent’s correlation)  
8. `PAYLOAD-SHA256:<64-hex-char>` (hash of the payload section only)  

**PAYLOAD**  
- Begins on the line immediately after the header.  
- Format is defined per message type (see Section 6 for required fields).  
- Must be valid UTF-8 text.  
- Length unrestricted but should be concise; large artifacts are referenced by hash rather than embedded.  
- No blank lines between header and payload.  
- Payload may contain multiple lines; internal structure is defined by the message type specification.  

**EXAMPLE MESSAGE FRAME:**  
```
PROTOCOL:ACP/v1.0
TYPE:STATUS_UPDATE
FROM:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
TO:AGENT:orchestrator:887e105-initial-commit
MISSION:mission-abc123
TIMESTAMP:2026-08-03T14:22:00.123Z
CORRELATION:9f1e2d3c-4b5a-6d7e-8f9a-0b1c2d3e4f5a
PAYLOAD-SHA256:a3f5c2e9b1d4f6a8c0e2b7d4f6a8c0e2b7d4f6a8c0e2b7d4f6a8c0e2b7d4f6a8
[Payload lines begin here...]
```  

---  

### 6. REQUIRED METADATA (PER MESSAGE TYPE)  
Each message type must include the following fields in its payload, in the order listed. Omission of a required field renders the message invalid.  

**ASSIGNMENT**  
- `OBJECTIVE:<one-sentence goal>`  
- `BOUNDARIES:<included-work>|<excluded-work>|<repo-boundaries>|<ownership-boundaries>` (pipe-delimited sections)  
- `AUTHORITY:<autonomous-decisions>|<escalation-required>` (pipe-delimited)  
- `DELIVERABLES:<list-of-expected-outputs>`  
- `PRIORITY:<Critical|High|Medium|Low>`  
- `VALUE:<metric>:<baseline>-><target>`  

**STATUS_UPDATE**  
- `STEP:<current-step>/<total-steps>` (or `STEP:N/A` for non-queue work)  
- `PROGRESS-PERCENT:<0-100>`  
- `BLOCKERS:<list-or-NONE>`  
- `RESOURCE-USAGE:<cpu>|<mem>|<disk>` (percentage or absolute)  
- `NEXT-EXPECTED-OUTCOME:<description>`  

**PROGRESS**  
- `COMPLETED-STEP:<step-id-or-description>`  
- `EVIDENCE-REF:<artifact-hash-or-path>`  
- `OUTCOME:<brief-result-statement>`  
- `NEXT-STEP:<step-id-or-description>`  

**EVIDENCE**  
- `TYPE:<test|log|scan|artifact|document>`  
- `REFERENCE:<file-path>|<artifact-id>|<url>`  
- `HASH:<SHA-256-of-referenced-content>`  
- `CONTEXT:<why-this-evidence-matters>`  
- `TIME-RANGE:<start>-><end>` (if temporal)  

**QUESTION**  
- `WHAT-IS-NEEDED:<specific-information-requested>`  
- `WHY-NEEDED:<blocking-reason-or-uncertainty>`  
- `CONTEXT-REFERENCE:<related-evidence-or-mission-data>`  
- `RESPONSE-DEADLINE:<ISO-8601-timestamp>` (optional)  

**ESCALATION**  
- `ISSUE-TYPE:<blocker|violation|safety|resource|dependency>`  
- `DESCRIPTION:<concise-problem-statement>`  
- `EVIDENCE-REF:<hash-or-path-to-supporting-data>`  
- `IMPACT:<effect-on-mission-or-system>`  
- `REQUESTED-ACTION:<specific-assistance-needed>`  
- `TIME-BLOCKED:<duration-or-timestamp>`  

**WARNING**  
- `CONDITION:<observed-state>`  
- `POTENTIAL-IMPACT:<what-might-happen-if-unaddressed>`  
- `SUGGESTED-MITIGATION:<optional-recommendation>`  
- `TIME-OBSERVED:<ISO-8601-timestamp>`  

**FAILURE**  
- `ERROR-CODE:<agent-domain-specific>`  
- `MESSAGE:<human-readable-error>`  
- `STACK-TRACE-or-LOG-REF:<hash-or-path>`  
- `ROOT-CAUSE-HYPOTHESIS:<speculative-or-confirmed>`  
- `RECOVERABLE:<YES|NO>`  
- `SUGGECTED-NEXT-STEP:<retry|escalate|abort|investigate>`  

**RECOVERY**  
- `FAILURE-REF:<correlation-id-of-failure-message>`  
- `RECOVERY-POINT:<last-known-good-state-description>`  
- `STATE-CORRECTIONS:<list-of-changes-made>`  
- `VALIDATION-REF:<evidence-that-state-is-sound>`  
- `READY-TO-RESUME:<YES|NO>`  

**VALIDATION**  
- `GATE:<code-review|security|qa|performance|documentation|contracts|integrity|readiness>`  
- `RESULT:<PASS|FAIL|BLOCKED>`  
- `FINDINGS:<summary-of-issues-or-confirmation>`  
- `EVIDENCE-REF:<hash-or-path-to-detailed-report>`  
- `REQUIRED-ACTIONS:<list-or-NONE>`  
- `RETRY-ALLOWED:<YES|NO>`  

**APPROVAL**  
- `APPROVING-AGENT:<agent-id>`  
- `ITEM-APPROVED:<mission-id>|<artifact-id>|<decision-id>`  
- `APPROVAL-TYPE:<authority|stakeholder|gate>`  
- `CONDITIONS:<list-or-NONE>`  
- `EFFECTIVE-UNTIL:<ISO-8601-timestamp>` (if time-bound)  

**COMPLETION**  
- `ALL-GATES-PASSED:<YES|NO>`  
- `DELIVERABLES-REF:<hash-or-path-to-package>`  
- `OUTCOME-VALUE:<achieved-metric-result>`  
- `HANDOFF-READY:<YES|NO>`  
- `POST-COMPLETION-NOTES:<optional>`  

**CANCELLATION**  
- `CANCELLING-AGENT:<agent-id>`  
- `REASON:<business-priority|constitutional|blocked-impossible|other>`  
- `JUSTIFICATION:<concise-explanation>`  
- `PARTIAL-WORK-STATUS:<preserve|discard|archive>`  
- `NOTIFICATION-REQ:<list-of-stakeholders>`  

**REVIEW**  
- `ITEM-UNDER-REVIEW:<artifact-id>|<design-doc>|<code-change>`  
- `REVIEW-TYPE:<informal|formal|peer|stakeholder>`  
- `FEEDBACK-REQUESTED:<specific-aspects>`  
- `DEADLINE:<ISO-8601-timestamp>` (optional)  
- `CONTEXT:<why-this-review-matters>`  

**DECISION**  
- `DECISION-ID:<uuidv4>`  
- `CHOSEN-OPTION:<selected-alternative>`  
- `ALTERNATIVES-CONSIDERED:<list>`  
- `EVIDENCE-BASIS:<evidence-ref-or-summary>`  
- `EXPECTED-IMPACT:<outcome-projection>`  
- `REVERSIBLE:<YES|NO>`  
- `REVERSIBILITY-CONDITIONS:<description-or-NONE>`  

**KNOWLEDGE_UPDATE**  
- `KNOWLEDGE-TYPE:<pattern|lesson|best-practice|architecture-decision>`  
- `TITLE:<concise-label>`  
- `DESCRIPTION:<detailed-explanation>`  
- `APPLICABLE-SCOPE:<technologies|domains|contexts>`  
- `EVIDENCE-REF:<supporting-artifact-or-experiment>`  
- `ENTRY-TIME:<ISO-8601-timestamp>`  

**MISSION_UPDATE**  
- `FIELD-CHANGED:<objective|scope|priority|boundaries|deliverables>`  
- `OLD-VALUE:<previous-value>`  
- `NEW-VALUE:<updated-value>`  
- `CHANGE-REASON:<justification>`  
- `EFFECTIVE-IMMEDIATELY:<YES|NO>`  
- `ACKNOWLEDGMENT-REQ:<list-of-agent-ids>`  

**HEARTBEAT**  
- `STATUS:<ready|busy|blocked|failed>`  
- `CURRENT-TASK:<task-id-or-NONE>`  
- `RESOURCE-LOAD:<cpu>|<mem>` (percentage)  
- `LAST-HEARTBEAT:<ISO-8601-timestamp>` (self-referential for jitter calc)  
- `NOTES:<optional-operational-context>`  

---  

### 7. COMMUNICATION STATES  
Every message progresses through a defined lifecycle. Agents must track the state of each outgoing and incoming message to handle retransmissions, acknowledgments, and timeouts.  

- **QUEUED**: Message constructed and awaiting transmission (local send buffer).  
- **ACCEPTED**: Message received by recipient agent and passed to its message handler (syntactically valid).  
- **EXECUTING**: Recipient agent is actively processing the message (e.g., performing requested work).  
- **WAITING**: Sender is awaiting a response or acknowledgment (applies to request/response patterns).  
- **BLOCKED**: Message processing halted due to missing dependency, resource contention, or external blocker.  
- **REVIEW**: Message content under evaluation by a third party (e.g., peer review, validation gate).  
- **VALIDATED**: Message has been checked for semantic correctness and compliance with mission rules.  
- **COMPLETED**: Message’s intended action or information transfer has been successfully fulfilled.  
- **CANCELLED**: Sender withdrew the message before completion (e.g., obsolete request).  
- **FAILED**: Message processing encountered an irrecoverable error (invalid payload, security violation).  
- **RECOVERED**: Message was retransmitted after a failure and now accepted.  
- **ARCHIVED**: Message retained for audit purposes after completion or cancellation.  

State transitions are logged in the agent’s local message journal and may be reflected in heartbeat or status updates.  

---  

### 8. HANDOFF PROTOCOL  
When responsibility for a mission, task, or artifact transfers from one agent to another, the following steps must occur:  

1. **PREPARATION**  
   - The sending agent completes all work within its authority.  
   - All relevant evidence is gathered and referenced by hash.  
   - A KNOWLEDGE_UPDATE message may be sent to capture context.  

2. **HANDOFF MESSAGE**  
   - Sent from outgoing to incoming agent.  
   - Type: `MISSION_UPDATE` (if changing assignee) or a dedicated `HANDOFF` subtype of `STATUS_UPDATE`.  
   - Must include:  
     - `WHAT-BEING-HANDOFF:<mission-id>|<artifact-id>|<task-description>`  
     - `CURRENT-STATE:<description-of-progress>`  
     - `EVIDENCE-PACKAGE:<hash-or-location>`  
     - `OUTSTANDING-ITEMS:<list-or-NONE>`  
     - `KNOWN-RISKS:<list-or-NONE>`  
     - `NEXT-STEP-RECOMMENDATION:<action-for-incoming-agent>`  

3. **ACKNOWLEDGMENT**  
   - Incoming agent replies with `ACKNOWLEDGMENT` (a specialized `STATUS_UPDATE` with `STATUS:HANDOFF-ACCEPTED`).  
   - If unable to accept, sends `FAILURE` with reason.  

4. **STATE UPDATE**  
   - Orchestrator updates mission state to reflect new assignee.  
   - Both agents update their local agent state (workload, capabilities).  

5. **CLEANUP**  
   - Outgoing agent releases locks, clears temporary state (unless preserved per mission rules), and stops heartbeating for the handed-off item.  

---  

### 9. CONFLICT RESOLUTION  
Conflicts arise when two or more agents attempt to modify the same state, propose contradictory decisions, or assign incompatible work. ACP resolves conflicts deterministically:  

- **STATE CONFLICT** (e.g., two agents committing changes to same file)  
  - Detected via version vectors in repository state.  
  - Resolution: The agent with higher seniority (based on agent-type precedence: orchestrator > architect > manager > specialist) wins. If equal seniority, the agent with lexicographically smaller ID wins.  
  - The losing agent receives a `FAILURE` message with `ERROR-CODE:STATE_CONFLICT` and must rebase or retry.  

- **DECISION CONFLICT** (e.g., two agents proposing opposing architectural choices)  
  - Detected via competing `DECISION` messages with overlapping scope.  
  - Resolution: The decision with stronger evidence basis (more validation references, higher confidence scores) wins. If tied, the earlier timestamp wins.  
  - The losing agent must record a `KNOWLEDGE_UPDATE` noting the override and align with the winning decision.  

- **AUTHORITY CONFLICT** (e.g., agent attempts autonomous action outside its delegation)  
  - Detected by orchestrator or policy engine via authority rules in mission specification.  
  - Resolution: Immediate `FAILURE` with `ERROR-CODE:AUTHORITY_VIOLATION`, required escalation, and possible agent retraining.  

- **MESSAGE CONFLICT** (e.g., duplicate, out-of-order, or corrupted messages)  
  - Handled by the communication layer: duplicates discarded, out-of-order buffered until predecessors arrive, corrupted messages treated as failed and trigger retransmission request.  

All conflict resolutions are logged as `DECISION` messages with type `CONFLICT_RESOLUTION` for auditability.  

---  

### 10. PARALLEL COMMUNICATION RULES  
To enable safe concurrency, ACP enforces the following:  

- **READ-ONLY BROADCASTS**: Messages with `TO:BROADCAST` and payloads that only convey information (e.g., `STATUS_UPDATE`, `KNOWLEDGE_UPDATE`) may be sent concurrently by any number of agents without coordination.  
- **EXCLUSIVE WRITES**: Any message that intends to modify shared state (e.g., `MISSION_UPDATE`, `DECISION`, `ASSIGNMENT` changing boundaries) must be sent only by the agent with current ownership, as defined in mission or company state.  
- **LOCKING PROTOCOL**: For fine-grained resource contention (e.g., two agents needing to update the same validation gate artifact), agents must first send a `QUESTION` with `TYPE:LOCK-REQUEST`. The orchestrator grants lock via `QUESTION` reply with `TYPE:LOCK-GRANT`. Unlock via `QUESTION` with `TYPE:LOCK-RELEASE`.  
- **IDempotENCY**: All message processing must be idempotent; receiving the same message twice must not change state beyond the first receipt.  
- **NON-BLOCKING SENDS**: Agents must not wait for acknowledgment before proceeding with other work, unless the message type explicitly requires synchronous response (e.g., `QUESTION` awaiting answer).  
- **THROTTLING**: Agents must limit message frequency to prevent flooding; maximum rates are defined in agent type profiles (e.g., no more than 1 `STATUS_UPDATE` per 30 seconds per mission).  

---  

### 11. OWNERSHIP TRANSFER  
Ownership of mission-specific resources (execution queue, validation gate artifacts, deliverables) transfers only via explicit handoff (Section 8). Ownership of company-level resources (e.g., agent registry, policy definitions) follows constitutional amendment procedures. Transfer rules:  

- An agent may only relinquish ownership after confirming the recipient has acknowledged receipt and capability to assume responsibility.  
- Ownership cannot be transferred mid-validation gate; the gate must complete or be formally blocked.  
- The orchestrator retains ultimate ownership of mission state and may revoke or reassign at any time for constitutional or safety reasons, issuing a `MISSION_UPDATE` with reason.  
- Upon ownership transfer, all associated locks are released by the sender and re-acquired by the receiver as needed.  

---  

### 12. AGENT AUTHORITY VERIFICATION  
Before executing an autonomous action, an agent must verify that the action falls within its delegated authority:  

1. Consult the mission specification’s `AUTHORITY` field (from the most recent `ASSIGNMENT` or `MISSION_UPDATE`).  
2. Check company policies for domain-specific constraints (e.g., security prohibitions).  
3. If uncertain, send a `QUESTION` to the orchestrator requesting clarification—**do not proceed on assumption**.  
4. Actions taken without verifiable authority are violations and trigger immediate `FAILURE` with `ERROR-CODE:AUTHORITY_VIOLATION`.  

The orchestrator performs periodic audits of agent actions against delegated authority using mission logs.  

---  

### 13. VALIDATION MESSAGES  
Validation messages follow the `VALIDATION` type structure but are further specialized by gate. Each gate agent must:  

- Receive input via the mission’s execution queue or explicit handoff.  
- Execute its validation logic against the defined criteria.  
- Produce a `VALIDATION` message with:  
  - Exact gate name matching the mission specification.  
  - Result: `PASS` only if *all* criteria satisfied; `FAIL` if any criterion unmet; `BLOCKED` if external dependency prevents completion.  
  - Findings must be specific, actionable, and traceable to evidence.  
  - If `FAIL`, include `REQUIRED-ACTIONS` that, if addressed, would convert the result to `PASS`.  
  - Evidence reference must point to a reproducible artifact (log file, test report, scan output).  

Validation messages are immutable after sending; a gate may not change its result without a new mission authorizing re-validation (treated as a new validation instance).  

---  

### 14. EVIDENCE MESSAGES  
Evidence must satisfy these rules to be acceptable:  

- **IMMUTABILITY**: Referenced artifact must not change after evidence submission (enforced via hash verification).  
- **TRACEABILITY**: Evidence must reference the exact mission step, validation gate, or decision it supports.  
- **TIME-BOUNDING**: For temporal evidence (logs, metrics), include start and end timestamps.  
- **CONTEXT**: Explain why this evidence proves the claim; raw data alone is insufficient.  
- **MINIMAL SUFFICIENCY**: Submit only the evidence necessary to establish the fact; avoid extraneous data.  
- **FORMAT**: Prefer machine-readable formats (JSON, XML, TAP, JUnit) for automated validation; free-form text only for human-readable summaries.  

Evidence messages are treated as `VALIDATION` payloads when submitted for gate completion, or as standalone `EVIDENCE` messages when supporting claims in `QUESTION`, `DECISION`, or `PROGRESS` messages.  

---  

### 15. FAILURE MESSAGES  
Failure messages must enable root cause analysis and informed retry decisions. In addition to the required fields in Section 6:  

- `ERROR-CODE` must follow the format: `<domain>:<subdomain>:<severity>`  
  - Example: `BUILD:COMPILE:HIGH`, `NETWORK:TIMEOUT:MEDIUM`, `SECURITY:CRETENTIAL-LEAK:CRITICAL`  
- `STACK-TRACE-or-LOG-REF` must point to a retrievable artifact; if the failure is environmental (e.g., disk full), reference the system state snapshot.  
- `ROOT-CAUSE-HYPOTHESIS` must be falsifiable and based on evidence, not speculation.  
- `RECOVERABLE:NO` indicates the mission cannot continue without external intervention (e.g., missing credentials, legal block).  
- `SUGGECTED-NEXT-STEP` must be one of: `RETRY` (with backoff), `ESCALATE` (to human or higher authority), `ABORT` (mission impossible), `INVESTIGATE` (requires diagnostic work).  

After sending a `FAILURE`, the agent must transition to `STATUS:FAILED` in its heartbeat and await instructions; it must not proceed autonomously.  

---  

### 16. RECOVERY MESSAGES  
Recovery messages enable resumption after failure or interruption. Key requirements:  

- Must reference the specific `FAILURE` message being addressed via `FAILURE-REF`.  
- `RECOVERY-POINT` must be a verifiable state (e.g., git commit hash, last checkpoint ID, completed validation gate).  
- `STATE-CORRECTIONS` must list exact changes made (e.g., “removed corrupted lock file”, “reset retry counter to zero”).  
- `VALIDATION-REF` must prove the system is now in a consistent state (e.g., clean build, passing smoke test).  
- `READY-TO-RESUME` must be `YES` only if the agent confirms it can safely continue from the recovery point.  

Upon accepting a recovery message, the receiving agent must:  
- Validate the referenced recovery point exists and is accessible.  
- Apply the stated corrections (if any) to its local state.  
- Verify readiness via the provided evidence or local checks.  
- Transition to `STATUS:READY` and await the next assigned task or execution queue continuation.  

---  

### 17. ESCALATION MESSAGES  
Escalation is the formal mechanism for an agent to request help beyond its authority. Proper escalation includes:  

- Clear `ISSUE-TYPE` from the enumerated list.  
- `DESCRIPTION` that a technically competent peer can understand without additional context.  
- `EVIDENCE-REF` that substantiates the claim (e.g., log excerpt, metric trend, policy violation).  
- `IMPACT` quantified where possible (e.g., “blocks 3 mission steps”, “exposes PII to logs”).  
- `REQUESTED-ACTION` that is specific, actionable, and within the responder’s authority (e.g., “approve scope change”, “provide access to system X”, “make architectural decision Y”).  
- `TIME-BLOCKED` showing how long the agent has been stuck (helps prioritize).  

Agents must attempt self-resolution for a bounded time (defined in agent type profile, typically 15–30 minutes for non-safety issues) before escalating, unless the issue is safety-related or constitutional.  

Escalation messages are routed via the orchestrator unless the `TO` field specifies a known expert agent (e.g., `TO:AGENT:security-lead:...`). The orchestrator logs all escalations and may auto-assign based on workload and expertise.  

---  

### 18. REVIEW MESSAGES  
Review messages request feedback but do not block mission progression unless the mission specification mandates it. Key aspects:  

- `ITEM-UNDER-REVIEW` must be unambiguously identifiable (e.g., file path with version, artifact ID).  
- `REVIEW-TYPE` sets expectations: `informal` (quick opinion), `formal` (detailed critique with checklist), `peer` (technical correctness), `stakeholder` (business alignment).  
- `FEEDBACK-REQUESTED` should list specific aspects (e.g., “check for error handling”, “verify performance numbers”, “assess clarity for end users”).  
- If a deadline is provided, the responder must acknowledge receipt and indicate whether they can meet it.  
- Review responses are sent as `REVIEW` messages with `TYPE:REVIEW-RESPONSE` in the payload or as comments in a threaded discussion system; they must reference the original review’s correlation ID.  

Reviews do not alter state unless the reviewer has explicit authority (e.g., a gate keeper sending an `APPROVAL` after review).  

---  

### 19. SECURITY REQUIREMENTS  
ACP mandates the following security mechanisms:  

- **AUTHENTICATION**: Every message must be verifiably signed by the sender’s private key. The signature is computed over the concatenation of header and payload (excluding the signature field itself). The corresponding public key is stored in the agent registry in company state.  
- **INTEGRITY**: The `PAYLOAD-SHA256` header field prevents tampering in transit; any mismatch results in message rejection and a `FAILURE` with `ERROR-CODE:MESSAGE_INTEGRITY`.  
- **CONFIDENTIALITY**: For messages containing sensitive data (e.g., credentials, proprietary algorithms), the payload must be encrypted using a session key established via a pre-shared key exchange or the company’s vault service. The header indicates encryption via `ENCRYPTED:YES` and includes a key identifier.  
- **NON-REPUDIATION**: Signed messages provide proof of origin; agents cannot deny sending a message that validates against their registered key.  
- **REPLAY PROTECTION**: Each message includes a timestamp and a nonce (the `CORRELATION` field). Agents must reject messages with timestamps outside a synchronized window (e.g., ±5 minutes) or duplicate correlation IDs within a session.  
- **MINIMUM PRIVILEGE**: Agents only decrypt and process messages for which they are the intended recipient (`TO` matches their ID) or that are broadcasts intended for their role (determined via agent-type subscription lists).  
- **AUDIT LOGGING**: All message transfers are logged in an immutable audit trail (separate from PESE) with sufficient detail for forensic reconstruction.  

---  

### 20. AUDIT REQUIREMENTS  
ACP supports comprehensive auditing through:  

- **IMMUTABLE MESSAGE LOG**: Every sent and received message is appended to a write-ahead log in `.project-os/AUDIT/` with timestamp, direction (IN/OUT), full message content, and verification status.  
- **CORRELATION CHAINS**: Messages sharing a `CORRELATION` ID form a traceable thread from initial request through responses, evidence, and completion.  
- **STATE TRANSITION LOG**: Changes to mission, execution, agent, and validation state are logged as `DECISION`-like entries with before/after state hashes.  
- **ACCESS LOG**: Every read or write to PESE state is logged with agent ID, timestamp, and operation type (only for debugging and forensics; may be disabled in production).  
- **COMPLIANCE REPORTING**: On demand, the system can generate a report showing:  
  - All messages related to a mission or agent.  
  - Validation gate outcomes with evidence.  
  - Escalation history and resolutions.  
  - Handoffs and ownership transfers.  
  - Deviations from expected protocols (warnings, failures).  

All audit entries are tamper-evident via hash chaining and periodic cryptographic signing by a designated auditor agent.  

---  

### 21. VERSION COMPATIBILITY  
ACP v1.0 uses a extensible but strictly versioned approach:  

- **HEADER VERSION**: The `PROTOCOL` field declares the exact version (e.g., `ACP/v1.0`).  
- **FORWARD COMPATIBILITY**: Agents receiving a message with a higher minor version (e.g., `ACP/v1.1` when implementing v1.0) must:  
  - Process the message if they can safely ignore the unknown additions (based on field-specific rules).  
  - If the message contains critical incompatibilities (e.g., new mandatory header field), reject with `FAILURE` and `ERROR-CODE:PROTOCOL_VERSION_MISMATCH`.  
- **BACKWARD COMPATIBILITY**: Agents must accept and correctly process any message with the same major version (e.g., v1.0 agent must handle `ACP/v1.0` through `ACP/v1.9`).  
- **PAYLOAD VERSIONING**: If a message type’s payload structure changes, the new version is indicated by a `VERSION` field in the payload (e.g., `VERSION:1.2`). Older agents process up to their supported version and treat higher versions as unsupported.  
- **DEPRECATION**: Fields marked deprecated in a minor version are supported for two additional minor versions before removal.  
- **VERSION NEGOTIATION**: During agent initialization (heartbeat handshake), agents exchange supported version ranges and agree on a common version for subsequent messages.  

---  

### 22. AI HOST COMPATIBILITY  
ACP is designed to work with any AI host that can:  

- Generate and parse plain text messages adhering to the header/payload structure.  
- Perform cryptographic signing and verification (using standard libraries like OpenSSL, libsodium, or platform APIs).  
- Maintain persistent storage for PESE and message journals.  
- Execute operating system processes to run validation tools, compilers, test suites, etc.  
- Communicate over standard network protocols (HTTP, WebSockets, or message queues) if remote agents are used.  

The protocol does not require:  
- Proprietary APIs from specific AI vendors.  
- Access to the AI host’s internal state, token streams, or model weights.  
- Particular programming languages or runtime environments.  
- Cloud-specific services; it functions equally well in local, containerized, or air-gapped environments.  

---  

### 23. FAILURE MODES  
ACP defines specific failure modes and associated responses:  

- **MISSING HEADER FIELD**: Message rejected; sender receives `NACK` via escalation or direct `FAILURE` with `ERROR-CODE:HEADER_INCOMPLETE`.  
- **INVALID PAYLOAD HASH**: Message treated as corrupted; receiver requests retransmission via `QUESTION` with `TYPE:MESSAGE_RESEND`.  
- **TIMESTAMP OUT OF WINDOW**: Message rejected as potentially replayed; logged as security event.  
- **UNSUPPORTED PROTOCOL VERSION**: Sender notified via `FAILURE` with `ERROR-CODE:PROTOCOL_VERSION_MISMATCH`; must upgrade or negotiate.  
- **UNAUTHORIZED SENDER**: Message rejected if signature does not match registered key; treated as intrusion attempt.  
- **REPLY TIMEOUT**: For messages expecting a response (e.g., `QUESTION`), if no reply within agent-type-specified timeout, sender treats as failure and may escalate.  
- **AGENT OFFLINE**: Heartbeat absence >2× interval triggers `AGENT_UNRESPONSIVE` escalation to orchestrator.  
- **MESSAGE LOSS**: Detected via gaps in correlation sequences or missing acknowledgments; recovered via retransmission requests after timeout.  
- **BUFFER OVERFLOW**: If an agent’s inbound queue exceeds capacity, it sends `WARNING` with `CONDITION:QUEUE_FULL` and begins dropping lowest-priority messages (e.g., `STATUS_UPDATE` before `ESCALATION`).  
- **DEADLOCK**: Detected via circular wait in resource requests; resolved by preemption (the agent with least progress aborts and sends `FAILURE`).  
- **CORRUPTED STATE DETECTION**: If PESE state fails integrity checks during message processing, agent sends `ESCALATION` with `ISSUE-TYPE:STATE_CORRUPTION` and halts autonomous work.  

---  

### 24. PROTOCOL LIFECYCLE  
ACP governs communication from agent inception to termination:  

1. **INITIALIZATION**  
   - Agent reads its identity from environment or secure store.  
   - Loads company state to verify validity and fetch public keys of known agents.  
   - Sends `HEARTBEAT` with `STATUS:INITIALIZING` to announce presence.  
   - Awaits orchestrator acknowledgment or mission assignment.  

2. **REGISTRATION**  
   - Upon receiving `HEARTBEAT` acknowledgment or direct assignment, agent updates its local agent state to `STATUS:REGISTERED`.  
   - Subscribes to relevant message types (e.g., all missions of its type, broadcast announcements).  

3. **ACTIVE OPERATION**  
   - Sends and receives messages per mission flow.  
   - Updates heartbeat at least every 30 seconds (configurable per agent type).  
   - Handles inbound messages according to their type and current state.  

4. **GRACEFUL TERMINATION**  
   - When no further work is assigned, agent sends `HEARTBEAT` with `STATUS:TERMINATING`.  
   - Completes any in-flight message processing and flushes journals.  
   - Sends final `STATUS_UPDATE` with `STATUS:TERMINATED`.  
   - Deregisters from message queues and releases resources.  

5. **FORCED TERMINATION**  
   - On detecting prolonged heartbeat absence (>5 minutes), orchestrator assumes failure.  
   - Initiates recovery protocol: checkpoints state, attempts to contact agent via alternate channels, reassigns work if unresponsive.  
   - Logs termination event as `DECISION` with type `AGENT_FAILURE`.  

---  

### 25. COMPLETE EXAMPLES  

#### EXAMPLE 1: REPOSITORY INVESTIGATION  
**Context**: Orchestrator assigns investigator to repo root analysis.  

1. **ASSIGNMENT** (Orchestrator → Investigator)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:ASSIGNMENT
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0
   TIMESTAMP:2026-08-03T09:00:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   OBJECTIVE:Determine project type and confidence for ASC Orchestrator v2 repository
   BOUNDARIES:Included Work:Read .git, scan manifests, assess directory structure|Excluded Work:Modify any files, run build tools|Repo Boundaries:https://github.com/example/asco@feature/milestone-1-foundation|Ownership Boundaries:Repository state only
   AUTHORITY:Autonomous:File inspection, manifest parsing, directory traversal|Escalation-Required:Any modification to repo, external network calls
   DELIVERABLES:Investigation report, confidence scores, recommended domain pack
   PRIORITY:Medium
   VALUE:Project classification accuracy:baseline unknown->target ≥0.9 confidence
   [End of headers]
   ```
2. **STATUS_UPDATE** (Investigator → Orchestrator, every 5 mins)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:STATUS_UPDATE
   FROM:AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T09:05:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   STEP:2/5
   PROGRESS-PERCENT:40
   BLOCKERS:NONE
   RESOURCE-USAGE:5|10|2
   NEXT-EXPECTED-OUTCOME:Manifest analysis complete
   [End of headers]
   ```
3. **EVIDENCE** (Investigator → Orchestrator, upon finding manifest)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:EVIDENCE
   FROM:AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T09:12:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   TYPE:manifest
   REFERENCE:repo/package.json
   HASH:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
   CONTEXT:Defines Node.js project with dependencies indicating CLI tool
   TIME-RANGE:N/A
   [End of headers]
   ```
4. **PROGRESS** (Investigator → Orchestrator, after completing scan)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:PROGRESS
   FROM:AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T09:30:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   COMPLETED-STEP:manifest-scan
   EVIDENCE-REF:repo/manifest-summary.json
   OUTCOME:Found package.json (Node.js), Cargo.toml absent, go.mod absent
   NEXT-STEP:framework-detection
   [End of headers]
   ```
5. **VALIDATION** (Validator agent → Orchestrator, after cross-check)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:VALIDATION
   FROM:AGENT:validator:sec-validator-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T09:45:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   GATE:integrity
   RESULT:PASS
   FINDINGS:All manifests consistent, no conflicting language signals
   EVIDENCE-REF:repo/validation-log.txt
   REQUIRED-ACTIONS:NONE
   RETRY-ALLOWED:NONE
   [End of headers]
   ```
6. **COMPLETION** (Investigator → Orchestrator, final)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:COMPLETION
   FROM:AGENT:investigator:3f8d1a2e-b4c9-4f1a-b2d3-e5f6a7b8c9d0
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T10:00:00.000Z
   CORRELATION:inv-001
   PAYLOAD-SHA256:...
   ALL-GATES-PASSED:YES
   DELIVERABLES-REF:repo/investigation-report.pdf
   OUTCOME-VALUE:Classification confidence:0.92 (Node.js CLI tool)
   HANDOFF-READY:YES
   POST-COMPLETION-NOTES:Recommend loading cli-tool department pack
   [End of headers]
   ```  

#### EXAMPLE 2: BUG FIX (INTERRUPTED AND RECOVERED)  
**Context**: Developer assigned to fix null pointer; crash occurs mid-work.  

1. **ASSIGNMENT** (Orchestrator → Developer)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:ASSIGNMENT
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TIMESTAMP:2026-08-03T11:00:00.000Z
   CORRELATION:bugfix-42
   PAYLOAD-SHA256:...
   OBJECTIVE:Fix null pointer exception in user profile upload handler
   BOUNDARIES:Included Work:src/service/avatar/AvatarService.java, src/api/users/AvatarController.java|Excluded Work:UI changes, database schema|Repo Boundaries:https://github.com/example/user-service@main|Ownership Boundaries:User service API and avatar service
   AUTHORITY:Autonomous:Null checks, input validation, unit tests|Escalation-Required:API contract changes, auth middleware changes
   DELIVERABLES:Fixed source code, unit tests, release notes
   PRIORITY:High
   VALUE:Profile upload 5xx error rate:baseline 2%->target <0.1%
   [End of headers]
   ```
2. **STATUS_UPDATE** (Developer → Orchestrator)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:STATUS_UPDATE
   FROM:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:15:00.000Z
   CORRELATION:bugfix-42
   PAYLOAD-SHA256:...
   STEP:3/7
   PROGRESS-PERCENT:42
   BLOCKERS:NONE
   RESOURCE-USAGE:20|15|5
   NEXT-EXPECTED-OUTCOME:Writing fix for AvatarService.java
   [End of headers]
   ```
3. **PROGRESS** (Developer → Orchestrator, after locating bug)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:PROGRESS
   FROM:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:20:00.000Z
   CORRELATION:bugfix-42
   PAYLOAD-SHA256:...
   COMPLETED-STEP:bug-location
   EVIDENCE-REF:src/service/avatar/AvatarService.java:142
   OUTCOME:Null pointer at avatarContext.getUser() without null check
   NEXT-STEP:implement-fix
   [End of headers]
   ```
4. **HEARTBEAT** (Developer → Orchestrator, last before crash)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:HEARTBEAT
   FROM:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:25:00.000Z
   CORRELATION:hb-001
   PAYLOAD-SHA256:...
   STATUS:busy
   CURRENT-TASK:implement-fix
   RESOURCE-LOAD:45|30
   LAST-HEARTBEAT:2026-08-03T11:25:00.000Z
   NOTES:Editing AvatarService.java
   [End of headers]
   ```
   *(Crash occurs; no further heartbeats)*  
5. **ESCALATION** (Orchestrator → Orchestrator, via monitor detecting missed heartbeats)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:ESCALATION
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:35:00.000Z
   CORRELATION:esc-001
   PAYLOAD-SHA256:...
   ISSUE-TYPE:AGENT_UNRESPONSIVE
   DESCRIPTION:Developer agent a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8 missed 3 consecutive heartbeats
   EVIDENCE-REF:project-os/AGENTS/a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8/HEARTBEAT (last timestamp 11:25:00)
   IMPACT:Work on bugfix-42 stalled; potential data loss if unsaved edits
   REQUESTED-ACTION:Determine agent state, recover work if possible, reassign if necessary
   TIME-BLOCKED:10 minutes
   [End of headers]
   ```
6. **RECOVERY ATTEMPT** (Orchestrator → Recovery Agent)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:QUESTION
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:recovery-agent:rec-001
   TIMESTAMP:2026-08-03T11:36:00.000Z
   CORRELATION:rec-001
   PAYLOAD-SHA256:...
   WHAT-IS-NEEDED:Status of agent a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8 and workspace
   WHY-NEEDED:Potential crash requiring state recovery
   CONTEXT-REFERENCE:Mission bugfix-42, last known step implement-fix
   RESPONSE-DEADLINE:2026-08-03T11:41:00.000Z
   [End of headers]
   ```
7. **QUESTION RESPONSE** (Recovery Agent → Orchestrator)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:QUESTION
   FROM:AGENT:recovery-agent:rec-001
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:38:00.000Z
   CORRELATION:rec-001
   PAYLOAD-SHA256:...
   WHAT-IS-NEEDED:None (providing update)
   WHY-NEEDED:N/A
   CONTEXT-REFERENCE:Recovery check
   [Payload begins:]
   AGENT-STATUS:CRASHED (process exited with signal 11)
   WORKSPACE-STATE:Partial edit in AvatarService.java (unsaved)
   LAST-KNOWN-GOOD:Commit main:a1b2c3d4 (before edit)
   RECOVERY-POINT:Git stash at timestamp 11:24:00
   STATE-CORRECTIONS:Stash applied, working tree clean at commit a1b2c3d4
   VALIDATION-REF:build-success.log (from stash state)
   READY-TO-RESUME:YES
   [End of payload]
   ```
8. **MISSION_UPDATE** (Orchestrator → Developer, reassigning after recovery)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:MISSION_UPDATE
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TIMESTAMP:2026-08-03T11:42:00.000Z
   CORRELATION:bugfix-42
   PAYLOAD-SHA256:...
   FIELD-CHANGED:None (same mission)
   OLD-VALUE:N/A
   NEW-VALUE:N/A
   CHANGE-REASON:Agent recovered from crash; resuming from last known good point
   EFFECTIVE-IMMEDIATELY:YES
   ACKNOWLEDGMENT-REQ:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   [End of headers]
   ```
9. **STATUS_UPDATE** (Developer → Orchestrator, after recovery)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:STATUS_UPDATE
   FROM:AGENT:developer:a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T11:45:00.000Z
   CORRELATION:bugfix-42
   PAYLOAD-SHA256:...
   STEP:3/7
   PROGRESS-PERCENT:42
   BLOCKERS:NONE
   RESOURCE-USAGE:5|5|2
   NEXT-EXPECTED-OUTCOME:Re-applying fix from recovery point
   [End of headers]
   ```  
   *(Work proceeds to completion; omitted further steps for brevity)*  

#### EXAMPLE 3: RELEASE PREPARATION  
**Context**: Release manager orchestrates v2.1.0 release.  

1. **ASSIGNMENT** (Orchestrator → Release Manager)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:ASSIGNMENT
   FROM:AGENT:orchestrator:887e105-initial-commit
   TO:AGENT:release-manager:oscar-release-01
   TIMESTAMP:2026-08-03T13:00:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   OBJECTIVE:Prepare v2.1.0 release for payment processing service
   BOUNDARIES:Included Work:Version bump, changelog, artifact build, security scan, staging deploy, prod deploy|Excluded Work:Feature dev for v2.2, infra changes|Repo Boundaries:https://github.com/example/payment-service@release/v2.1.0|Ownership Boundaries:Release artifacts, deployment pipelines
   AUTHORITY:Autonomous:Version number (semver), release timing within window, artifact tagging, canary percentage|Escalation-Required:Release outside window, major version without product approval, deploy without security signoff
   DELIVERABLES:Release notes, Docker image, Helm chart, test reports, rollback plan
   PRIORITY:High
   VALUE:Fraud false positive rate:baseline 15%->target 10.5%
   [End of headers]
   ```
2. **STATUS_UPDATE** (Release Manager → Orchestrator, pre-build)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:STATUS_UPDATE
   FROM:AGENT:release-manager:oscar-release-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T13:10:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   STEP:1/8
   PROGRESS-PERCENT:12
   BLOCKERS:NONE
   RESOURCE-USAGE:10|20|50
   NEXT-EXPECTED-OUTCOME:Version bump and changelog generation
   [End of headers]
   ```
3. **PROGRESS** (Release Manager → Orchestrator, after build success)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:PROGRESS
   FROM:AGENT:release-manager:oscar-release-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T13:45:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   COMPLETED-STEP:build-success
   EVIDENCE-REF:docker-image-sha256:abc123..., helm-chart-sha256:def456...
   OUTCOME:Docker image and Helm chart built successfully, no errors
   NEXT-STEP:security-scan
   [End of headers]
   ```
4. **VALIDATION** (Security Agent → Orchestrator, after scan)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:VALIDATION
   FROM:AGENT:security-agent:sec-scan-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T14:20:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   GATE:security
   RESULT:PASS
   FINDINGS:No new critical/high vulnerabilities; license check clean
   EVIDENCE-REF:artifacts/security-scan-v2.1.0.json
   REQUIRED-ACTIONS:NONE
   RETRY-ALLOWED:NO
   [End of headers]
   ```
5. **VALIDATION** (QA Agent → Orchestrator, after staging tests)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:VALIDATION
   FROM:AGENT:qa-agent:qa-staging-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T14:50:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   GATE:qa
   RESULT:PASS
   FINDINGS:All integration and contract tests passed in staging
   EVIDENCE-REF:artifacts/test-summary-v2.1.0.xml
   REQUIRED-ACTIONS:NONE
   RETRY-ALLOWED:NO
   [End of headers]
   ```
6. **APPROVAL** (Product Manager → Release Manager, post-validation)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:APPROVAL
   FROM:AGENT:product-manager:nancy-pm-01
   TO:AGENT:release-manager:oscar-release-01
   TIMESTAMP:2026-08-03T15:00:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   APPROVING-AGENT:AGENT:product-manager:nancy-pm-01
   ITEM-APPROVED:MISSION:release-v2.1.0
   APPROVAL-TYPE:stakeholder
   CONDITIONS:None
   EFFECTIVE-UNTIL:NONE
   [End of headers]
   ```
7. **PROGRESS** (Release Manager → Orchestrator, after prod deploy)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:PROGRESS
   FROM:AGENT:release-manager:oscar-release-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T16:30:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   COMPLETED-STEP:production-deploy
   EVIDENCE-REF:deployment-log-v2.1.0.txt
   OUTCOMPACT:v2.1.0 promoted to 100% traffic, health checks green
   NEXT-STEP:post-deploy-validation
   [End of headers]
   ```
8. **VALIDATION** (Monitoring Agent → Orchestrator, post-deploy)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:VALIDATION
   FROM:AGENT:monitoring-agent:mon-prod-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T17:30:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   GATE:readiness
   RESULT:PASS
   FINDINGS:Error rate <0.1%, latency p95 <110% baseline, new fraud feature active
   EVIDENCE-REF:metrics/post-deploy-v2.1.0.json
   REQUIRED-ACTIONS:NONE
   RETRY-ALLOWED:NO
   [End of headers]
   ```
9. **COMPLETION** (Release Manager → Orchestrator)  
   ```
   PROTOCOL:ACP/v1.0
   TYPE:COMPLETION
   FROM:AGENT:release-manager:oscar-release-01
   TO:AGENT:orchestrator:887e105-initial-commit
   TIMESTAMP:2026-08-03T18:00:00.000Z
   CORRELATION:release-v2.1.0
   PAYLOAD-SHA256:...
   ALL-GATES-PASSED:YES
   DELIVERABLES-REF:artifacts/release-package-v2.1.0.tar.gz
   OUTCOME-VALUE:Fraud false positive rate measured 10.2% (target met)
   HANDOFF-READY:YES
   POST-COMPLETION-NOTES:Release successful; monitor for 48h
   [End of headers]
   ```  

---  

*This specification is the permanent, immutable standard for all agent communication within ASC Orchestrator v2. All future agents, missions, and implementations MUST conform to ACP v1.0. No deviations are permitted without formal amendment through the constitutional governance process.*  

*End of Specification*