
# learning.artifacts verifiable delivery index

Source implementation commit: `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f`  
Delivery-index commit: this document's containing commit  
Integration base: `a126987b84737dbc2ee2592442a314117bddb4a2`

| Capability | Source SHA | Implementation entry | Executed test/evidence | Latest actual result | Remaining limit |
|---|---|---|---|---|---|
| Canonical durable request identity | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `owner/request_identity.rs`; `LearningArtifactOwnerService::publish` | Package-native identity/replay tests are required on exact head and ordered-parent merge | Code written; native qualification pending at index creation | Historical rows are DENY_ALL receipts; no authority renewal |
| Typed owner control transitions | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `owner/operational_state.rs`; durable withdrawal/drain helpers | Unit transitions plus crash/reopen suites | Code written; native qualification pending at index creation | Whole-store rollback still needs an independent external floor |
| Actionable operational metrics | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `owner/operational_metrics.rs`; `operational_metrics(now)` | Fixed-histogram unit tests and package suite | Code written; native qualification pending at index creation | Exporter/alerts and product pin/erasure gauges are host responsibilities |
| Stage-based performance measurement | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `PERFORMANCE_PROTOCOL.md`; measured pinned-load adapter | Package tests; target-host harness still external | Protocol and in-process histograms written | No target-host SLO or power-loss claim |
| Durable owner drain | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `LearningArtifactOwnerService::begin_drain_durable_at` | Service drain and crash/reopen tests | Code written; native qualification pending at index creation | Reference-host shutdown action integration and lifecycle authorization remain pending |
| Exact-candidate qualification | `6fdf4ddba394c60b04d2f9c5c46ae629bc47b61f` | `.github/workflows/hepta-learning-artifacts-operational-closure.yml` | Branch exact-source and PR merge-context native gates | Not yet passed for this source commit | macOS/target-host evidence, required-check installation and independent acceptance remain external |

The four delivery states are intentionally separate:

- **code written** means the source path exists at the source commit;
- **executed** requires retained command/test evidence for that exact source;
- **native qualified** requires every mandatory gate to pass on exact source and the
  deterministic ordered-parent merge;
- **on main** requires a later protected merge and is false for this branch.

No row in this index grants activation, selection, promotion, release or external
effect authority.
