# Joint Cell stages: integrated source and bounded native verification

**Selected engineering verification is complete at the tested source below; S0–S5 research admission remains HOLD.**
The final code identity is byte-for-byte equal to the tested source. The sealed raw archive and per-member manifest are described below.
Repository paths below are relative to the repository root; raw receipt paths are relative to the `payload/` directory inside the final evidence archive.

## Engineering result and source identity

| Scope | Exact tested identity | Observed result |
| --- | --- | --- |
| Common starting branch | `f49128e503b24bb52ccdb32a860939e6392c8e08` ([#5346](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5346)) | Starting identity; its failed hosted CI remains historical evidence. |
| Pre-successor combined candidate | `c37ebf8de8efc660229e66e4030d589be46bc194`, tree `ac1bd96d97186f404bf38cbaa22edbe021e29290` | **1,774 selected native passes**: V3's first eight successful scopes plus V4's final three. V3 itself did not complete successfully. |
| Circuit successor composition | `710df84a6b10afa005976c24a1108fb2a57810d3`, tree `37bf89db155cdd04145914cc63f6a8e1b4e1b2bd` | **1,097 selected native passes**, six V5 scopes, all command exits 0; `complete=true`. |
| Final code after maintenance | `710df84a6b10afa005976c24a1108fb2a57810d3`, tree `37bf89db155cdd04145914cc63f6a8e1b4e1b2bd` | All **13,641 tracked files** match the tested bytes. Scoped lint and formatting exited 0; no tests followed final formatting. The enclosing evidence commit adds only documentation, the sealed archive and its exact asset pin. |

The 710df84 candidate cleanly merges [#5388](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5388) at `f21e41039046b1247d64536bdec2bd308816f16d` onto c37, with no handwritten source conflict resolution.
The two native pass totals belong to different source snapshots and overlapping suites. They are not additive unique-test, scientific-sample, or efficacy counts.

V5 observed scopes, from `joint-circuit-validation-v5/RESULT.json`:

| Scope | Passed | Skipped by the recorded scope/profile |
| --- | ---: | ---: |
| Agentd / Automation / Neuron libraries | 993 | 60 |
| Inference and joint proposal | 69 | 0 |
| Action authority integration | 19 | 2 |
| Agentd product wiring | 5 | 0 |
| G14 qualification feature | 9 | 4 |
| Paired supervisor lifecycle | 2 | 1 |

The paired lifecycle tests completed in 145.120 s and 48.281 s; their nextest summary is 193.401 s.
The outer command took 204.422 s, including compilation/runner overhead. These nested scopes must not be added.
The source/lock inputs remained unchanged during the recorded V5 commands. Package-local binaries were supplied by Cargo/nextest; endpoint binary hashes do not assert absence of an intervening rebuild.

Additional bounded engineering evidence is kept separately:

- **28 research compatibility checks** on the frozen selected Python capsule at `30385c7440e3137ca5951982fbb61fcdd7ab58b8`; optimizer construction was rejected by that runner. This is not a full-tree training comparison.
- **41 ORG1 fixture regressions** at c37; no repeat of the historical 99-pair reference campaign and no real ABCDE dataset access.
- **Darwin Notes:** actual Rust red-to-green evidence, 9 selected tests after the repair; the original 9-test attempt had 3 failures. Linux also passed the 9 selected Notes tests. The Python socket probe is separate diagnostic evidence.
- **Matrix:** original scoped default suite 289 passed / 2 ignored, plus two separately run old-producer/new-consumer migration phases, each 1 pass. They are not 291 distinct default tests.

Primary raw receipts: `joint-native-bound-v3/RESULT.json`, `joint-native-remaining-v4/RESULT.json`, `joint-circuit-validation-v5/RESULT.json`, `joint-org1-validation/RESULT.json`, and `joint-research-validation/`.
The source import/AST audit is in `joint-research-audit-68d8/`; it does not claim later full-tree execution.

## Dependency and platform repairs included in the common source

The all-feature resolver and official Bazel lock updater passed at the earlier composed source, and the lock bytes remain unchanged in the final source.
The exact CI `cargo-deny 0.19.0 --all-features check` invocation passed at `68d8c41eaf94c89604d34acc65f3bb04a2f3d7d3`; later composition did not change its dependency graph or audit policies.
Its advisory, license, source and ban checks are engineering dependency checks, not stage advancement. See `joint-audit-final-v1/RESULT.json`.

AWS parent backports remove the retained pin-utils dependency without weakening the original pinning contracts.
The Matrix stack resolves SDK/crypto/sqlite 0.19.1 and vodozemac 0.11.2 with zeroization enabled.
The old-version encrypted-store producer and new-version consumer actually ran, including decryption with retained Olm/Megolm sessions; this is not a mocked schema assertion.
The migration changes crypto schema 17→19, state 15→16 and event cache 14→18; the cache resets and media remains at 2. Old-binary reopening is not qualified; a consistent pre-upgrade backup remains the rollback boundary.
Official third-party bytes and licenses are retained; compatibility manifests and archived failures remain separately reviewable in [#5398](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5398)–[#5401](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5401) and [#5405](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5405).

Platform work canonicalizes actual fixture roots and short private Unix socket paths, repairs Darwin buffered Notes reads without extending the original operation deadline, and preserves Windows known-folder/handle-pinning checks.
The paired-process test harness uses its scoped watchdog/serialization settings while retaining the original product deadlines, assertions and failed timeout attempts.

## S0–S5 research admission: HOLD

The retained common gate was rerun at c37 and matched its retained result exactly.
Its zero-authority and HOLD result is in `joint-org1-validation/CURRENT_RESULT.json`; historical source evidence is not silently promoted into an admitted common experiment.

| Stage | Implemented or observed engineering work | Unmet stage exit |
| --- | --- | --- |
| **S0 — shared measurement and versions** | Source composition, immutable receipts, owner/recovery contracts, exact source/asset checks, and bounded native recovery regressions. | The retained gate still lacks its qualified joint configuration/protocol/foundation binding and supported owner-authentication, recovery, and successor adapters. Complete measurement and actual successor/evaluator handoff are not established across the whole study. |
| **S1 — memory, decision, verification** | MEM-1, CTRL-1, VERIFY-1 sources and their original evidence are included; scoped owner/scope/replay and authority checks are composed. | No admitted common, complete-budget terminal-utility comparison with qualified old-capability retention. Existing module evidence is not that combined experiment. |
| **S2 — perception, prediction, action** | PERC-1, PRED-1, ACT-1 sources plus selected native action/process integration regressions. | Reduced useless evidence collection/planning/actions and robustness under delays/failures are not jointly established under complete equal budgets. |
| **S3 — learning kernel** | Delayed-credit and plasticity references, HCSN numerical mechanisms, configurable official baseline adapters, real-scalar/connectivity audits, ABC training and D development interfaces; historical bounded development fits retained. | This joint verification starts no new formal fits and accesses no E data. Full numerical/ablation domains, sufficient training, HCSN capacity reference, and independently allocated full-study budget are missing. No qualified advantage over strong temporal/gradient baselines. |
| **S4 — organizational plasticity** | Before-state pair binding repair; split/merge/rewire reference execution, finite-panel reviewer, and recoverable artifact checks. | No qualified matched native D benefit comparison against a demonstrated strong fixed-graph scheduler. Full organization cost, independent evaluation, representative tasks/fits, and native successor/adoption receipts remain incomplete. |
| **S5 — inheritable improver** | Four-arm solver/improver transfer, complete attempt denominators, separate history cost, and bounded synthetic reference execution. | No demonstrated improvement-efficiency superiority from common starts under complete equal budgets, real-task transfer, independent native evaluation, or qualified successor consumption. |

No stage table entry grants runtime authority, production adoption, or permission to bypass the existing owner gates.

## Historical scientific observations retain their own source identity

**S1–S2 module evidence.** The frozen VERIFY-1 v2 archive records 108 trajectories and 652 model forwards; all 43 read-only audit checks passed. This joint verification did not rerun it as a new model experiment.
PRED-1's registered net gain is 0.0191314, below its 0.02 threshold; the retained physical fit denominator is 48 fits plus 2 reconstruction fits, not seven independent seeds.
PERC-1's synthetic trajectory and native parser/interface checks do not provide a real media encoder under a frozen complete budget.
See `qualification/cell-research-stages-20261108/followthrough-20261108/`, `qualification/pred1/` and `qualification/perc-1-20261108/`.


**Shared foundations — [#5347](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5347).**
Source `d967d91c177f413d6962fe8526976680618c441e`, evidence `9aa9fa75f74ad7a15c3a3db36586502f0215aff0`: each original native/CI run retained 68 tests and 54 predeclared synthetic reference slots.
Both environments reused seeds 11, 29 and 47; they do not add independent seeds. Temporal kernels were frozen and only ten head parameters trained.
Diffusion did not beat type-specific modulation; HCSN and GRU scored 0.5 on the principal frozen-kernel panels; all 18 task-learning targets were censored within budget.
These observations establish neither HCSN task advantage nor a plasticity time-to-target speedup. See `qualification/cell_common_foundations/evidence/20261108/{RESULTS.md,SUMMARY.json,SOURCE_BINDING.json}`.
They are separate from the new localization formal-study counter below.

**S3 development — [#5377](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5377)–[#5382](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5382).**
The retained run has 5 fresh baseline fits, seed 101, each with 16 diagnostic and 12 main updates: **140 actual optimizer updates**.
The first main epoch was incomplete; only attention passed the short memorization threshold.
PLIF has 6,236 positive-moment scalars out of 9,770 trainable real scalars; the other 3,534 cannot count as gradient use merely because weight decay changed them.
The later endpoint/zero-moment diagnosis ([#5389](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5389)) is read-only evidence, not a new training run.
See `qualification/hcsn-localization-trainer-20261108/{MANIFEST.json,NATIVE_AUDIT_SUMMARY.json,README.md}` and `proposals/localization-v2/formal_protocol.json`.
The 1,843,158-byte raw evidence ZIP is bound by `27d4f684ba9df1b9dec5c518377c50f80239d2a3f4998045f88939593fa01bcc`.

**B is separate from D/ORG1 — [#5345](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5345).**
B's matched-state pilot completed 56 training jobs and retained 960 planned deployment records, but has only 2 independent training seeds.
All eight development utility point differences against the preselected strongest planning comparator were negative.
Retention has only **2 cases / 2 source groups**; all 160 retained records scored zero. Zero contrasts do not establish preservation or generalization.
The shared start precedes mode-specific pretraining; this is not an ablation from the same already-trained checkpoint.
See `qualification/cell-causal-abcde-20261108/{README.md,B_CONTRASTS.csv,B_LOCKED_COMPARATOR.csv,D_CAPABILITY_AUDIT.json}`.
Do not attribute those B results or sample counts to a real D organization experiment.

**ORG1 — [#5375](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5375), source `093b7a703eb4e31fcea3d8ab5d3f4749664504c5`.**
The original archives retain **99 paired tasks / 198 arm-task executions**.
Each operation has 33 correct tasks per arm; the fixed dictionary-indexed router already reaches full correctness.
Rewiring increases messages from 36 to 69 without a quality improvement.
Resident-byte integrals, energy/provider charges, and complete runtime costs are unknown; `mean_net_gain` remains null and decisions remain HOLD/NoUpdate.
These deterministic reference panels are not independent training fits, a production fault-frequency estimate, or native structural adoption. Dictionary split does not establish learned differentiation; dormancy, retirement and learned skill composition remain unqualified.
The new joint 41-method regression run does not rerun or relabel those archived pairs.
See `qualification/cell-organization-20261108/{README.md,RESULTS.json,ARTIFACTS.json,INTEGRATION.json}`.

**EVOLVE-1 — [#5348](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5348), source `c600204c6095b438746e7efd8a098bc38e1d8613`.**
The synthetic NumPy pilot contains 3 discovery seeds, 12 runs and 72 attempts; 24 historical discovery candidates and an earlier development campaign remain separate.
All 12 runs meet the pilot's numerical criterion, but **qualified=0, unresolved=12** and cost per effective improvement is null.
The descendant improver reduces both adaptation gain and retention loss. That tradeoff is not demonstrated improvement-efficiency superiority.
See `qualification/evolve-1-20261108/{README.md,CURRENT.json,campaign-final.json,PROTOCOL.md}`.

### Old S81 remains UNKNOWN; new formal=0 cannot reset it

The earlier CPU V1 owner reserved **20 of 160 registered fits** and made one provider submission.
Its original effect remains **UNKNOWN / MAY_HAVE_BEEN_SENT**, without verified remote identity or accepted completion capsule.
140 locally unstarted fits, zero verified completions, and zero released/replayed reservations do not mean zero remote fits or optimizer updates.
A later read-only GET did not resolve the original submission.
The exact historical record is [FORMAL_HALT at 60af6862](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/60af6862c23d94a45e30c39e3de91ade8b058ae6/qualification/hcsn_regenerative/studies/s81-cpu-v1-20261107/FORMAL_HALT_20261108.md) and its adjacent `FORMAL_HALT_STATUS_20261108.json`.
Those historical archives were not imported as new joint completion credit. Reservations, unknown effects and unknown costs are not cleared.

The joint native verification launched **zero new registered scientific experiments or formal confirmation studies**.
That counter does not instrument all Rust unit-test learning/optimizer activity, and does not erase the earlier 5 development fits / 140 updates.
It also does not turn missing energy, provider charges, or whole-run costs into zero.

## Source composition and publication index

These are source/evidence references, not claims that every listed PR is merged upstream or that its historical CI qualifies the joint candidate.
An exact commit is used where a corresponding PR number was not independently verified.

| Component | Published reference / exact source |
| --- | --- |
| Common base | [#5346](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5346), `f49128e5` |
| Shared foundations | [#5347](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5347), `9aa9fa75f74ad7a15c3a3db36586502f0215aff0`; research-only import |
| Circuit framework | Initial `1eb72a1131285f5de98beeb7c95a27eab72d647e`; successor [#5388](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5388) at `f21e41039046b1247d64536bdec2bd308816f16d` |
| MEM-1 | `afa0638cc26792772830f1f9ec87bc154a20a430`; `qualification/memory-cell-mem1/` |
| CTRL-1 | [#5374](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5374), `b2646b4cbf19817145c9cb680d95333a267d19f4` |
| VERIFY-1 | `a6b174fa26e0d4f4870266ed0f65d96cb4cb3c02`; `qualification/verify1-native-20261108/` |
| PERC-1 | `473897f97a492f1455dda2caa8152786242bc8ac`; `qualification/perc-1-20261108/` |
| PRED-1 | `3959aac6829a345ef674b7901cbdd62316305d89`; `qualification/pred1/` |
| ACT-1 | [#5376](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5376), `0b2496534b50f601726bccecd5b66d665d95131c` |
| HCSN learning closure | [#5377](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5377)–[#5382](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5382), [#5389](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5389); imported research closure from `60af6862c23d94a45e30c39e3de91ade8b058ae6` |
| B/D and ORG1 | [#5345](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5345) at `a55a209e20fe78c59644b5bff0298c36fe61294c`; [#5375](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5375) at `093b7a703eb4e31fcea3d8ab5d3f4749664504c5` |
| EVOLVE-1 | [#5348](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5348), `c600204c6095b438746e7efd8a098bc38e1d8613` |
| AWS parent backports | [#5391](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5391), [#5392](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5392), [#5394](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5394); evidence head `30ee3ff30adf9048dd7aaf97e257b9a65ef9f763` |
| Matrix migration/security closure | [#5398](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5398)–[#5401](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5401), [#5405](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5405); final source/evidence `0fd7b1eb0b0958205052ae120f19e43d458f7637` |
| Platform and Windows fixtures | [#5402](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5402), [#5403](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5403); Windows [#5396](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5396), `62d0927e6f7079e5c138a4e16abdc467eeda03a9` |
| Darwin Notes buffered read | [#5404](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5404); code `a4f85fef87942a414a26051e8dd403f6aeea8319`, evidence `a48a266f4a3772760b4569a16cd60c5644c81c73` |

The early `JOINT_COMPOSITION.json` is an import ledger, not the final-head declaration: its recorded head predates ORG1 and the Circuit successor.
Use the later integration receipts and tested identities above for those additions.
`qualification/joint-research-import-20261108/IMPORT.json` records the selected 101-file learning import and 12-file missing research dependency closure.
This import does not replace the common native FinalUse/authority baseline with the different research ancestor's Rust files.

## Circuit installation and version boundary

Ordinary signed ObjectiveStart reaches the durable Circuit/Cell/result-consumer path only when a host explicitly selects `AgentdConfig::with_circuit_task_bootstrap`.
The default daemon does not manufacture the original Cell state/inference owners, retained input provider, stable invocation provider, or durable idempotent result consumer.
The explicit Circuit profile is mutually exclusive with canonical-intelligence and finite Notes/Desktop execution profiles.
Fixture integration verifies real AuthBus, RunStart, SQLite history and Cell journals with controlled issuer/model/source/readiness; it is not a production-model quality result.

The new `RecoverySettled` event settles original claimed work under a settlement-only fence; it neither renews execution nor reauthorizes an old ObjectiveStart.
Absent `settlement_fence_revision` is omitted to preserve old state digests.
Once the new `recovery_settled` event is written, **old-binary downgrade compatibility is not claimed**.
Preserve/fence Cell clock epochs across reboot/migration. Cross-generation product recovery still needs the current supervisor and original receipt owners.
See `codex-rs/hepta-agentd/acceptance/2026-11-08-circuit-product/README.md` and raw `framework-successor-readonly/`.

## Retained failure and preparation ledger

| Attempt or prerequisite | Actual outcome and correction | Original evidence |
| --- | --- | --- |
| V1 common compilation | Getter/interface compilation failed before tests. Both getters already existed in that source; no getter repair was made. The retained evidence identifies reuse of normal-library artifacts from older worktrees. | `joint-native-final-v1/` |
| Shared target reuse | Four retained rmeta originals pointed to older platform/Notes worktrees. The source/artifact mismatch was preserved before cleanup. The original rustc --extern argv was not retained, so the exact older variant selected by that compiler invocation cannot be established. | `joint-cache-diagnostic/`, `joint-boundary-review/` |
| Target isolation | Same-filesystem rename to the exclusive joint target; clean all 204 local/workspace/vendor package IDs. Checked 202 local library names had no rmeta/rlib/so residue in the two relevant deps directories. This is not a claim that every unknown old artifact vanished. | `joint-cache-isolation/`, `target-isolation-readonly-20261108/` |
| V2 helper prerequisite | 1,232 ran: 1,219 passed, 13 failed, 63 skipped. Eight Neuron and five Agentd tests lacked actual hepta-joint-propose metadata. Original failures/retries remain. | `joint-native-isolated-v2/`, `joint-generation-failure-diagnostic/` |
| Real helper preparation | Build the non-test executable and select its absolute path from compiler artifacts; bind the same SHA through both Cargo/nextest aliases, including underscore aliases preserved by /bin/sh. | `joint-binary-preparation-v1/`, `joint-circuit-helper-v5/` |
| V3 operator selector | Exit 4: zero selected, 25 skipped. Remove the incorrect file-name-derived filter; V4 runs all 25 operator tests plus the remaining paired/storage scopes. No assertion or no-tests rule was relaxed. | `joint-native-bound-v3/`, `joint-native-remaining-v4/` |

Helper SHA256 used by the bound runs: `49de6829f51fcb10c5d9aa83c761e06d2a2f8670458d4a8efe26d70428fbd44f`.
Do not globally override Agentd's package-local executable metadata: G14 and ordinary tests build different feature variants.
Retained raw attempts also include S3 environment failures/recovery, Matrix fixture/compiler/resolver/receipt-wrapper failures, and blob-policy failures before exact content pins.
Their later successful scoped commands do not erase their costs or change the original failure status.

## Hosted CI and platform limits

These selected native passes do **not** establish a green full repository CI matrix, a complete macOS/Windows qualification, or production readiness.
The starting f491 hosted required check ended in failure; the original-regressions workflow was cancelled.
Darwin's targeted Notes fix is supported by actual Rust red/green results. The remaining Windows/macOS/full-CI surface is not promoted to green by Linux tests.
The seven original CI logs remain in `qualification/cell-platform-fixtures-20261108/native-and-ci-evidence.tar.gz` (SHA256 `11ba543a46a6150bbd89c2ac5513bea56660c69358ddb348122b4bae57533fe7`).
See also raw `matrix-validation/F491_REMAINING_CI_REVIEW.json`. Published-head hosted CI is tracked on the draft PRs. This evidence package makes no claim that the full required CI gate has passed.

## Final maintenance and evidence seal

- Ten changed first-party product packages passed `just fix --locked` (exit 0).
- `just fmt --base c37ebf8de8efc660229e66e4030d589be46bc194` passed. This scope covers the Circuit successor and any maintenance diff; it does not reformat third-party source or claim whole-tree formatting.
- The only lint edits changed two non-Windows unit-value statements in `hepta-operator-acceptance/src/durable.rs`. Independent review confirmed no behavior change; the suggestions introduced `path_statements` warnings and were discarded.
- The exact tested statements were restored and the same scoped formatter passed again. All **13,641 tracked files** match the pre-maintenance snapshot; the source tree is clean and remains **710df84a6b10afa005976c24a1108fb2a57810d3 / 37bf89db155cdd04145914cc63f6a8e1b4e1b2bd**.
- No behavioral tests were run after final fix/fmt. The earlier raw lint diff remains preserved alongside the restoration receipt.
- Original proof: `joint-finalization/{RESULT.json,FINAL_SOURCE_IDENTITY.json,final.patch}`, `joint-boundary-review/FINAL_FIX_PIN_REVIEW.json` and `root-native-termination-receipts/{INDEX.json,FINALIZATION_INDEX.json}`.
- Sealed archive: `joint-final-native-evidence.tar.gz`, **9923429 bytes**, SHA256 **`9abc9567e66334a8f16df97b0e7187a286ec04d140a126bb8dcb9300b64cf64a`**; **360 regular members** passed complete member readback. The wrapper manifest is `MANIFEST.json`; original packer metadata is retained losslessly as `raw-manifest.json.gz` and `archive-result.json.gz`.
- The archive preserves all four forensic rmeta originals and the selected attempts, source identities, real helper bindings, raw output and terminal receipts. The seven earlier hosted-CI logs retain their original platform archive identity above.
- The existing 512,000-byte blob policy receives only an exact SHA256-and-path entry for this archive. Its threshold and all prior entries are unchanged. Publication requires the policy to pass on the actual staged tree; the draft PR records the observed result.
- The evidence commit contains no product/source behavior change. Code and evidence branches are published atomically through the native host and independently read back from GitHub; publication receipts follow the raw snapshot boundary.

The archive's root completion signal denotes packaging orchestration, not an authenticated scientific evaluator or runtime owner.
Scientific UNKNOWN/HOLD and missing physical costs remain independent of engineering pass counts.
