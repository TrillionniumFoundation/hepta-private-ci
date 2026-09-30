# kernel.evidence current status

This file is wholly generated.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This is generated from `qualification/kernel-evidence/STATUS_SOURCE.json`.
Runtime readiness is separately bound to the exact tested SHA by
`scripts/kernel_evidence_readiness.py`; neither source claims nor CI may
self-issue independent acceptance, production activation, or release.

- Source anchor commit: `d52005035c2e08d8e04ac1acde08894bdf6e448c`
- Source anchor tree: `16ab1946fa0de31c3b2b4d295516264131a90a68`
- Canonical status SHA-256: `1f398fbf15805339633e2db3e1a510a7be9ea56b57a4f8d441dd426a10c5c44e`
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

> Repository implementation is not deployment evidence. A CI workflow
> receipt is not independent acceptance or release authority.
<!-- END GENERATED KERNEL EVIDENCE STATUS -->
