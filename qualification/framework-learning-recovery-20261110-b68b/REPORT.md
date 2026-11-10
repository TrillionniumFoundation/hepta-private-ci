# Ordinary learning delivery and bounded recovery

## Status and source

**Draft candidate; scoped code verification PASS, overall production/required-CI HOLD. Current candidate `06f3219…` has passed its own 22-case source QA, complete caller inventory, all 75 selected native tests including the seven new regressions, subsequent scoped maintenance with unchanged source, and scoped Windows qualification. Those results have retained original evidence. Required Linux CI remains open; real production learning assembly and scientific benefit are not qualified. Earlier-source results and failures remain separate.**

- Candidate: [PR #5720](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5720), current published commit `06f32191452df9f03bb5dc21ff8105db6b66d3d6`, tree `d6db19d921be786713a7b1f91aa2a460b2ead8fe`.
- Original base: `abf75d8e2097785b2ad01897c15a7531eebe6e44` / Draft #5707. The cumulative code diff has 11 files, 732 added lines, and 25 removed lines.
- Initial published behavior candidate: `6c5e5fa199ef291c5dbbc0ab13fe3e565d750fec`, tree `8ac7e89fb13e732e3c8c5191eba3a0dc40bbd792`. The original local two-commit candidate `7ba319b1decb50aee4b99f293010b4161aba5808` has this same tree.
- Follow-up `204da40ebd7a1e5b41cb3c3a684f7d83e3398b37`, tree `09815e81e8ce622bac96b6dba534fce0dbc94668`, is a direct child of `6c5e5fa…`. It adds explicit `pretty_assertions::assert_eq` imports in the two new test modules only; production code was unchanged by that follow-up.
- Current `06f3219…` is a direct child of `204da40…` and adds the independent readback budget plus three actor regressions: 3 files, 200 added lines, 3 removed lines. The common clock, remaining-time, and maximum-future-expiry checks are retained.
- Evidence branch: `codex/framework-learning-evidence-20261110-b68b`, independent of the frozen #5720 code head. The report and raw records belong to an evidence tree; every test result remains bound to the actual code SHA/tree it exercised. The evidence commit's own SHA is not a test target and need not be embedded in its own contents. #5720 remains at `06f3219…`.

## Three behavior repairs

### Reserve actor capacity before claiming an outbox delivery

The parent persisted the SQLite delivery claim before `LearningIterationHandleV1::submit` attempted a bounded `try_send`. A known full or closed actor could therefore leave a claimed operation without any dispatched work or checkpoint. The ordinary consumer correctly allows only readback after that claim, so capacity rejection could strand the operation.

`learning_iteration.rs` now retains an actor permit through `LearningIterationReservationV1`; `circuit_learning_delivery.rs` reserves before the durable claim. The design is a minimal integration of the existing shared-framework reservation at `374af2c7b28c76e3ebf1e3a90593389c8f6f7bd0`, not a second queue or owner. Known capacity/owner unavailability leaves the completion unclaimed. The same permit crosses the claim and the existing Root post-claim source check. That check still runs before submission. A source refusal releases the permit and retains the original claim for reconciliation.

Loss after claim remains uncertain. No fresh identity, automatic resubmission, checkpoint fabrication, or extra training authority is introduced. This repair does not make independent owner reads and SQLite writes atomic.

New SQLite/actor regressions exercise actual queue saturation, an unchanged pending row, successful delivery after capacity returns, capacity retention during the source check, and loss of the delivery response followed by readback without repeated stages or checkpoint writes. Existing closed-owner and post-claim refusal regressions retain their original recovery assertions. Their stage outputs and signatures are fixtures, not genuine training evidence.

### Revalidate Evaluation from a recovered learning history

The parent evaluation bridge required the supplied history's last receipt to be Training. A legitimate recovered history ending at Evaluation, Proposal, Selection, or NextUse could not use that bridge to re-read its original Evaluation.

`read_cell_learning_evaluation_v1` now validates the entire supplied history first, reconstructs the original Training predecessor when Evaluation is retained, and prepares the original result against that predecessor. The prepared Evaluation must exactly equal the retained receipt before either owner is contacted. Original trainer/evaluator readback remains bound to the supplied history; current trust, principal separation, qualification, and post-await revalidation remain required. Reconstructing a predecessor does not repeat the holdout or mint a new timestamp.

New framed-owner regressions cover both qualified and NoUpdate histories, intermediate and completed suffixes after the original work expiry, and rejection before owner I/O for malformed history or substituted evidence, timestamp, disposition, and missing Training. The signed evidence and downstream suffixes are explicitly synthetic. These cases do not prove production selection, adoption, or next-task use.

### Give explicit Readback its own bounded recovery time

The actor previously wrapped both Submit and Readback in `remaining.max(1)` seconds, computed from the original work expiry. An expired completed operation therefore had only one second to restore its checkpoint and re-read the original signed stage evidence. Several individually bounded owner reads can exceed that total, making otherwise valid reconciliation fail with `CommitUncertain`.

`06f3219…` gives explicit Readback a fixed 30-second total recovery budget. Submit keeps the original `remaining.max(1)` timeout, including while it restores an existing checkpoint. Both modes still perform the same current-clock calculation and reject a remaining expiry beyond the existing 86,400-second limit before choosing their timeout. Timeout still returns `CommitUncertain`; it does not complete or acknowledge work.

Readback continues to use only the original restore/authentication path. Agent/generation scope, frozen-scope validation, snapshot/request/owner equality, original signed evidence, current trust, and readiness checks remain enforced. The change adds no stage execution, checkpoint writes, changed operation IDs, extended training deadlines, or relaxed Root exchange/session limits. The existing CALLERS guards and typed source scanner are unchanged.

Three new tests drive the real handle/actor with synthetic evidence ports and paused Tokio time after fixture initialization. They cover eleven 125 ms attestation delays that exceed the former one-second total, a 60-second owner stall that must hit the 30-second recovery bound, and Submit retaining a five-second work deadline while restore delays ten seconds. They assert the retained snapshot is unchanged and no stages or checkpoints are repeated. All three passed on `06f3219…`, as recorded in the original native log and fresh JUnit. These are actor timing regressions, not evidence of real training or an end-to-end Root transport qualification.

## Typed caller guard repair and retained observations

The original post-claim callback used `let source_state = Arc::clone(&state)`. The unchanged typed caller scanner refused to infer the receiver for `source_state.require_circuit_learning_source(...)`. An explicit `Arc<AgentdState>` annotation resolves that source proof; the scanner and privileged caller sets are not relaxed.

The exact same ten-test source-closure command was run before and after this one-line annotation:

| Observation | Result | Recorded exit |
| --- | --- | ---: |
| Before annotation | 10 tests; 1 error at `root_learning_completed_circuit_source` | 1 |
| After annotation | 10 tests; no errors | 0 |

Original stdout/stderr and command/cwd/time/exit metadata are retained under `raw/`. This is a scoped source-guard observation, not a native behavior test or an entire frozen-source CI qualification. The original metadata did not capture a complete working-tree digest at invocation; it must not be upgraded to such evidence. `SCOPE_STATUS.json` records the retained file hashes and separate pending gates.

### Fresh static verification on the published code commit

The later observations below ran on the actual published commit `6c5e5fa199ef291c5dbbc0ab13fe3e565d750fec`, tree `8ac7e89fb13e732e3c8c5191eba3a0dc40bbd792`. Each retained execution record identifies that commit/tree and records an empty Git status before and after its command(s).

| Frozen-source observation | Raw result | Recorded interval (UTC, 2026-11-10) |
| --- | --- | --- |
| Root learning bootstrap source closure | 10 tests, no errors; exit 0 | 13:06:35–13:06:38 |
| Cell learning Evaluation source closure | 8 tests, no errors; exit 0 | Within 13:21:30–13:21:31 |
| Evaluation recovery source closure | 4 tests, no errors; exit 0 | Within 13:21:30–13:21:31 |
| Complete privileged caller inventory | `PASS_HEPTA_CALLER_CLOSED_SET`; 6,180 Rust files, 196 boundaries, 182 protected files; exit 0 | 13:06:51–13:14:39 |

The caller receipt explicitly has `authorityGranted=false`. Its complete scan still records the four empty product caller sets below. The 22 Python test cases and caller inventory establish these source checks on this code commit; they do not establish native execution, independent training/evaluation custody, production assembly, or scientific gain. Original logs and metadata are copied byte-for-byte, including the complete 90,873-byte caller receipt. Their hashes are in `SCOPE_STATUS.json`.

### Separate frozen static verification of `204da40…`

The repaired test-import commit was then verified independently at `204da40ebd7a1e5b41cb3c3a684f7d83e3398b37`, tree `09815e81e8ce622bac96b6dba534fce0dbc94668`. Its four execution records all bind that source and record clean Git status before and after. The original eight log/metadata files are retained under `raw/static-204da40/`.

| `204da40…` observation | Result | Recorded interval (UTC, 2026-11-10) |
| --- | --- | --- |
| Root learning bootstrap source closure | 10 tests, no errors; exit 0 | 13:26:55–13:26:57 |
| Cell Evaluation source closure | 8 tests, no errors; exit 0 | 13:26:57 |
| Evaluation recovery source closure | 4 tests, no errors; exit 0 | 13:26:57 |
| Complete caller inventory | `PASS_HEPTA_CALLER_CLOSED_SET`; 6,180 Rust files, 196 boundaries, 182 protected files; `authorityGranted=false`; exit 0 | 13:26:58–13:34:03 |

The new caller log is 90,873 bytes, SHA-256 `1f65cd9dc1f5a286b155416ef8b4841f450d9d911d710a64c42ecbc564372b2e`. These are independent observations of `204da40…`. They do not apply to the now-published readback-budget commit `06f3219…`.

### Current `06f3219…` source validation

The current checkout was independently observed at clean `06f3219…` / `d6db19d9…`; `raw/source-06f3219-observation.json` records the identity, diff sizes, and changed-source file hashes. Root and the budget implementation agent report Rust 1.96 formatting and diff checks completed before publication. Those reports are not native test results, and their original command outputs have not yet been attached here.

All four new executions completed successfully on this exact code SHA/tree, each recording clean Git status before and after. Their eight original log/metadata files are retained under `raw/static-06f3219/`.

| Current `06f3219…` observation | Result | Recorded interval (UTC, 2026-11-10) |
| --- | --- | --- |
| Root learning bootstrap source closure | 10 tests, no errors; exit 0 | 13:45:48–13:45:50 |
| Cell Evaluation source closure | 8 tests, no errors; exit 0 | 13:45:50–13:45:51 |
| Evaluation recovery source closure | 4 tests, no errors; exit 0 | 13:45:52 |
| Complete caller inventory | `PASS_HEPTA_CALLER_CLOSED_SET`; 6,181 Rust files, 196 boundaries, 182 protected files; `authorityGranted=false`; exit 0 | 13:45:53–13:53:47 |

The caller count includes the newly added budget regression file. The complete 90,873-byte caller receipt has SHA-256 `2c5cecb6700566bf7147bae7d5d96c9e8f0a0ca43b6c670c04ccd81d7373485c`. These are actual current-source static results, not inherited observations. They establish source closure only; native execution, production owner assembly, adoption, and scientific gain remain separate gates.

### Native and hosted CI observations awaiting final reconciliation

The original `6c5e5fa…` Windows job log, run/job metadata, workflow, PR observation and manifest are now retained under `raw/windows-6c5e5fa/`. The job log is 220,694 bytes with SHA-256 `9eaf47e27831e4ee5768c97116be7fb37b8bb37d5ed8cc491a1158b4d9bdacbe`. Other remote lane artifacts are still being collected. These remote outcomes remain separate from the frozen local static checks above.

| Lane | Source / run | Observed state |
| --- | --- | --- |
| #5720 current-head remote native | `06f3219…` | Observed 75/75 selected tests passed, 802 excluded by selection, exit 0; all seven new cases passed; fresh JUnit and unchanged source verified; final fix/format/diff checks all exit 0 |
| #5720 current-head local native fallback | `06f3219…` | Cancelled before any Rust test phase when original remote execution became observable; controller exit 130, zero native cases; original cancellation/source records retained |
| #5720 current-head Windows | `06f3219…`, [run 42827391087](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42827391087), job `129868257070` | Success, completed 14:05:49 UTC; 33 selected Rust tests, 6 Python guard tests and the native acquisition qualification passed within their stated scope |
| #5720 current-head Linux CI | `06f3219…`, [run 42827391368](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42827391368) | Last reported queued; no terminal result attached |
| #5720 historical test-import Windows | `204da40…`, [run 42824184414](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42824184414), job `129857015849` | Completed, cancelled during the Agentd step; later formatting and acquisition qualification skipped |
| #5720 original desktop native | `6c5e5fa…` | Terminal compilation failure, test command exit 101; 13 E0659 errors; zero tests executed |
| #5720 Windows | [run 42820133051](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42820133051), job `129843260076` | Compilation failed: new capacity tests have ambiguous `assert_eq` imports, E0659 |
| #5720 Linux CI | `6c5e5fa…` | Queued; no success inferred |
| Separate #5719 shared-framework workflow | `dbb3bce393685469bd5587bb591d01099f1df697`, [run 42820868946](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42820868946) | Dispatch observed, queued; belongs to a separate candidate |

The original Windows failure is in the initial candidate's new test code: the parent's `pretty_assertions::assert_eq` arrives through `super::*` and conflicts with the prelude macro. Published follow-up `204da40…` adds explicit macro imports in both new test modules. The failure is retained; each static execution above keeps its actual source identity, and native/CI outcomes are also kept separately by commit.

The superseded `204da40…` Windows run subsequently ended cancelled. Its original run/job metadata and hash manifest are retained under `raw/windows-204da40/`; the job metadata records the Agentd step as cancelled and the later formatting/acquisition qualification steps as skipped. No native case count or successful Agentd qualification is inferred from this metadata. The run's own `head_sha` is `204da40…`, even though its nested live PR head now names `06f3219…`.

The remote observation channel previously returned `Internal`, leaving the original request's status unknown. It later became observable as the original `06f3219…` execution. The retained original native records now establish exit 0 and **75 selected tests passed**, with **802 excluded by the nextest selection**. JUnit contains 75 executed cases, zero failed and zero skipped cases. All seven new regressions appear exactly once as passed in both JUnit and the original log: two capacity/delivery cases, two Evaluation-history cases, and three Readback-budget cases.

The native command ran from 14:03:14.350713 to 14:06:28.534391 UTC; nextest reported 44.064 seconds of test execution. The 31,107-byte original stderr has SHA-256 `8558fb5d0b73802a6aa2818ea8ee20707789b84604a34fbb3556efd8aea0166d`. The 20,505-byte JUnit has SHA-256 `e390fe7db52460fca225482d2ca3ad97d46ff1b0ce2ebc8631132317e182df76`. Its original mtime is inside this invocation's interval, and the driver requires fresh source-bound JUnit before accepting the case set. `source_before.json` and `source_after_tests.json` are byte-identical, clean `06f3219…` / `d6db19d9…`, including the index and all eleven changed-source hashes.

The 23 original remote files, their provider size/SHA/version manifest, the native-pass summary, and the exact request/driver input records are retained under `raw/native-06f3219-test-pass/`. Their content hashes and the seven named case outcomes were independently checked.

Final maintenance completed at **14:14:14.050929 UTC** with driver exit 0. `just fix -p codex-hepta-agentd --locked --offline --profile dev-small`, `just fmt`, the binary diff capture, and `git diff --check` all exited 0. The maintenance diff is empty. All five source records—before tests, after tests, after fix, after formatting, and final—are byte-identical with SHA-256 `bd1a687dc6ca8a1483c531f7c1136c870dd6d7b59b077e56b799d3f5924490ea`, retaining clean `06f3219…` / `d6db19d9…`. The final driver records one native invocation and no tests repeated after maintenance.

The 16 original final-stage files plus their provider manifest and completion summary are retained under `raw/native-06f3219-final/`; they bind the same invocation and native gate as the immutable test-phase archive. Maintenance was not warning-free: the original Clippy log contains two Agentd `duplicate_mod` warnings for `learning_iteration_checkpoint_test_support.rs` and `neuron_generation_runtime_test_support.rs`, plus two dependency `mismatched_lifetime_syntaxes` warnings in `third_party/i18n-config-0.4.8`. These warnings did not change the successful exit status or source. The completion summary's two-warning field describes the Agentd duplicate-module warnings; the original log retains the dependency warnings as well.

Original record bytes are preserved when directories are relocated into this pack. In particular, `raw/native-06f3219-final/completion-summary.json` retains its original `test_phase_artifacts: "../06f3219"` value; in this evidence layout that reference maps to `raw/native-06f3219-test-pass/`. `SCOPE_STATUS.json` records this relocation explicitly. It does not rewrite the source record or its hash.

The local fallback had verified the source and toolchain, completed a read-only formatting check, and waited for the occupied Cargo target and resources. Root reports its six locked dependency files passed checksum verification. Once the remote request became observable, the local fallback was stopped before any Rust test phase. Its retained controller receipt has exit 130 and its cancellation summary records zero executed cases. `source_before.json` and `source_after_cancellation.json` are byte-identical, clean `06f3219…` / `d6db19d9…`. The original driver's last status still says resource wait because interruption preceded a final driver checkpoint; the separate cancellation receipt supplies the terminal fact. These 26 original files are retained under `raw/native-local-06f3219/`. Cancellation is not a failed test and supplies no native pass count.

The final Windows job's seven original metadata/log/workflow/manifest files are retained under `raw/windows-06f3219/`. The original log is 235,852 bytes, SHA-256 `b2981ec1505045dada5d4fa059a23b08c5ce9cb62d0d2b8c216692d8f7263e17`. The run/job records bind `06f3219…`; the retained commit API record maps it to `d6db19d9…`, and all 14 job steps, including formatting and unchanged-source checks, completed successfully.

Windows executed **33 selected Rust tests**: 15 path/ACL tests, 2 Prompt Registry tests, 3 final-use store tests, 2 authority-lease tests, and 11 Prompt Runtime tests. Its **6 Python acquisition-guard tests** also passed. The native acquisition positive lane exited 0 and rejected both original attacks. Two deliberately mutated negative lanes exited 1 as expected, demonstrating the corresponding check detects unchecked creation and path substitution; these expected failures are not production-test failures. The Windows selection did not execute the new learning capacity or readback-budget tests, and the Evaluation reader is Linux-only. Those cases require the separate native learning run above.

The original Windows run did execute **22 preceding security/owner tests** (15 private-file/ACL tests, 2 Prompt Registry tests, and 3 + 2 signed-store tests). Its Agentd test binary then failed compilation with ten E0659 errors, so **zero Agentd tests executed** in that invocation. The later formatting and directory-attack qualification steps were skipped. These 22 Windows tests are different from the 22 Python source checks above; their counts must not be combined or treated as learning-repair coverage.

The original desktop/Linux native invocation also reached a natural terminal failure: the selected `just test` command exited **101** after 13 E0659 errors (10 in the capacity module and 3 in the Linux evaluation-recovery module), before executing any tests. The driver exit was 1. Its `source_before.json`, `source_after_tests.json`, and `source_final.json` are byte-identical, retaining clean `6c5e5fa…` / `8ac7e89f…`, the index digest, and the ten changed-source hashes. The preflight read-only `just fmt --check --base abf75d8e…` returned 0; post-test `just fix`/format maintenance was not reached. This does not qualify native behavior.

The 23 original native files and their readback manifest, including original file version identities, are retained under `raw/native-6c5e5fa/`. The original 76,956-byte native stderr has SHA-256 `c3c86d0a75194bbbadb05a27ea65c5fdb7a911fbdf95c1d5248f27df4bd982b9`. The candidate macro-import follow-up addresses this shared compile failure; its execution results remain separate.

The current native learning and Windows passes are supported by their retained original records. Their scopes remain separate. The shared-framework dispatch does not qualify #5720, and the earlier Windows compile failure remains a failure of its original source.

## Ordinary owner assembly remains missing

At the parent source, repository search found the only `LearningIterationStageOwnerPortsV1` implementation in `learning_iteration_checkpoint_ports_tests.rs::StageOwners`. Production `CheckpointedIterationPorts` delegates to an external stage provider; it does not supply one. `production_launcher` receives the Root capability and refuses unassembled learning through `require_root_learning_assembled`.

The following exact product caller sets remain empty in `CALLERS.toml`:

- `root_learning_original_stage_assembly` (`AgentdConfig::with_root_learning_stage_owners`).
- `learning_evidence_original_owner_constructor` (`LearningIterationEvidenceClientV1::from_owner_stream`).
- `cell_learning_evaluation_profile_freeze` (`freeze_cell_learning_evaluation_plan_v1`).
- `cell_learning_evaluation_original_readback` (`read_cell_learning_evaluation_v1`).

`AgentdTerminalLearningOwnerV1::train/readback` does perform a narrow native tabular fit through the original Replay and Ledger owners. Its receipts explicitly are not Cell compatibility bundles or adoption receipts, its job cache is limited to one owner lifetime, and its constructor/channel have no ordinary product caller. It cannot be relabeled as the generic Cell Training owner. The evidence client only reads already-issued attestations; it cannot replace training, original custody, or a signer.

The unresolved assembly requires real Experience/Dataset/Training owners, independent Evaluation with original evidence and holdout custody, authoritative Selection/NoUpdate, and a committed distinct NextUse. Persistent trainer identity, cancellation/recovery, data withdrawal, original CURRENT/FinalUse, and cold restart must remain enforced when those owners are connected.

## Six framework boundaries

This is the scope assessment for the candidate, not a claim that every branch or every six-boundary gate has been qualified.

| Boundary | Existing source evidence | Remaining work / candidate effect |
| --- | --- | --- |
| Cell and kernel | V1 `cell_types.rs` still exposes `SparseConfig` and `SparseCheckpoint`; V2 `CellBackendManifestV2` separates component and input/state/output bindings. | Retain the stronger versioned backend path; general V1 migration and all ordinary loaders remain outside this patch. |
| Representation | Cell input/encoding contracts bind source, encoder, timing, and bounded bytes; V2 names explicit schemas and components. | These bindings do not by themselves prove complete multimodal collection, coordinate/time/missing-value semantics, or latent compatibility in ordinary execution. |
| Learning timescales | `CellLearningBindingV2` separates frozen weights from resumable optimizer/RNG/sampler/cursor bindings; `FrozenLearningScopeV2` restricts Cell/Organ changes and refuses slow-release scopes. | Real durable training custody and slow consolidation remain unassembled. No task state is promoted to adopted weights by this patch. |
| Ordinary learning entry | Root handoff, outbox delivery, current-source checks, checkpoint composition and signed evidence readers exist. | This candidate repairs claim-before-capacity, recovered Evaluation history, and expired-readback timeout. The empty caller sets above prevent claiming complete product learning assembly. |
| Shared scheduling/compute | Existing `cell_batch.rs` and composed Q24 paths provide bounded/shared building blocks. | Actor reservation removes one known claim-before-capacity failure. General shared worker admission, fairness, batching efficiency, and complete-cost benefit remain separate gates. |
| Version/migration | Generation manifests/journals bind state schemas, generations, writer epochs, committed output and current publication. | Recovery retains original evidence and has a separate bounded Readback time budget. General cross-kernel/state/topology migration and full process cold recovery remain unqualified. |

Keep the existing AppServer/session/tool backbone, owner identities, single-writer journals, artifacts, generations, and execution boundaries. This candidate changes neither public effect authority nor production activation.

## Verification commands and next gate

Observed static commands, separately completed on `6c5e5fa…`, `204da40…`, and current `06f3219…` (repository root):

```bash
python3 -m unittest discover -s qa/b4-no-bypass -p test_root_learning_bootstrap_source_closure.py
python3 -m unittest discover -s qa/b4-no-bypass -p test_cell_learning_evaluation_source_closure.py
python3 -m unittest discover -s qa/b4-no-bypass -p test_learning_evaluation_recovery_source_closure.py
python3 scripts/verify_hepta_callers.py verify
```

Observed scoped native command from `codex-rs`, followed by the completed maintenance described above:

```bash
just test --locked --offline --cargo-profile dev-small -p codex-hepta-agentd --lib \
  -E 'test(learning_iteration) | test(circuit_learning_delivery) | test(root_production_learning_inputs)' \
  --test-threads 2 --retries 0
```

Exact-source native output/JUnit, all seven new cases, scoped maintenance under `AGENTS.md`, current caller closure, and current Windows qualification are now retained and reconciled. The validated code is `06f32191452df9f03bb5dc21ff8105db6b66d3d6` / `d6db19d921be786713a7b1f91aa2a460b2ead8fe`; records on the independent `codex/framework-learning-evidence-20261110-b68b` branch preserve that tested source identity. The still-queued required Linux lane must be reconciled on its own source. Complete product assembly/adoption, process cold recovery, sustained benefit, and RSI claims remain HOLD. No main merge or production activation is represented by this evidence pack.
