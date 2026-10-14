# Outcome-supervised depth routing, with a two-by-two teacher ablation

Parent `66258d5871cd022c0fa13995dd6ba787b4d2359e`, Draft #1550. The existing
entrypoint gains `outcome_depth_routing_v1`; no old profile, solver, threshold,
production owner or workflow step is removed. No new pretrained forward occurs.

## What is different

The old depth router learns a numerical teacher's expected model-value gain.
This experiment instead also labels the same two continuations by their FINAL
verified simulator outcomes: +1 correct, -1 wrong, 0 abstain, minus .02 per
requested verification. Actual outcome gain may be negative even when optimal
model value cannot decrease. Both labels are saved beside the prior predictions.
The simulator's exact grammar is an explicit source of knowledge, not an
independent human judgement or a secure separate execution principal.

Both new routers use the same existing 265-parameter gated architecture, fifteen
observable features, initial parameter state, 160 AdamW updates and learning
rate .01. They receive identical training contexts. Only the binary training
label differs (gain > .002). The score is NOT a calibrated success probability.
A two-by-two comparison varies TRAINING LABEL (model/outcome) and threshold
SELECTION OBJECTIVE (model/outcome) separately. Every selection score breakpoint
and reject-all are searched without test outcomes. The cheap confidence gate
uses the same outcome selection set. The existing numerical router, no-check,
one/two-step, selected fixed depth, verify-all and exact reverse controls remain.

The .002 deep-request price is a declared utility proxy, not CPU or energy. It
is charged consistently to requested depth-two solves, including the fixed-two
arm; actual nodes, process CPU and verification fees are reported separately.
A depth-two request that stops at the model bound is NOT two executed reasoning
steps. Choosing one-step remains an approximation, not a global optimality proof.

## Frozen source and split boundaries

Load and independently audit a complete prior depth-study artifact. Its three
base Heads, 129-parameter residual, calibration and original numerical router are
immutable and serialized beside the new evidence. Historical source preparation
costs are copied, not re-executed or silently treated as free. Current shared
lexical vectors and Head forwards are executed and charged; each comparison arm
executes its OWN planning and selected verification sequence. No deep answer is
borrowed from another arm. Pilot, gate, extension and disposal share the original
100ms process-CPU / 20k-node allocation boundary; total verification allowance is
still two. No GC or thread setting is changed to admit a rejected request.

Previously explored renderer frames become 288 router training and 96 selection
stories. Eight newly specified frames supply 192 evaluation stories, plus 60
known-form retention replays. All raw event texts are disjoint across these four
splits. This does not establish source independence: the 192 evaluation stories
reuse only 48 instruction strings. The new frames were specified before the first
model run, without filtering cases by prediction, disagreement or success. They
are generated, constrained examples, not unseen human tasks or a future window.
All evaluation predictions are saved before final labels are scored. Training
predictions are immutable buffer snapshots before labels are appended; this is a
logical record order, not crash-durable or independently authenticated chronology.

## First observed result; no post-test threshold changes

On 288 training stories, 86 have positive model gain but only 21 have positive
verified outcome gain. On 96 selection stories those counts are 14 versus 2.
No observed positive-model / negative-outcome case occurs in these two splits;
the latter possibility is separately covered by a mathematical unit example.

All new methods keep the SAME frozen semantic model. On the 192 new stories,
one-step gets 188 correct / 191 answered with 166 checks. Fixed-two gets 189/192
with 180 checks. Outcome-trained/outcome-selected routing also gets 189/192,
with 168 checks and only TWO deep requests. The matched confidence control gets
exactly the same correct/answered/check counts with FOUR deep requests and lower
measured CPU. Exact reverse remains 192/192 and cheaper; verify-all is also exact.
All modes retain 60/60 known-form answers. Hence no general language, calibrated
risk, full lifecycle or superiority over the strongest cheap algorithm is claimed.

The first full run is retained. Subsequent arithmetic/test repairs change neither
training data, labels, features, policy thresholds nor outputs. Initial tests
incorrectly expected a particular equivalent threshold tie, and the first audit
used ordinary sums near threshold breakpoints. The final independent scalar
reconstruction uses the specified compensated sums, without epsilon-altered
routing. Both original failures are preserved. The final code and raw runs are
checked separately; historical bytes are not relabelled as a new execution.

The saved-file auditor imports neither Torch, the runtime planner nor executor.
It recomputes source operations by regex (rather than renderer matching), forward
world probabilities, both teacher targets, frozen threshold choices, selected
revelations, rendered answers, model bindings, and physical timing sums. Hashes
show consistency, not authentic hardware execution or independent sources.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile outcome_depth_routing_v1 --evidence-dir /fixed/depth-study \
  --output /new/outcome-study
```

## Validation scope

467 source regressions passed, and the same count passed in a reconstructed parent
qualification subtree. The 117 actual Torch methods executed in five batches:
116 passed, one inherited retained-object tracking test hit the original 100ms
proposal CPU limit. No rerun-to-green or budget change. The three new router-fit
methods passed. Seven complete artifact mutation tests passed; an earlier combined
invocation was interrupted by the tool's 45-second limit and its partial log remains.
The final experiment rerun uses unchanged scientific rules and is reproducibility
checking, not another independent test set. Raw first/final runs and the original
threshold/audit repair logs remain available. No full native/Rust build or new
pretrained execution was performed. Final-head/merge CI must qualify separately.
