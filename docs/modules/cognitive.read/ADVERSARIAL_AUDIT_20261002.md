# cognitive.read continuation audit, 2026-10-02

## Exact starting point and evidence

The independently observed candidate is
`ab60cb27a160dd350a6b89d2ac7dffa33d9a23d1`, tree
`02fbbdb413956fac9df050e63634c000978c69ec`, from
[PR 1302](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1302).
Live branch refs were checked against stacked base
`8a2f9256102a7bf36fbab4f22152573ba8fb91ad` and main
`c6f90d48c40f7b5267db587bb3c3f4934f1414a8`. These are distinct source identities;
the stacked base is not implicitly current main.

[Qualification run 36799382189](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36799382189)
failed both the exact-head and synthetic-merge jobs. The exact-head artifact
`11137329634` was downloaded and its ZIP digest, tar digest and every retained
file checksum verified. ZIP SHA-256 is
`09f85695e5d9f7b936d71ccfc3dbeede553f5fc4241263a3a8a2641da26fa17a`;
tar SHA-256 is
`7ddc9337ccb047f2ec553e1c5fe8399d32ca5dcbee8953cb7198130601cb9515`.
The exact-head receipt records 47 gates: 39 successful, eight unsuccessful.
Those counts describe that old exact candidate only.

## Reproduced failures, repairs and outstanding work

| Boundary | Evidence and action | Remaining verification |
| --- | --- | --- |
| Qualification toolchain | Format and both strict-lint gates failed because the explicitly selected Rust 1.95 toolchain lacked rustfmt/clippy. Both workflow lanes now install and verify these components using the same validated candidate pin as the qualifier. Shell behavior tests verify the pin overrides the runner default and installation failure stops immediately. | Execute both complete workflow lanes on the new committed candidate; installing components is not a lint pass. |
| Cold recovery witness fixture | The exact CI failure, `trigger ... already exists`, reproduced twice locally. The test now captures schema, drops the guard, introduces witness drift and restores the exact guard in one SQLite transaction. The repaired case passes and reaches the intended live-owner and cold-image rejection assertions. | The owner package still has the separate deep-history timeout below. No production schema, guard or recovery admission rule was weakened. |
| Native final-use fixture startup | The helper attached a real cognitive owner but omitted `mark_runtime_prerequisites_ready`; Health therefore retained false critical-store/revocation prerequisites forever. The helper now mirrors the default production startup sequence before socket binding. Three authored regressions require the actual owner, prerequisites and App Server readiness. | All three new Agentd readiness regressions pass locally. Physical worker qualification remains separate. The helper uses the documented zero-production-effect revocation baseline; it does not install an effect grant. Worker final-use authorization stays independent. |
| Deep owner history | The unchanged 17,000-revision case times out at the existing 60-second limit. Independent SQLite runs over the compiled migrations measure about 5.14M, 20.04M and 79.08M VM instructions for 250, 500 and 1,000 same-scope revision appends. Canonical per-append counter audits explain approximately fourfold work for each doubling. | Migration `0021` keeps canonical per-write checks while using indexed first/last scope keys to prove when SQLite table counts equal filtered scope counts. Mixed-scope counts retain the canonical query; global reopen audits remain independent. The unchanged 17,000-history Rust test now passes in 5.617 seconds. The test, data size, ancestry ceiling and timeout were preserved. Mixed-scope and tombstone-heavy history can still require proportional recount work; this is not a universal constant-time write or production p99 claim. |
| Agentd recovery and unavailable-owner cases | The retained package log rejects incomplete immutable recovery-file identity; a separate old availability fixture waits for readiness without its now-required cognitive owner. | Diagnose and reconcile each owner contract. Do not relax immutable-identity or readiness checks to obtain green tests. |
| Intelligence product cases | Positive admission and final-use revocation tests both fail earlier at `EvaluationAdmitted`. | Repair the caller/fixture under its current authenticated evaluation contract; these failures do not exercise the claimed final-use boundary. |

## Projection, ownership and consumer assessment

The bounded source review covered exact-ID request validation and complete byte
preflight, canonical V1/V2 bindings and decoding, prepared immutable borrows,
canonical shadow source-revision bridges, selected owner witness acquisition,
clock regression and validity transitions, Agentd publication/final-use ordering,
retained preparation identity, and native dispatch-before-final-use ordering.
No new bypass of these projection/currentness checks was reproduced in this pass.
That is a scoped negative result, not proof of exhaustive correctness.

Partial structural snapshots and cross-record or unselected-fork predecessors
are deliberate compatibility inputs. The read crate cannot infer missing
ancestors or authenticate source ownership. The durable SQLite owner separately
validates complete selected ancestry. This audit did not incorrectly strengthen
the transient API by turning those compatibility cases into owner assertions.

All seven consumer package gates passed on the retained exact head, but their
normal-product states remain different:

- `compact.engine`: exact-owner candidate API; no ordinary checkpoint publisher
- `context.compiler`: legacy product path; V2 ingress source exists, provider-bound use pending
- `memory.federation`: local owner/extension composition; cross-host admission remains separate
- `memory.retrieval`: ordinary Agentd/worker source path; physical final-use qualification blocked
- `neuron.runtime`: owner source; daemon lifecycle composition pending
- `objective.compiler`: authenticated source composition; activation pending
- `utility.ndu`: request-local deny-all planning; authenticated production composition pending

The failed intelligence gate blocks several consumer rows even though each
package passed. Preparation protocol, ledger preparation, native handoff,
delivery join, witness-integrity and the narrower owner-currentness cases passed
in the retained artifact. None substitutes for the failed physical-worker gate.
Every V2 migration flag and independent acceptance/activation/release flag stays
false. SQLite remains Fact-only; no memory-kind migration was introduced.

## Fresh local observations and completion boundary

- Unmodified baseline core: `just test --locked --offline -p codex-hepta-cognitive-read`, 56 passed
- Repaired cold-recovery case: one passed, after two reproduced baseline failures
- Cognitive Python regression suite after count-path repair: 105 passed, including four new upgrade/equivalence, forgery/orphan and VM-work regressions
- Complete memory package after count-path repair: 287 passed, seven original skips; the unchanged deep-history case passes in 5.617 seconds (14.897 seconds for package execution, excluding build)
- Scoped `just fix --locked --offline -p codex-hepta-memory` completed; repository `just fmt` completed after directing DotSlash to its existing writable tool cache, with unrelated baseline formatting churn restored
- New Agentd startup regressions: three passed; complete Agentd package: 201 passed, 25 failed, six skipped (socket EPERM plus retained recovery/unavailable-owner failures)

Local observations use the original workspace lockfile and a dedicated bounded
build target. They are not rebound into an immutable final-head or synthetic-merge
qualification receipt. Detailed developer documentation exists, but completion
still requires selected-host/mixed-scope performance qualification, fresh complete source/merge execution,
physical consumer qualification, independent review and operator-selected host
acceptance. No numeric completion percentage or production readiness claim is
justified by the current evidence.

## Count-path invariants

The optimized current-scope view is used only for checking a witness already
selected by an immutable owner key. Missing-witness detection remains fail-closed:
all maintenance triggers require a valid witness after their write, and the global
reopen audit still derives scopes from canonical source and memory rows. The
complete schema inventory and independent schema digest include the new views
and tombstone index. Old migration files and their checksums are unchanged.

Whole-table child counts are equivalent because citation, fact and head foreign
keys reference unique immutable memory revisions. Ordinary and recovery opens
independently reject pre-existing FK violations. Even with foreign keys disabled,
new orphan child insertions abort through the retained post-write witness guards.
Direct counter forgery, empty scopes, mixed-scope head updates/deletes, and upgrade
from migration 20 are checked against the independent unoptimized audit. No
mutable counter is used to infer that all source rows share a scope.

Independent review repeated all four new SQL cases and exercised 120 mixed-scope
source/memory/citation/fact appends with head updates/deletes, comparing both
expected views after each step. No additional scoped invariant defect was found.
The 50M-VM-operation regression limits SQL interpreter work, not SQLite internal
B-tree traversal performed by COUNT; no asymptotic wall-clock claim follows.

The attempted targeted Agentd/core build exhausted the shared filesystem during
compilation of codex-mcp/codex-rollout, before those tests could execute. Its log
is retained; the reproducible incremental build cache was cleared. This is not
an Agentd test pass and does not supersede earlier physical-worker blockers.

After reclaiming only reproducible build caches, the Agentd retry compiled all
18 test binaries successfully. A first module-path filter selected zero tests;
the corrected exact-name filter ran and passed all three new readiness tests.
The subsequent complete package executed 226 tests: 201 passed, 25 failed and
six were skipped. Physical socket cases remain blocked by EPERM; the original
immutable recovery-file identity and unavailable-owner readiness issues remain
reported rather than being converted into authority or weakened assertions.
Core rerun: 56 passed. Final scoped memory fix and repository format completed;
unrelated baseline formatting churn was restored. No claim is made that all
Agentd or source/merge qualification gates pass.

The connector-published source commit `ba347dbf5e173c7af455060a703f9214bf7beac4`
has exact tree `5bedf33fdcd4b209613fe8d2e9531a0f8c071ce9`, byte-identical to local
source `8c8e69bbf` (including fixture predecessor `989e1261b`). The metadata child
records this source identity, not a new execution or acceptance receipt.

## Follow-up recovery lifecycle and unavailable-owner startup

The complete Agentd run has 23 explicit Unix-socket EPERM failures, one product
recovery identity rejection, and one runtime.codex provider mock expectation
failure (zero requests). The latter installs its expectation before waiting for
Agentd readiness, so a startup failure can be masked by the mock's destructor.
The expectation now installs only after readiness, preserving the one-request
assertion for any run that actually reaches the provider boundary.

The recovery product fixture dropped the SQLite store without awaiting worker
closure, unlike the passing internal recovery cases. `CognitiveStore::close`
now explicitly awaits closure of the shared pool; all cloned handles become
closed, and retained clones still hold the owner lock until dropped. The fixture
awaits closure before attempting immutable recovery identity binding. All 14
owner recovery tests and the complete 287-test memory package pass after this
change. The actual product recovery fixture remains to be executed on the new
candidate; this is a lifecycle repair, not a claimed proof that every observed
identity rejection had this cause. Descriptor, sidecar and metadata validation
are unchanged.

Default runtime startup previously permitted an unavailable cognitive runtime,
but `state.rs::mark_runtime_prerequisites_ready` requires the actual cognitive
owner to establish `critical_stores_ready`. This leaves a process waiting for a
readiness state it cannot obtain. Lane B runtime composition section 5 requires
owner physical state before readiness; section 13 requires critical-store
uncertainty to remain not-ready/quarantined. Its explicit optional-advisory
fallback does not classify the critical cognitive owner as optional.

The default profile now reports `critical cognitive owner unavailable` before
opening its control socket or App Server. The obsolete positive degraded-startup
fixture is replaced by the existing fail-closed product scenario, exercised in
both profiles with their respective diagnostic. A default-profile unit case
covers the gate; the product case also requires no control socket was created.
Available-owner behavior and the qualification writer's authority checks do not
change. Migration impact: an unavailable default owner produces an immediate
startup failure instead of an indefinitely not-ready daemon. This grants no
writer or degraded-ready capability. These new Agentd cases are pending fresh
execution; earlier 201/25/6 package counts describe the pre-follow-up source.

## Verified hosted continuation at 8145cc37

The repair checks below initially ran on an unpublished mixed worktree. They
are historical evidence and are not execution receipts for the independent
continuation described at the end of this report.

Run `36982711540` produced separate exact-head and synthetic-merge receipts for
identical tree `d879624146f7ab3183149097e7126608a6647dc5`. Both archives and their
inner file checksums were verified. Each passed 41 of 47 command gates; the
overall qualification remains failed. Owner tests passed all 287 cases, and
Agentd executed 225 passing cases with two failures, including successful real
socket/provider flows previously blocked locally. The unchanged 17,000-history
case passed. Delivery, preparation, witness integrity and owner-currentness
checks passed in both receipts.

The remaining evidence drives a further repair round:

- Migrate the older duplicate degraded-startup unit assertion to the same
  critical-owner contract; retain one canonical test case.
- The recovery product test now reaches writer admission. Its pre-writer anchor
  cannot equal the post-acquisition state after an authenticated lease append.
  Check unchanged predecessor bytes, owner/schema continuity, a distinct
  recovered database and the actual new writer lease instead.
- Reconcile completed assistant-message snapshots with streamed deltas so a
  successful real turn cannot silently return empty output for valid
  completed-only messages. Preserve per-item bounds and reject post-completion drift.
- Reuse the existing independently signed evaluation fixture and activated host
  trust for the two legacy positive/final-use tests. Do not bypass evaluation
  admission or change production evidence validation.
- Route AuthBus SQLite construction through the central owner shim while
  preserving its durable and transient pool policies; fix mechanical closures.
- Commit the standalone fuzz workspace lock and require `--locked`; do not
  exempt an untracked lockfile from source sealing.
- Build the Codex executable before the Agentd process workflow's library tests
  that invoke a real App Server.

These are pending repair/verification items, not a passing replacement receipt.
Exact-head artifact `11217416946` has ZIP SHA-256
`ebacff2dfb21f175619d7511e46f23fbfb8479d82e62e906f8d55bc27b0d2cef`;
merge artifact `11218020810` has ZIP SHA-256
`61bfe3fd9077cf9786753bd69902225a0109d8a5e2ea343dbf0e1b7a4f4dbd89`.

Local repair checks completed so far: the message collector's nine focused
cases pass on the complete dependency graph, including completed-only text,
interleaved items, duplicate/conflicting snapshots, foreign turn isolation,
Unicode byte limits and the 1,024-item bound. Item completion does not establish
terminal turn success. Cognitive evidence Python tests pass 106 cases; the
Agentd process workflow tests pass 16 cases. The standalone fuzz harness passes
its locked all-target compilation; this is not a fuzz campaign receipt.

The blocking workflow at this source also passes Rust formatting, Python SDK
and all three host-native path checks. Its repository/Bazel preflight fails two
workspace-manifest test expectations (changed diagnostic wording and a larger
reviewed exception set); both verifier and tests are byte-identical to stacked
base `ab60cb27a160dd350a6b89d2ac7dffa33d9a23d1`, and a local run reproduces
9 passing / 2 failing tests. These failures do not justify weakening the feature
policy or claiming that the broad blocking workflow passes.

The targeted unavailable-owner and final-use revocation cases pass. The recovery
product fixture also passes with the new lease-aware assertions after a build
retry; the initial attempt never executed a test because a concurrent cache
fetch exhausted disk during linking. Both attempt logs are retained.

The signed legacy positive case exposed a second issue at decision append:
`MissingAbstainCandidate`. The qualification-only adapter forwarded policy
actions as a complete ledger universe. The ledger's existing shadow adapter
reserves and inserts the intrinsic abstain alternative itself; inserting a fake
policy action in the fixture would change the policy universe. Reuse the narrow
reviewed `intelligence_learning_candidates` helper from intelligence candidate
`5dd6acba5b5cc1ab4218953b9aa2924a23cfc86a` only in the qualification-gated legacy
append path. It rejects empty, duplicate, reserved-abstain and over-capacity
inputs and produces a sorted fresh ledger candidate list. Canonical bindings,
modern signed payload construction and persisted records are unchanged. Tests
also check that the original prepared action list remains unchanged. This
adapter repair is pending its targeted rerun.

The fresh targeted rerun after the intrinsic-candidate adapter repair passes all
five selected tests: decision/outcome/reopen, final-use revocation, default
unavailable owner, canonical projection/rejections and candidate-capacity bound.
The canonical action list remains unchanged while the new legacy ledger event
contains the intrinsic abstain alternative. These focused checks do not replace
the pending full hosted qualification or authorize a production legacy writer.


## Independent continuation from 8145cc37

The isolated continuation extracts 15 source, fixture, workflow and documentation
files from the reviewed repair set. It includes completed-message collection,
legacy candidate completeness, signed positive fixtures, the default-owner unit
expectation, recovery lease assertions and building Codex before physical-worker
library tests. It makes no Cargo manifest or root dependency-lock change.

All nine AuthBus/state-shim/dependency files remain exactly as in the 8145cc37
base. The separate AuthBus schema fixture and dependency-lock repair is deferred.
Original strict-lint errors in those unchanged AuthBus files remain unresolved.

Three independent but coupled files are also deferred: the standalone fuzz
Cargo.lock, the evidence command's --locked flag and its unit test. The repository
requires a Bazel lock refresh for lockfile changes; that dependency work is
outside this isolated continuation. The original hosted untracked-fuzz
lock/source-sealing failure remains visible and unresolved here.

The earlier five Agentd, one recovery and nine output-collector passes were run
against the mixed worktree and are not transferred to this isolated candidate.
Fresh isolated verification is recorded below. No executable, activation, independent
acceptance or release claim is promoted by this extraction.

Fresh isolated lightweight checks pass: 105 cognitive Python cases and 16
Agentd workflow cases. The earlier 106 count included the deferred fuzz-command
regression. Fresh isolated Rust checks now pass: five selected Agentd cases, the product
recovery case, and nine completed-output collector/observation cases. The
Agentd suite includes both legacy integration cases and the intrinsic-candidate
rejection/capacity tests. These are new executions with the base AuthBus and
root lock, not transfers of mixed-worktree results. Full hosted qualification
and the deferred dependency/source-sealing repairs remain outstanding.

Scoped `just fix` completed; unrelated baseline suggestions were restored, and
only an equivalent collapsed conditional in the edited worker was retained.
Repository formatting completed, with unrelated baseline formatting restored.
A fresh strict all-target Agentd/worker Clippy attempt stops in unchanged
`core/src/client.rs::map_response_events` (eight arguments, lint limit seven).
That file is byte-identical to 8145cc37. This is an additional inherited lint
blocker; it does not establish that downstream AuthBus lint errors are resolved.
No lint policy or authority validation was relaxed. The focused test receipts
precede the final mechanical fix/format, following the repository workflow.
