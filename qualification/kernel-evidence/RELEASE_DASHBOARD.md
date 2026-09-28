# kernel.evidence release dashboard

This file is wholly generated. Do not edit it directly.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `d01b9571d74a2b25b0517f7aa2584ada7b9887ea`
- Source anchor tree: `3863e415078027f8c6a85deed2aa8f0b0d57c8cd`
- Canonical status SHA-256: `453a82332547fdffaedec0e593ddfdc974164b8f8e5aa771928f3323fc74dc19`
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
