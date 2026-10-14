# Signed outcome gain: align the loss, retain the cheap controls

Parent: `18aaee987fdb67716dc65f354630e7e3c90ba3b3`, Draft PR #1550.
The original entry gains `gain_weighted_routing_v1`. No existing model, loss,
profile, threshold, solver, CPU limit or production owner is replaced.

## Decision objective, not an accuracy promise

Let D be verified deep utility minus verified shallow utility, minus the existing
.002 deep-request price. This price is a declared utility proxy, NOT measured CPU.
The original unweighted binary loss estimates P(D>0|features); that frequency need
not rank E[D|features]. Example: one context yields +.01 with probability .9 and
-.99 otherwise; another yields +.99 with probability .1 and -.01 otherwise. Their
positive frequencies are .9 and .1, but expected net gains are -.09 and +.09.
A scalar threshold on those exact frequencies cannot choose only the second.

New signed weighting keeps y=1[D>0], and uses w=abs(D). Conditional weighted log
loss is -A log p - B log(1-p), with A=E[D_+|x], B=E[(-D)_+|x]. If A+B>0 its
minimizer is p=A/(A+B). Hence p>=1/2 selects the nonnegative expected net gain.
If A+B=0 all actions tie in this target; all-zero training weight rejects rather
than fabricating a fitted model. This is a population objective identity, not a
finite-network, probability-calibration, distribution-shift or source guarantee.
The fixed .5 variant and a separate selection-tuned threshold are BOTH retained;
the latter is empirical selection and does not inherit the .5 identity.

Related cost-sensitive deferral background (not a claim to reproduce its method):
Mozannar and Sontag, ICML 2020, Consistent Estimators for Learning to Defer to an
Expert, https://proceedings.mlr.press/v119/mozannar20b.html.
The two-action reduction above is stated explicitly for this experiment.

## Matched experiment and source boundaries

Both new fits use the SAME 265-parameter gated network, seed 982451653, 15 public
pilot features, 160 AdamW updates and learning rate .01. Frequency and signed
weighting are compared with fixed-half AND selection-tuned thresholds. The full
old twelve-method comparison remains, giving sixteen methods. Each arm executes
its own pilot, selected revelations and continuation inside the existing 100ms
process CPU / 20k-node decision limit and two-verification total allowance.
No answer or deep result is borrowed across arms; all adaptive gates use the
same prepared-gate execution path. Preparation and training are charged.

Load and independently audit the prior outcome-depth artifact. Its 288 training
and 96 selection stories supply original verified teacher gains; no test label
enters fitting/threshold choice. The three frozen lexical Heads, residual and
calibration stay fixed. Eight new frames were specified before the first scoring
run, without filtering by model disagreement/errors. They yield 192 stories with
48 unique instruction strings. Sixty known-form stories are explicitly replays.
Neither repeated tasks nor disjoint strings establish independent authors or a
future observation window. Truth uses a constrained simulator, not human labels.
All output buffers are closed before new evaluation labels are scored.

## Observed result, including the unchanged errors

On the new 192-story batch, one-step, fixed-two, confidence, frequency-selected
and signed-selected each return 192 answers, 189 correct, with 94 verifications.
Signed-half also gives 189 correct but requests nineteen deep solves. Signed-
selected requests zero, as do one-step/frequency-selected/confidence. Fixed-two
requests 192; requested horizon is NOT executed sequential reasoning depth.
Exact reverse is 192/192 with no learned planner. Verify-all is 192/192 with
384 checks. All sixteen methods retain 60/60 known-form answers.

The independent post-score diagnostic shows one-step and two-step have the SAME
final answer on all 192 stories, including the same three errors. An oracle that
can ONLY select between THESE TWO fixed continuations cannot exceed 189 correct.
This is not a bound on other actions, verifiers, models or all two-check policies.
The three errors occur in the participant-exclusion frame and exhaust the two-
check budget; selecting a deeper root alone does not repair them.

Final local controller CPU: one-step .048220533s, fixed-two .084602651s,
frequency-selected .073523806s, signed-selected .082065844s, signed-half
.115328174s, confidence .094900238s, exact reverse .011950800s. These are one
batch's component observations, not stable ranking or full lifecycle advantage.
The first batch's timings, including a faster confidence result, remain retained.
No advantage over one-step or exact reverse is claimed. Signed fit loss falls
.83019495 to .02002800; lower loss is not independent task improvement.

## Reproduction, audit and failures

Use the original study entry, with a complete byte-bound outcome-depth artifact:

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile gain_weighted_routing_v1 --evidence-dir /fixed/outcome-study \
  --output /new/gain-study
```

The no-Torch/no-runtime-planner auditor reconstructs teacher provenance, signed
weights, selected thresholds, source semantics, frozen logits, conditional worlds,
revealed checks, final answers and CPU totals. The fast source parser uses compiled
registered grammar; the audit enumerates renderers independently. Exhaustive role
permutation tests check their meanings. Switching that parser after the first run
changed neither data, labels, policies nor any of 4,032 paired non-work outputs.
No post-test tuning of loss, threshold, budget or probability was performed.

484 source regressions pass. Actual Torch checks execute 120 methods: 119 pass,
one inherited retained-object tracking test fails at the original 100ms proposal
limit. It is not retried to green. Three new signed-fit contracts pass, including
an actual fit on the two-context witness. The tool transport timed out during a
combined command, while its child tests/run completed with separately recorded
exit status; no completed result is inferred merely from that transport event.
Artifact mutation tests and clean-parent application are separate retained logs.
No new pretrained forward, native Rust build, independent risk qualification,
main merge, general continuous FBSDE claim or model activation. Keep Draft.
