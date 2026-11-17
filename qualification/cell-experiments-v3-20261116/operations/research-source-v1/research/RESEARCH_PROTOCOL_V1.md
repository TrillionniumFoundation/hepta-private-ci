# Authored-target research SFT v1

## Status and provenance

This is a new, explicitly post-failure exploratory protocol. It is not a recovery
of the native E1/E2 run, a successful capability qualification, or a relaxation
of the original 64 core modules. It was authorized after the complete parent03
baseline had shown A=0/6, repository=0/9 and SQLite=0/3.

The earlier reviewed design had SHA256
d4aa19925cd347602e853570c2ff62c1b7744597aaa70c9f2cc18a883162738f.
Its local RAM original was lost when that environment disappeared. This document
re-states the approved rules under a new file identity; it does not claim to
recover those original bytes. Root explicitly reconfirmed the rules after that
loss. All current code, tests and this restatement are preserved on Mac.

The exact original parent03 RESULT file SHA256 is
33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d.
The exact parent03 FREEZE file SHA256 is
02fa20ad7ce2d74d8631dd5a6ac1a2b8a5496a8632244fcdf4676eb1c21aad2c.
The actual base-manifest digest is
f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6.
Every preparation binds these identities, all retained readiness files, the
original/control business evidence, the actual generated raw steps and the
source119 inventory. A successful baseline counter is never invented.

## Question and limits

The research question is whether supervised updates from authorized, independently
business-checked authored A targets change descriptive outcomes on these already
exposed A/B tasks when this exact frozen parent has zero observed A successes.
Supervised cross entropy does not mathematically require an earlier greedy
baseline task success. This allows an explicit new study, while the original
positive-A native admission requirement remains enforced by the unchanged core.

These are old exposed development tasks, not new independent user/task samples.
No new teachers, users, independent sources, selection cohort, confirmation C,
adoption event or circuit experiment is supplied. Completion, decreasing loss,
changed parameters or any improved repeated-task result alone cannot establish
scientific generalization, PoUW eligibility or a new foundation model.

## Fixed input, runtime and output boundaries

WORKSPACE_ROOT is exactly:
 /dev/shm/hepta-cell-experiments-v3-20261116-0c078a

RUNTIME_ROOT remains exactly:
 /home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a

The runtime interpreter is RUNTIME_ROOT/venv/bin/python with -I -B. The unchanged
helper04 runtime guard checks this exact interpreter and prefix, every installed
distribution, exact pinned versions, and recovery evidence hashes at HOME.
The workspace cannot substitute for that runtime root.

The fixed source is WORKSPACE_ROOT/candidate-qwen-03. Its original source02
archive SHA is 38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7.
Its source119 manifest SHA is
f4baf14dfb07513ade469adf6877ce6cd15ac98fbcc0e390854fcf24c85ae2be.
The original 64 core files, 32 hepta_cells files, fixtures, model materials and
helpers01-04 are unchanged. Historical confirmation members remain excluded.

Readiness is WORKSPACE_ROOT/probe-qwen-parent-03.
Helpers are WORKSPACE_ROOT/e1e2-operation-helpers-04.
Actual research code is intended for WORKSPACE_ROOT/research-sft-v1-source.
Actual research output is intended for WORKSPACE_ROOT/research-sft-01.
Only root owns deployment/launch of that real research operation.

All preparation/output/source/readiness/helper/diagnostic paths are explicit
absolute nonsymlink descendants of the RAM workspace. Output must be separate
from source, helper, research code, diagnostic source and prior readiness paths.
Create-only outputs preserve failures and prohibit silent continuation/retries.

## New admission and artifact contract

The four new runtime modules are research_sft_contract_v1.py,
research_sft_train_v1.py, research_sft_execution_v1.py and
run_research_sft_v1.py. They have their own exact source inventory.

Profile: research.authored-sft.v1.
Admission: verified_authored_A_research_only.
Plan schema: hepta.research-authored-sft-plan.v1.
Model schema: hepta.research-authored-sft-model.v1.
Model family: hepta-qwen25-coder-research-authored-sft-v1.

The original native candidate validator rejects this new model schema. No native
contract/global is monkeypatched. Only frozen pure helpers and numeric kernels
are reused. Each of six A labels must remain authorized for training, keep its
original task/source/lineage/split/input/final-answer identity, and have a bound
actual successful original/control reference receipt. Student actions remain
trainable=False. The complete real baseline is recomputed and retained with its
actual A success count, including zero.

Retrieval is constructed from these verified authored A examples even when the
baseline count is zero. It uses the unchanged retrieve function, excludes the
same task/lineage and never reads an exposed B answer into the shown prompt.

## Six arms and four fits

1. parent: unchanged base, primary evaluation and independent-process cold repeat.
2. retrieval: unchanged base with A-only retrieval, same evaluations.
3. final_answer: 64-step SFT of authored final answers.
4. trajectory: 64-step SFT of original prepared authored trajectories.
5. shadow_correction: 64-step trajectory SFT after six fresh, unexecuted parent
   shadow predictions and authored corrections.
6. controlled_correction: 64-step trajectory SFT using the actual earlier parent03
   controlled A observations plus authored corrections.

The collector performs only six fresh shadow generations. Those predictions are
not executed as patches or counted as business successes. Controlled observations
are reused with their actual failures, outputs, feedback and costs linked to
parent03; reuse adds no new generation/verifier call or independent sample.
It is not new on-policy experience from an updated student.

The collector performs twelve actual authored-reference checks, one per derived
shadow/controlled correction. It saves all four cohort files, all four plans and
a complete PLANS bundle before any fit. Every fit checks that whole bundle,
its own record/plan hashes and operation identity. No fit replaces a failed arm.

## Exact budgets and numeric policy

Each of the four fits has 64 steps, sequence length 1536, batch size one,
learning rate 0.0003, seed 1729, LoRA rank 4, alpha 8, dropout 0, q_proj/v_proj
targets, AdamW betas [0.9,0.999], eps 1e-8, weight decay 0.01 and gradient norm
limit 1.0. Gradient checkpointing remains enabled with use_reentrant=False.
Only LoRA parameters train. CUDA BF16, 70% allocator limit and the unchanged
4 GiB free-memory check are retained for actual research.

The original selected_token_loss and parameter-hash function are directly reused.
The original 64-step round-robin record/turn loop is reused; its tokenizer pad
value becomes an explicit argument for a real CPU engineering fixture.
There is no truncation. After train() returns, gc.collect and
torch.cuda.empty_cache reclaim released tensors before evaluation's unchanged
4 GiB device check.

Maximums for the new operation:
- 4 fits, 256 optimizer steps, 393216 padded training positions.
- 2 attempts per evaluated task, 384 new tokens and 4096 input tokens per call.
- 6 fresh shadow calls plus at most 216 evaluation calls = 222 model calls.
- At most 85248 generated tokens.
- 12 correction references plus 24 mandatory fit references = 36 reference calls.
- At most 216 student-evaluation verifier calls.
- Collector 600 s; fitted primary with evaluation 1800 s; each other evaluation
  600 s; complete coordinator operation 14400 s.
- Automatic retry false; truncation false.

The thirteen-stage schedule is collector, then primary/cold for each of six arms.
A failed primary remains failed and receives no replacement fit or cold run.
A failed cold run retains its primary evidence but is not a complete cold slot.

## Measurement and partial failures

Evaluation uses all six A retention tasks and three exposed B tasks. Each attempt
retains request, generated output, actual verification and original/control
business evidence. Syntax admission alone is not success. First-attempt and final
bounded-attempt outcomes stay separate.

Each authored reference invocation durably saves an intent before the call and
the actual receipt immediately on return. Failures retain their cost/unknown
tail. Training-level REFERENCE_RECHECKS is a summary and is never counted again.
Every optimizer step is separately fsynced to STEPS.jsonl.

The retained ledger counts readable raw evidence, records corrupt-file byte
identities and unknown gaps, and retains completed subtotals. It does not infer
zero calls/tokens/costs from missing output, a truncated log, an empty child list,
or a failed process. Durable train entry is named fit_attempts_started, distinct
from measured optimizer updates and completed fits. Measured monetary cost,
energy and GPU active time remain unknown when no measurement exists.

Coordinator, worker, training and panel cost scopes overlap and are not additive.
Panel costs exclude load/close. Previous parent03 costs are linked separately
and excluded from new-operation totals, not erased or claimed zero.

Cold recovery must load the identical manifest/adapter bytes in a separate actual
process. Deterioration remains an observed result; identical scheduling or source
does not promise bitwise cross-host determinism.

## Diagnostics and universal unqualified scope

A separate read-only diagnostic implementation/rules file is frozen before any
fit. The operation freeze binds that file path and full SHA plus its adjacent
source SHA. There is no circular dependency on future candidate identities.

Fixed three-slot diagnostics use final_answer, trajectory and
controlled_correction. Shadow correction is separate. No failed slot replacement
is allowed. Full slot admission requires complete primary fit/evaluation and
exact cold identity. A union of successes is not learned routing, a circuit,
a selected winner or evidence of source-growth scaling.

Every result/plan/model carries research_only=true and
protocol_changed_after_observed_failure=true. The following remain false:
scientific_confirmation_qualified, native_cell_adoption,
proof_of_useful_work_eligible, circuit_qualified, independent_selection and new_C.
candidate_selected remains null. Independent sample increment, added teachers and
new users remain zero. E3, E4, E5 and E6 remain explicitly BLOCKED.

Equal steps and padded positions do not establish equal supervised-token counts,
wall time or inference cost. Shadow uses one unexecuted prediction while controlled
observations contain executed feedback/history, so their difference has multiple
causal components. The protocol reports these limitations rather than tuning
the settings after seeing a result.

## Engineering boundary

Engineering runs use an isolated WORKSPACE_ROOT/research-sft-v1-engineering-01,
the same pinned interpreter, CUDA_VISIBLE_DEVICES="", offline environment and a
300-second limit for each CPU child. Twelve behavioral cases cover admission,
failure accounting, native exclusion, retrieval, cold identity and a read-only
real parent03 compatibility check. One tensor case builds a random tiny Qwen2
configuration and real PEFT adapter, calls the production fit_steps for 64 padded
steps, checks actual CE/gradients/AdamW, and verifies saved adapter roundtrip through
the new loader. Only its base-loading boundary is explicitly synthetic.

No pretrained model or tokenizer is loaded by engineering, no real Qwen generation
or research fit occurs, and no authored business verifier is executed there.
Synthetic receipts and numeric fixtures never enter experimental samples,
operation budgets, task success rates or qualifications. Real exits, logs,
failures and skips are preserved; absent Torch cannot count as a pass.
