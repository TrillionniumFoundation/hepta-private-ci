# kernel.evidence closure traceability

This matrix describes the current source candidate. Source and test references
prove only that an implementation and oracle exist. A retained workflow artifact
proves only the exact commands and Git object recorded in that artifact.
Deployment, independent acceptance, canary, promotion and release require
separate authorities.

| Requirement | Source | Test / oracle | Current receipt boundary |
|---|---|---|---|
| Role independence uses frame-correct backtracking and distinct principal plus signing identity | `identity_assignment.rs` | fixed three-role counterexample; exhaustive cartesian-oracle equivalence; work-budget cases | final evidence Rust suite required |
| Verification requirements cannot be lowered by a caller | `qualification_policy.rs`, Agentd protocol/host | empty, duplicate, weakened, unknown and mismatched profile cases | final evidence and Agentd suites required |
| Product code cannot forge raw trust bindings or issuer registrations | `verified_trust.rs`, sealed traits | compile boundary and forged-binding regressions | final evidence build/test required |
| Trust schema V2 advances monotonically and binds predecessor digest | `verified_trust.rs`, `trust_acceptance.rs`, migration `0015` | stale, skipped, changed-predecessor, restart and atomic-acceptance tests | external trust ceremony remains separate |
| Append authenticates the exact envelope and commits replay, evidence and publication intent together | `qualification.rs`, migrations `0011`, `0014`, `0016` | retry/idempotency, replay, payload drift and injected rollback cases | final source/merge artifacts required |
| Recovery snapshot is one SQLite snapshot and commits complete authenticated admission | `recovery_snapshot.rs`, `qualification_commitment.rs` | concurrent mutation, signature/trust-field mutation, row/byte-bound and reopen tests | final evidence artifact required |
| Production rejects historical rows without original signature/trust provenance | migration `0016`, production provenance verification | legacy-row negative and complete-provenance positive cases | no historical field is manufactured |
| Trust and frontier acceptance are atomic at the expected snapshot | `trust_acceptance.rs`, `frontier_acceptance.rs` | snapshot drift, failed trust rotation, rollback and reopen cases | final evidence artifact required |
| Publication has durable owner fencing and exact batch identity | `publication.rs`, migration `0014` | stale owner, lease/generation, semantic conflict and restart cases | final publication diagnostic required |
| CAS uncertain outcome cannot be hidden by a new ID or blind retry | `publication.rs`, Agentd publication driver | before/after CAS crash, indeterminate latest-match/predecessor/divergent cases | final publication diagnostic required |
| Agentd exposes stable paging and bounded verification summaries | protocol `evidence.rs`, `evidence_host.rs`, `qualification_summary.rs` | real product paging, cursor/profile parsing and 48 KiB response cases | final Agentd artifact required |
| Production mode is explicit and cannot silently degrade | `evidence_host.rs`, `evidence_cli_profile.rs` | development/production profile and legacy-route rejection cases | operator configuration remains external |
| Production admission hashes the real backup object bytes | `evidence_backup_manifest.rs` | object digest/length, link/path/owner and replacement cases | actual deployed object remains external |
| Executable is bound to governed build provenance | `evidence_backup_manifest.rs`, `evidence_production.rs` | source/tree/workflow/artifact/toolchain/recipe/log/executable mismatch cases | builder authority remains external |
| Restore witness is bound to object, snapshot and integrity-check digest | `evidence_backup_manifest.rs` | missing, failed, stale and mismatched witness cases | real operator witness remains external |
| Segmented history rolls without deleting prior evidence | `frontier_backend_file/segmented/*` | rollover, immutable segment, chain and history-range tests | final evidence artifact required |
| Latest lookup is bounded by an authenticated atomic index | segmented backend | stale/missing/tampered index reconstruction and fast-latest tests | selected filesystem semantics remain external |
| Capacity is observable before rollover/exhaustion | segmented capacity API | active/archived bytes, headroom and alert tests | target-platform thresholds remain external |
| External CAS admits exactly one next generation | backend trait/file adapter | stale/skipped generation and eight-process single-winner test | coherent lock/fsync deployment remains external |
| Exact-source and fixed-base merge checks retain command/log/artifact identity | qualification/convergence workflows and record validators | real Git candidate tests and closed-world receipt regressions | queued/skipped/cancelled/action-required is not success |
| Documentation and implementation map describe the same current source closure | this document, technical guide, store guide and implementation map | docs and map validators | must pass on the unchanged final head |
| Repository CI cannot self-issue independent acceptance or release | canonical status source | closed-world status/gate tests | all external gates remain false without receipts |

## Integration-candidate policy

`fix/kernel-evidence-production-closure` is the sole integration candidate for
this closure. Earlier draft PRs are historical inputs only; their tests and
artifacts do not transfer to the current head.

The final qualification must bind:

- the exact source commit/tree;
- the immutable main base used by the PR event;
- the deterministic two-parent merge with base/source parent order;
- successful evidence, Agentd, Lane-A, documentation and implementation-map
  command records;
- retained raw logs and artifact digests;
- a clean checkout before and after every governed command.

A later metadata-only commit still creates a new candidate. It must receive its
own source and merge receipts unless the qualification record explicitly tests
that exact commit/tree.

## Repository-controlled closure

Tracks A–C are represented by direct Rust, SQL, product-wire and test sources,
not by a future code-generation script. The remaining repository-controlled
work is limited to obtaining successful final-head source/merge, formatting,
lint, build, repository CI and architecture records; repairing any actual
failures without weakening the oracles; and retaining artifact identities.

A successful repository workflow may establish execution on the recorded Git
object. It does not establish that the external backend is deployed, that a
target host survived power loss, that an independent reviewer accepted the
candidate, or that canary/release occurred.

## External gates

The following require separately authorized receipts and remain false in the
checked-in status source:

- independently provisioned rollback-domain storage and verified lock/fsync
  semantics;
- trust and signer ceremonies;
- real target-platform capacity, RPO/RTO and power-loss qualification;
- durable backup publication plus witnessed restore and rollback rejection;
- independent exact-candidate semantic/security acceptance;
- operator acceptance, canary, promotion and release.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `9108f9b1b2c73d6defb6b536d87ce76834eb5abb`
- Source anchor tree: `2606b7df789e1f50a22465998cd607060636782c`
- Canonical status SHA-256: `848dce603e2d5e78561730ede309a115f822e918d786e772a132b23add62577f`
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
| Owner-controlled non-degradable verification profiles | `true` |
| Sealed monotonic verified trust snapshots | `true` |
| Single-transaction authenticated recovery snapshot V2 | `true` |
| Complete authenticated-admission commitment | `true` |
| Durable fenced publication and CAS reconciliation | `true` |
| Bounded product verification summaries | `true` |
| Real backup-object byte verification | `true` |
| Governed source-to-executable build provenance | `true` |
| Backup restore-witness binding | `true` |
| Immutable segmented frontier history | `true` |
| Self-authenticating atomic latest-frontier index | `true` |
| Frontier rollover and capacity observability | `true` |

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
