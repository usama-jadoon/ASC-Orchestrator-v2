# AGENT CAPABILITY REGISTRY (ACR v1.0) SPECIFICATION

## 1. OVERVIEW
The Agent Capability Registry (ACR v1.0) is the authoritative source defining all specialist agent types within the ASC Orchestrator v2 ecosystem. It specifies the identity, purpose, responsibilities, authorities, skills, tools, boundaries, and contractual obligations for every agent. The registry enables:
- Dynamic agent spawning with precise capability boundaries
- Clear delegation of work via ACP v1.0
- Autonomous operation within defined limits
- Interoperability between agents of different types
- Compliance validation against constitutional principles
- Performance measurement and optimization

The registry is stored as part of company state in `.project-os/COMPANY/DEPARTMENTS/` with one file per agent type (e.g., `investigator.yaml`, `developer.yaml`). While the physical format may evolve, the logical structure defined herein is permanent.

## 2. AGENT ENTRY STRUCTURE
Each agent type is defined by a complete entry containing the following sections. All fields are mandatory unless explicitly marked optional. Entries must validate against the ACR v1.0 schema.

### 2.1 IDENTITY
- **agent-id**: Unique, lowercase, kebab-case string identifying the agent type (e.g., `investigator`, `developer`, `security-auditor`). Must match the `agent-type` component in ACP agent identifiers (`AGENT:<agent-type>:<instance-id>`).
- **version**: Semantic version string (MAJOR.MINOR.PATCH) of the agent capability definition. Incremented for any change to the entry.
- **display-name**: Human-readable name for documentation and UI (e.g., "Repository Investigator").
- **description**: Concise (1-2 sentence) summary of the agent’s primary function.

### 2.2 PURPOSE
- **mission-types**: List of mission types (from MSS v1.0) this agent is authorized to execute (e.g., `[Investigation, Development, Security]`).
- **value-streams**: Business areas where this agent delivers value (e.g., `[code-quality, security, release-velocity]`).
- **strategic-objectives**: Company objectives this agent supports (e.g., `["reduce time-to-market", "increase system reliability"]`).

### 2.3 RESPONSIBILITIES
- **primary-duties**: Ordered list of core responsibilities (e.g., `["Inspect repository structure", "Identify project manifests", "Classify project type"]`).
- **secondary-duties**: Optional list of supplementary responsibilities (e.g., `["Maintain investigation knowledge base", "Mentor junior investigators"]`).
- **excluded-duties**: Explicit list of responsibilities this agent must never perform (e.g., `["Modify production configurations", "Authorize security exceptions"]`).

### 2.4 AUTHORITY
- **autonomous-decisions**: List of decisions the agent may make without escalation (e.g., `["Select inspection tools", "Determine file sampling depth", "Classify confidence levels"]`).
- **escalation-decisions**: List of decisions requiring escalation (e.g., `["Modify repository files", "Invoke external network services", "Declare project type confidence <0.4"]`).
- **authority-scope**: Boundary definition using MSS v1.0 terminology (e.g., `["Repository State read-only", "Mission State observation only"]`).

### 2.5 DECISION RIGHTS
- **decision-types**: Types of decisions the agent may record via `DECISION` ACP messages (e.g., `["project-classification", "manifest-analysis"]`).
- **decision-criteria**: Evidence required to substantiate each decision type (e.g., `project-classification requires: [manifest-evidence, directory-structure-evidence, language-prevalence]`).
- **reversibility**: Whether decisions of this type can be overturned and under what conditions (e.g., `project-classification decisions are reversible only with new definitive evidence`).

### 2.6 ESCALATION RIGHTS
- **escalation-triggers**: Conditions that mandate escalation (e.g., `["conflicting-manifest-evidence", "unclassifiable-project", "suspicious-files-detected"]`).
- **escalation-paths**: Ordered list of recipients for each trigger (e.g., `conflicting-manifest-evidence → [orchestrator, software-architect] → [constitutional-board]`).
- **escalation-timeout**: Maximum time (in minutes) to await resolution before automatic re-escalation (e.g., `30`).

### 2.7 REQUIRED SKILLS
- **competencies**: Discrete, measurable abilities (e.g., `[manifest-parsing, language-detection, confidence-scoring]`).
- **proficiency-levels**: Minimum competency level for each skill (e.g., `manifest-parsing: expert, language-detection: advanced, confidence-scoring: intermediate`).
- **skill-validators**: Methods to verify skill proficiency (e.g., `manifest-parsing: correct classification of 100+ known repositories`).

### 2.8 ALLOWED TOOLS
- **tool-categories**: Categories of tools permitted (e.g., `[scanners, parsers, analyzers]`).
- **specific-tools**: Explicitly allowed tools with versions (e.g., `["trivy:v0.40.0", "jq:v1.6", "ripgrep:v14.0.0"]`).
- **tool-restrictions**: Prohibited tools or usage patterns (e.g., `["network-scanners", "packet-sniffers", "any-tool-modifying-files"]`).
- **tool-validation**: Requirements for tool use (e.g., `all-tools-must-pass-license-check`, `no-tools-without-sbom`).

### 2.9 ALLOWED MCP SERVERS
- **mcp-server-types**: Types of Model Context Protocol servers permitted (e.g., `[filesystem, git, memory]`).
- **specific-servers**: Allowed server implementations with constraints (e.g., `filesystem:read-only:/repo`, `git:local-only:/repo`).
- **mcp-restrictions**: Prohibited MCP capabilities (e.g., `["network-access", "system-command-execution", "process-spawning"]`).

### 2.10 OWNED ARTIFACTS
- **artifact-types**: Types of artifacts the agent may create or modify (e.g., `[investigation-report, manifest-summary, confidence-matrix]`).
- **artifact-locations**: Permitted paths for each artifact type (e.g., `investigation-report: docs/investigations/`).
- **artifact-ownership**: Whether ownership is exclusive or shared (e.g., `investigation-report: exclusive`, `manifest-summary: shared-with-validator`).
- **artifact-retention**: Minimum retention period (e.g., `investigation-report: 90 days`).

### 2.11 OWNED REPOSITORY AREAS
- **owned-paths**: Repository paths the agent may read (e.g., `[/**, !/src/**, !/docs/**, !/tests/]**` for read-only investigation).
- **writable-paths**: Repository paths the agent may modify (e.g., `[]` for pure investigation agents).
- **path-restrictions**: Paths the agent must never access (e.g., `["/.git/", "/.project-os/", "/secrets/"]`).
- **path-validation**: Mechanisms to enforce path boundaries (e.g., `all-file-access-must-be-via-mcp-filesystem-server`).

### 2.12 COMMUNICATION RIGHTS
- **message-types-sent**: ACP message types the agent may send (e.g., `[QUESTION, EVIDENCE, PROGRESS, STATUS_UPDATE, HEARTBEAT]`).
- **message-types-received**: ACP message types the agent may receive (e.g., `[ASSIGNMENT, MISSION_UPDATE, QUESTION, VALIDATION, ESCALATION]`).
- **communication-restrictions**: Prohibited message patterns (e.g., `["AGENT:developer:* → AGENT:investigator:* with TYPE:ASSIGNMENT"]`).
- **correlation-rules**: Requirements for CORRELATION field usage (e.g., `must-retain-parent-correlation-for-QUESTION-responses`).

### 2.13 VALIDATION DUTIES
- **validation-gates**: List of validation gates (from MSS v1.0) the agent is responsible for executing (e.g., `[integrity]` for investigator).
- **validation-criteria**: Specific criteria the agent must check for each gate (e.g., `integrity: [no-conflicting-manifests, no-modification-attempts, consistent-language-signals]`).
- **evidence-requirements**: Types of evidence the agent must produce for each gate (e.g., `integrity: [manifest-hash-comparison, directory-tree-scan, language-statistics]`).
- **validation-automation**: Whether validation must be fully automated (e.g., `integrity-gate: fully-automated`).

### 2.14 RECOVERY DUTIES
- **recovery-scenarios**: Failure conditions the agent must be able to recover from (e.g., `[agent-crash, missed-heartbeat, workspace-corruption]`).
- **recovery-procedures**: Steps the agent must take for each scenario (e.g., `agent-crash: [last-heartbeat-check, workspace-state-verification, stash-application-if-available]`).
- **state-checkpoints**: State components the agent must checkpoint before risky operations (e.g., `pre-manifest-scan: [execution-queue, agent-self-state]`).
- **recovery-validation**: Evidence required to confirm successful recovery (e.g., `workspace-clean-build-success`).

### 2.15 KPIs AND SUCCESS METRICS
- **kpi-definitions**: Quantifiable metrics with targets (e.g., `investigation-accuracy: target ≥0.95, investigation-speed: target ≤5min/1000 files`).
- **metric-collection-method**: How each KPI is measured (e.g., `investigation-accuracy: compare classification against ground truth set`).
- **success-thresholds**: Minimum acceptable performance (e.g., `investigation-accuracy: ≥0.80 triggers retraining`).
- **metric-reporting-frequency**: How often metrics are reported (e.g., `per-mission`, `daily`, `per-sprint`).

### 2.16 PARALLEL EXECUTION RULES
- **can-run-concurrently**: Whether multiple instances of this agent type can work simultaneously (e.g., `yes: multiple investigators on different repositories`).
- **shared-resources**: Resources requiring coordination if running concurrently (e.g., `none: investigator uses read-only access only`).
- **conflict-resolution**: How conflicts between instances are resolved (e.g., `timestamp-order: earliest-start-wins`).
- **resource-limits**: Maximum concurrent instances (e.g., `unbounded` or `max: 5`).

### 2.17 DEPENDENCIES
- **agent-dependencies**: Other agent types this agent requires to function (e.g., `none: investigator is self-contained for core duties`).
- **tool-dependencies**: External tools or services required (e.g., `git:v2.40.0, python:v3.11`).
- **environment-dependencies**: Required runtime environment (e.g., `posix-compliant-shell, utf8-capable-terminal`).
- **dependency-validation**: How dependencies are verified (e.g., `all-dependencies-must-be-in-PESE-ENVIRONMENT-STATE`).

### 2.18 INPUT CONTRACTS
- **input-message-types**: ACP message types that serve as input (e.g., `[ASSIGNMENT, QUESTION]`).
- **input-schema**: Required fields in each input message type (e.g., `ASSIGNMENT must include: OBJECTIVE, BOUNDARIES, AUTHORITY`).
- **input-validation**: Checks performed on input (e.g., `verify BOUNDARIES.excluded-work does not include owned-paths`).
- **input-state-requirements**: PESE state that must be present for input processing (e.g., `REPO-STATE must contain valid HEAD`).

### 2.19 OUTPUT CONTRACTS
- **output-message-types**: ACP message types the agent produces (e.g., `[EVIDENCE, PROGRESS, STATUS_UPDATE]`).
- **output-schema**: Guarantees about each output message type (e.g., `EVIDENCE always includes REFERENCE and HASH`).
- **output-state-changes**: PESE state modifications the agent makes (e.g., `updates VALIDATION/INTEGRITY/ARTIFACTS with investigation-report`).
- **output-validation**: How output correctness is verified (e.g., `EVIDENCE.REFERENCE must resolve to existing file`).

## 3. REGISTRY MANAGEMENT RULES
- **immutability-principle**: Once an agent type is released to production, its identity (`agent-id`) and core purpose cannot be changed.
- **versioning**: All changes require a new MINOR or PATCH version; MAJOR version indicates breaking changes requiring migration.
- **backward-compatibility**: PATCH versions must be backward compatible; MINOR versions may add features but must not break existing contracts.
- **deprecation**: Fields marked deprecated in MINOR version must be supported for two additional MINOR versions before removal.
- **registry-validation**: The orchestrator must validate all agent entries against this specification before spawning agents.
- **emergency-override**: Only constitutional amendment process may temporarily override agent capabilities for critical incidents.

## 4. EXAMPLE AGENT ENTRIES

### 4.1 REPOSITORY INVESTIGATOR (INVESTIGATOR)
```
agent-id: investigator
version: 1.2.0
display-name: Repository Investigator
description: Inspects repositories to determine project type, technology stack, and structural characteristics for domain pack selection.

purpose:
  mission-types: [Investigation]
  value-streams: [project-understanding, risk-assessment]
  strategic-objectives: ["reduce misclassification-rate", "increase-autonomous-onboarding-speed"]

responsibilities:
  primary-duties:
    - Scan repository for version control markers
    - Identify and parse language/framework manifests
    - Analyze directory structure and file prevalence
    - Detect monorepo and polyrepo patterns
    - Calculate confidence scores for project classifications
    - Generate investigation report with evidence
  secondary-duties:
    - Maintain known manifest patterns database
    - Mentor junior investigators on detection techniques
  excluded-duties:
    - Modify any repository files
    - Execute build tools or test suites
    - Authorize domain pack selection without confidence threshold

authority:
  autonomous-decisions:
    - Select inspection tools and depth
    - Determine file sampling strategies
    - Classify confidence levels based on evidence
    - Recommend domain pack based on classification
  escalation-decisions:
    - Modify repository files or directories
    - Invoke external network services beyond cloning
    - Declare project type with confidence <0.4
    - Override constitutional classification rules
  authority-scope:
    - Repository State: read-only access
    - Mission State: observation of assigned mission
    - Execution State: update own progress and step completion

decision-rights:
  decision-types:
    - project-classification
    - manifest-analysis
    - language-prevalence
  decision-criteria:
    project-classification: [definitive-manifest-evidence, language-evidence-weighting, directory-convention-evidence]
    manifest-analysis: [manifest-file-existence, parsing-success, dependency-extraction]
    language-prevalence: [file-extension-count, loc-analysis, commit-history-weighted]
  reversibility:
    project-classification: reversible only with new definitive evidence manifesting in repository state
    manifest-analysis: reversible if manifest file changes
    language-prevalence: reversible if file composition changes by >15%

escalation-rights:
  escalation-triggers:
    - conflicting-manifest-evidence
    - unclassifiable-project (confidence <0.4 for all types)
    - suspicious-files-detected (potential malware, exposed credentials)
    - repository-access-denied
  escalation-paths:
    conflicting-manifest-evidence: [orchestrator, software-architect] → [constitutional-board]
    unclassifiable-project: [orchestrator, product-strategist] → [constitutional-board]
    suspicious-files-detected: [security-lead, orchestrator] → [constitutional-board, legal-counsel]
    repository-access-denied: [orchestrator, dev-ops-lead] → [constitutional-board]
  escalation-timeout: 30

required-skills:
  competencies:
    - manifest-parsing
    - language-detection
    - confidence-scoring
    - directory-structure-analysis
    - evidence-correlation
  proficiency-levels:
    manifest-parsing: expert
    language-detection: advanced
    confidence-scoring: intermediate
    directory-structure-analysis: advanced
    evidence-correlation: intermediate
  skill-validators:
    manifest-parsing: correct identification of 95% of manifests in OCTO-benchmark suite
    language-detection: <5% error rate on Polyglot-1000 dataset
    confidence-scoring: correlation coefficient >0.85 with expert judgments
    directory-structure-analysis: F1-score >0.90 on RepoStruct-200
    evidence-correlation: ability to trace 100% of claims to verifiable evidence

allowed-tools:
  tool-categories:
    - scanners
    - parsers
    - analyzers
  specific-tools:
    - trivy:v0.40.0 (for security scanning of manifests only)
    - jq:v1.6 (for JSON manifest processing)
    - yq:v4.30.0 (for YAML manifest processing)
    - ripgrep:v14.0.0 (for text pattern matching)
    - git:v2.40.0 (read-only repository access)
    - python:v3.11 (for analysis scripts)
  tool-restrictions:
    - network-scanners
    - packet-sniffers
    - any-tool-modifying-files
    - tools-requiring-executive-permissions
  tool-validation:
    all-tools-must-pass-license-check
    no-tools-without-sbom-in-company-state
    mandatory-sandbox-execution-for-all-tools

allowed-mcp-servers:
  mcp-server-types:
    - filesystem
    - git
  specific-servers:
    filesystem:read-only:/repo
    git:local-only:/repo
    memory:ephemeral:/investigator-scratch
  mcp-restrictions:
    - network-access
    - system-command-execution
    - process-spawning
    - file-writes-outside-scratch

owned-artifacts:
  artifact-types:
    - investigation-report
    - manifest-summary
    - confidence-matrix
    - language-statistics
  artifact-locations:
    investigation-report: docs/investigations/
    manifest-summary: tmp/investigator/
    confidence-matrix: tmp/investigator/
    language-statistics: tmp/investigator/
  artifact-ownership:
    investigation-report: exclusive
    manifest-summary: shared-with-validator
    confidence-matrix: exclusive
    language-statistics: shared-with-knowledge-base
  artifact-retention:
    investigation-report: 90 days
    manifest-summary: 30 days
    confidence-matrix: 30 days
    language-statistics: 365 days

owned-repository-areas:
  owned-paths: []
  writable-paths: []
  path-restrictions:
    - /.git/
    - /.project-os/
    - /secrets/
    - /private-keys/
    - /.*-history
    - /.*-backup
  path-validation:
    all-file-access-must-be-via-mcp-filesystem-server
    no-direct-filesystem-access-permitted
    path-traversal-attempts-trigger-immediate-escalation

communication-rights:
  message-types-sent:
    - QUESTION
    - EVIDENCE
    - PROGRESS
    - STATUS_UPDATE
    - HEARTBEAT
    - KNOWLEDGE_UPDATE
  message-types-received:
    - ASSIGNMENT
    - MISSION_UPDATE
    - QUESTION
    - VALIDATION
    - ESCALATION
  communication-restrictions:
    - AGENT:investigator:* → AGENT:investigator:* with TYPE:ASSIGNMENT
    - AGENT:investigator:* → * with TYPE:MISSION_UPDATE
    - AGENT:investigator:* → * with TYPE:APPROVAL
  correlation-rules:
    QUESTION-responses-must-retain-parent-correlation
    PROGRESS-must-use-new-correlation-per-step
    STATUS_UPDATE-must-use-mission-correlation

validation-duties:
  validation-gates:
    - integrity
  validation-criteria:
    integrity:
      - no-conflicting-manifests (two+ definitive manifests for different project types)
      - no-modification-attempts (verified via PESE EXECUTION-STATE and git status)
      - consistent-language-signals (language prevalence aligns with manifest claims)
  evidence-requirements:
    integrity:
      - manifest-hash-comparison (SHA-256 of all manifests)
      - directory-tree-scan (json of top-level directories)
      - language-statistics (file extension counts, LOC per language)
  validation-automation:
    integrity-gate: fully-automated

recovery-duties:
  recovery-scenarios:
    - agent-crash (SIGSEGV, SIGKILL, OOM)
    - missed-heartbeat (>3 intervals)
    - workspace-corruption (unexpected file changes)
    - mcp-server-failure
  recovery-procedures:
    agent-crash:
      - check last heartbeat timestamp
      - verify workspace state against last checkpoint
      - apply git stash if available and valid
      - reconstruct execution state from PESE
    missed-heartbeat:
      - send ESCALATION to orchestrator with ISSUE-TYPE:AGENT_UNRESPONSIVE
      - attempt to contact via alternate channels
      - if unresponsive >5min, assume failure and reassign work
    workspace-corruption:
      - compare current state to last checkpoint
      - restore from checkpoint if changes unauthorized
      - escalate if changes appear malicious
    mcp-server-failure:
      - switch to backup MCP server if configured
      - escalate if no backup available
  state-checkpoints:
    pre-manifest-scan: [execution-queue, agent-self-state, manifest-cache]
    pre-language-analysis: [execution-queue, agent-self-state]
    pre-confidence-scoring: [execution-queue, agent-self-state, manifest-summary]
  recovery-validation:
    workspace-clean-build-success: N/A (investigator does not build)
    manifest-parsing-success: ability to parse at least one manifest
    confidence-calculation-success: production of confidence matrix

kpis-and-success-metrics:
  kpi-definitions:
    investigation-accuracy:
      description: Percentage of investigations matching ground truth classification
      target: ≥0.95
      measurement-method: Comparison against OCTO-benchmark ground truth set
    investigation-speed:
      description: Average time to complete investigation per 1000 files
      target: ≤5min
      measurement-method: Timer from ASSIGNMENT receipt to COMPLETION send
    false-positive-rate:
      description: Percentage of investigations recommending incorrect domain pack
      target: ≤0.02
      measurement-domain: Post-validation domain pack suitability
  success-thresholds:
    investigation-accuracy: ≥0.80 triggers mandatory retraining
    investigation-speed: >10min triggers performance review
    false-positive-rate: >0.05 triggers escalation to architecture-team
  metric-reporting-frequency:
    investigation-accuracy: per-mission
    investigation-speed: per-mission
    false-positive-rate: weekly-aggregate

parallel-execution-rules:
  can-run-concurrently: yes
  shared-resources: none (read-only repository access)
  conflict-resolution: timestamp-order (earliest ASSIGNMENT timestamp wins repository)
  resource-limits: unbounded (limited only by repository access concurrency)

dependencies:
  agent-dependencies: none
  tool-dependencies:
    - git:v2.40.0
    - python:v3.11
    - jq:v1.6
    - yq:v4.30.0
    - ripgrep:v14.0.0
  environment-dependencies:
    - posix-compliant-shell
    - utf8-capable-terminal
    - temporary-directory-access (≥100MB)
  dependency-validation:
    all-dependencies-must-be-in-PESE-ENVIRONMENT-STATE
    tool-versions-must-match-exactly-or-be-higher-within-major

input-contracts:
  input-message-types:
    - ASSIGNMENT
    - QUESTION
  input-schema:
    ASSIGNMENT:
      required: [OBJECTIVE, BOUNDARIES, AUTHORITY, DELIVERABLES, PRIORITY, VALUE]
      BOUNDARIES must include: Included Work, Excluded Work, Repo Boundaries, Ownership Boundaries
      AUTHORITY must include: Autonomous Decisions, Escalation-Required Decisions
    QUESTION:
      required: [WHAT-IS-NEEDED, WHY-NEEDED, CONTEXT-REFERENCE]
  input-validation:
    verify BOUNDARIES.excluded-work does not intersect with owned-paths
    verify AUTHORITY.escalation-required includes any file modification
    verify MISSION-ID in ASSIGNMENT matches active mission in PESE
  input-state-requirements:
    REPO-STATE must contain valid HEAD and BRANCH
    MISSION-STATE must contain active mission with matching ID

output-contracts:
  output-message-types:
    - EVIDENCE
    - PROGRESS
    - STATUS_UPDATE
    - COMPLETION
  output-schema:
    EVIDENCE:
      required: [TYPE, REFERENCE, HASH, CONTEXT]
      TYPE must be one of: [manifest, directory-structure, language-statistic, confidence-matrix]
      REFERENCE must be a path within repo
      HASH must be valid SHA-256 hex string
    PROGRESS:
      required: [COMPLETED-STEP, EVIDENCE-REF, OUTCOME, NEXT-STEP]
      COMPLETED-STEP must match a step in the mission-specific execution queue
    STATUS_UPDATE:
      required: [STEP, PROGRESS-PERCENT, BLOCKERS, RESOURCE-USAGE, NEXT-EXPECTED-OUTCOME]
      STEP format must be <current>/<total> or N/A
  output-state-changes:
    - VALIDATION/INTEGRITY/ARTIFACTS: adds investigation-report artifact reference
    - KNOWLEDGE/BASE: may add new manifest patterns or language detection heuristics
    - EXECUTION/STEP_STATE: updates completed step and evidence references
  output-validation:
    verify EVIDENCE.REFERENCE resolves to file that existed at time of ASSIGNMENT
    verify EVIDENCE.HASH matches SHA-256 of referenced file content
    verify PROGRESS.EVIDENCE-REF points to artifact created during this mission
```

### 4.2 SECURITY AUDITOR (SECURITY-AUDITOR)
```
agent-id: security-auditor
version: 2.1.0
display-name: Security Auditor
description: Conducts security vulnerability scans, compliance checks, and threat modeling for repositories and dependencies.

purpose:
  mission-types: [Security, Investigation]
  value-streams: [risk-reduction, compliance-assurance]
  strategic-objectives: ["reduce-critical-vulnerabilities", "achieve-zero-compliance-exceptions"]

responsibilities:
  primary-duties:
    - Execute SAST, SCA, and secret scanning on repositories
    - Verify license compliance of dependencies
    - Check for hardcoded credentials and sensitive data
    - Validate configuration files against security baselines
    - Generate security remediation backlog with prioritization
    - Conduct threat modeling for new features
  secondary-duties:
    - Maintain known vulnerability signatures database
    - Provide security awareness briefings to development teams
  excluded-duties:
    - Modify any source code or configuration files
    - Authorize security exceptions or policy waivers
    - Deploy patches or remediation fixes
    - Access production credentials or secrets

authority:
  autonomous-decisions:
    - Select scanning tools and configurations within policy
    - Determine scan depth and file inclusions/exclusions
    - Classify vulnerability severity using company matrix
    - Generate initial remediation backlog
    - Recommend false positive classifications
  escalation-decisions:
    - Modify repository files or directories
    - Authorize security exceptions or policy waivers
    - Access or extract production credentials/secrets
    - Declare vulnerability as false positive without evidence
    - Share vulnerability details outside authorized channels
  authority-scope:
    - Repository State: read-only access
    - Validation State: read/write for security gate artifacts
    - Risk State: read/write for active risk registry
    - Mission State: observation of assigned mission

decision-rights:
  decision-types:
    - vulnerability-classification
    - false-positive-assessment
    - compliance-gap-identification
  decision-criteria:
    vulnerability-classification: [tool-output, exploit-availability, cvss-score, asset-criticality]
    false-positive-assessment: [manual-verification, exploit-attempt, context-analysis]
    compliance-gap-identification: [policy-requirement, current-state, gap-analysis]
  reversibility:
    vulnerability-classification: reversible with new exploit evidence or CVSS update
    false-positive-assessment: reversible with successful exploit demonstration
    compliance-gap-identification: reversible with policy change or state remediation

escalation-rights:
  escalation-triggers:
    - critical-vulnerability-internet-facing
    - license-violation-requiring-legal-action
    - credential-exposure-in-public-repo
    - policy-violation-requiring-exception
    - scan-failure-due-to-access-issues
  escalation-paths:
    critical-vulnerability-internet-facing: [security-lead, orchestrator] → [constitutional-board, legal-counsel, ciso]
    license-violation-requiring-legal-action: [legal-counsel, orchestrator] → [constitutional-board]
    credential-exposure-in-public-repo: [security-lead, orchestrator] → [constitutional-board, infosec-team]
    policy-violation-requiring-exception: [security-lead, orchestrator] → [constitutional-board]
    scan-failure-due-to-access-issues: [orchestrator, dev-ops-lead] → [constitutional-board]
  escalation-timeout: 15 (for critical triggers), 60 (for others)

required-skills:
  competencies:
    - vulnerability-assessment
    - license-compliance-checking
    - secret-detection
    - threat-modeling
    - risk-prioritization
  proficiency-levels:
    vulnerability-assessment: expert
    license-compliance-checking: advanced
    secret-detection: expert
    threat-modeling: intermediate
    risk-prioritization: intermediate
  skill-validators:
    vulnerability-assessment: <2% false negative rate on NVD-benchmark suite
    license-compliance-checking: 100% accuracy on SPDX-license-mock dataset
    secret-detection: <0.1% false positive rate on entropy-distribution-test
    threat-modeling: STRIDE-model application success rate >90%
    risk-prioritization: alignment with CVSS v3.1 exploitability metrics

allowed-tools:
  tool-categories:
    - scanners
    - analyzers
    - parsers
  specific-tools:
    - trivy:v0.40.0 (SAST, SCA, secret scanning)
    - owasp-dependency-check:v8.4.0 (SCA)
    - git-secrets:v2.0.0 (secret scanning)
    - semgrep:v1.32.0 (custom rule scanning)
    - syft:v0.80.0 (SBOM generation)
    - grype:v0.65.0 (vulnerability database matching)
    - licensee:v8.10.0 (license detection)
  tool-restrictions:
    - network-exploitation-tools
    - password-crackers
    - privilege-escalation-tools
    - any-tool-modifying-files
  tool-validation:
    all-scanning-tools-must-have-valid-sbom
    no-tools-without-osi-approved-license
    mandatory-airgap-execution-for-secret-scanning-tools

allowed-mcp-servers:
  mcp-server-types:
    - filesystem
    - git
    - memory
  specific-servers:
    filesystem:read-only:/repo
    git:local-only:/repo
    memory:persistent:/security-audit-cache
  mcp-restrictions:
    - network-access
    - system-command-execution
    - process-spawning
    - file-writes-outside-designated-cache

owned-artifacts:
  artifact-types:
    - security-scan-report
    - sbom-document
    - vulnerability-backlog
    - false-positive-analysis
    - compliance-assessment
  artifact-locations:
    security-scan-report: docs/security/
    sbom-document: tmp/security/
    vulnerability-backlog: docs/security/
    false-positive-analysis: tmp/security/
    compliance-assessment: docs/security/
  artifact-ownership:
    security-scan-report: exclusive
    sbom-document: shared-with-dev-ops
    vulnerability-backlog: exclusive
    false-positive-analysis: exclusive
    compliance-assessment: shared-with-compliance-team
  artifact-retention:
    security-scan-report: 365 days
    sbom-document: 90 days
    vulnerability-backlog: 730 days
    false-positive-analysis: 180 days
    compliance-assessment: 365 days

owned-repository-areas:
  owned-paths: []
  writable-paths: []
  path-restrictions:
    - /.git/
    - /.project-os/
    - /secrets/
    - /private-keys/
    - /.*-history
    - /.*-backup
    - /prod-credentials
  path-validation:
    all-file-access-must-be-via-mcp-filesystem-server
    no-direct-filesystem-access-permitted
    path-traversal-attempts-trigger-immediate-escalation
    any-attempt-to-read-secrets-triggers-security-incident

communication-rights:
  message-types-sent:
    - QUESTION
    - EVIDENCE
    - PROGRESS
    - STATUS_UPDATE
    - VALIDATION
    - KNOWLEDGE_UPDATE
    - ESCALATION
  message-types-received:
    - ASSIGNMENT
    - MISSION_UPDATE
    - QUESTION
    - VALIDATION
    - ESCALATION
  communication-restrictions:
    - AGENT:security-auditor:* → * with TYPE:APPROVAL
    - AGENT:security-auditor:* → * with TYPE:MISSION_UPDATE (unless explicitly authorized)
  correlation-rules:
    VALIDATION-messages-must-use-mission-correlation
    ESCALATION-messages-must-use-new-correlation-per-incident

validation-duties:
  validation-gates:
    - security
    - integrity (when security-related)
  validation-criteria:
    security:
      - no-new-critical-or-high-vulnerabilities (per company matrix)
      - license-compliance-achieved (all dependencies approved)
      - no-exposed-secrets (verified via secret scanning)
      - configuration-baseline-met (per hardened profiles)
  evidence-requirements:
    security:
      - scan-output-files (trivy, dependency-check, etc.)
      - sbom-document (for dependency verification)
      - secret-scan-logs (for credential detection)
      - configuration-baseline-diff (against company hardened profiles)
  validation-automation:
    security-gate: fully-automated
    integrity-gate (security-context): semi-automated (requires manual review for logic bombs)

recovery-duties:
  recovery-scenarios:
    - agent-crash
    - missed-heartbeat
    - scan-failure
    - mcp-server-failure
    - false-positive-dispute
  recovery-procedures:
    agent-crash:
      - verify last checkpoint integrity
      - restore scan state from temporary files
      - reconstruct evidence from partial outputs
    missed-heartbeat:
      - send ESCALATION to orchestrator with ISSUE-TYPE:AGENT_UNRESPONSIVE
      - attempt contact via secure channel
    scan-failure:
      - diagnose failure cause (timeout, OOM, access)
      - retry with reduced scope or different tool
      - escalate if >3 consecutive failures
    mcp-server-failure:
      - switch to backup MCP server
      - escalate if no backup and scan critical
    false-positive-dispute:
      - initiate manual verification procedure
      - escalate to security-lead if unresolved in 30min
  state-checkpoints:
    pre-scan-initialization: [execution-queue, agent-self-state, tool-cache]
    mid-scan-large-repo: [execution-queue, agent-self-state, partial-results]
    pre-backlog-generation: [execution-queue, agent-self-state, scan-results]
  recovery-validation:
    scan-tool-executable-verification: tool runs and produces output
    sbom-generation-success: syft produces valid SPDX document
    secret-scan-baseline: known test secret detected in test repository

kpis-and-success-metrics:
  kpi-definitions:
    critical-vulnerability-detection-rate:
      description: Percentage of known critical vulnerabilities detected
      target: ≥0.98
      measurement-method: Comparison against NVD-benchmark with ground truth
    false-positive-rate:
      description: Percentage of reported vulnerabilities that are false positives
      target: ≤0.05
      measurement-method: Manual verification of random sample
    scan-completion-time:
      description: Average time to complete security scan per 1000 lines of code
      target: ≤2min
      measurement-method: Timer from scan start to VALIDATION send
    mean-time-to-remediation:
      description: Average days from vulnerability discovery to fix deployment
      target: ≤7
      measurement-method: Tracking via vulnerability-backlog
  success-thresholds:
    critical-vulnerability-detection-rate: <0.90 triggers tool review
    false-positive-rate: >0.10 triggers process investigation
    scan-completion-time: >5min per 1000 LOC triggers performance review
  metric-reporting-frequency:
    critical-vulnerability-detection-rate: per-scan
    false-positive-rate: per-scan
    scan-completion-time: per-scan
    mean-time-to-remediation: monthly-aggregate

parallel-execution-rules:
  can-run-concurrently: yes (on different repositories)
  shared-resources: vulnerability-database (read-only, synchronized access)
  conflict-resolution: first-come-first-served for shared database access
  resource-limits: max: 3 concurrent scans on same repository (to avoid resource exhaustion)

dependencies:
  agent-dependencies: none
  tool-dependencies:
    - trivy:v0.40.0
    - owasp-dependency-check:v8.4.0
    - git-secrets:v2.0.0
    - semgrep:v1.32.0
    - syft:v0.80.0
    - grype:v0.65.0
    - licensee:v8.10.0
  environment-dependencies:
    - posix-compliant-shell
    - utf8-capable-terminal
    - internet-access (for vulnerability database updates, optional)
    - temporary-directory-access (≥500MB)
  dependency-validation:
    all-dependencies-must-be-in-PESE-ENVIRONMENT-STATE
    vulnerability-database-must-be-updateable-within-24h
    internet-access-optional-but-recommended-for-current-feeds

input-contracts:
  input-message-types:
    - ASSIGNMENT
    - QUESTION
    - VALIDATION (for re-validation requests)
  input-schema:
    ASSIGNMENT:
      required: [OBJECTIVE, BOUNDARIES, AUTHORITY, DELIVERABLES, PRIORITY, VALUE]
      BOUNDARIES must include: Included Work, Excluded Work, Repo Boundaries, Ownership Boundaries
      AUTHORITY must include: Escalation-Required Decisions containing any security exception authorization
    QUESTION:
      required: [WHAT-IS-NEEDED, WHY-NEEDED, CONTEXT-REFERENCE]
    VALIDATION:
      required: [GATE, RESULT, FINDINGS, EVIDENCE-REF]
      GATE must be security for re-validation requests
  input-validation:
    verify BOUNDARIES.excluded-work does not include any security-relevant paths
    verify AUTHORITY.escalation-required includes security exception authorization
    verify MISSION-ID in ASSIGNMENT matches active mission in PESE
    for VALIDATION input: verify GATE is security and RESULT is FAIL requesting re-validation
  input-state-requirements:
    REPO-STATE must contain valid HEAD and BRANCH
    RISK-STATE must contain active risk registry
    MISSION-STATE must contain active mission with matching ID

output-contracts:
  output-message-types:
    - EVIDENCE
    - PROGRESS
    - STATUS_UPDATE
    - VALIDATION
    - KNOWLEDGE_UPDATE
  output-schema:
    EVIDENCE:
      required: [TYPE, REFERENCE, HASH, CONTEXT]
      TYPE must be one of: [scan-output, sbom, secret-log, false-positive-analysis]
      REFERENCE must be a path within repo or temp
      HASH must be valid SHA-256 hex string
    VALIDATION:
      required: [GATE, RESULT, FINDINGS, EVIDENCE-REF, REQUIRED-ACTIONS]
      GATE must be security
      RESULT must be PASS, FAIL, or BLOCKED
      if RESULT is FAIL, REQUIRED-ACTIONS must be non-empty list
  output-state-changes:
    - VALIDATION/SECURITY/ARTIFACTS: adds security-scan-report and sbom-document references
    - RISK/ACTIVE/REGISTRY: adds new vulnerability entries with severity and mitigation status
    - KNOWLEDGE/BASE: may add new vulnerability signatures or detection patterns
    - EXECUTION/STEP_STATE: updates completed step and evidence references
  output-validation:
    verify EVIDENCE.REFERENCE resolves to file that existed at time of ASSIGNMENT
    verify EVIDENCE.HASH matches SHA-256 of referenced file content
    verify VALIDATION.EVIDENCE-REF points to artifact created during this mission
    for VALIDATION messages with RESULT:FAIL, verify REQUIRED-ACTIONS are specific and addressable
```

## 5. REGISTRY EVOLUTION AND MAINTENANCE
- **addition-process**: New agent types require:
  1. Draft entry conforming to this specification
  2. Review by architecture and governance teams
  3. Proof-of-concept implementation in isolated environment
  4. Successful completion of qualification missions
  5. Approval by constitutional governance body
- **modification-process**: Changes to existing entries require:
  1. Impact analysis on all missions using this agent type
  2. Backward compatibility verification
  3. Review by affected stakeholders
  4. Version increment per semantic versioning rules
  5. Notification to all orchestrators and agents
- **deprecation-process**: Deprecating capabilities requires:
  1. Deprecation notice in MINOR version
  2. Grace period of two MINOR versions
  3. Removal in subsequent MAJOR version with migration path
- **audit-and-compliance**: Registry entries must be:
  - Reviewed annually for relevance and effectiveness
  - Validated against quarterly mission performance data
  - Updated to reflect changes in tools, technologies, and threats
  - Made available to all agents via PESE COMPANY state

## 6. QUALITY REQUIREMENTS FOR THE REGISTRY ITSELF
The ACR v1.0 specification must satisfy:
- **completeness**: Defines all necessary aspects for agent operation
- **consistency**: No contradictory requirements within or across entries
- **clarity**: Unambiguous interpretation by implementation teams
- **feasibility**: All requirements can be implemented with reasonable effort
- **future-proofing**: Designed to accommodate technological evolution
- **enforceability**: Compliance can be verified through automated checks
- **auditability**: Complete traceability of changes and rationale

---  

*This specification becomes effective immediately upon ratification by the ASC Orchestrator v2 Governance Body. All agent entries in the registry MUST conform to ACR v1.0. Existing entries have 180 days to achieve compliance.*  

*End of Specification*