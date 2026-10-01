# runtime.supervisor — third adversarial audit, 2026-10-01 UTC

## Scope and current development documents

Detailed technical development documentation exists. Start with
`docs/modules/runtime.supervisor/TECHNICAL.md`, then the ownership/lifetime,
read isolation, recovery, production boundary and control runbook documents.
`CAPABILITY_STATUS.json` is the checked claim matrix; `CURRENT_STATUS.md` is its
generated projection. Historical amendment and authoring artifacts do not
supersede this matrix or establish execution/acceptance.

This pass begins at PR #1306 head
`6012fc54edd67a8b19dcd8055bc01bbe9fc9a128`, tree
`873473ee81f3e5c1f2b6d62b5e5d484191c344ed`, based on
`e8f8f2d0ca399b0a68abba4da90a3be5114d0735`.
The prior two-pass report and local execution observation remain historical
checkpoints. This report records new execution observations and repairs; it is
not a qualification receipt or independent acceptance.

The final repaired source is commit
`9cd7423a227cfb9b01fe5a3b25a297203720725f`, tree
`9e7eb22c0c5cb84305c7d91168ba25860261e6dd`. Subsequent commits add
source navigation and unsigned observations without changing these inputs.

`runtime.supervisor` is the generation-fenced lifecycle execution plant.
Fleet owns release bytes and current allow/revoke admission; Agentd owns
turn/RPC admission and drain acknowledgement. Kernel authority and Operations
retain their authority and operation-truth boundaries. Supervisor readiness
cannot authorize model/tool/secret use or establish user-task success.

## Latest repository comparison

The observed `main` is `997e7beef8151160065df36b024bc8da5c989e93`.
Its supervisor implementation and technical design did not change; its map
identity change is not new supervisor execution evidence. The 24 compared
supervisor branches supplied no newer descendant of this candidate.
PR #1303 at `98ab5559e7a61a7960756a6336e16e82167698a5` is a divergent
integration alternative, not this branch's replacement. Its local model-authority
private-key custody/signing requires a separate explicit owner contract under
the registered supervisor's denied secret/model/tool domains. No acceptance
credit is assigned merely for those additional source files.
Exact observations and retrieved CI identifiers are in
`REMOTE_CI_OBSERVATION_20261001_R3.json`.

## Actual CI failures and repairs

| Finding | Repair and preserved boundary |
| --- | --- |
| Native qualification supplied `--no-fail-fast` twice through the real `just test` recipe. All eight native plan steps failed argument parsing before execution. | Remove the duplicate plan flag. Regression invokes the actual root Justfile with a cargo argv recorder across all 16 stable/current plans, verifying parameters, environment and exactly one default flag. Missing `just` fails the regression; the scope job installs the pinned tool. |
| Exact-head qualification had 335/336 passes; the paired Stop supersession fixture's 10 ms wall-clock grace expired during durable writes even while its synthetic Instant stayed fixed. | Give this supersession fixture a 5 s grace. Keep all original graceful Stop/Kill-count and supersession assertions; retain independent expired-deadline and original-deadline coverage. Production deadline semantics are unchanged. |
| Deep qualification bypassed repository test defaults and applied strict warnings to unrelated dependencies. Its source and merged library execution actually ran; merged default/qualification were 331/331 and 336/336. | Execute native deep gates through `just test`, add the original restart/recovery and Robrix integration targets, install pinned just/nextest, and align strict all-target supervisor Clippy with `--no-deps`. Dependency compilation remains enabled; the historical Operations lint failure is recorded, not labelled passed. |
| Repository integrity rejected a safe reusable caller because only its callee contains real checkouts. | Parse a bounded conservative workflow subset, inspect actual checkout options and read-only permissions, and recursively bind local `workflow_call` callees to the immutable candidate. Shell/comment/environment tokens cannot stand in for checkout configuration. Reject external reusable refs, ambiguous YAML and bounded-file/call-graph failures. |
| Independent review reproduced expression-valued permissions bypassing literal write detection, and a safe worktree caller masking a harmful candidate caller. | Require literal read/none permission values and bind both caller and callee regular blobs to the candidate. Add malicious-candidate/safe-worktree and dynamic-permission regressions. |
| A completed one-shot authoring workflow still carried branch-write permission and persisted credentials. Its original successful path was designed to self-delete. | Retire it from active workflows and archive the exact original 9,279 bytes under `history/`; retain the bound source-generation CLI tools. The archive is not an active gate or production authorizer. |
| Every read-view refresh rebuilt unchanged per-Agent status, serialization and CAS digest. | Capture fresh complete Fleet records and supervisor metadata; reuse an immutable status Arc only when epoch, record and all metadata compare equal. Recheck physical ownership readiness on every refresh. Keep the original freshness clock, expiry, invalidation, poison and live mutation fence behavior. |
| Public automatic restart attempt/exhaustion events were declared and required by existing integration tests but never emitted. Exhaustion was reported as an exceptional fault. | Publish the charged attempt only after durable budget and exact lineage/deadline admission. Report exhaustion as the normal bounded policy outcome, preserve Failed/cleanup/no extra spawn, and keep all journal/admission errors as faults. Preserve both original integration assertions and test once-only publication through real write/cleanup faults. |
| An admission journal fault could be hidden permanently by a simultaneous exact-exit or companion cleanup error. | Preserve each observed fault in the same bounded tick report while retaining owner cleanup continuation. Fault aggregation does not create a new durable authority state. |
| A failed main/Matrix signal could be hidden by a subsequent main probe or cleanup failure; a successful companion retry erased its first error. | Preserve each earlier error while observation or cleanup remains unresolved. Add five one-shot fault regressions; retain both existing exact-exit-success assertions that intentionally tolerate a failed main signal. |
| Two generated Robrix artifacts disagreed with the actual writer: retained Matrix activity was treated as readiness, and nullable generations admitted zero. A response bucket assertion was also stale. | Regenerate only the supervisord schema and its manifest; keep all 72 corpus cases, constants and Matrix schema unchanged. Require all five artifacts byte-for-byte and all structural/semantic parser checks; correct the response bucket to its actual 18 cases. |
| Failed artifact comparison dumped the complete multi-megabyte byte maps, producing a 75 MB failure log. | Keep exact file-set and byte equality, but report only bounded filename, lengths, digests and first difference offset. Exercise tail/append/missing/extra mutations without dumping payloads. |
| The valid deterministic 256-instance qualification was killed by the repository's 60 s nextest watchdog. | A separate bounded run completed in 222.584 s. Give only this binary a named qualification profile with a 10-minute watchdog and no retries; explicitly select it through just and cover the profile file in workflow scopes. Normal tests retain their original budgets. This is fixture completion, not a product latency pass. |
| The relative-root CLI test inspected only anyhow's top context and missed its chained absolute-path error. | Check the exact context and chained cause, and assert rejection leaves no Fleet/daemon files. Production rejection behavior is unchanged. |

The archived workflow blob is `7096a6275e824eb06c4f19f19a5e8b8b959ff73a`;
SHA-256 is `34c3b04945fee25600229e5a3cbb06bca5bd0be04bd493f9e5808cbc6047c043`.

## Completion and optimization boundaries

The highest remaining release blockers are durable cross-daemon cleanup proof,
complete process replacement lineage through the launch-before-lease interval,
and the atomic owner-generated recovery observation. Source scaffolding cannot
substitute for those contracts. The repaired runtime issues principally affect
fault visibility and bounded restart policy; the repaired CI and integrity
issues affect whether incomplete or unsafe execution can be accepted as evidence.
Read-projection reuse is a source optimization whose target-host benefit still
needs measurement.

The 16-row source inventory now has **12 implemented, 2 partial and 2 not
implemented**. This is not a production completion percentage. The new
per-Agent projection is partial: status/digest computation is reused, but
Fleet I/O, full metadata scanning and roster-map construction still run on each
refresh. Dirty notification propagation, incremental I/O and target-host
performance improvement have not been established. No benchmark result is
claimed from pointer reuse tests.

Tests cover two real Agent records, external Fleet CAS/removal, health changes
without a control revision, Matrix/hidden CAS metadata changes, epoch and cache
invalidation, physical lease readiness, poisoned locks and unchanged diagnostic
rings. Public full snapshots retain their diagnostic payload; observation
optimization cannot affect mutation authorization.

The remaining obligations include cross-daemon exit finalization, the
launch-before-lease ownership boundary, complete predecessor/replacement
lineage, and the normative atomic production-recovery observation. Dormant
prototypes do not close these contracts. Wiring incomplete payloads into the
crate or importing divergent local key custody would overclaim completion.
Further writer partitioning or dirty Fleet notifications require explicit
ordering/failure contracts and target-host measurements.

The long qualification exposed substantial owner waiting, but it does not
attribute that time to one source function or exercise the new read projection.
Source review identifies repeated full Fleet reads in `Supervisor::record` on
the tick/control path. `metadata_snapshot` is a pure slot read and publication
already loads Fleet once. Substituting `FleetRegistry::load_agent` would narrow
global corruption/workspace-isolation failure detection; it needs a separate
admission/immutable-identity contract and regression evidence before replacing
the current full read. The measured waiter time alone cannot authorize that
semantic change.

Actual document verification at the old head also failed seven *other modules*'
non-ancestor observations; the supervisor map was not among the reported
failures. Derived projection stopped at automation.taskflow before parity
execution. These inherited integration failures are not silently rebound to
this module's source or claimed repaired. Target-host qualification, independent
security/code/operations acceptance, activation and release remain unestablished.

## This pass's verification

Final execution and source comparison are recorded in
`LOCAL_EXECUTION_OBSERVATION_20261001_R3.json` after the frozen native and Python
runs, scoped fixes, mandatory formatting and strict compilation. A failed,
excluded, pending or skipped step is never counted as a pass. Earlier remote
331/336-test results bind the old head/merge, not the newly repaired candidate.

| Local verification | Observed result |
| --- | --- |
| Default selected native library | 340/340 passed; 8 environment socket cases excluded |
| Qualification/offline-authority selected package | 369/369 passed across 15 binaries; 12 environment socket cases excluded and 2 existing helper cases ignored |
| Explicit supervisord CLI tests | 6/6 passed |
| Hosted validators / evidence / workflow integrity Python | 70 + 30 + 24 = 124 passed |
| Scoped fix, mandatory full formatting | Both fix configurations and `just fmt` passed |
| All-target strict Clippy | Default and qualification/offline-authority configurations passed |

All three native stages used one frozen 138-file source manifest and the same
external build inputs without drift or retries. After fix/formatting, production
Rust changes are canonical-format equivalent; eight changed Python files have
identical ASTs. One test-only redundant clone was removed and compiled by both
strict checks. Tests were not rerun after fix/formatting, as required by the
repository instructions. The final 256-instance HOL parent passed in 242.111 s
under the qualification-only 600 s watchdog. The earlier 222.584 s result above
belongs to its separately recorded historical checkpoint. Neither establishes
target-host product latency. ENOSPC and missing cached crate-source failures
before successful final chores remain recorded as failures, never passes.

Separate agents performed implementation and adversarial cross-review. New
reproducible issues are repaired and reviewed again within this scope; this
bounded process does not prove that future optimization or target-host failures
are impossible.
