# learning.artifacts verifiable delivery index

This index separates four different facts which must never be collapsed into one
`COMPLETE` claim:

1. **source implemented** — ordinary source exists in the candidate;
2. **executed** — the named test or measurement actually ran for the exact source;
3. **native qualified** — all mandatory exact-head and actual-base lanes passed;
4. **integrated to main** — the qualified source is reachable from protected `main`.

The authoritative source SHA is the `sourceSha` in the retained
`hepta.learning-artifacts-exact-head-qualification.v1` receipt. The receipt SHA,
Git tree, source objects, commands and outcomes must all agree. A branch name or
this document is not execution evidence.

Initial convergence commit:
`fdc4ed165e45ee56929275c436d934e518c44971`, combining the durable owner line
and the authenticated reference-host line. Later commits on the same branch must
qualify under their own exact SHA.

## Delivery ledger

| Capability | Candidate source state | Implementation entry point | Named evidence | Latest exact-source result | Protected-main state | Remaining limitation |
| --- | --- | --- | --- | --- | --- | --- |
| Canonical publication request identity | Source implemented | `owner/request_identity.rs`, `owner/durable_request_identity.rs`, `LearningArtifactOwnerService::publish` | terminal semantic-drift rejection; missing-sidecar rejection; SIGKILL phase recovery | Pending final exact-head receipt | Not integrated | Legacy checkpoints without the identity sidecar fail closed and require explicit migration or retirement |
| Durable withdrawal lower bound | Source implemented | `owner/durable_withdrawals.rs`, `install_withdrawal_frontier` | monotone prefix, old/fork input, truncation, unknown entry and process-death tests | Pending final exact-head receipt | Not integrated | Local floor does not replace independently retained rollback protection or authenticate withdrawal actors |
| Durable one-way drain | Source implemented | `owner/durable_control.rs`, `begin_drain_durable_at` | restart, truncation, invalid-type and SIGKILL tests | Pending final exact-head receipt | Not integrated | No online clear/resume API; deployment still needs an independent operator stop floor for whole-store rollback |
| Stable owner error taxonomy | Source implemented | `LearningArtifactOwnerErrorCodeV1`, `LearningArtifactOwnerServiceError::code` | error-code contract regression | Pending final exact-head receipt | Not integrated | Transport adapters must preserve codes instead of flattening every error to retryable/unavailable |
| Actionable owner state | Source implemented | `LearningArtifactOwnerService::operational_state` | pending-recovery age, drain age, record counts and durability-state regression | Pending final exact-head receipt | Not integrated | Consumer pin counts and physical-erasure queues are not owned by this service and remain explicitly unknown |
| Bounded stage measurement | Source implemented | `owner/measurement.rs`, `MeasuredLearningArtifactOwnerHostV1` | recorder success/failure and null-resource-accounting regression | Pending final exact-head receipt | Not integrated | Method-boundary samples are not target-host SLO evidence until run on each supported deployment/filesystem class |
| Authenticated reference host | Source implemented | `owner/publication_coordination.rs`, `LearningArtifactReferenceHostV1` | capability, journal replay, recovery, backup and process tests | Pending final exact-head receipt | Not integrated | Production identities, key custody, non-loopback transport and target-host power-loss behavior remain external |
| Exact source qualification | Workflow implemented | `.github/workflows/hepta-learning-artifacts-qualification.yml`, `scripts/hepta_artifact_qualification.py`, `scripts/hepta-learning-artifacts-qualification.py` | Linux/macOS exact-head plus ordered-parent actual-base synthetic merge; protected `CI required` fan-in | Running/pending for the final candidate until a retained receipt says otherwise | Not integrated | Historical jobs and earlier candidate receipts do not qualify later commits |
| Withdrawal propagation to existing consumers | Partial | admission-time withdrawal validation and current-registry revalidation | source and reader regressions | Not qualified as full lifecycle closure | Not integrated | Previously issued decoded/pinned state needs an explicit product policy and consumer-owned revalidation/retirement proof |
| Pin/retention/physical erase accounting | Not implemented in this owner | Reported as `null`/`resourceAccountingComplete=false` by stage report | metrics schema regression | Not applicable | Not integrated | Consumer and retention owners must supply actual pinned bytes, pending erase bytes and completion witnesses |
| Production activation, acceptance, promotion and release | External gate | protected deployment/release systems | independently authenticated approvals and target-host evidence | False | False | Source, tests, receipts and documentation cannot self-issue these authorities |

## Reading an exact candidate

For any claimed candidate, reviewers must check in this order:

1. the PR head SHA and ordered integration base;
2. the exact-head and deterministic ordered-parent merge receipts;
3. every mandatory command outcome, including nonzero/skipped/retried cases;
4. Git objects for source, tests, workflows, this index and the implementation map;
5. native test identities and fault boundaries;
6. external gates separately from repository-controlled source qualification.

A row may move from **source implemented** to **executed** only through retained
exact-source command evidence. It may move to **native qualified** only when all
mandatory lanes pass. It may move to **integrated to main** only after the exact
qualified commit is reachable from protected `main`; merging a different tree or
re-running a subset does not count.
