# Hepta Runtime: invocation recovery frontier and retained validation

**Status: system acceptance remains HOLD.** The fixed source adds ordinary
governance invocation history to the PQ recovery frontier, validates the actual
SQLite pagination keys, and rejects malformed typed projections without
panicking. Local source-contract checks and fourteen dispatcher tests have
completed on `97ae5b4…`. The first full evidence-library attempt timed out,
and its later exact 17-name owner selection failed to compile with 15 E0277
errors and zero executed tests. The separately published `ff19c86…` repair
now has its own 120 static passes and exact 17 owner passes, but its dispatcher
selection failed to compile with E0432 and zero executed tests. The final fixture-import
repair is frozen and published as `9438a6c…`; its own 120 static, 17 owner,
14 dispatcher and 11 signed selections passed. The full evidence library
passed 155 eligible cases, with one existing ignored subprocess fixture.
Original process controls failed 0 passed / 3 failed; recovery process controls
failed 2 passed / 2 failed, with real Unix control-socket bind EPERM in each
failed case. No production, independent custody or whole-machine restore
acceptance is granted.

The original scoped `just fix` completed with exit 0 and unchanged source,
but project lint warnings and dependency deprecations remain. This does not
establish strict zero-warning acceptance. The original `just fmt` also exited
0 with no changed files to format; it did not run a whole-repository `--all`
format check. Both commands retain clean 9438 source observations and add no
test execution credit.

> Evidence prepared 2026-11-05 for the private directory
> `evidence/pq-invocation-recovery-20261105/`. Original receipt/log basenames and
> bytes are retained. Every local command described below has its own source
> identity and terminal outcome; failures and warnings remain part of the record.
> Source publication, evidence publication and system acceptance are separate.

## 1. Frozen source and later evidence are separate objects

| Object | Exact identity or current status |
| --- | --- |
| Observed Hepta source before fixture repair | `97ae5b4bf5e5f0d0589c1c653f1861e1d9c1242f` |
| Observed source tree | `fdce3b8e854629315cea088f5d549aed3f8b2021` |
| Observed source parent | `7530e4bc7aa61a0c23a5933fef4a65d86a586cf8` |
| Existing integration PR | [#4812](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4812); earlier `97ae5b4…` publication/readback confirmed; `ff19c86…` lease push and remote ref readback confirmed by the publication owner |
| Published intermediate fixture-repair source | `ff19c86b7190204e9172a1595a58d8eb9f897c6d`; tree `1c34e75019730bfdd238ebc612701d9f9583759d`; published and locally aligned to the exact clean source/tree |
| Repair source parent | `c90d13228514440e82d4bbb0da2bdaf13d145c8a` |
| Final frozen fixture-import repair source | `9438a6c27a5e2f25169445f39499631db4e00529`; tree `a9cba014de26164f0285c6c886fb071b19a04845`; parent `ff19c86b7190204e9172a1595a58d8eb9f897c6d`; exact local import, push and remote readback confirmed |
| Evidence publication identity | The Git commit containing this directory pins its evidence. The prepared evidence-only follow-up is rooted at source `9438a6c27a5e2f25169445f39499631db4e00529`; no evidence commit SHA is invented before that commit exists. |
| Execution-bound executable identity | **HOLD**; later local debug-artifact hashes are recorded below, but the receipts do not bind those hashes to a named executed path |
| Hosted source-head and prospective-merge receipts | **HOLD**; the required fixed-source hosted architecture/merge receipts are not supplied by this local evidence |
| Paired Chain implementation | [1d6a9f9b5e8abd9e86457f45199a4922f9376360](https://github.com/TrillionniumFoundation/Trillionnium-Chain/commit/1d6a9f9b5e8abd9e86457f45199a4922f9376360), tree `4a0314e72ebc45659986d03e7ca2f96cab9399ea`; its evidence remains separately source-bound |

The original source changes 23 files against its recorded parent. The repair
source `ff19c86…` corrects the two test fixture modules' `SqlSafeStr` handling
relative to parent `c90d132…`. That parent also adds 27 concurrent sealed
qualification paths relative to `97ae5b4…` (24 source, three evidence); those
paths are retained byte-for-byte. Local source/tree alignment, lease push and
remote ref readback are confirmed. New 120 static and 17 owner results below
retain the ff19 identity; its dispatcher compile failure is separate. The 97ae
static/dispatcher successes and owner compile failure retain their original
identity. A later evidence-only
commit must retain executable source, lockfiles and runtime policy unchanged,
while preserving each receipt's tested SHA/tree. Evidence publication does not
retroactively execute the new HEAD. The frontier's signed `sourceCommit` and
`sourceTree` fields are qualification metadata, not an installed-executable
measurement. Exact source, binary, policy and independent operator identities
remain separate obligations.

## 2. Actual local observations

| Source-bound invocation or acceptance gate | Observed outcome | Boundary |
| --- | --- | --- |
| Lane-A/static checks on `97ae5b4…` | **PASS, exit 0**; 86 + 19 + 15 = **120 static tests**, plus the named static gates | Clean, equal before/after source. No native execution is credited to these checks. |
| Full `codex-hepta-evidence --lib` on `97ae5b4…`, original 600-second runner budget, minimum 17 | **FAILED / TIMED OUT**; wrapper exit **124**, child exit **-9**, **0 completed tests**, elapsed 608.895 seconds | The runner's termination handling extends elapsed time beyond the configured 600 seconds. Compilation progress is not passing execution. |
| Original dispatcher selection on `97ae5b4…`, minimum 14, 3,600-second budget | **14 named tests passed exactly once**, exit 0, no selected skips, 1,515.256 seconds elapsed; finished 09:46:58 UTC | The original 14-name set, log hash and clean before/after source match. Local execution does not satisfy hosted or independent acceptance. |
| Exact 17 recovery-owner selection on `97ae5b4…` | **FAILED TO COMPILE**, exit **101**, **15 E0277**, **zero executed tests**, 147.701 seconds; no timeout | Original seven controls plus seven invocation and three schema controls; 600 seconds and zero retries retained. |
| `ff19c86…` new source-contract invocation | **120 static tests passed**, exit 0, 26.398 seconds | Clean matching ff19 before/after source; new receipt, not old-source execution credit. |
| `ff19c86…` exact owner revalidation | **17 named tests passed once**, exit 0, 27.102-second invocation / 6.715-second test summary | Original 600-second limit, zero retries and one thread; all selected names executed, no selected skip or failure. |
| `ff19c86…` original dispatcher14 revalidation | **FAILED TO COMPILE**, exit **101**, **one E0432**, **zero executed tests**, 74.852 seconds | Original 3,600-second budget retained; no timeout. The earlier 97ae dispatcher14 success is separate. |
| Final `9438a6c…` source contracts | **120 static tests passed**, exit 0, 20.791 seconds | Exact clean final-source before/after identity. |
| Final `9438a6c…` exact owner17 | **17 named tests passed once**, exit 0, 11.596 seconds | Original 600-second budget, minimum17, zero retries and one test thread; no selected skip. |
| Final `9438a6c…` original dispatcher14 | **14 named tests passed once**, exit 0, 81.902-second invocation / 21.051-second test summary | Original 3,600-second budget; 238 cases outside the filter, no selected skip. |
| Final `9438a6c…` full evidence library | **155 passed / 0 failed**, exit 0, 78.994-second invocation / 72.761-second test summary | Original 600-second budget and minimum17. 156 discovered, 155 eligible/executed, one existing ignored subprocess fixture. Includes the owner17; do not add the totals. |
| Final `9438a6c…` exact signed11 | **11 named tests passed once**, exit 0, 8.256-second invocation / 3.208-second test summary | Original nine controls plus two signed controls; 600 seconds, zero retries; 241 outside-filter cases, no selected skip. |
| Final `9438a6c…` three original AuthBus/Agentd process controls | **FAILED**, exit100, **0 passed / 3 failed**, 40.827 seconds | All three fail on real Agentd Unix control-socket bind EPERM. Original 1,800 seconds and zero retries retained. |
| Final `9438a6c…` four real recovery process controls | **FAILED**, exit100, **2 passed / 2 failed**, 15.868 seconds | Rollback rejection controls pass; startup/current-image positive paths fail on Unix bind EPERM. Original 1,800 seconds and zero retries retained. |
| Final `9438a6c…` scoped `just fix` | **Exit 0 with warnings**, 778.748-second invocation / Cargo12m50s | Original 1,200-second budget; clean unchanged source. Residual project/dependency warnings remain. Zero tests executed; not strict zero-warning acceptance. |
| Final `9438a6c…` original `just fmt` | **Exit 0**, 3.732 seconds; no changed files needed formatting | Clean unchanged source, zero tests; the command did not run a full-repository `--all` format check. |
| All four hosted PR architecture/source-head/merge lanes | **HOLD** | No local run/job metadata attests these required lanes. |

The completed static [receipt](hepta-source-contracts.json) refers to
[its 1,129-byte log](hepta-source-contracts.json.e9e8a2fbe2b4416caa8a6c4dbe092b57.log),
SHA-256 `175cd95ffd5df48ca7e1dc49226efcdac7d39bda85138be7e496c58c0be3d34f`.
The timed-out library [receipt](hepta-evidence-all-lib.json) refers to
[its 25,006-byte log](hepta-evidence-all-lib.json.e1ddb53bb2af40ad99d7513feec0ee32.log),
SHA-256 `c0ac5e455dff2d69d1b0bdde30365ed143935fb5f7a01b5449ba16b7283de7dc`.
The completed dispatcher [receipt](hepta-dispatcher.json) refers to
[its 68,545-byte log](hepta-dispatcher.json.bba37527c9f1425e9d44af0919503ad7.log),
SHA-256 `a7e611fcdce88f164666e8e5e0ccf2993a4e8e5df2e6b31cb22035133c55ebca`.

The selected owner [receipt](hepta-recovery-owner.json) refers to
[its 48,100-byte log](hepta-recovery-owner.json.486b16f2692b4c5cabaafb38351cf404.log),
SHA-256 `b16287e44ee4b931eeacd421fe06261136bd0f4ab6277a6a80812831aba823d9`.
It records clean matching `97ae5b4…` / `fdce3b8…` source observations, exit 101,
no timeout, zero observed passed/failed tests, and 147.701 seconds elapsed.
The compiler identifies 15 fixture SQL calls that do not satisfy `SqlSafeStr`;
no test body ran. This is a source compile failure distinct from the earlier
600-second full-library timeout. The new fixture repair cannot erase it.

The new source-contract [receipt](hepta-composed-source-contracts.json) refers to
[its 1,129-byte log](hepta-composed-source-contracts.json.1feeb0e85672419c9135f60264a479df.log),
SHA-256 `7defc3d0186ccf30a0f239b58f5c8dedc5612a06f9e9f56413da9ab2dfae77da`.
The repaired-owner [receipt](hepta-recovery-owner-fixed.json) refers to
[its 31,709-byte log](hepta-recovery-owner-fixed.json.1d2a046377124822864fc953aba3e3bb.log),
SHA-256 `aa5b8dfa4717e283ba013b9c6a6cd6025bd11d4947334fce0778cbba39ab8659`.
Both finish with exit 0 and clean equal `ff19c86…` / `1c34e75…` before/after
identity. The owner log's summary reports 17 passed and 139 skipped: the 139
are outside the exact selected filter, while all 17 required names appear once
as `ok`, with no selected skip. The invocation elapsed 27.101723209 seconds;
6.715 seconds is the test-summary interval, not total build/invocation time.
No speedup or capacity claim is derived from these different attempts.

The [ff19 roster inspection](hepta-recovery-ff19-roster-observation.json)
records owner PASS and signed PENDING, so its overall result remains
`NOT_PASSED`. The [cross-source negative](hepta-recovery-cross-source-refusal.json)
rejects the original 97ae failed receipt when ff19 is requested. Original
failures and old-source successes remain unmodified.

The intermediate source's dispatcher [receipt](hepta-composed-dispatcher.json)
refers to [its 26,925-byte log](hepta-composed-dispatcher.json.c3eb0d09e1404761b1e702ffcf920126.log),
SHA-256 `0b5b580c2bb98c4f55402915817d14e3f0fc084f52f6ba5778ff308c71367934`.
It records clean equal ff19 before/after source, exit 101, no timeout, zero
observed passed/failed tests and 74.851582505 seconds elapsed. Agentd library
test compilation fails with E0432 because a concurrently added qualification
test imports `pretty_assertions` without the corresponding Agentd development
dependency. No dispatcher test body ran. The one-line import deletion is now frozen in `9438a6c…`, preserving the
standard assertion and dependencies. Local Git review confirms parent ff19 and
exactly one deletion in `intelligence_evaluation_tests.rs`; the publication
owner confirms push/readback. Final source/owner/dispatcher/signed results have
their own 120 / 17 / 14 / 11 successes; full-library and failed process results
appear below. The intermediate 17-owner/120-static successes do not make this
separate compile failure pass and cannot be assigned to the final repair.

The final source-contract [receipt](hepta-final-source-contracts.json) and
[1,129-byte log](hepta-final-source-contracts.json.588801a597134e7ab4bf6785bce901e2.log)
record 120 static passes, exit 0, 20.790556732 seconds and SHA-256
`68c94e74b64a58978dad8efe4f9795b48bca389d18a1548678808bca6f9f7d38`.
The final owner [receipt](hepta-final-recovery-owner.json) and
[31,603-byte log](hepta-final-recovery-owner.json.f8c148a73bcb483b86b13cbf81924736.log)
record 17 passes, exit 0, 11.595617016 seconds and SHA-256
`1588557c6b50c4e1d43d17979d0f99747b03253d5d0e761a2b4d13ea11b975a7`.
The final dispatcher [receipt](hepta-final-dispatcher.json) and
[33,590-byte log](hepta-final-dispatcher.json.85cf9a4704b54604bff6e23aa63a7fc2.log)
record 14 passes, exit 0, 81.901775713 seconds and SHA-256
`c8f1b83e5ab5eb403ca7d5719cfd8bea6e29eea0c71ff24d0c5ff690b592baee`.
All three retain clean matching 9438 commit/tree observations. The earlier
[final owner-only inspection](hepta-recovery-9438-owner-observation.json) and
[dispatcher exact-name inspection](hepta-final-dispatcher-roster-observation.json)
confirm the required selected names each passed once. The historical owner-only
inspection remains `NOT_PASSED` because signed evidence was not yet supplied
when that observation was recorded; it is not overwritten.

The final signed [receipt](hepta-final-recovery-signed.json) and
[31,238-byte log](hepta-final-recovery-signed.json.02f4394aa7b74d95920c19ad550ad6ba.log)
record 11 passes, exit 0, 8.255539793 seconds and SHA-256
`88dd6d57042320f41cc9758166761bcf14049a098beb74f6c38a55055e9ff440`.
Its summary reports 241 cases outside the exact filter; all 11 required names
passed once. The new [combined final 17/11 inspection](hepta-recovery-9438-selected-roster-observation.json)
records `LOCAL_ROSTERS_PASS` with `hosted_qualification=false`. It checks exact
source/tree, source-defined rosters and retained log hashes. It does not
complete the failed process gates or any hosted/independent deployment gate.

The [final source object](hepta-final-source-commit.json) and
[final environment](hepta-final-native-environment.json) retain
`9438a6c27a5e2f25169445f39499631db4e00529` /
`a9cba014de26164f0285c6c886fb071b19a04845`. The
[successful-old-source refusal](hepta-recovery-final-cross-source-refusal.json)
shows that the passing ff19 owner receipt is rejected when 9438 is requested;
this is a provenance check, not a failure of the original ff19 test run.

The additional full-library [receipt](hepta-final-evidence-all-lib.json) and
[98,540-byte log](hepta-final-evidence-all-lib.json.87fb01727a694674a032fb0a41392bba.log)
record **155 passed / 0 failed**, exit 0, 78.994334806 seconds, and SHA-256
`ec605f959a63eb50de4459f451b74040190fbc23b14f996c4e4bc09fbdfed5f8`.
The original 600-second budget and minimum17 remain. The library has **156
discovered cases, 155 eligible/executed, and one existing ignored subprocess
fixture**: `authbus_outbox_tests::crash_delivery_child` is marked `subprocess
crash fixture`, with parent tests responsible for launching it. This separate
local regression covers the shared typed decoders and existing callers. Its
155 passes include the 17 owner controls; do not add those totals or substitute
the full library for a hosted selected job. The first 97ae library timeout
remains unchanged.

The original process [receipt](hepta-final-product.json) and
[29,662-byte log](hepta-final-product.json.48a3714b131d4ce181e55109958c8171.log)
record **0 passed / 3 failed**, exit100, 40.827457140 seconds, and SHA-256
`b0482fa3d24ff0d0bee356bc4511c6ed18a43137fc015b60ecbafa214629414d`.
The recovery process [receipt](hepta-final-recovery-product.json) and
[29,567-byte log](hepta-final-recovery-product.json.eef56bd983c64e508b57e46f6bc5c43d.log)
record **2 passed / 2 failed**, exit100, 15.867673866 seconds, and SHA-256
`928f5f9b8ec947672247932179658e7772377168104db77976adac9881abf580`.
Both retain clean matching 9438 before/after identity, original 1,800-second
budgets, zero retries, one test thread and zero selected skips. The recovery
passes are `signed_recovery_frontier_rejects_valid_older_database_image` and
`signed_recovery_frontier_rejects_effect_only_database_rollback`. The failures
are the real composed Agentd startup and exact-current-database positive
paths. In all five failed process cases, Agentd's real Unix control-socket
bind returns EPERM. No process test was replaced with TCP or waived. The
[terminal regression inspection](hepta-final-runtime-regression-observation.json)
checks the original hashes, exact final source, 155 distinct eligible library
outcomes and both process rosters without rerunning a native command.

### Scoped lint completed with remaining warnings

The scoped fix [receipt](hepta-final-fix.json) and
[54,472-byte original log](hepta-final-fix.json.b4340218c5b74bb58250a5bd7923471e.log)
record **exit 0**, 778.748031740 seconds, and SHA-256
`4ae8d59c9261f9dd49f3d43705b37ec77c56889bb7693b68db40984620aa64ac`.
The original 1,200-second budget remains. The command is `just fix --locked`
scoped to `codex-hepta-evidence`, `codex-hepta-agentd` and
`codex-hepta-infer-worker-host`. Both source observations remain clean at
9438/a9, with no source changes and zero executed tests. Cargo's 12m50s line
is the compile interval, separate from the full invocation duration.

The log retains these project warnings:

| Location | Reported lint |
| --- | --- |
| `hepta-agentd/tests/cognitive_product_e2e.rs` | `clippy::type_complexity` |
| `hepta-agentd/src/intelligence_qualification_test_support.rs` | `clippy::duplicate_mod` |
| `hepta-agentd/src/evidence_frontier_tests.rs` | `clippy::expect_used` in the frontier test fixture |
| `hepta-evidence/src/recovery_invocation_schema_tests.rs` | `clippy::disallowed_methods` for direct SQLite test connection creation |

The original log also retains SQLx SQLite dependency deprecation warnings,
including its 40-warning summary and repeated dependency summary. Some
project diagnostics retain the underlying command-line deny-lint notes.
The observed fix command nevertheless exited 0 with warnings. Do not report
that all lint issues were repaired, that a strict `-D warnings` gate passed,
or that formatting or lint compilation executed the native tests.

The final format [receipt](hepta-final-fmt.json) and
[73-byte original log](hepta-final-fmt.json.9908e27b8ac147dbbbc2b3aafaa727cf.log)
record **exit 0**, 3.732444791 seconds and SHA-256
`b6a6d5ad920f48c9b49a3ca8c2308227b7849b9e0a498dc452f3a7bd2f7fb752`.
The original command is `just fmt`. Its log says no changed files needed
formatting and directs full-repository checking to `--all`; that broader
command was not run in this observation. Before/after source remains clean
9438/a9, with zero tests and no source changes. This closes the recorded local
format step without claiming a full-repository format audit.

Do not count a minimum as an observed total. A full library and an exact
selected owner run are distinct invocations; later completion cannot erase the
first timeout. Preserve failed, skipped, canceled and incomplete tasks in the
observation denominator. Per-test partial output does not supersede a failed
or missing terminal summary. The existing
[receipt reader](../../scripts/hepta_ci_exec.py) and
[workflow's exact-name audit](../../.github/workflows/hepta-pq-policy-renewal.yml)
remain authoritative for their respective checks.

The original [composition record](hepta-fixture-composition-alignment-20261105.json)
predates final commit import/publication and retains its original false
import/ref-update flags. The [created source object](hepta-fixture-composed-source-commit.json)
and later [local source composition review](hepta-ff19-source-composition-review.json)
bind the ff19 tree/parent and confirm only the two fixture paths change from
c90, preserving its 27 concurrent paths. Remote ref readback was performed by
the publication owner; local object review is not itself remote readback.

## 3. Current recovery contract

Ordinary Agentd startup now requires **frontier V4**, an ML-DSA-65 signature
under authentication profile `ml_dsa65_v2`, **snapshot V3**, and the existing
**signer trust V2**. Snapshot V3 retains the migration, qualification,
AuthBus-replay and provider-effect components and adds:

- `providerInvocationRows`: all retained ordinary governance invocation
  intent and terminal rows, including pending attempts and indeterminate
  outcomes.
- `providerInvocationFrontierSha256`: an ordered commitment to table identity,
  sequence, validated canonical payload digest and `recorded_at_ms`.

The scan reads intents before terminals, in sequence pages of 256, and fails
above one million combined rows. Each terminal must refer to its exact
authoritative intent. Validation and the complete commitment occur through the
same SQLite read transaction. The signature covers the new fields under the
current domain. Valid classical V1/V2 frontiers, incomplete PQ V3 frontiers,
old V2 snapshots and old signatures relabelled as the new schema do not gain
admission.

Before pagination, the narrow schema guard examines actual SQLite table and
index metadata. Each `seq` must be the sole INTEGER primary key and a rowid
alias. Required identity columns retain NOT NULL TEXT. Exact unconditional
BINARY unique keys must exist for intent `attempt_id`, intent
`(attempt_id, request_binding_id)`, terminal `receipt_id`, and terminal
`attempt_id`. Wrong-column, extra-column, partial, expression, non-unique and
differently collated indexes cannot substitute. This protects the recovery
scan's key assumptions and supplements the existing schema validator; it does
not certify the whole database schema.

Shared invocation decoders use fallible typed reads. A stored BLOB in a text
projection returns `EvidenceError::Corrupt` through the existing error path
instead of panicking. Source controls cover a real 257-terminal-row image whose
duplicate sequence would be hidden beyond the original 256-row walk, real
BLOB corruption after close/read-only reopen, original pending/terminal
history, authoritative-intent binding, and schema/key variants. Test bodies
are source evidence. Their exact owner selection failed during compilation
on `97ae5b4…`; all 17 selected owner controls now pass on `ff19c86…`, while
the intermediate dispatcher selection then failed to compile. Final9438
source/owner/dispatcher/signed selections passed independently; its full
library passed 155 eligible cases with one existing ignored fixture. Process
groups retain 0 passed / 3 failed and 2 passed / 2 failed; positive startup
and current-database admission are not qualified in this environment.

[`preflight_evidence_recovery`](../../codex-rs/hepta-agentd/src/evidence_frontier.rs)
loads the external authority with `load_evidence_recovery_for_config`, checks
an existing image through `check_existing_read_only`, and does not create,
migrate or bind that image. Ordinary `run` independently reloads/checks the
authority and compares the snapshot again after writable open and before
state/effect admission. A previous preflight is not a reusable grant.

Read the [current recovery contract](../../docs/lane-a-foundation/kernel.evidence/RECOVERY_FRONTIER_V1.md),
[invocation commitment](../../codex-rs/hepta-evidence/src/recovery_invocation_frontier.rs),
[actual SQLite key guard](../../codex-rs/hepta-evidence/src/recovery_invocation_schema.rs),
[fallible decoder](../../codex-rs/hepta-evidence/src/provider_record.rs),
[invocation controls](../../codex-rs/hepta-evidence/src/recovery_invocation_frontier_tests.rs)
and [schema controls](../../codex-rs/hepta-evidence/src/recovery_invocation_schema_tests.rs).

## 4. Gate and baseline maintenance did not grant acceptance

The workflow preserves all original seven recovery-owner and nine
signed-frontier IDs. Its current exact rosters are 17 and 11; existing
dispatcher and product rosters remain. Recovery limits remain 600 seconds,
process limits remain 1,800 seconds, dispatcher remains 3,600 seconds, retries
remain zero, and the job remains 90 minutes. Both x86_64 and arm64
source-head/prospective-merge lanes remain required for a PR.

The matrix and capability map were reordered to their existing canonical
seven-module/42-capability roster. Physical migration lineage, machine labels
and gate lists now consistently include 0001 through 0016. Missing document
sections and stale source/test anchors were repaired against actual current
calls. No original module, capability, section requirement or acceptance state
was removed.

The native-source manifest keeps its historical commit/blob provenance and
false execution/caller-proof flags. Current authority symbol requirements and
the observation-array digest were refreshed under the manifest's existing
provenance-only definition; current HEAD/tree/blob identities still require a
separate current-source observation. This is not a historical native pass.
See the [truth matrix](../../docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json),
[capability map](../../docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json), and
[native bindings](../../qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json).

## 5. Environment and failure-domain limits

The retained [97ae environment](hepta-native-environment.json),
[ff19 environment](hepta-composed-native-environment.json), and
[final9438 environment](hepta-final-native-environment.json) each keep their own
source identity. They record local Rust/Cargo 1.96.0, just **1.59.0** and
cargo-nextest **0.9.151**. The frozen workflow pins just **1.51.0** and nextest
**0.9.103**. The local runner uses one Cargo build job; the hosted workflow uses
two. Incremental compilation and test/dev debug information are disabled;
dependencies are offline and locked. These environment observations are not
attested reproductions of the hosted pins and do not supply executable hashes.
No environment record is relabelled for another source.

The separate [local unit-test binary observation](hepta-test-binary-observations-9438a6c27a5e.json)
has SHA-256 `f712627fc52a903bef3d769f98d64eaaac580f13bdc0ee525a0a81c14a167218`.
It records stable later hashes for two local debug test artifacts:

| Observed local artifact | SHA-256 |
| --- | --- |
| `codex_hepta_agentd-13943d509610e217` | `d818e4f5227342c78a05179fe383dd8082b3c1f95462478a8ad7a6717ddcf8aa` |
| `codex_hepta_evidence-0f5076227f347d3a` | `d74fd5a8153ecc0d7fc3b52ad7b17e541e1217aec37fab39c0a6e95f629915b3` |

The four included unit-test receipts have no `Running` binary-path lines.
Cargo fingerprints, dependency paths and mtimes provide local association,
not signed build provenance or the artifact hash at earlier execution. Read
the [observer's limits](hepta-test-binary-observations-README.txt). The
[later cache backup record](final-runtime-binary-cache-backup.json) preserves
five completed local debug artifacts, including process executables, using
gzip and verified decompression before removing cache copies while all three
Cargo locks were held and no original inode was running. The record keeps
`execution_binary_hash_binding=false` and
`independent_deployment_qualified=false`. Neither artifact observation is a
release/deployment qualification. Backup archives remain private.

The final environment record binds these SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| `codex-rs/Cargo.lock` | `0f458d7746a0ca0b95bedc5404fd3347c1b0a7508f1c387f3b1f3f71ced08663` |
| `codex-rs/Cargo.toml` | `0a5c94692252cc1b0511be6c053201596788f24da3406b9a741cddb195681c69` |
| `codex-rs/rust-toolchain.toml` | `e8b379eaa492bf59d35187de269afd1c4f55d85e0322f6fea32803a3fec1a380` |

The shared disk filled during parallel heavy builds. Subsequent heavy native
test execution was serialized and superseded Chain cache was reclaimed;
source and raw logs were preserved. After cleanup, the separate final Chain
test-build-only invocation overlapped Runtime scoped lint. `--no-run` compiles
without executing test bodies; actual native test execution remains sequential.
Warm caches or a changed build schedule do not turn the original timeout into
success.

Unix-domain socket bind was already observed to fail with **EPERM** in this
container. Earlier TCP bind success does not satisfy Unix-dependent product
prerequisites. Both final process groups reproduced the real control-socket
failure. All five failed cases remain failed; there is no bypass,
selected-skip credit or relaxed acceptance gate. Library success alone cannot
establish successful Agentd startup. Preserve the original environment
observation alongside the actual failed process logs.

## 6. All six system domains remain HOLD

| Domain | Still required | Verdict |
| --- | --- | --- |
| Every authorization entry | Ordinary account/governance/publication/recovery and CURRENT-to-FinalUse real effects must remain under the same current PQ root, including revoked/retired-key and downgrade negatives. | **HOLD** |
| Work and proof | Complete native relation and actual proof for the new statement/`IMAGE_ID`; explicit instantiated quantum/QROM objective, assumptions, losses and whole proving-to-confirmation costs. The research `2^-128` failure budget is not a protocol guarantee or quantum work factor. | **HOLD** |
| Mining and fork choice | Cheapest legal work and preprocessing, DAA/time, private forks and propagation must be established jointly. A mining time fix or formal model test is insufficient. | **HOLD** |
| Historical migration | Independent freshness, consumed rights/nonces/debts/retired keys, stable effect reconciliation, and the old-Q0 whole-machine restore case must hold across owners. | **HOLD** |
| Hostile capacity | Real PQ wire, memory, tails, History/recovery and the original four-second/16-hostile-W1 and 4,105-block/four-renewal campaigns, with failures and incomplete tasks retained. | **HOLD** |
| Independent deployment | Fixed source and actual binary/config pins, separate administration and failure domains, at least three independent operators, and the preregistered at-least-72-hour campaign. | **HOLD** |

The concrete Q0 gap remains: a matching old database S0 plus valid checkpoint
Q0 can be restored after consumption or an external effect advances only local
state to S1, before an independent authority retains Q1. A signature cannot
distinguish that restored old pair from the old valid state. A canonical file
path outside Agent-owned roots is not an independent rollback domain.

The implementation verifies supplied signed files. It does not implement an
authenticated fresh remote frontier fetch, expected-old CAS, durable co-signing
or atomic external consume/checkpoint publication before every provider call.
It also does not cover the separate AutomationStore owner or compose FinalUse
consumption atomically with its budget and effect journal. Retaining invocation
history broadens what a fresh frontier commits; it does not close these
external synchronization windows or authorize a new provider operation.

## 7. Reproduction commands and exact selections

Choose the original `97ae5b4…` only to reproduce its original observations;
choose `ff19c86b7190204e9172a1595a58d8eb9f897c6d` /
`1c34e75019730bfdd238ebc612701d9f9583759d` only for the intermediate
source's observations. Use the separately supplied final commit/tree for
revalidation after the dispatcher fixture-import repair: final source
`9438a6c27a5e2f25169445f39499631db4e00529`, tree
`a9cba014de26164f0285c6c886fb071b19a04845`.
Publication/local alignment has been confirmed, and each invocation still
requires its own source-bound receipt.
Use an isolated checkout and a distinct output directory for each source and
attempt. Retain full source/environment and binary identities, and use the
pinned hosted tools when claiming the hosted
lane. These commands document the existing selected invocations; they were
not run while writing this README. Put receipts outside the source checkout
and run heavy commands sequentially. Preserve original budgets and zero
retries. The 90-minute workflow limit and all architecture/merge lanes remain
independent requirements.

```sh
set -euo pipefail
export GIT_NO_LAZY_FETCH=1 GIT_NO_REPLACE_OBJECTS=1
: "${HEPTA_TESTED_COMMIT:?set the explicit original or repaired commit}"
: "${HEPTA_TESTED_TREE:?set its matching tree}"
test "$(git rev-parse HEAD)" = "$HEPTA_TESTED_COMMIT"
test "$(git rev-parse HEAD^{tree})" = "$HEPTA_TESTED_TREE"
: "${HEPTA_EVIDENCE_DIR:?set an external evidence directory}"
mkdir -p "$HEPTA_EVIDENCE_DIR"
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/verify_lane_a_foundation.py self-test
```

Use the original dispatcher and product selections from the
[fixed workflow](../../.github/workflows/hepta-pq-policy-renewal.yml). The three
recovery selections below copy its exact names, package, budget and retry
settings. Their minimum counts are guards, not an execution result.

### Recovery owner: exact 17-test selection

```sh
python3 scripts/hepta_ci_exec.py \
  --output "$HEPTA_EVIDENCE_DIR/recovery-owner.json" \
  --minimum-tests 17 --timeout-seconds 600 -- \
  just test --locked -p codex-hepta-evidence --lib \
  -E 'test(=recovery_effect_frontier_tests::recovery_snapshot_commits_intent_unknown_and_original_operation_receipt)
  | test(=recovery_effect_frontier_tests::recovery_snapshot_distinguishes_a_valid_effect_only_database_rollback)
  | test(=recovery_effect_frontier_tests::recovery_snapshot_commits_ack_provenance_and_cross_table_order)
  | test(=recovery_effect_frontier_tests::recovery_snapshot_commits_effect_history_after_the_first_page)
  | test(=recovery_effect_frontier_tests::recovery_snapshot_refuses_changed_json_with_retained_record_digests)
  | test(=provider_effect_recovery_provenance_tests::recovery_provenance_rejects_late_dispatch_after_status_without_uncertainty)
  | test(=provider_effect_recovery_provenance_tests::recovery_provenance_preserves_dispatch_then_authoritative_status)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_commits_pending_invocations_and_terminal_states)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_commits_invocations_after_the_first_page)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_revalidates_invocation_payloads_and_projected_columns)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_requires_the_terminals_authoritative_intent)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_refuses_duplicate_terminal_hidden_at_page_boundary)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_refuses_invocation_column_type_corruption_without_panicking)
  | test(=recovery_invocation_frontier_tests::recovery_snapshot_binds_invocation_sequence_and_recording_time)
  | test(=recovery_invocation_schema_tests::recovery_invocation_schema_accepts_current_migration_keys)
  | test(=recovery_invocation_schema_tests::recovery_invocation_schema_refuses_non_rowid_or_composite_sequences)
  | test(=recovery_invocation_schema_tests::recovery_invocation_schema_requires_exact_unconditional_column_uniqueness)' \
  --no-capture --retries 0 --test-threads=1
```

### Recovery signed: exact 11-test selection

```sh
python3 scripts/hepta_ci_exec.py \
  --output "$HEPTA_EVIDENCE_DIR/recovery-signed.json" \
  --minimum-tests 11 --timeout-seconds 600 -- \
  just test --locked -p codex-hepta-agentd --lib \
  -E 'test(=evidence_frontier::tests::recovery_frontier_refuses_valid_classical_v1_and_v2_signatures)
  | test(=evidence_frontier::tests::recovery_frontier_authenticates_both_effect_fields)
  | test(=evidence_frontier::tests::recovery_frontier_pq_survives_store_close_and_reopen)
  | test(=evidence_frontier::tests::recovery_frontier_read_only_preflight_never_binds_or_changes_the_image)
  | test(=evidence_frontier::tests::recovery_frontier_cannot_be_omitted_at_the_ordinary_agentd_run_entry)
  | test(=evidence_frontier::tests::recovery_frontier_rejects_wrong_domain_and_profile)
  | test(=evidence_frontier::tests::recovery_frontier_enforces_root_scope_epoch_revocation_and_generation_floor)
  | test(=evidence_frontier::tests::recovery_frontier_rejects_wrong_key_pin_and_noncanonical_signature)
  | test(=evidence_frontier::tests::recovery_frontier_root_rotation_retires_the_old_key)
  | test(=evidence_frontier::tests::recovery_frontier_refuses_valid_pq_v3_and_relabelled_v2_snapshots)
  | test(=evidence_frontier::tests::recovery_frontier_pq_rejects_invocation_only_database_rollbacks)' \
  --no-capture --retries 0 --test-threads=1
```

### Recovery product: exact 4-test selection

```sh
python3 scripts/hepta_ci_exec.py \
  --output "$HEPTA_EVIDENCE_DIR/recovery-product.json" \
  --minimum-tests 4 --timeout-seconds 1800 -- \
  just test --locked -p codex-hepta-agentd --test kernel_evidence_product \
  -E 'test(=real_agentd_composes_authenticated_evidence_writer_query_verifier_and_terminal_observer)
  | test(=signed_recovery_frontier_allows_exact_current_database)
  | test(=signed_recovery_frontier_rejects_valid_older_database_image)
  | test(=signed_recovery_frontier_rejects_effect_only_database_rollback)' \
  --no-capture --retries 0 --test-threads=1
```

After every required group, execute the unchanged workflow's exact-name,
exact-once/no-selected-skip audit. A summary count alone is insufficient.
Retain both initial failed and later successful attempts with their own raw
logs and original source identities. The supplementary
[receipt inspection script](verify_hepta_recovery_receipts.py) can inspect
owner/signed evidence, but neither runs tests nor attests the hosted tools,
binary identity, process controls or independent deployment.

The supplementary inspector now requires explicit full `--source` and `--tree`
arguments. It reads the workflow and official summary reader from that commit,
then rejects receipt source/tree mismatches. Run it separately for each source;
missing, running and failed receipts never pass. For example, inspection of
the original owner failure below is expected to return nonzero:

```sh
python3 verify_hepta_recovery_receipts.py \
  --repo "$HEPTA_REPO" \
  --source 97ae5b4bf5e5f0d0589c1c653f1861e1d9c1242f \
  --tree fdce3b8e854629315cea088f5d549aed3f8b2021 \
  --owner-receipt "$HEPTA_EVIDENCE_DIR/hepta-recovery-owner.json"
```

Use a new output filename for a repaired-source inspection. Preserve the
original receipt, original raw log and earlier NOT_PASSED inspection; do not
replace them with the repair's result.

The completed final-source owner/signed pair can be checked without native
execution using its own explicit identity and retained sibling logs:

```sh
python3 verify_hepta_recovery_receipts.py \
  --repo "$HEPTA_REPO" --tool-dir "$HEPTA_TOOL_DIR" \
  --source 9438a6c27a5e2f25169445f39499631db4e00529 \
  --tree a9cba014de26164f0285c6c886fb071b19a04845 \
  --owner-receipt "$HEPTA_EVIDENCE_DIR/hepta-final-recovery-owner.json" \
  --signed-receipt "$HEPTA_EVIDENCE_DIR/hepta-final-recovery-signed.json"
```

Set `HEPTA_TOOL_DIR` to the directory containing the intended local `just` and
`cargo-nextest` binaries. Tool version probing is an observation, not proof that
those executables ran an earlier receipt. The recorded result for this pair is
`LOCAL_ROSTERS_PASS`; the two failed process groups remain separate failures.

## 8. Evidence publication and remaining holds

This directory is the prepared evidence-only follow-up to frozen Runtime source
9438. Its actual containing Git commit identifies publication once created;
the receipt fields continue to name their original tested source/tree. The
original siblings retain their bytes and recorded hashes. Publication and ref
readback are separate observations and do not rerun the final source.

All local commands in this round are terminal. The record retains the old
full-library timeout, selected-owner compile failure and intermediate
dispatcher compile failure, both final process-group failures, the existing
ignored library fixture, and the remaining fix-command warnings. The last
format command made no source changes and executed no tests.

Execution-bound binary identity and required hosted source-head/merge lanes
remain **HOLD**. Independent administration, Q0 freshness,
CURRENT-to-FinalUse effects, the W1/quantum obligations and the original
service/History gates also remain **HOLD**. Local successes, source stability
and evidence publication do not grant those system properties.
