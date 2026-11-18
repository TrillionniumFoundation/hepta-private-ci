# Actual current-policy Round03 execution

This evidence records one frozen engineering experiment on the existing six
development A tasks and three development B tasks. It does not add independent
tasks, independently authenticated users, external teachers, native owner
adoption, FinalUse, or settlement eligibility.

## Measured result

The full ten-job sequence completed once, without automatic retries. All three
final models scored **0/3 on B**, in both primary and cold processes. The updated
controlled student actually executed the next collection round; its observations
were not a replay of the initial student's actions.

| State | A first attempt | A final, up to two attempts | A model calls | Recovery after executed first failure | Recovery after unexecuted rejection | B final, primary / cold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Common initial adapter, controlled round 000 | 5/6 | 5/6 | 7 | 0/1 | null (0 cases) | unmeasured |
| Reference-trajectory final, 128 updates | 3/6 | 6/6 | 9 | 3/3 | null (0 cases) | 0/3 / 0/3 |
| Shadow final, 128 updates | 3/6 | 3/6 | 9 | 0/2 | 0/1 | 0/3 / 0/3 |
| Controlled after 64 updates, round 001 collection | 0/6 | 0/6 | 12 | 0/3 | 0/3 | unmeasured |
| Controlled final, 128 updates | 4/6 | 4/6 | 8 | 0/2 | null (0 cases) | 0/3 / 0/3 |

The final A rows use post-update collections; the primary and cold evaluations
independently agree with these outcomes. Shadow's twelve unexecuted training
predictions have no measured task success or recovery rate. A verifier call can
reject a patch before business execution, so the two failure cohorts stay separate.

The reference-trajectory final student's nine A actions are byte-identical to the
nine authored demonstration actions, including the three failed first actions and
their repairs. Relative to the initial adapter, first-attempt A success falls by
two, final A success rises by one, and inference uses two extra calls. This is
consistent with reproduction of the trained trajectories; it does not establish
a unique causal explanation, an information-matched gain, or generalization.
`REFERENCE_ACTION_MATCH.json` in the archive retains every paired action hash.

Controlled's final adapter repairs `A-colon-repair`, but loses the previously
successful `A-mse` and `A-pair-map`; the other three A tasks remain successful.
Its intermediate 0/6 result and final 4/6 result are both retained. No arm was
selected or promoted after these observations.

## Measured cost scopes

| Arm | Optimizer steps | Training input tokens | Supervised tokens | Inference model / student-verifier calls | Inference input / output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference trajectories | 128 | 51,764 | 9,768 | 39 / 39 | 13,547 / 3,161 |
| Shadow | 128 | 62,889 | 10,780 | 51 / 39 | 17,862 / 5,196 |
| Controlled | 128 | 82,494 | 10,780 | 55 / 55 | 18,813 / 4,421 |
| Total | 384 | 197,147 | 31,328 | 145 / 133 | 50,222 / 12,778 |

Each arm uses 196,608 padded training positions. Inference totals cover the two
collections, post-update A, primary A/B, and cold A/B. They exclude numerical
preparation tests and earlier runtime recovery. Each arm additionally performs
24 measured authored-reference rechecks; preparation adds six, for 78 retained
reference measurements. These are separate from student-verifier totals.

The two training scopes total 264.642, 245.028, and 241.938 seconds respectively.
Those scopes include reference/load/encode/train/save and are nested inside the
loop and worker lifetimes. They must not be added to their enclosing durations.
`EVIDENCE.json` separates collection, post-update, primary, cold, training,
reference, and worker costs. Energy, GPU active time, money, and complete system
costs remain unknown; equal attempt caps or optimizer steps are not equal actual cost.

## Candidate and interventions

All three E2 arms begin from the same retained `final_answer` adapter, model
digest `b8d926d13b45314e131514a4f5625aed9c7f902505b98f7d4b5b3d44c5fcc8db`.
Each arm performs two rounds of 64 optimizer steps. Each next round loads the
actual preceding adapter parameters and initializes a fresh AdamW optimizer.
Only the latest round's observations enter that round's fit. These controls
match optimizer steps and initial state; they do not establish equal actual
inference tokens, elapsed time, energy, or monetary cost.

The reference-trajectory arm (`teacher` in the CLI) uses the existing authored
A trajectories, including their demonstrated failed and repaired actions.
Training calls `native_examples(records, "trajectory")`; there are no external
teacher calls. `shadow` collects one unexecuted current-student prediction.
`controlled` executes the current student with up to two attempts and measured
feedback. Every arm's final updated
student executes A, followed by separate primary and cold processes executing
the same exposed A/B panel. Cold repetition checks candidate reload and
observational agreement; it is not a new C/D task or a native adoption receipt.

For shadow and controlled, student actions are context with `trainable=False`;
the loop rejects a trainable student action. Their targets come from verified
authored A corrections (`external_teacher=False`). Controlled therefore studies
actual current-student execution and feedback as context for reference
correction supervision. It does not train directly on the student's mistakes.
The reference-trajectory arm has nine supervised turns per round; shadow and
controlled have six. Information and supervision are not completely aligned.

## Frozen sources and runtime

The 27 `online_v4` modules match commit
`9801487a07834ca9c2d1c11ca9d47672913c0a60` (Draft #6665), which applies a test
fixture correction to the Round03 source at
`eb56c51e4e73b0d466795b257a547ab93a0baa63`. The production implementation is
unchanged. The explicit fixture patch sets the generic tiny tokenizer's model
inputs to `input_ids` and `attention_mask`, as required by the actual Qwen
generation interface.

The retained candidate's 119 source/material files were checked against their
original inventory and all 119 Git blobs at `eb56c51`. Legacy research and
operation-helper modules are separately pinned. The complete retained directory
inventory includes historical bytecode and audit material; all 17 original
Python 3.12 bytecode objects were compared with compilation of their pinned
source. No historical files were removed to manufacture an exact inventory.

The source closure SHA-256 is
`9e56b5cb0e906568a17c17f3aeeaf3979766fdcee880bac6fd40a78f310f5f12`.
The frozen 27-module source manifest SHA-256 is
`928aaa75c75023954432302b46d2064311ccf5e290e3e605e82193e4c7ba7814`.
The comparison digest is
`8424c071295244ea11e7e4a4d2cc31c47dbcd5dbfe2ed83d5ca14c02a600e525`.
These form an explicit source/runtime/model/protocol tuple; unrelated HIA or E6
branch results do not qualify this candidate.

The original runtime was restored by matching absent files to their original
installed-file SHA-256 values. The complete original manifest check covered
19,079 files and 7,111,800,439 bytes, with no missing or different files. The
versions remain torch 2.9.1+cu128, transformers 4.57.3, peft 0.18.0, and NumPy
1.26.4. A real CUDA matrix multiplication on the RTX 4060 passed after restoration.
The restoration receipt SHA-256 is
`fbf283210529410a5708e366468078f38107b2ae6b60d55ad993e80b985eecf1`.

## Preparation and retained failure

The first actual prepare failed before GPU research jobs: the generic tiny
tokenizer emitted unsupported `token_type_ids` during the shared-pool numerical
test. The failed output is retained under SHA-256
`a09898b961dab39c84141010ec0653ae433690ba1daf91dd07ab847757c4a2b2`.
The test fixture fix was frozen in a new source directory and a new run name.
The complete formal prepare was then rerun. Both real CPU tensor tests passed
with zero skips; all six authored reference rechecks and the backend smoke
passed in that same preparation. The new engineering gate file SHA-256 is
`233891fd4709889e9eff2f904ad1ee2bbd191c100620b292643389a27af00ad0`.

## Evidence interpretation

Recovery readouts use the implementation at
`b2d1fceeb779b9392c2842bfa32e16feb1079024` (Draft #6653). It binds every
retained request, feedback sequence, model identity, step digest, actual
verifier outcome, and call/token total. Recovery after an executed failed
action is separated from recovery after a rejected, unexecuted action.
Unexecuted shadow predictions have no measured success or recovery rate;
empty recovery denominators produce null rates.

Training, collection, post-update A, primary evaluation, and cold evaluation
costs must be shown separately. Reference checks are additional actual
operations. Nested wall-time scopes cannot be added to their parent scope.
Energy, GPU active time, money, and complete system costs remain unknown where
the original measurement did not collect them. No absent receipt is counted
as a zero cost, and successful process exit is not counted as business success.

The independent-source and future-task requirements for E1, authenticated
distinct teachers for E3, and native-owner adoption requirements for E6 remain
open. This run can establish current-student execution and recovery on the
retained development panel; it cannot establish generalization or production
adoption.

The E1 four-arm comparison of frozen, retrieval, answer SFT, and trajectory SFT
on independent future tasks was not performed in this run. The common initial
adapter is the prior answer-SFT result, and its actual two-attempt A baseline
is observed in controlled round 000. That observation does not supply an E1
four-arm test or a same-protocol initial B evaluation. No additional answer-only
or filtered-failure counterfactual arm was added after seeing these results.

## Durable originals and offline replay

[RAW_EVIDENCE.tar.gz](RAW_EVIDENCE.tar.gz) contains 1,743 original files, with
9,678,998 uncompressed original bytes, plus a complete `RAW_FILES.json` index.
The archive is 2,056,539 bytes and has SHA-256
`42ea473db654bae43fae4587533e97c2501083afa41b5375c6d89d9e500b55a0`.
Every member was checked against its indexed size and SHA-256 before publication.
The archive includes all retained requests, outputs, verification receipts,
training steps, source closure, process ownership records, readout code, failure
receipts, and the original task material. It excludes model tensor binaries.

[EVIDENCE.json](EVIDENCE.json) identifies the initial and all six new model
digests, the immutable source/runtime/protocol tuple, every process PID, readout
and training receipts, and durable checkpoint hashes. `WEIGHTS.json` in the
archive maps every excluded adapter and optimizer file to a verified persistent
checkpoint member; the original base model's persistent files are also hashed.
Optimizer files are retained for audit; this run never resumes optimizer state.

A local replay verified all three arm reports byte-for-byte, using only the
archive. It changed the builder's `ROOT` to the extracted `workspace` directory
and its output directory to `recovery-readout-replayed`. Model-library imports,
subprocess execution, and network connections were denied during replay; it
made zero model or verifier calls. [OFFLINE_REPLAY.json](OFFLINE_REPLAY.json)
records the original and relocated builder hashes and all three output hashes.
The replayed index's builder hash changes with relocation; the arm reports do not.

To reproduce the readout, verify the archive SHA, extract to a new directory,
then edit only those two path constants in
`workspace/operations/read_round03_recovery_392934_b_v2.py` and run it with
Python 3.12 and `PYTHONDONTWRITEBYTECODE=1`. No model weights or GPU are required.
The three reports must match the hashes in `OFFLINE_REPLAY.json`. The original
readout and exporter were formatted with the repository's `just fmt`; their
pre/post-format AST identity receipts are in [FORMAT.json](FORMAT.json).
