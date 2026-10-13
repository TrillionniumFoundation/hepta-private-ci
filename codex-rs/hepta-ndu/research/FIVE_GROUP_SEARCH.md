# Native Group evidence search and one-step NDU allocation

Source parent: `41a5bf670f827e332459614313f338e15969458e`, PR #1697.
This additive implementation extends E3/E4, preserving the existing Reader,
Head, experiment, dual-signature admission and historical diagnostic code.
It does not replace the local Rust owners, selected models or production policy.

## What is now implemented

`five_group_search.py` adds a real PyTorch `GroupValueCell`: a shared projection,
GRUCell state, action-value prediction and a common stateless answer-value
readout. Inference has no optimizer or parameter mutation. At width 384 and
hidden width 32 its structural parameter count is 18,786, counted once per
Group controller, not once per logical Cell or search node. This is a count
from tensor geometry, not an executed device-memory measurement.

The `train` path actually performs bounded candidate-only SGD on supplied
TRAIN histories, evidence-view features, raw-answer features and independently
observed outcome labels. Future/evaluation rows, missing outcome lineage,
nonfinite values and invalid dimensions are rejected. Checkpoints are written
as safetensors and reloaded for equality. The training receipt does not
self-authenticate its outcomes, establish causal support or grant adoption.

The inference path uses the existing `LocalEncoder` and `NativeSession` from
`five_causal_native.py`. Each scoped comparison trial loads one frozen Encoder,
one frozen Reader and one Group controller; all search nodes reuse them.
A new attempt changes the delivered evidence view, not merely its arm label.
Raw answer observations update Group state, changing later action selection.
The final answer is selected with the SAME frozen learned answer-value readout
in every control. There is no best-of-gold selection or answer postprocessing.
This learned readout is not an independent semantic verifier.

## Actual evidence actions and all controls

The preregistered menu is one empty view, all singleton views, and all pairs
in original source order. One to eight original text sources are supported;
with eight sources the menu has 37 genuinely different evidence inputs.
No query, source content, target label or answer is manufactured. All arms pay
for one initial empty-evidence Reader call. There are at most eight Reader
requests per trial, including that initial call. Every view is used at most
once. No deliberate padding is performed when a controller stops.

E3 preserves the existing four arm names and implements these explicit controls:

- `stateless`: score remaining views with zero state on every round.
- `independent_attempts`: a frozen query-keyed permutation of independent Reader
  views, with no state transferred between attempts.
- `fixed_search`: fixed larger-view-first traversal, with no learned routing.
- `learned_recurrent`: choose from the same views using updated Group state.

All E3 arms use the same maximum request count, the same Reader and the same
final readout. Same caps are not a claim of matched actual FLOPs or latency.

E4 uses the same recurrent controller and final readout:

- `fixed_budget`: keep choosing predicted-best views to the call cap.
- `threshold_rule`: stop when the common incumbent prediction reaches a fixed
  confidence threshold; otherwise use the same predicted-best routing.
- `shuffled_utility`: rotate the same vector of predicted values by a frozen
  nonidentity permutation before allocation; labels and final readout are unchanged.
- `ndu_allocation`: continue only when the best predicted next-answer score
  exceeds the incumbent score by more than the declared per-call utility cost.

The NDU profile is `hepta.five-group.one-step-expected-score.v1`:
`max_a predicted_quality(next_answer | state,a) - incumbent_quality - call_cost`.
This is a one-step, fixed external-score special case, not a general recursive
utility, calibrated stochastic environment model, Brownian/FBSDE solver or
optimal-stopping theorem. The cost is a REGISTERED UTILITY-UNIT charge per Reader
request, not fabricated joules, dollars or FLOPs. Actual resource observations
remain separate. A deeper search may have value not captured by this one-step
rule; future comparisons must test that limitation rather than hide it.

## Admission and complete execution

The `run` command invokes the EXISTING frozen-cohort and independently signed
Reader gate via `admit_stage`. E3/E4 cannot enter through the historical diagnostic
or a fixture key. It verifies current running-source SHA and exact full bundle,
Reader/Encoder/preprocessor/menu/verifier binding. Every arm on a given task
uses the same Group descriptor, controller weights and request cap.

The descriptor schema `hepta.five-group.bundle.v1` is stored at
`bundles/<SHA256-of-exact-canonical-JSON>.json` and contains:

- profile, scope, purpose, generation, complete `bindings` and exact `menu`;
- `reader_checkpoint_sha256` pointing to the existing native Reader descriptor,
  with the same scope, purpose, generation and bindings;
- `encoder: {path, snapshot, maximum_tokens}` using the existing verified loader;
- `controller: {path, sha256, width, hidden, training_receipt_sha256,
  calibration_receipt_sha256}` for local safetensors;
- `maximum_reader_calls`, `call_cost` and `confidence_threshold`.

`bindings.encoder` binds the exact snapshot. `bindings.action_menu` is the
canonical digest of `MENU`; `bindings.preprocessor` is the canonical digest of
`five-group.public-view-and-raw-answer.mean-pool.v1`. `bindings.verifier` is the
digest of `{controller_sha256: <weights SHA>, profile: common-stateless-answer-judge-v1}`.
Reader/tokenizer/prompt/decoder bindings use the existing native implementation.
The external review owns authentic calibration and outcome evidence: two strings
containing hashes do not prove that calibration or independent review occurred.

Every trial journals a fsynced start before model loading. Every Reader dispatch
journals another start before invoking the model. Action inputs, raw answers,
predicted values and stopping decisions are retained without hidden retries.
Post-dispatch errors and overruns retain failure/unknown evidence. If a trial
fails, it stays in the registered denominator and cannot receive a valid scored
answer through the existing analysis path. Deadline checks are at operation
boundaries, not GPU/kernel preemption. No restart-resume is added here.

All evidence views are encoded up front and the cost is counted; this is not a
claim of free observation acquisition. Actual raw answers are encoded as further
observations and those forwards are counted too. Reader requests, Reader forward
calls, Encoder forward calls, model loading and total wall time are distinct.
Shared-model lifetime is per comparison trial; there is no across-control warm
cache advantage. Cross-trial resident amortization, target-host peak memory,
energy, FLOPs and total training/migration economics are not established.

## Commands

```sh
python scripts/memory_cell/five_group_search.py train \
  --plan /approved/train-plan.json --output /new/group-candidate

HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256=<independent-preregistration-pin> \
HEPTA_FIVE_READER_REVIEW_SHA256=<independent-reader-admission-pin> \
HEPTA_REVIEWER_ROSTER_SHA256=<independent-authorized-roster-pin> \
python scripts/memory_cell/five_group_search.py run \
  --plan /approved/frozen-bundle.json --review /approved/preregistration.json \
  --reader-review /approved/reader-admission.json --root /approved/materials \
  --experiment system2 --output /new/group-run
```

Use `--experiment ndu` for E4. The TRAIN plan schema is
`hepta.five-group.training.v1`, with `data_kind` (`approved_training` or
`historical_development`), width/hidden, steps/learning_rate/seed, the pinned
encoder_snapshot_sha256 and examples. dataset_sha256 must be the canonical
SHA256 of the supplied examples. Each example has exactly id, split=train,
history (at most 16 feature observations), view, answer, outcome in [0,1] and
outcome_receipt_sha256. No human approval, model checkpoint or new natural-task
label is generated by the tool. Provenance and data-use permissions must come
from their existing owners before a production training integration.

## Current evidence and limitations

This turn's container and Python execution probes failed with `ClientError`.
The existing exact-source native workflow 38365144109 was still queued when
read. Therefore the new optimizer/loop tests are SUBMITTED, not claimed passed;
there are no new pretrained outputs or independent natural-task outcomes.
The scoped workflow installs the pinned CPU dependencies and tests the new
controller alongside inherited experiment, Reader, Head and signature tests.
It deliberately does not repeat the earlier 376 MB acquisition/16-call Reader
job or declare its pending execution successful.

The previous attached 6,938-parameter Head results remain historical exposed-
TRAIN diagnostics, not this source's new evidence. They do not validate this
18,786-parameter Group controller or prove reasoning transfer. E1/E2 full
independent results, trained real E3/E4 checkpoints, evaluator calibration,
new task families, target-host resource accounting, E5 media/split backends and
production owner integration all remain open. No main merge or promotion occurs.
