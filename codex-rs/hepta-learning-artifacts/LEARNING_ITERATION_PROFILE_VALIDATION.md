# Frozen evaluation profile: native validation record

**Validation, 2026-11-08.** The primary native batch passed 39 selected tests and
a separate batch passed three direct owner-learning controls on `4a93aaf`.
Scoped fix, formatting of all 16 changed Rust files and strict Clippy passed on
the reviewed lint-only successor `ed1ea56`. GitHub also reports the existing
Windows private-state security qualification workflow succeeded on `4a93aaf`.
The earlier build and maintenance failures remain in the evidence history.
This record concerns engineering controls; production qualification remains
`HOLD_NO_GO`.

The behavior under test is described in
[Frozen evaluation profile in native learning iterations](LEARNING_ITERATION_PROFILE.md).
The original owner commits the evaluation profile before training; training and
both evaluation outcomes must preserve it. NoUpdate retains the full incumbent
bundle and still requires independent selection and actual next use. Chain
evidence does not replace evaluation or current owner authority.

## Exact source identity

| Item | Pinned identity |
| --- | --- |
| Corrected source tested by native-v3 | `4a93aaf01a594258bcc3e65a1a37ac772675be63` |
| Whole repository tree | `f9375fd1dc5f9151a8337fc51b0c6f574049f198` |
| `codex-rs` subtree | `3e7f1024a78aad91438496cf70008d2caaf1faa0` |
| Later test-only lint clarification | `ed1ea5691798a2dbffbbcc8216f2929e67724af7` |
| Lint clarification whole repository tree | `a1029394b64ef1f0ac46511716dba6892fdbb261` |
| Lint clarification `codex-rs` subtree | `b710c1c49dc42598b79206dfdd37708da506f114` |
| Initial implementation, failed build attempts | `f6247df765bb82d18247ed7d492635d09d2bb403` |
| Initial implementation tree | `f04abc058a7ca542984517bc5463ca0c7a482268` |
| Initial implementation `codex-rs` subtree | `eda105c2b03d32287d64ae58679189c16b2772f5` |
| Chain evidence commit | `5f7eccf86e252cce67bf5dd6f614c1c7a1824e53` |
| Chain evidence tree | `4f08a68b8bfabba90bfc408e276e480e5da67fb5` |

[The corrective commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/4a93aaf01a594258bcc3e65a1a37ac772675be63)
adds an explicit `pretty_assertions::assert_eq` import to the agentd profile
test module and names six positional timestamp arguments in the artifacts
profile tests. It changes no production behavior or test selection. The native
checkout was fully populated before the corrected run; missing compile-time
inputs from earlier sparse checkouts were restored from the pinned source.

The successful run records identical pre-run and post-run HEAD, tree, index
tree and `codex-rs` subtree, with an empty Git status. A later evidence-only
documentation commit must not be substituted for this tested source identity.

## Run history and denominators

| Attempt | Source | Requested / executed | Observed outcome |
| --- | --- | --- | --- |
| native-v1, Linux | `f6247df` | 39 / 0 | Compile failed, exit 101: sparse checkout lacked `docs/modules/MODULES.json`, used by `include_str!`. No JUnit test run was created. |
| native-v2, Linux | `f6247df` | 39 / 0 | Compile failed, exit 101: missing `qualification/neuron-v13-generation/proposal_worker.py` and nine `E0659` ambiguous `assert_eq` errors. No JUnit test run was created. |
| Hosted Windows qualification | `f6247df` | Separate workflow selection | Agentd test compilation failed with the same nine `E0659` errors. Earlier workflow subsets ran; they are not passes for the 39-test native selection. |
| Corrected hosted Windows qualification | `4a93aaf` | Test count not inferred | GitHub reports the existing Windows private-state security workflow and all 14 job steps completed successfully. This is a separate workflow observation. |
| native-v3, Linux | `4a93aaf` | 39 / 39 | Exit 0; all 39 selected tests passed, with no selected failures or skips. Raw JUnit and log hashes verified; 823 other tests were outside the focused selection. |
| Direct owner-learning controls, Linux | `4a93aaf` | 3 / 3 | Exit 0; all three selected tests passed with no selected failures or skips. Raw JUnit/log verified; 859 other tests were outside the focused selection. |
| First post-test maintenance | `4a93aaf` | Not a test batch | Scoped fix exited 0; plain `just fmt` exited 0 with no files selected. Strict Clippy exited 101 for two `duplicate_mod` diagnostics. Source remained unchanged. |
| Lint-only successor maintenance | `ed1ea56` | Not a test batch | Scoped fix, actual 16-file formatting and strict Clippy all exited 0; source remained unchanged. Native tests were not rerun or relabeled as tests of this successor. |

The failed Linux attempts requested 39 exact selectors but executed zero tests.
They contribute neither successful cases nor failed test cases to native-v3.
The separate three-test batch must retain its own run ID and JUnit record; it
must not be presented as a single 42-test native-v3 execution.

The Windows failure is
[run 42478192065, job 128724143747](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42478192065/job/128724143747),
`ACL, anti-reparse, signed-owner durability and recovery on Windows`, at the
`Validate Agentd Prompt Runtime integration and reopened state` step. The
retained file is the connector-decoded UTF-8 log, 228,811 bytes, rather than a
claim to the original downloadable ZIP bytes. Its SHA-256 is
`25e10038492bf8a16d9d2342d39e33a90f38ced9b9646e8a437d1dec8a8dc411`.

The corrected source has a separate successful observation:
[run 42480262145, job 128730448818](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42480262145/job/128730448818).
The preserved GitHub workflow and jobs API responses pin HEAD to
`4a93aaf01a594258bcc3e65a1a37ac772675be63` and report `completed` / `success`,
with all 14 job steps successful, including Agentd Prompt Runtime integration,
the original directory-acquisition attack controls and unchanged-source checks.
The scope is the existing Windows private-state security qualification
workflow. The successful run's logs were not downloaded for this record; no
Windows test count is inferred from API step counts. This observation is not
assigned to `ed1ea56` or a later documentation commit, and does not establish
production activation. The API texts and bounded index are retained in
[hosted-windows-4a93/index.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/hosted-windows-4a93/index.json).
Hosted checks for `ed1ea56` and later documentation heads are not asserted
complete by this record.

## Exact native test selections

The primary selection is archived as
[native-readbacks/expected-native-test-names.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/expected-native-test-names.json) (originally
`exact-test-names.json`), 4,763 bytes, SHA-256
`70c73f29515e30588203a1fba9d78741ba8f27f376a78537485a42d5216c8855`.
An independent source-name check resolved the Rust module declarations and
found exactly 39 unique test names, with no extra, missing or duplicate names.
The two-file corrective commit leaves those names unchanged.

| Native suite | Exact module prefixes | Count |
| --- | --- | ---: |
| Artifacts and complete incumbent retention | `learning_iteration::{tests,retained_tests,profile_tests}` | 12 |
| Durable checkpoint and frozen-profile recovery | `learning_iteration_checkpoint::{tests,profile_tests}` | 9 |
| Native owner runtime, signature and recovery boundaries | `plasticity_runtime::lifetime_tests::learning_iteration_tests`, including `recovery_tests` and `profile_tests` | 13 |
| Original retained/adopted actor readback controls | `neuron_generation_runtime::tests::update::{learning,adopted_learning}` | 5 |
| **Primary native batch** | Exact names in the hashed manifest | **39** |

The [primary JUnit record](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/native-controls.junit.xml)
has run ID `daa6f76b-4408-4a08-b6ce-22d1fb7d7bdd`.
The raw XML contains exactly the 39 manifest names, each once, with no failure,
error or skipped testcase elements. Its log and XML hashes match the result
record. Nextest reports 823 other tests skipped by the focused selection; this
is not a full-binary or full-workspace test run.

The separate selection is archived as
[direct-owner-controls/exact-test-names.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/exact-test-names.json) (originally
`extra-native-test-names.json`), 387 bytes, SHA-256
`a85f94bf141745d1face6fed1f0f66240cbefe9a0322911eb7ff72ce4348c7aa`.
Its three exact names are:

```text
neuron_generation_update_bootstrap::learning::tests::actual_same_model_use_cold_reopens_without_new_nonce_or_journal_work
neuron_generation_update_bootstrap::learning::tests::retained_use_rejects_failed_cancelled_rejected_and_late_work
neuron_generation_update_bootstrap::learning::tests::current_withdrawal_and_revocation_refuse_new_learning_observations_and_recovery
```

These controls exercise the direct production-owner adapter for retained-model
use, refusal of unsuccessful or late work, and current withdrawal/revocation.
Their [separate JUnit record](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/native-controls.junit.xml)
has run ID `c7136f6b-8515-4198-ad9b-9441c1ac964c`.
The raw XML contains exactly those three names, with no failure, error or
skipped testcase elements. The names are disjoint from the primary 39; both
batches used the same clean pinned source. The archive's
`direct-owner-controls/index.json` records the preflight checks, original file
mapping, lengths and SHA-256 hashes. Its `native-controls.stdout` preserves the
original `.log` bytes unchanged.

## Native environment and source provenance

The native-v3 result records Linux x86-64, Rust `1.96.0`
(`ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96`), Cargo `1.96.0` and Just `1.51.0`.
The command uses the repository's `just test --locked` recipe, both
`codex-hepta-learning-artifacts` and `codex-hepta-agentd`, `--lib`, and a nextest
expression made from the exact manifest. Full argv and runner identity are
retained in the result and launch records.

The private build target was initialized from a read-only seed cache. Cache
reuse is an optimization, not source or binary provenance. The corrected run
records its exact source before and after execution, produced-binary hashes,
log hash, JUnit hash and run ID independently of that cache.

The bounded job used an 8,589,934,592-byte memory limit, CPU quota of two cores,
nice level 10 and a 90-minute runtime limit. Native-v3 observed a peak of
6,384,611,328 bytes and zero swap usage. The configured swap limit was unlimited;
zero observed swap usage is not a claim that swap was disabled.

## Paired native checkpoint and readback evidence

The five original actor controls include retained-model and adopted-candidate
fixtures. The existing opt-in stdout path emits the original readback together
with exact `HEPLCP02` bytes from the native production codec. The checkpoint
head must equal the actor's original learning head. Export does not reconstruct
the checkpoint from JSON.

There are two engineering cases, each observed at pending-output and
acknowledged-output stages: `retained_pending`, `retained_acked`,
`adopted_pending` and `adopted_acked`. Four records are not four independent
experiments. The Chain reader joins the frozen request and owner set, receipt
chain, Selection decision and original first-use readback. A Selection-stage
checkpoint is not a completed full learning-iteration checkpoint.

The paired native export manifest is
[native-readbacks/fixture-manifest.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/fixture-manifest.json), SHA-256
`597a20d27e48a91dd6b19dc3102952ed7048fc39946bc9d42e84c23a40fc3557`.
The Chain validation record reports 25/25 new join tests and 26/26 original
readback tests passed, with no skips, using these genuine native exports.
[validation/results.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/validation/results.json) has SHA-256
`6776089f585417ecbf6dcd4d1ed4984b604b622c07ca7dd27283a3cde6014a06`.
Its Python source files were checked against the published base blobs and
hashed individually; this does not claim an exact whole-workspace Git HEAD.

Raw captures and reader outcomes are published in the
[fixed Chain evidence archive](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108)
at commit `5f7eccf86e252cce67bf5dd6f614c1c7a1824e53`, introduced by
[Chain PR #809](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/809).
The archive includes `native-readbacks/`, `direct-owner-controls/`,
`maintenance/`, `validation/`, `failed-attempts/`, `hosted-windows-4a93/`,
`provenance/` and `tools/`. Every evidence link in this record pins that commit.
Synthetic negative inputs do not substitute for positive native exports.

## Post-test maintenance

The first post-test maintenance attempt ran:

```text
just fix -p codex-hepta-learning-artifacts -p codex-hepta-agentd --lib --locked
just fmt
just clippy -p codex-hepta-learning-artifacts -p codex-hepta-agentd --lib --locked -- -D warnings
```

Attempt 01: **failed strict Clippy**. Scoped fix exited 0. Plain `just fmt` exited
0 but selected no files in the clean checkout, so this was not an effective
format check of the changed Rust files. Strict Clippy exited 101 with two
`duplicate_mod` errors: the new test-only modules
include the existing private production checkpoint codec and original fsync
CAS support file. All four retained source-diff files are empty; HEAD, whole
tree, index tree and Git status remained the same clean tested source.

The nine original artifacts are preserved in `maintenance/attempt-01/` with
logs renamed to `.stdout` without changing their bytes. The result SHA-256 is
`3908a74073088c92b01af7bca0db40b36c3f65a8661ad54963e9f53a91c9179e`;
the strict Clippy log SHA-256 is
`69d93c15e5d853c9203763d1ef94f9c25cd1f25c8a20f80abe95241b7c95dcaf`.
The failure is retained even if a later maintenance attempt passes.

[The lint-only successor](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ed1ea5691798a2dbffbbcc8216f2929e67724af7)
adds eight lines: a justified `clippy::duplicate_mod` allowance only to each of
the two new test-only module inclusions. Both containing modules are already
behind `#[cfg(test)]`. This preserves the private production API, test names
and test/module behavior, and changes no global lint configuration.

Attempt 02: **passed on the lint-only successor**. The exact commands were:

| Command | Exit | Observed scope |
| --- | ---: | --- |
| `just fix -p codex-hepta-learning-artifacts -p codex-hepta-agentd --lib --locked` | 0 | Scoped maintenance; no source changes. |
| `just fmt --base f1785ca15e41e4e49509a5b211a659e3cbdbf60e` | 0 | All 16 changed Rust files under the pinned Rust 1.96.0 toolchain; no source changes. |
| `just clippy -p codex-hepta-learning-artifacts -p codex-hepta-agentd --lib --locked -- -D warnings` | 0 | Strict lint gate; no source changes. |

The full changed-path set recorded before formatting has 17 entries: 16 Rust
files and one Markdown file. The explicit base makes the format scope effective
in the clean checkout. All four maintenance source-diff records are empty.
Before and after every command, HEAD was `ed1ea56`, the full tree was
`a1029394b64ef1f0ac46511716dba6892fdbb261`, the `codex-rs` subtree was
`b710c1c49dc42598b79206dfdd37708da506f114`, and Git status was empty.

Before dispatch, the
[source-equivalence record](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/maintenance/attempt-02/tested-source-equivalence.json)
verified the direct parent
relationship to `4a93aaf`, the exact two changed paths and eight added attribute
lines. Removing only those exact attributes reproduces the tested source bytes.
Its SHA-256 is
`8e8b72af7fcb24231f9883f9079f2d303a739fb6219583b2b3241a9c92804808`.
The original result, logs, source-equivalence proof, reviewed delta, runner and
launch record are retained in `maintenance/attempt-02/`; its result SHA-256 is
`49401819d4b64d24efaeca2a0a9406fa316d70f2fee96f17543a748fdf873710`.

Tests were not rerun after maintenance. The 39+3 native executions stay pinned
to `4a93aaf`; the lint-only successor has its own source identity and reviewed
delta, without relabeling the earlier test results. The successful second
attempt does not remove or convert the failed first attempt.

## Preserved evidence hashes

The linked files below are pinned to the published Chain evidence commit.
Their SHA-256 values were checked against the archived bytes; the failed
Windows log uses the decoded-text representation described above.

| Record | SHA-256 |
| --- | --- |
| [failed-attempts/native-v1/result.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/failed-attempts/native-v1/result.json) | `11f8955045ca11d3027630032cff9edf0e5fceb3177ceeb17be7bc4d8fd355b4` |
| [failed-attempts/native-v1/native-controls.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/failed-attempts/native-v1/native-controls.stdout) | `32f79dd4c227717b3bb4e80e9b0ee781311eb96423ca87816441afdd75c87ed3` |
| [failed-attempts/native-v2/result.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/failed-attempts/native-v2/result.json) | `a7476c379b75f18017531f72bea437b1eb6f40e456c01fb05d3e9c6eeab5a476` |
| [failed-attempts/native-v2/native-controls.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/failed-attempts/native-v2/native-controls.stdout) | `bc5314441729d26f4d0f3345ff03b582a052e41e2877b2e6d2e8ec7c3d4705d2` |
| [failed-attempts/windows-f6247/job128724143747.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/failed-attempts/windows-f6247/job128724143747.stdout) | `25e10038492bf8a16d9d2342d39e33a90f38ced9b9646e8a437d1dec8a8dc411` |
| [native-readbacks/native-result.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/native-result.json) | `7ed73680708e579af144d4c6b1b457bfc0cfc2f87905a70bb268826cc354a552` |
| [native-readbacks/source-01.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/source-01.stdout) | `e0e75da06c749313b986eb10daeef0a786d148d76381023c10bb681d5a3bd36a` |
| [native-readbacks/native-controls.junit.xml](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/native-readbacks/native-controls.junit.xml) | `10c64d05635532a030c9d58967473a88d9b2ed05f0913abc2e495251562457fa` |
| [direct-owner-controls/result.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/result.json) | `0d97b795871f5478aba50dca46c7f8ea02eebd7ff0bae35ff170f2190f662696` |
| [direct-owner-controls/native-controls.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/native-controls.stdout) | `8791c1abe519bf1a3c55e86b118a59ec4faf7bc8edd024ef69cf2234b4d6fad1` |
| [direct-owner-controls/native-controls.junit.xml](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/native-controls.junit.xml) | `ee7777400d6e6cbc03748486a86a01c4700c54f057f5815f65bf3927fcffb7ec` |
| [direct-owner-controls/index.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/direct-owner-controls/index.json) | `3bcfed668061bced584cf1989595480bdac7450f3fa481c24da653d899ec9d9a` |
| [maintenance/index.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/maintenance/index.json) | `16f726d1d53e1962fae8c99aed3fb22a20de1e1d882959fa0067e18ff0d594f5` |
| [maintenance/attempt-02/result.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/maintenance/attempt-02/result.json) | `49401819d4b64d24efaeca2a0a9406fa316d70f2fee96f17543a748fdf873710` |
| [maintenance/attempt-02/strict-clippy.stdout](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/maintenance/attempt-02/strict-clippy.stdout) | `ca34b1b50708b3b1d35d783d847a9ac572fb1c3df4c1f29477804bc670d076b9` |
| [hosted-windows-4a93/index.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/hosted-windows-4a93/index.json) | `168dcc2429ac539a47c7bf80bb5d1f9ae84ffe546b8bdca70ad820f9f83a0526` |
| [provenance/test-selection-source-map.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/provenance/test-selection-source-map.json) | `3c7bf4271ce2fae00a367fb509415f09aa45a0292f7ef3e02fdfe7d3e44a4b51` |
| [provenance/independent-registry-audit.json](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/5f7eccf86e252cce67bf5dd6f614c1c7a1824e53/evidence/cell-learning-iteration-20261108/provenance/independent-registry-audit.json), audit of initial implementation names | `a6a49943dc1e5a5fac793c49828411d5a486192b8649ffef46f3e7ff44f8a13f` |

## Production responsibilities that remain open

All exported fixture reports retain `authority = DENY_ALL`,
`current_permission = NOT_EXPORTED` and `qualification = HOLD_NO_GO`.
Engineering test success does not close the following obligations.

| Responsible boundary | Evidence still required for production |
| --- | --- |
| Original owner and protected checkpoint custody | Independently retain and authenticate the initial owner-frozen request, profile, owners, budget and head before dispatch; establish protected persistence, current trust, signature verification and cold-recovery custody. Fixture-derived pins do not establish this provenance. |
| Cell execution, dataset and training owners | Perform real model execution and training with complete authenticated resource receipts, exact lineage and dataset identity. Native deterministic controls do not establish training, neural loading, cost completeness or externally delivered work. |
| Independent evaluator | Register and execute the no-change, cell-only, routing-only and joint comparisons with matched budgets, holdout protection, retention/interference checks and declared decision rules. A profile digest binds identity; it does not interpret the protocol or prove its scientific adequacy. Both improvement and NoUpdate must be admissible outcomes. |
| Node, M12 and PoN work/settlement boundary | Establish fresh qualifying work, uniqueness, admissibility, ordered evidence and actual settlement under the frozen work rules. Execution and work claims may share computations and proof material, but each required proposition still needs its own evidence. The learning tests do not qualify chain economics or consensus. |
| Chain evidence reader | Independently authenticate frozen-pin origin, owner and grant signatures, pre-dispatch timing and actor/control identity. Structural digest and byte consistency alone does not authenticate those claims, export current permission or complete the full learning lifecycle. |
| Current adoption and FinalUse owner | At actual use, recheck current authority, withdrawal/revocation, version dependencies and local risk, then bind the exact selected complete bundle, installation/loading and real next-task use. A chain confirmation does not confer irreversible external execution authority. |
| Deployment and long-lived operation | Validate supported platform/runtime behavior, protected production backends and recovery under real operational conditions. The Windows observation is limited to the existing private-state security workflow on `4a93aaf`; macOS, newer source heads, multiple independent hosts, production deployment and physical installation need their own applicable evidence. |

Different nodes may retain different valid versions. Correctly retaining the
incumbent and stopping after an unsuccessful experiment remains a valid
learning outcome. Neither the chain nor this validation record promises an
improvement in every round.
