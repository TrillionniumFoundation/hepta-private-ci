# learning.artifacts verifiable delivery index

Source implementation commit: `5a128fc3966218cd65ced02d8c52d9c3a660aa7a`  
Delivery-index commit: this document's containing commit  
Integration base: `a126987b84737dbc2ee2592442a314117bddb4a2`

| Capability | Source SHA | Implementation entry | Executed test/evidence | Latest actual result | Remaining limit |
|---|---|---|---|---|---|
| Canonical durable request identity | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `owner/request_identity.rs`; `LearningArtifactOwnerService::publish` | Exact-head and ordered-parent package-native identity/replay tests are required | Code written; native qualification pending at index creation | Historical terminal receipts grant no renewed authority |
| Typed owner control transitions | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `owner/operational_state.rs`; durable withdrawal/drain helpers | Unit transitions plus crash/reopen suites | Code written; native qualification pending at index creation | Whole-store rollback still needs an independent external floor |
| Live withdrawal revalidation | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `admission_v3.rs::validate_artifact_publication_v3` | Authoritative membership race regression | Code written; native qualification pending at index creation | Already issued pinned-view policy and physical erasure remain separate |
| Actionable operational metrics | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `owner/operational_metrics.rs`; `operational_metrics(now)` | Fixed-histogram unit tests and package suite | Code written; native qualification pending at index creation | Exporter/alerts and product pin/erasure gauges are host responsibilities |
| Stage-based performance measurement | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `PERFORMANCE_PROTOCOL.md`; measured pinned-load adapter | Package tests; target-host harness remains external | Protocol and in-process histograms written | No target-host SLO or power-loss claim |
| Durable owner drain | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `LearningArtifactOwnerService::begin_drain_durable_at` | Service drain and crash/reopen tests | Code written; native qualification pending at index creation | Reference-host shutdown-action integration and lifecycle authorization remain pending |
| Exact-candidate qualification | `5a128fc3966218cd65ced02d8c52d9c3a660aa7a` | `.github/workflows/hepta-learning-artifacts-operational-closure.yml` | Exact source and PR merge-context native gates | Not yet passed for this source commit | macOS/target-host evidence, required-check installation and independent acceptance remain external |

The four delivery states are intentionally separate:

- **code written** means the source path exists at the source commit;
- **executed** requires retained command/test evidence for that exact candidate;
- **native qualified** requires every mandatory exact-head and ordered-parent merge gate to pass;
- **on main** requires a later protected merge and is false for this branch.

No row in this index grants activation, selection, promotion, release or external-effect authority.
