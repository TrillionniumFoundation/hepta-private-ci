# P1–P4 current-source blocker audit — 2026-10-20

## Decision

This is a read-only, exact-source review. It identifies reusable engineering work and remaining software gaps, without treating fixture tests, reference math, self-asserted observer fields, or historical branch checks as production qualification. Permission posture remains **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.

The most immediate source-backed work is to reuse the existing #2850 matrix validation repair, reconcile #2734 telemetry availability with the stronger #2918 metrics design, and preserve #2918's already-tested FinalUse/Q24/B4 composition. A separate canonical physical CellSplit chain already exists under #2684; the #2734 Supervisor example must not become a second executor.

No production files, frozen Windows files, CI workflows, Git refs or remote PRs were changed by this audit. No Cargo build, model download, actual target-host workload, independent signature or physical split was performed. The only new local execution was an eight-outcome Python adversarial repro against immutable validator source copies.

## Exact owner and qualification bindings

The PR API's recorded base is distinguished from a live branch when drift is observed. Complete PR metadata, check runs and comparisons are in `github_snapshot.json`, `followup_snapshot.json` and `canonical_owner_dag.json`; all inspected source copies have verified Git blobs in `source_bindings.json`.

| Owner | Source head | PR-recorded base | Synthetic merge | Current evidence boundary |
|---|---|---|---|---|
| #2734 Cell data plane / Scope WAL / secondary Supervisor seam | `dc271d4f47028e941decce70cc8ef81fb24d2141` | main `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | `cb55c1e964f6a6bf80cd2d51ebc0caea56e16184` | Original Windows WAL failure; current report validator has reproduced acceptance defects. |
| #2918 signed Neuron / microbatch / Q24 + independent B4 | `ca5b70d2684fb96063f5b70bb276525906dae7b6` | #2757 `b920d259bfc55c4afb6f0f9ab0f9698e72db1add` | `a613f63377b7776ff14d44c63c3ef1d5948658b9` | Exact-source signed lane succeeds; global required CI remains failed. |
| #2695 shared Encoder / lightweight Head / NDU shadow | `ecc4f8c42035bf6fdec288137ddc822e619d5e59` | main `f8c9419df6ddeb36ff8b522a50219981fb8d9345` | `fa7867406e0c76dd0e596e4044a29137745a82de` | Concrete trait and bounded shared-buffer seams; no inspected pinned pretrained driver/real future-window qualification. |
| #2920 caller candidate | `20bf22ba773148a28a1e6b0d16b8401b731d37db` | #2757 `b920d259bfc55c4afb6f0f9ab0f9698e72db1add` | `8006ff8b98f909da01b4b77fd3ae9e2eac7165d3` | Actual signed lane fails its caller proof. |
| #2921 caller candidate | `22293e588c95f4fcb5b45907eb4fed3b73fdb755` | #2757 `b920d259bfc55c4afb6f0f9ab0f9698e72db1add` | `64dfd477668c495a03bff2e07b02e701dfdeba2e` | Caller parity succeeds, but it is not the complete #2918 Q24 + independent-B4 composition. |
| #2850 existing four-scale matrix repair | `05cf9bb88fc22054ebda949b34d95e908c4ab9de` | old #2734 `3d4cc109ee04cfcdae1f74dde395d3fb7b8622fe` | `2ed23fc3b3282b62b53c10e5cd14a898fc449f04` | 27 exact-source Python contract tests pass; relative to current dc271: diverged, ahead 1 / behind 2. |
| #2684 canonical CellSplit | `b5d32004467c1d9fc7fe27ff9dbf9fbf0a13f6d7` | #2642 `f4a688592a0102f82dfe086b2b2c9f7c5224e89f` | `375306f6ef9140213206320c429fdd8792663348` | Actual source-head Architecture succeeds, including 69 canonical owner tests; global required CI fails. |

### Raw executed evidence

| PR / job | What actually executed | What it does not qualify |
|---|---|---|
| #2918 [118223944566](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39300447494/job/118223944566) | Checkout ca5b70; caller proof scans 4,409 Rust files; five independent B4 Python tests pass, including `test_signed_neuron_final_use_callers_match_both_inventories`; Rust result groups 81, 89 and 7 passed, all zero failed. CALLERS / INDEPENDENT_B4 / FORMAT / TESTS / COMPILE / QUALIFICATION / CLIPPY succeed. | Current main merge/global CI, independent signer custody, pretrained model performance or physical owner effects. |
| #2920 [118411015933](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39356071148/job/118411015933) | Checkout 20bf22; `final_use_guarded_effect` caller mismatch: unexpected Neuron runtime and worker paths. Other Rust groups 81/89/5 pass, while CALLERS fails. | A successful caller closure. Passing unrelated tests does not erase the failure. |
| #2921 [118411313757](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39356162951/job/118411313757) | Checkout 22293e; caller closed-set succeeds; Rust groups 81/89/5 pass and signed lane succeeds. | The two additional #2918 Q24 tests or #2918 independent B4 workflow step. |
| #2850 [117703142266](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39136901877/job/117703142266) | Explicit EXPECTED_SHA 05cf9bb, pytest 8.4.2, cryptography 46.0.4, **27 passed in 12.88s**; both scripts formatted and checkout clean. | 64 real native workload executions, measured target-host scale, independent production attestation. |
| #2684 [117564830781](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39089565684/job/117564830781) | Actual source-head gate includes **69 canonical execution-owner tests passed**, plus nonzero native CNS/Supervisor/target-host fixture groups and focused post-effect withdrawal regressions. | Independently held production signers, atomic original Control B→effect→C, physical power-loss/target-host approval. |

Raw logs are preserved as gzip without changing decoded bytes; SHA-256, run/source bindings and concise excerpts are in `log_index.json` and `logs/`. A zero-test filtered group is not counted as executed evidence. A result group is not a count of independent production scenarios.

## S1 — #2920 still omits two guarded-effect callers; #2918 already closes it

`CALLERS.toml` on #2920, blob `494c0b6b90fe4baf764d8503296738b2cbe2471f`, lists the two Neuron paths under `final_use_claim` but omits them from `final_use_guarded_effect`. Its latter set contains only `hepta-automation/src/authorized_effect.rs`. The exact raw job reports both missing inventory registrations as unexpected actual callers.

#2918 and #2921 `CALLERS.toml` are byte-identical, blob `9171cd7059507cb70b91440a4c2d6c4f1dc72c9a`, and contain the automation, microbatch and Neuron runtime guarded-effect callers. #2918 also retains the independent inventory blob `3bc0927b935c6aac429d59964fe7210b4af96052` at `qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json`, the regression and the independent B4 workflow gate. See `caller_parity_comparison.json`.

**Shortest next action:** retain the exact #2918 composition while P0 is integrated. There is no reason to create another equivalent caller PR or replace ca5b70 with the numerically newer, less complete #2920/#2921 branches.

The inspected runtime boundary is substantive: `NeuronRuntime::tick` is crate-private; product `tick_authorized` obtains the independently signed claim and executes the model/journal call inside `with_verified_effect`. The worker's product `run_authorized` also claims and holds that guard through private execution. These closures are synchronous; this review found no cross-`await` hole in those two inspected methods. B4 source inventory proves its own closed set, not independent operational custody of signing keys.

## S2 — #2734 converts unavailable telemetry into numeric measurements

At `codex-rs/hepta-infer-worker-host/src/neuron_microbatch.rs`, blob `e56584aa36046710c767ec264fbe09757ae67a3a`, `execute` records CPU using `.unwrap_or(elapsed_micros)` and RSS using `.unwrap_or(0)`. Both sampling helpers return `None` outside Linux, and can fail on Linux as well. The record has no per-sample availability flag at this call site. Consequently an unavailable CPU counter becomes a wall-clock duration, while an unavailable RSS counter becomes numeric zero. A comment documents this convention, but downstream consumers cannot distinguish true zero from unavailable measurement using the event alone.

The same event writes one elapsed batch duration to both p95 and p99. With a single sample, equal quantiles are mathematically possible; this is therefore a limitation of the offered measurement evidence rather than proof of a quantile algorithm defect. It cannot establish a distribution across real workload runs. The Linux CPU helper also assumes a 100 Hz conversion; that is an unverified platform assumption in the inspected source, not a claim that every Linux host has another rate.

#2918 has a stronger existing model: `NeuronHostResourceSampleV1` uses `Option` values; `NeuronBatchMetricV1` persists an availability bitmask and rejects inconsistent nonzero values when a bit is unset. Its worker derives per-head quantiles from observed result samples and flushes metrics before acknowledgment. Relevant blobs: worker `18592309972fb936462b2a8100f7006f260a282e`; metrics `bc31ba1a063c41427ab070f221fd818c15a33071`.

**Shortest next action:** add explicit availability to the Cell-owner metric schema and its writer/replay/export consumers, retaining backward-compatible decoding or a deliberate version change. Reuse the #2918 Option/mask contract after mapping the two owner APIs. Do not overwrite the entire same-named worker file: #2734 and #2918 use different plans, backends and metrics types. Then test unavailable CPU/RSS and measured zero separately; target-host sampling remains a later requirement.

## S3 — Four current #2734 report validator defects are reproduced

The frozen script `scripts/hepta-cell-split-target-matrix.py`, blob `a9081eadf885afd3d14aeb2b885168ed94f272aa`, generates only 16 factor rows. `validate_report` checks the set of IDs, but not row count/uniqueness or the factor tuple, accepts `observer.verified=true` without a trusted public key or signature, and does not validate its final `reportDigest`.

The local `negative_validator_repro.py` imports exact immutable source copies and calls only `validate_report`. It never runs a workload, creates a signature, or persists a fabricated qualified report. Numeric fields and observer identities are explicitly synthetic malicious inputs. The audit stores only acceptance/rejection outcomes:

| Negative input | #2734 dc271 | Existing #2850 05cf9bb |
|---|---|---|
| Unsigned self-asserted observer | Accepted, 16 rows | Rejected: independently trusted Ed25519 key required, 64 rows |
| Duplicate case with recomputed untrusted hashes | Accepted, 17 rows | Rejected, 65 rows: unique complete coverage required |
| Invalid encoder-topology factor with recomputed hashes | Accepted | Rejected: factor / Cell-count identity mismatch |
| Incorrect final report digest | Accepted | Rejected: report digest mismatch |

The script remains DENY_ALL, so these defects falsify an evidence qualification label rather than issue an effect grant. They must be repaired before any downstream code treats `qualified` as trustworthy evidence.

**Existing repair to reuse:** #2850 script blob `39cfb2a7df5295db978e0089bcb9d201fa402456` and test blob `6a2ed3fc803e44da30b766b7f8e75ddb944739cf`. This version checks 64/256/1024/4096 × 16 identities, strict statuses and field sets, final hashes, externally pinned Ed25519 observer signatures, prime-order keys, source/workload continuity, subprocess deadlines and leftover descendants, and unknown GPU as null/observed=false. Preserve all 27 current parameter-expanded tests, including bad keys, unsigned field extensions, dirty/source drift, worker factor echoes and workload mutation.

**Shortest next action:** continue the existing #2850 owner branch or deliberately project its two complete script blobs onto the current Cell integration base, retaining all current-source changes and required gates. Git compare shows #2850 diverged from current dc271 at `3d4cc109ee04cfcdae1f74dde395d3fb7b8622fe`, ahead one and behind two. Its historical green cannot qualify a new merge. The existing repair is larger than 800 changed lines across code and tests; any new review unit should follow the project’s staged-review rule with explicit dependencies. No synonymous new matrix PR was created here.

## P1 — Shared allocation and batch seams exist; pretrained execution and real worker wiring remain work

#2695 `shared_encoder.rs`, blob `195d93e81308b33662dc4dcba0516aa1d5071f3e`, defines `SharedEncoderDriver::encode`. `SharedEncoderOwnerV1::encode_for_cells` validates the request, invokes that driver once, validates the result, and converts one vector to shared `Arc` feature storage for all Cells. Lightweight bounded Q24 Head and multimodal-mask/projection implementations also exist. A generic driver trait and fixture tests are not a pinned pretrained backend: this reviewed source set contains no independently qualified ModernBERT/mmBERT/Granite/Jina SDK weight load.

#2734 `data_plane.rs`, blob `2778ad028aad2d9a3ed9c5e2209ba6480cafb765`, contains a bounded compatible-model index, retired-ID checks, shared snapshot and `ReferenceBackendBatchV1`. Its outer `execute` loops over requests and calls each reference Head's deterministic math. One outer function call is not evidence of one pretrained SDK batch execution.

#2918 separates `NeuronMicrobatchBackendV1::execute_batch` from its fixed reference implementation. `run_reference` accepts only the latter, which explicitly calls itself non-learned and produces deterministic Q24 fixture outputs. Authorized product execution calls one backend method and validates identities/output bounds before durable acknowledgment. The qualification binary uses four Cell counts and 256-item chunks, but fixture encoder/tokenizer/source digests; it is reference structural/WAL testing.

The inspected product entrypoint `hepta-infer-worker.rs`, blob `eda16d16177b6ba90d2984265e9e34b1602b01bd`, constructs `AppServerModelDriver` and native AppServer dispatch. It does not wire the Neuron microbatch worker into that loop. In the reviewed #2918 worker/neuron tree, the concrete reference qualification binary is the visible constructing caller; `model_worker.rs` exposes a single-feature driver seam. This is a source-scoped finding, not a claim about every historical branch in the repository.

**Software next action:** reconcile the selected Cell/shared-feature representation with #2918’s signed worker, implement the pinned SDK backend and actual bounded dequeue/batch/execute/ack path under the existing FinalUse guard, then require backend invocation and isolation/replay negative tests. **External evidence needed after that:** actual pinned weights/tokenizer/license, named host and driver, binary/workload hashes, same-budget no-change comparison, observed CPU/RSS/GPU/latencies and independent source custody. Do not whole-merge #2695’s unrelated vendor/supply-chain changes merely to acquire its shared Encoder seam.

## P2 — Preserve the existing canonical executor; do not activate the Supervisor reference

#2734 `hepta-supervisor/src/cell_split.rs`, blob `69de2e053bdc657278230a620abfa63b27d58dc5`, contains real bounded file-CAS/recovery mechanics, but explicitly gates its execution mutators through `require_fixture_execution`. Outside tests it returns `CanonicalOwnerRequired`. Create, execute, resume, migration reconciliation, rollback reconciliation and receipt advancement were checked. No bypass was found in those mutators. The read-only recovery seam does not turn this into an authorized physical executor.

The current canonical implementation is on **#2684**, under `hepta-operator-acceptance/src/`, and is absent from that module on #2734. Its existing owner blob `ee76a01aff2fd53ccac066b998645a7870441e27` preserves the four original external effects, pinned original receipts, fsynced prepared intents, post-effect original-owner readback plus current NDU/Selector revalidation, local continuity checks and Ambiguous outcomes. Recovery retains the same intent and reconciles; it must not issue another Execute for an effect that might already have committed. The public legacy CLI blob `aa4093880d1e0052c0f3549aca73942ad285595b` denies callback-only production advancement before configuration reads/RPC.

`cell_split_target_host_runtime.rs`, blob `f5b0d3e8909d8718a648ca37257d167c42588a16`, provides the typed external runtime trait and lifecycle runner. The local adapter performs actual file operations but uses file routes, caller-supplied resource samples and an externally provided power-loss witness. It is not proof of same-owner Control/CNS/TaskFlow/Supervisor transactions on the target system. The runner emits unsigned events for later host/observer verification; it does not issue production permission.

**Exact DAG caveat:** #2595 current `1fd7682...` is the recorded base of #2597; #2597's historical `9030451...` was used by #2642 `f4a6885...`, then #2684 `b5d3200...`. Live #2597 is now `91a662a1921aaaef794c33df61442494bb9c0b32`, three CI/style commits ahead of `9030451...`. Compare live #2597→#2684 is diverged, ahead 12 / behind 3. Those three commits serialize the complete original `ndu_publication` suite and require at least 30 tests. #2684's successful source log still uses `--minimum-tests 1` and no `--test-threads=1` on that collective suite. Its success does not disprove an intermittent cross-test lock problem. The upstream explanation that fork inherits file locks is explicitly a hypothesis; this audit did not reproduce that cause.

**Software next action:** keep #2684 as the canonical execution owner; separately review the three existing #2597 CI changes and any exact owner API integration needed. Maintain the six current post-effect regressions and no-new-effect guards. **External/architectural closure still needed:** atomic original Control B→signed physical effect/current readback→C, native final-use and generation enforcement at every actual effect, persistent original CNS state and independently witnessed rollback floor, genuine process/power-loss recovery, TaskFlow/ledger replay, trusted host/observer custody and operator acceptance. Do not create a second Cell owner on #2734.

## P3 — Reuse existing signed prospective evaluation; do not invent another window contract

#2734 `cell_ndu_selection.rs`, blob `4bc497de0abd65c33dc7eb16389f65cf42cd103e`, freezes baseline/artifacts/generation, rejects evaluator/selector/executor ID collisions, preserves complete evidence and negative migration, and yields a private single-use selection token without effect authority. Each candidate has one opaque `future_window_digest`; admission checks it is nonzero. That advisory summary alone cannot establish prospective timing, but a stronger existing implementation is already present on the exact same source tree.

`hepta-intelligence-eval/src/longitudinal_time.rs`, blob `a75053280ae55e6329eab4276034cbfebb8d23b3`, defines `ObservedFutureWindowV1` and `LongitudinalTimeEvidenceV1`. It requires 2–32 windows, exact signed freeze time, positive observation counts, distinct nonzero source cuts, distinct window IDs matching the frozen set, non-overlapping intervals strictly after freeze and fully before observer issuance/current trusted time, and a preregistered minimum duration. It verifies Observer, Generator and Evaluator evidence and independently controlled roles. These are existing enforceable source contracts, not merely window names.

There are concrete callers: `ProductEvaluationRunnerV1::qualify_and_persist` in `product_runner.rs`, blob `d407375ed7a8f645523e58f0f9435b0359b6f25d`, calls signed longitudinal admission for SystemLongitudinal qualification after fenced final-holdout consumption; `prepare_self_evolution_selection_v1` in `self_evolution_selection.rs`, blob `39efe8c7583678df35ddd63ee98cfd5e0e6c17d4`, also uses it and carries the independent selector/rollback admission path. `fenced_holdout.rs`, blob `b46cb572492afa8646b92e5213ce9c47a4feaf7d`, supplies the fenced durable holdout owner. The internal admission routine is crate-private at the public export surface. This review therefore does not classify “missing future-window schema” as a repository bug.

#2695 `group.rs`, blob `6554ae80d91e8e46a2178afed999591695a09aff`, is a deterministic advisory candidate/abstention decision and explicitly does not claim learned FBSDE or mutation. `shadow_system2.rs`, blob `963ddeeb8115df60a4a66d621367fac6bd773d69`, applies bounded deterministic risk/uncertainty changes as a fixture for a later learned critic. Both retain DENY_ALL. These are useful seams, not evidence that a production self-learning loop or learned critic was trained.

**Software next action:** trace the selected Cell/physical owner’s consumer through these existing opaque verified-selection and product-qualification receipts; map any advisory summary to that verified provenance instead of treating its single digest as qualification. Preserve the current no-change path and consumed-token protections. No current production authorization bypass was demonstrated in the inspected advisory seam, and no new window schema is needed. **External next action:** supply a real preregistered freeze, trustworthy clock and independently held observer/generator/evaluator/selector custody, then collect genuinely prospective data under the existing policy and execute the predefined statistical/negative-transfer comparison. The source module itself states signatures authenticate attestations, not empirical truth or reliable clocks. Retrospective data renamed `future_1/future_2` cannot close it.

## P4 — What remains outside the validator repair

The current evidence supports reference structural execution, validator adversarial tests and selected real filesystem/recovery mechanics. It does not contain 64 unique production workload runs on a named target machine or independently trusted host/observer/operator attestations. Four numeric sizes in the reference qualification binary and 64 generated validator rows are separate from that requirement.

The shortest honest external handoff is a fixed native worker/model build and pinned workload, then 64/256/1024/4096 × 16 actual runs with raw source/case-bound outputs, complete measured distributions and resource availability, fault/recovery receipts, paired split/no-change utility/resource costs, separately held prime-order Ed25519 observer keys and final operator acceptance. The source checks must be completed first; external custody must not be simulated by the executor.

## Cell WAL handoff completed before this audit

The prior `../cell_p0/` package selects existing #2909 `5993cb909547070e4b56ca9465996a5a946fafca`, tree `dfa98997ef9f82773c4c9967ab3034d717961abb`, for the exact four-path 109-addition/7-deletion projection onto #2734 dc271. It retains Unix no-follow/nlink/mode negative tests and all six original WAL tests, adding the stronger append-after-recovery regression. Windows job 118059888568 at that exact source executed **7 passed / 0 failed / 0 ignored**, with locked graph/format/clean source checks; it does not execute the two Unix-only attack tests or qualify full required CI. The broader required lane hit ENOSPC. Do not replace that complete chain with #2914's later-numbered but incomplete WAL ancestry or create an equivalent new PR.

## Artifact index and verification boundary

- `findings.json`: machine-readable classification, precise source bindings and shortest next actions.
- `source_bindings.json`: 97 inspected immutable source copies with Git blob and SHA-256 validation.
- `github_snapshot.json`, `followup_snapshot.json`, `canonical_owner_dag.json`: exact PR/base/merge/check/DAG evidence.
- `log_index.json`, `logs/`: five raw job logs compressed without altering decoded bytes and extracted markers.
- `negative_validator_repro.py`, `negative_validator_repro_results.json`: eight source-bound adversarial observations; zero real workloads/signatures/models.
- `caller_parity_comparison.json`: both caller sets on #2918/#2920/#2921.
- `sources/`: immutable source copies; original worktrees are untouched.
- `SHA256SUMS`: package file hashes.

An empty default-branch GitHub code search was not used as proof of absence on a PR branch. A failed read of unavailable local dc271 Git objects was not used as source evidence; the exact branch tree and files were fetched through GitHub instead. PR/check status never establishes a local or remote runtime PID. Global production qualification remains BLOCKED/UNVERIFIED as itemized above.
