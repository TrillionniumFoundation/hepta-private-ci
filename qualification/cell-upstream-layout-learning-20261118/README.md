# Upstream A repair targets and two evidence layouts

This prospective E1/E2 mechanism experiment follows the completed 24-call
collection in #6717. No old model output, score, NoUpdate decision, source
identity or generation budget is relabeled. The fixed primary arm is
**native_feedback**. **document_evidence** is its matched control. Both start
from the same actual P430f adapter and a fresh empty AdamW optimizer.

## Material and objective

The eight training records are the first actual P and C attempts for each
of the four authorized A upstream projects, in fixed project/P/C order.
The task, failed answer and exact real verification feedback are observations,
with every prefix label masked. The only positive target is the original
maintainer repair, admitted against the original source and byte-equal to
the original after revision. Existing successful isolated native test receipts
are checked by digest; preparation does not repeat those tests. T2 is not a
positive trajectory source: only its humanize repair passed the original tests.

The document control places the same task, answer and feedback into one labeled
user document. The primary uses the original user, assistant and tool message
sequence. The inherited native chat wire renders tool observations as labeled
user observations. This changes serialization and labels, not raw evidence.
Both arms learn exactly the same target token IDs and see the same record order.

Each arm performs 32 actual updates with a 3584-token padded sequence shape.
Targets are partitioned into at most 256 selected output-head positions per
full causal forward/backward; target-count weighting preserves the original
mean target loss. Every chunk retains the full input and masked prefix.
The CPU numerical test uses the real inherited loss/backward functions.
One fixed largest A record is calibrated on the real GPU for each layout
without an optimizer update before either fit. A failed calibration or fit
is retained and is not silently retried with a different budget.

Actual unpadded input lengths and wall times may differ. Matching target
positions, padded forward/backward shapes, update counts and initialization
does not establish identical physical energy or whole-system cost.

## Retained first calibration failure

The published 4096-token candidate a764cca4 was actually cold-loaded and entered
eager attention, then exhausted its existing 70% CUDA allocator budget.
It made zero optimizer updates and zero generation calls, but consumed real
model loading, attempted forward computation, host CPU time and energy.
Its exact completed forward/backward counts are unknown because the old
chunk helper did not persist partial events. All original failure receipts
remain published and the original execution directory is unchanged.

This separate candidate uses 3584 padded positions, the next 128-token multiple
above the actual longest complete 3471-token A sequence. No evidence or target
token is removed. Eager attention, the 70% cap, target chunks of 256, the common
parent and the 32-update budgets remain fixed. A new durable trace records
every attempted/completed forward and backward so partial failures retain
their observed computation. The real CPU numerical equivalence test is rerun
for this accounting implementation before the new freeze.

## Prospective evaluation

The maximum is 56 new generation calls: 16 A current-policy calls, eight A
common original-P-prefix calls, 24 B3 current-policy calls including P,
and eight B3 common-P-prefix calls. Every current-policy task receives two
calls even after success. All four parent first prefixes are kept, whether
successful or failed. Parent second outputs are reused as the exact-prefix
baseline; they are not fabricated as new calls or counted twice.

The original eight A P calls and their costs remain reused evidence. No new
training may read B3 task material. The four B3 task, protocol and verifier
hashes are committed by the coordinator before this experiment. Both actual
new weight manifests, parameter digests and the weight-freeze timestamp must
be complete before the coordinator releases B3.

The designated native_feedback candidate must improve final success counts
over P on both A and B3, lose none of P's final successes, and preserve P's
successful second calls on the same fixed prefixes. Otherwise the new result
is NoUpdate and P is retained. The document arm is evaluated regardless of A
results. A distinct serialization mechanism benefit requires native success
to strictly contain document success on identical parent prefixes; A and B3
are reported separately. B3 is not used to select which arm is the candidate.

The four-task B3 panel remains a small development evaluation. This does not
establish authenticated external custody, authenticated users, statistical
generalization, absence of base-model pretraining contamination, native
adoption, the full E1 retrieval controls, or E5 growth curves. Original
absolute-recovery-count gates and earlier NoUpdate decisions remain intact.

## Execution and evidence

The old GPU worker lock is used. Each phase has a new output directory,
actual child PID/wait status, explicit time limit and retained raw stdout,
stderr, model outputs, strict patch admissions, isolated pytest receipts,
failures and cost counters. Unknown requests are not restarted. The original
A sandbox and raw JSON patch contract are unchanged; generated code runs
only inside that actual isolated verifier. B3 uses its separately sealed
verifier and immutable original tests.

The inference policy is the already explicit 8192-input/2048-output collection
policy, with no input truncation and the full output reserve checked before
each call. It does not alter the ancestral 384-token model manifests.
CPU RAPL readings, when available, describe the entire host package window
and include concurrent background activity. GPU, network and money remain
unknown. Nested wall/CPU scopes and reused prior costs are not added twice.

Publication is staged into source, prepared data/protocol, actual weights,
and actual evaluation evidence so review can distinguish code from results.

## Explicit allocator revision

The separate 3584 candidate 8f583508 also stopped during its first real
forward: the existing allocator had 1.31 GiB reserved but unused when the
588 MiB softmax allocation failed. Its exact trace contains one started
forward, no completed forward or backward, and no optimizer or generation
call. Its completed P cold load and whole-host energy readings remain costs.

The next candidate keeps every tensor shape, target, attention implementation
and 70% cap. It explicitly configures the native allocator's
expandable_segments option in each owned child process. The
[PyTorch 2.9 memory-management documentation](https://docs.pytorch.org/docs/2.9/notes/cuda.html)
describes this option as reducing unusable fragments by growing allocation
segments. A real 8 MiB CUDA allocation on this installed 2.9.1 runtime showed
an expandable segment and the unchanged 0.70 cap; its raw receipt is retained.
This does not establish that the full training fits: the largest-record
calibration remains an actual gate. No daemon, driver, access policy, other
owner's process or shared environment is changed.


## Actual eager inner-checkpoint revision

The original three eager calibrations, including the real expandable allocator, failed before any optimizer update. The distinct fused SDPA probe completed four real F/B pairs but failed its frozen whole-logit and full-LoRA-gradient thresholds; that rejection remains unchanged. A subsequent original-eager/inner-softmax-checkpoint probe passed all four F/B pairs with zero observed logit or gradient difference on the fixed short A examples. Both have complete retained evidence.

This source adds non-reentrant checkpointing only to FP32 softmax blocks of 128 query rows. The original complete QK and AV matrix shapes and eager causal/padding mask are preserved. Existing decoder-layer checkpointing remains. The additional original/recompute function starts/completions are recorded for every group, including early-stop differences, and must match between arms. The old 72 outer F/B count is not a claim of the same physical work.

First run `owner.py --phase calibration_only` on the fixed largest full 3584-token group, with no optimizer or generation. On actual success, `freeze_training.py` checks original full-gate receipts and creates a new `TRAINING_ADMISSION.json`. Publish that exact admission before `TRAINING_DEPLOYMENT.json` and the two actual 32-step child fits. Both training children cold-load the same P and create fresh empty AdamW; calibration state/gradients are not reused. The main source/data/protocol remain identical across full calibration and training. B3 remains sealed until both real weight manifests and the existing WEIGHTS_FROZEN receipt exist. All previous NoUpdate decisions remain unchanged.


### Full-calibration entry wiring correction

The first full gate at 969903 completed one original eager forward and failed its backward. Its calibrate entry had omitted the new-engine installation call, although train included it; no TRAINING_ENGINE receipt existed. That is an implementation wiring failure, not evidence against full-length inner checkpointing. The original source, owner, partial computation and cost are retained.

Both entries now call the same installer before their first forward. It checks the actual Qwen2 registry callable by Python object identity, the frozen function and module SHA256, the original eager mask callable, all 28 layer configurations and actual forward class identity. Every CUDA chunk repeats the actual-dispatch check and records engine/function SHA and inner counters before model computation. No installed library file is edited. The mathematical checkpoint engine remains exact SHA81ad33310f7bb427d01d25fd4ff696d281e6c53f3bba24cbc80667df63316aaa, so the completed short-A numerical test is retained rather than repeated.
