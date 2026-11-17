# Read-only review plan for research-sft-01

Status: review plan written after the coordinator reported the unique research
launch and before this reviewer has read any live or terminal research result.
This is a repository review document, not a new scientific result, preregistered
confirmatory study, amended execution policy or permission to change a run.

## 1. Authority, evidence boundary and fixed references

Root owns the actual run, process control, final diagnostic execution and archive.
This reviewer will not start, terminate, retry or poll experiment processes; read
unexposed C; modify frozen code, data, budgets, diagnostic rules or outputs; or
invoke a model, tokenizer, training step or business verifier.

Root reported Mac PTY dpty-22194fb4ecaad80fc4e3d160942c8ec64adece6fd9315d47a90060d8b2413a7c,
Desktop coordinator PID 2229904, and launch freeze SHA256
7ab422618abbbff461c47798e67b5e9a1988aab9114cf26cffa51a0e84caee4a.
These are coordinator-supplied launch identifiers. This document does not claim
that this reviewer independently observed their current process state.

After root supplies a closed, verified Mac archive, review will read that archive
and its exact manifests and raw receipts. It will not infer closure from a nice
summary, the disappearance of a controller, or a numeric result alone. An archive
that lacks authoritative terminal evidence remains incomplete.

The implementation and protocol are frozen at:
 /Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a/research-sft-v1-source-working/

Key references:
- RESEARCH_PROTOCOL_V1.md:
  1f3171699624a18f705728f495d81c51c4909d2e7c3a6950df14335b31cdc0ee
- FINAL_SOURCE_MANIFEST_V1.json:
  f305a38ee6da70e886b5756eec663f12c0a9cce5baf23754836991f6cf321b71
- RESEARCH_SOURCE_V1.zip:
  a3e2228377c20dab52a8cdfa20ce3cef62f92b75c5eacb1a5cea426b43e922bc
- LAUNCH_INPUTS_V1.json:
  038e8c7702524b3a5270defe5bae386311104da94f5f84db0c2b5a8a270cd1ce
- Actual parent03 RESULT:
  33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d
- Actual parent03 FREEZE:
  02fa20ad7ce2d74d8631dd5a6ac1a2b8a5496a8632244fcdf4676eb1c21aad2c
- Base model digest:
  f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6
- Diagnostic rules:
  93dff768e527af37551a71b3cf89c47b2b8ad83dae461e11d7a8214cfc0e5ddc
- Diagnostic source:
  c43ff3c5f9bc99c5825a96e0f4b4020d361489d2ffa3ae31bffe49f03ddb6f91

The former design hash d4aa19925cd347602e853570c2ff62c1b7744597aaa70c9f2cc18a883162738f
is a historical review identity. Its lost RAM bytes have not been restored.
RESEARCH_PROTOCOL_V1.md is the explicit new approved restatement.

## 2. Separate the three questions

The report will distinguish:
1. Execution integrity: did the frozen operation actually run, produce bound
   artifacts, preserve failures, and respect its budgets?
2. Descriptive task outcomes: on these same old exposed tasks, which actual
   first/final business outcomes and resource measurements changed?
3. Causal and external claims: what remains unidentified despite those outcomes?

Passing question 1 is not evidence for positive question 2. A positive result for
question 2 does not establish generalization, online learning at user scale,
teacher complementarity, learned circuits, adoption, new C or PoUW.

The baseline admission remains the complete real parent03 with A=0/6. It is not
rewritten because a later repeated parent arm or trained artifact happens to
succeed. Native positive-A admission is still closed. New research admission
uses independently business-verified authored A targets under its own schema.

## 3. Closure and immutable identity checks

Before interpreting counts, review will bind the complete chain:
- Root launch freeze and exact argv, wrapper/source hashes and immutable inputs.
- Owned INTENT, STARTED and actual Popen.wait EXIT, including exact stream hashes.
- Terminal/controller observations preserved as actually returned, including any
  uncertainty; the controller response is not silently upgraded to a clean exit.
- Coordinator FREEZE, INPUTS and RESULT or FAILED; all plan/model/source identities.
- Worker LAUNCH and exactly one retained terminal receipt per launched process.
- Closed export manifest, ordered parts, whole archive/index identities, member
  identities and the final source comparison already performed by the exporter.

Reading a file successfully does not replace checking its recorded identity.
A sealed aggregate will be compared with its raw evidence, not treated as proof
that the described model call or business execution occurred.

This review does not need to load large base weights or unpickle optimizer files.
Adapter/optimizer byte identity can be checked against their recorded inventory.
Any additional check requiring execution must remain outside this read-only scope.

## 4. Four fits: actual updates, supervision and lineage

Expected fit arms are final_answer, trajectory, shadow_correction and
controlled_correction. There are six original A record groups in fixed order.

For each arm, review will inspect its frozen record/plan files and the complete
PLANS bundle, then workers/<arm>-primary/research-model/:
- STARTED.json, TRAINING.json or FAILED.json;
- STEPS.jsonl, manifest.json, adapter inventory and optimizer byte identity;
- references/<index>/REFERENCE_REQUEST.json, REFERENCE.json and measurement or
  failure evidence, plus the non-additive REFERENCE_RECHECKS summary.

Four plans must precede the first fit. Every plan must retain the exact six
authorized A identities, allowed targets, mode, source inventory and operation ID.
Student trajectory events must remain trainable=False. A changed record digest
will be resolved against actual task/input/target/lineage changes, not accepted
merely because a new aggregate hash is self-consistent.

A complete fit requires 64 actual durable step receipts numbered 1..64 and a
consistent complete training receipt. The six group update totals must be
[11,11,11,11,10,10]; turn selection must match the frozen round-robin rule.
A STARTED file alone establishes only a fit attempt, not a gradient update.
A loss entry, changed adapter or saved optimizer alone does not establish all
64 updates. Completed prefixes and missing/invalid tails stay visible.

The per-arm table will separately report:
- Fit attempt status, completed steps and parameter-change receipt.
- Original record groups and actual encoded supervised turns.
- Dropped terminal duplicates, record/turn update counts and source identities.
- Input tokens consumed, actual supervised tokens and padded positions.
- Actual wall/CPU measurements and peak allocated/reserved GPU memory.

Complete per-arm padded positions should be 64*1536=98304; all four would total
393216. Actual supervision is not required to match across arms and must never be
filled with the 128-token tiny engineering fixture value. Every synthetic CPU
fixture count, test artifact and pre-existing engineering result is excluded from
the actual study's budgets, samples and task outcomes.

The unchanged numerical profile will be checked through the plan/source and
artifact chain: rank 4, alpha 8, q_proj/v_proj, AdamW settings, seed 1729, sequence
1536, 64 steps, CUDA BF16 and the original device/memory policy. Review will not
change these values in response to a failure.

## 5. Business outcomes: first attempt and final bounded attempt

Each six-arm primary/cold evaluation has the same expected six A retention tasks
and three exposed B tasks. Review will join by original task/source/lineage IDs,
not by whichever rows are easiest to compare.

Each claimed success must trace to the actual generated output, request/history,
verification receipt and original/control business evidence. Syntax validity,
patch-format acceptance, model confidence, loss or a fabricated success counter
does not replace original/control business execution.

The report will keep these distinct:
- First-attempt business success.
- Final outcome after at most two actual attempts.
- Actual attempts used, execution/verification status, output-cap hits and any
  context-limit failure.
- Complete expected panel size, readable measured outcomes and missing outcomes.

An actual verifier rejection is a measured failure even when the candidate patch
was not executed. An interrupted call with no valid verifier receipt is unknown.
Missing outcomes are not converted to failures or silently removed to improve a
rate. A partial arm is reported with its known counts and explicit unknowns;
it does not receive a complete-panel success rate.

Task-level paired changes will be shown against the appropriate contemporaneous
frozen-parent primary results, with the historical parent03 A=0 observation kept
separate. Cold repeats are reported separately; primary/cold outcomes are not
cherry-picked into a stronger score.

With only three exposed B tasks, one task changes the complete-panel proportion
by one third; with six A tasks, one task changes it by one sixth. This granularity,
shared provenance and repeated exposure prevent a precise population-growth or
broad-generalization interpretation. Replays, seeds, subagent branches, attempts
and cold repeats never multiply the independent sample count.

### The A=0 retention distinction

Retention of the baseline's originally solved A tasks has a zero denominator.
That retention ratio is null, not 0%, 100%, "no forgetting", or perfect retention.

The six-task A panel still has meaningful observed success counts and, if fully
measured, an absolute success rate. New A successes may be reported as descriptive
learning on repeated exposed tasks. Relative improvement over a zero baseline is
undefined; absolute task changes do not establish retention of prior capability.
A wider forgetting claim would require an appropriate previously solved cohort
that this protocol does not add.

## 6. What E1 can and cannot attribute

The comparison includes the frozen parent, the same parent with A-only retrieval,
final-answer SFT and trajectory SFT. Review will verify that base identity,
generation policy, maximum attempts, panel identities and frozen budgets are
consistent before comparing outcomes.

Equal 64-step budgets and padded length do not imply equal supervised-token
budgets. Final-answer and trajectory modes can differ in trainable turns,
target lengths, duplicated terminal target handling and the number of selected
head logits. Effective target exposure and real wall/CPU/GPU-resource measurements
must accompany any claimed difference. The existing run cannot retrospectively
isolate "trajectory structure" from those supervision differences.

Retrieval can alter visible context length and inference cost while leaving
weights frozen. It is a relevant baseline, but cannot be assumed cost matched
merely because maximum input/output limits are equal. Exceeding a context bound
is a retained result, not a reason to truncate or replace a task.

Training may fit the authored references or these already exposed tasks. A gain
on old B is descriptive development evidence; it is not an independent holdout
estimate. This protocol was selected after observing failures, and that
post-failure status remains explicit even if its outcome is favorable.

The authored targets and trajectories do not constitute newly authenticated
external AI teachers. E1 here does not prove transfer from every existing agent,
multi-teacher complementarity, or a new foundation model.

## 7. What E2 can and cannot attribute

Shadow correction adds six fresh predictions from the unchanged parent, one per
A task, without patch execution or business verification of those predictions.
They remain unmeasured student actions, not successes or teacher targets.

Controlled correction reuses the complete actual parent03 A observations,
including its failed attempts and feedback. The reused observations must equal
the bound old raw steps. Reuse adds zero new model/verifier calls and zero
independent samples; its historical costs remain separately linked.

Both correction cohorts still use authorized authored final targets. Student
actions remain masked. Any difference can reflect history/state exposure,
feedback content, number/length of turns, selected-target exposure and earlier
execution costs. One unexecuted shadow prediction versus bounded executed
controlled attempts does not isolate a single causal treatment.

Controlled-vs-trajectory or controlled-vs-shadow improvements would therefore be
described as changes under this particular authored-correction construction.
They would not establish that student experience is necessary, that recovery
caused the gain, or that a continuously updated student learned online. The
controlled experience came from the parent before these fits, not a new
on-policy rollout of each updated student.

If later first/final outcomes diverge, repair behavior must be traced to actual
second-attempt feedback/history and cost. A final-success advantage alone does
not show a first-attempt capability gain.

## 8. Cold identity and the boundary of recovery

Each cold result must use the exact same manifest hash/model digest and unchanged
adapter inventory as its own primary, in a distinct actual process. Review will
bind MODEL_IDENTITY, MODEL_LOADED, generation settings and panel/request identities.
A different candidate with the same display name is not the same recovery.

Same-identity cold outcome deterioration or token/output differences are retained,
not averaged away or repaired by another cold run. Exact identity does not by
itself promise bitwise determinism or equal business outcomes.

This protocol cold-loads base plus adapter for inference. A saved optimizer file
is not evidence that optimizer state was restored and training resumed.
The review will not call this a demonstrated training-resume/checkpoint recovery.
It is also not E6's independent B selection followed by new C use and adoption.

## 9. Costs, incomplete work and non-additive scopes

Review will reconcile the frozen retained ledger against actual request/output/
step files, per-reference files and training step logs. Reference batch summaries
must not be counted again. A request is an intent; it is not proof of a completed
generation. Earlier completed work remains counted when a later call fails.

The expected new-operation ceilings are 222 generation calls, 85248 generated
tokens, 256 training steps, 393216 padded positions, 36 authored reference
rechecks and 216 student-evaluation verifier calls. Unused budget is not measured
work. Missing evidence is not measured zero. The report will distinguish
complete totals, measured subtotals, unknown gaps and any observed overrun.

Costs are kept by explicit scope:
- Coordinator operation cost, including completed child CPU as actually measured.
- Worker, fit and evaluation costs, which overlap the coordinator scope.
- Actual panel cost excluding model load/close.
- Historical parent03 cost, linked but excluded from new-operation totals.
- Engineering/preparation cost, separate from experimental treatment cost.

These rows are not summed together as if disjoint. Successful early stopping can
reduce the actual number of attempts, so equal call ceilings do not make actual
inference cost equal. Peak GPU bytes are capacity observations, not GPU active
seconds, energy, FLOPs or money. Missing GPU-time/energy/currency measurements stay
null. The report will not infer total-system cost matching from panel-only data.

## 10. Fixed slots, union and unchanged qualification

The fixed three diagnostic slots are final_answer, trajectory and
controlled_correction. Shadow is a separate arm. A slot needs a complete primary
fit/evaluation and exact cold identity under the frozen rules. Failed slots are
not replaced by whichever arm later performs better. Partial primary evidence
can remain visible without promoting its slot to available.

A union of successes over fixed experts is a descriptive opportunity measure.
It is not a learned router, an efficient Neural Circuit, an adopted candidate,
a trained foundation model or evidence of source-growth scaling. It does not
subtract routing/selection cost that was never measured.

Every reported conclusion must remain consistent with:
 research_only=true; protocol_changed_after_observed_failure=true;
 scientific_confirmation_qualified=false; native_cell_adoption=false;
 proof_of_useful_work_eligible=false; circuit_qualified=false;
 independent_selection=false; new_C=false; candidate_selected=null;
 independent_sample_increment=0; external_teacher_count_added=0; new_users=0.

E3, E4, E5 and E6 remain blocked by the missing experiments. Nothing in this
review adds a successful witness or changes the original native contract.

## 11. Result report structure after root supplies the archive

The eventual repository review will contain:
1. Exact archive/source/terminal identities and completeness.
2. A per-arm execution/training table, including partial failures.
3. Task-level first/final A and old-B outcomes, primary and cold separately.
4. Per-arm supervision/exposure and measured cost table with explicit scopes.
5. Same-candidate cold checks and any observed deterioration.
6. E1/E2 descriptive findings together with the identification limits above.
7. Contradictions, missing evidence and what remains unavailable.

A result may be negative, partial, mixed or uninformative. None of those states
will trigger a retry, budget change, hidden task substitution or altered frozen
metric. No result values are filled into this plan.
