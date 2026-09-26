# kernel.evidence release dashboard

This file is wholly generated. Do not edit it directly.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `410c6c10c6c05887d72031594ce2d3125868caf3`
- Source anchor tree: `c7f930f22582eb918b2661bed1a59a6faa7e441a`
- Canonical status SHA-256: `b4527fcf14f86e93e7edc2cdb4497c0acb1c74ef3678df133a4b7d8a2bb2cb6f`
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
| Disk-full fault injection | `false` |
| Multi-process contention benchmark | `false` |

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
