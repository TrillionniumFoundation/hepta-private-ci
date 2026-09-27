# prompt.registry qualification status

This file is the human-readable claim boundary for the current remediation candidate.
Machine-readable qualification receipts are produced by
`.github/workflows/hepta-prompt-registry-qualification.yml` and bind the exact
run ID, source SHA, base SHA, tested SHA/tree and owned source blob digests.

## Lifecycle states

| State | Current value | Meaning |
| --- | --- | --- |
| `sourceImplemented` | `true` | The registry, strict durable V4 relation state, authenticated publisher, consumer capability filtering and dispatch-time final-use fencing exist in source. |
| `sourceComposed` | `true` | Agentd constructs the prompt owner/runtime and exposes the governed source-level integration path. |
| `productActivated` | `false` | No claim is made that a deployed product has enabled this path or established a production publisher/operator. |
| `accepted` | `false` | Independent acceptance has not been issued. |
| `released` | `false` | Release authority has not approved or shipped this candidate. |

`productionReady` remains **false** until both exact-head and deterministic
base-merge qualification lanes pass formatting, unit/integration tests, strict
Clippy, Cargo source-graph validation and protocol/schema checks, and the
repository's protected postmerge checks are green.

## Provenance boundary

- Mainline source anchor at remediation start:
  `a126987b84737dbc2ee2592442a314117bddb4a2`.
- The workflow, not this document, is authoritative for the tested candidate
  identity and receipt digests.
- A queued, skipped, cancelled, historical or unrelated workflow result is not
  evidence that this module passed.
- Source composition does not grant activation, acceptance, merge, deployment,
  external-effect or release authority.
