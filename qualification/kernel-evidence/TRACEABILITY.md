# kernel.evidence closure traceability

This matrix is the canonical human-readable closure view for the current
`kernel.evidence` source candidate. Source and test references prove only that
an implementation and oracle exist. A retained GitHub Actions receipt proves
only the exact commands and candidate recorded in that artifact. Deployment,
independent acceptance, canary, promotion and release require authorities that
repository CI cannot manufacture.

| Requirement | Source | Test / oracle | Exact execution receipt | External authority |
|---|---|---|---|---|
| Native `append_receipt` authenticates the exact envelope and atomically advances replay plus append | `codex-rs/hepta-evidence/src/qualification.rs`, migration `0011_qualification_evidence.sql` | authenticated retry/idempotency, payload drift and transactional replay rollback cases | `evidence-tests.json` in source and merge artifacts | independent semantic review |
| `query_claim` and stable cursor paging bind candidate/tree/class and preserve append-sequence order | `qualification.rs`, `qualification_paging.rs` | EVID-02/EVID-04 and cursor paging tests | `evidence-tests.json` | workload/retention acceptance |
| `verify_chain` enforces expiry, lineage, current key/role trust, role coverage and distinct principal/signing identity | `qualification.rs`, Agentd `evidence_trust.rs` | EVID-01..04, shared-key rejection, key rotation and revocation tests | evidence and product command records | security review |
| Correction/revocation authority is principal/role scoped except explicit `security` emergency revocation | `qualification.rs`, `evidence_trust.rs` | lineage mutation authority test | `evidence-tests.json` | security policy acceptance |
| Durable evidence validity is separate from short AuthBus admission TTL | `qualification.rs` | independent-decision validity versus ingress TTL | `evidence-tests.json` | reviewer sets receipt expiry |
| `IndependentDecisionReceiptV1` binds candidate, principal, key, role, evidence set and expiry | `qualification.rs` | independent-decision binding test | `evidence-tests.json` | **must be issued by an external principal** |
| Qualification rows are database-append-only | migration `0011_qualification_evidence.sql`, schema verification | deny-trigger and missing-trigger reopen tests | `evidence-tests.json`, `lane-a-truth.json` | durability review |
| Runtime SQL cannot mutate protected schema/evidence through an unrestricted connection | `codex-rs/state/src/sqlite_evidence_runtime.rs` | SQLite authorizer allow/deny tests | `agentd-product-test.json` and evidence package build | deployment profile review |
| Product caller/writer is real Agentd composition | `hepta-agentd/src/evidence_host.rs`, `lib.rs`, `main.rs` | `tests/kernel_evidence_product.rs` | `agentd-product-test.json` | physical/operator activation |
| Development and production evidence modes cannot silently degrade into one another | Agentd mode parsing and `evidence_production.rs` | missing production descriptor/trust/backend/build/backup/frontier inputs all fail closed | `agentd-product-test.json` | operator configuration ceremony |
| Recovery-frontier v2 signs store generation, ledger root, migration, replay, trust, backend, build, qualification and backup identities | `frontier_v2.rs` | signing-domain mutations, invalid root/source and deterministic mutation corpus | `evidence-tests.json` | signer policy acceptance |
| Threshold signatures require distinct principals and current epochs and reject revoked signers | `evidence_frontier_signers.rs` | threshold, overlap rotation and revoked signer tests | `agentd-product-test.json` | signer registry ceremony |
| External backend exposes latest/CAS/history/identity and enforces monotonic generation | `frontier_backend.rs`, `frontier_backend_file.rs` | first publish, stale/skipped generation and history tests | `evidence-tests.json` | deployment on independent storage |
| External audit journal is private, bounded, append-only and hash chained | `frontier_backend_file.rs` | torn/empty tail, hard-link/symlink, identity/directory replacement and append-bound tests | `evidence-tests.json` | filesystem semantics acceptance |
| CAS success returns only after durable file and directory acknowledgement; uncertain writes poison the handle | `frontier_backend_file.rs` | injected write failure and indeterminate fencing tests | `evidence-tests.json` | storage durability acceptance |
| Cross-process generation contention has exactly one winner | `tests/frontier_backend_multiprocess.rs` | eight-process contention executable | `evidence-tests.json` | production throughput qualification |
| Local acceptance history is immutable and rejects generation rollback | `frontier_acceptance.rs`, migration `0013_recovery_frontier_acceptance.sql` | idempotency, conflict, reopen and rollback tests | `evidence-tests.json` | external latest-frontier witness |
| Production control files are private, canonical and resistant to symlink/parent replacement | Agentd `evidence_production.rs` | wrong owner/mode/path, identity drift and replacement tests | `agentd-product-test.json` | host hardening review |
| Exact-source receipt contains exactly five required command records and retained log identities | qualification workflow, `build_kernel_evidence_status.py`, Agentd production parser | missing/extra/failed/malformed check and log tests | `kernel-evidence-source-<SHA>` | independent receipt review |
| Deterministic merge receipt is from the same repository/run/attempt and has base/source parent order | workflow synthetic-merge job, Agentd production parser | run, artifact URL and parent-order rejection tests | `kernel-evidence-merge-<SHA>` | final-candidate acceptance |
| Qualification status and artifacts upload even when a command fails | `.github/workflows/hepta-kernel-evidence-qualification.yml` | split steps, `if: always()` diagnostics and fail-closed required fan-in | workflow run | repository required-check policy |
| `Kernel evidence required` reaches the protected `CI required` fan-in | qualification workflow and `.github/workflows/blocking-ci.yml` | workflow graph inspection | check run on exact PR head | repository administrator must configure protection |
| Disk-full and actual crash boundaries do not manufacture success | `store/runtime.rs`, AuthBus crash fixtures | disk-full, process exit before ack and reopen recovery | `evidence-tests.json` | operational fault drill |
| One machine-readable source generates all module status views | `STATUS_SOURCE.json`, `scripts/kernel_evidence_status.py` | closed-world key/source-anchor/projection drift tests | `docs.json` | none for repository facts; external gates still require receipts |
| Backup publication exactly matches the accepted snapshot, backend and generation | Agentd production admission | durable flag, digest, freshness and generation mismatch tests | `agentd-product-test.json` | backup operator witness |
| A valid stale complete SQLite image is rejected against a newer external frontier | frontier v2, backend, local acceptance and production admission | old-image/ledger-root mismatch tests | source/product artifact | witnessed recovery drill |

## Claim boundary

Repository-controlled implementation now includes:

- the exact-candidate qualification store and immutable lineage;
- a named Agentd product host with explicit development and production modes;
- recovery-frontier v2, threshold signer verification and immutable local
  acceptance;
- an explicit external monotonic backend contract and a locked-file adapter for
  a separately mounted rollback domain;
- read-only migration preflight, SQLite authorizer, denial triggers, stable
  cursor paging, disk-full/process-crash coverage and multi-process contention;
- split exact-source/synthetic-merge qualification with retained diagnostics;
- a canonical status source and generated documentation/dashboard projections.

The current persistent gates remain false until exact evidence exists for this
final candidate. In particular, source code does not prove that an external
backend is deployed, a backup/restore drill was witnessed, an independent
reviewer accepted the candidate, a canary passed, or release was approved. A
green workflow may establish exact-source and merge execution only; it cannot
advance the external gates by inference.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `88a46b13d5479370812ca2b680e77972fb770767`
- Source anchor tree: `94776711df64f9630c3dfd40b3a44f320d7d85ea`
- Canonical status SHA-256: `c55c659e400adc86c1e658b332f87c041ef8e1db7d218c6dae1b60c653fb8e1e`
- Workflow run ID: `none`
- Retained artifact digest: `none`

### Repository implementation capabilities

| Capability | Implemented |
| --- | --- |
| Recovery-frontier v2 signing domain | `true` |
| External monotonic CAS backend adapter | `true` |
| Fail-closed Agentd production mode | `true` |
| Immutable local frontier acceptance history | `true` |
| Distinct-principal threshold and key-epoch rotation | `true` |
| Read-only production migration preflight | `true` |
| Stable append-sequence cursor pagination | `true` |
| Database update/delete denial triggers | `true` |
| SQLite authorizer callback | `true` |
| Disk-full fault injection | `true` |
| Multi-process contention benchmark | `true` |

### Qualification, deployment and governance gates

| Gate | State | Persistent authority receipt |
| --- | --- | --- |
| Exact-source qualification | `false` | none |
| Deterministic-merge qualification | `false` | none |
| Independent acceptance | `false` | none |
| External frontier active | `false` | none |
| Backup/restore drill | `false` | none |
| Canary accepted | `false` | none |
| Release approved | `false` | none |

> Repository implementation is not deployment evidence. A CI workflow receipt
> is not independent acceptance or release authority.
<!-- END GENERATED KERNEL EVIDENCE STATUS -->
