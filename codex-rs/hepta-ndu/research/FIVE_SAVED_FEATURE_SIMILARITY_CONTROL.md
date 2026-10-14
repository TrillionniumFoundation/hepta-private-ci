# Frozen-feature similarity controls before investing in more Head capacity

2026-10-14. Additive followthrough on parent223031d5fcc5eff3595b084685cc174562f5bc42.
No old trainer, model architecture, scientific threshold, projection tolerance,
Reader qualification, recovery result or production owner is modified.

## Question and why a new comparison is needed

The five saved Head arms do not include a direct pretrained-feature similarity
baseline. Affine and evidence-only controls answer different questions. A trained
nonlinear Head can look useful while merely recovering information already
available from the frozen Encoder with no neural fitting. The present control
asks whether the SAME saved question/evidence vectors, SAME original SELECT
rectangles and SAME missing-recipient census can be read usefully with cosine.
It does not select another Encoder or claim the current Stem is optimal.

There are two explicitly different controls:

1. cosine_zero: no fitted parameter, score=cosine(q,e), fixed threshold0.
2. cosine_train_threshold: SAME scores minus one scalar threshold fitted on
   TRAIN only. It is NOT a zero-fitting control and is NOT calibrated confidence.

Cosine uses deterministic FP64 scalar arithmetic on the saved FP32 vectors,
with per-vector scaling before norm reduction. No statistics are fitted on
SELECT, and only final numerical overshoot outside[-1,1] is clamped. Feature
vectors remain unchanged. Test fixtures check scaling, zeros, nonfinite values,
geometry, source-role order and input immutability.

## Fixed scalar fitting and interpretability

Compute the already registered TRAIN matched/mismatched scores. Fit one threshold
by minimizing the number of strict sign errors across these paired examples.
The finite candidate set consists of TRAIN-score midpoints,0 if not itself a
TRAIN score, and outside endpoints-2/+2. Ties are broken by abs(threshold), then
numerical threshold. Equality to a score is not silently accepted as either
strict direction. All missing TRAIN pairs remain; all-missing inputs fail.

Save the threshold receipt BEFORE computing SELECT cosines. No SELECT fitting,
seed selection, best-checkpoint choice, new target supervision or early stopping
is present. The declared threshold rule is fixed before this new readout runs.
TRAIN weak labels remain inherited annotations, not independent semantic truth.
Because the developed dataset is already exposed, this is development, not a
new untouched validation claim or an independent hypothesis test.

Use the existing shared_gate_crossed_evidence.interaction/summarize functions
for both controls. Report both question rankings, both evidence rankings, all
four signs and the crossed interaction. A positive interaction alone does not
qualify a policy. Absolute gate logits and cosine scores have different scales:
NEVER subtract them to claim a gain. Instead, each of the15 saved Head/seed
results is paired by the exact same recipient against each control and records
candidate-only success, baseline-only success, both, and neither for each
existing criterion. Threshold changes do not add an interaction mechanism.
There is no significance interval; repeated seeds and reused donors are not
independent task families. Shared pass/fail patterns are not semantic accuracy.

## Reuse real saved features rather than acquiring another model

Accept only these exact authenticated successful origins:
- Head run38526481788/source592b5b645ada09c335f942ce7ca11561d5eb2cf1.
- Crossed run38526874475/source9da0908298f26fab8173a7ffa04807c9ab179ca7.

The source is not replaced by the newest branch head. Complete archive/member
hashes, actual reports, raw seals, all15 Head entries, old replay checks, exact
four-corner references, and the original cache tensor digest must validate.
A successful contract-only/deferred crossed job does NOT contain a model cache
and is rejected. Missing/failed/queued origins are explicit deferred inputs, not
zero scores or permission to reconstruct/retrain something else.

Read frozen-features.safetensors from the crossed output. Both the file hash
and the complete loaded tensor census/digest are checked. Vectors must be finite
CPU FP32 one-dimensional normalized features of one consistent width. Their
keys bind the original representation, source scope and exact input text.
Only result artifacts are downloaded; the original376MB model archive is NOT
needed. There is no Encoder/Reader/Head model constructor, no pretrained model
load, no optimizer and no new neural forward. Saved Head logits are reused
verbatim. Loading safetensors, validation, vector conversion, cosine reduction,
threshold search and tests still cost work and are timed. Tensor bytes do not
include Python vector object overhead, and no whole-process/joule/FLOP/TCO
superiority is inferred. Upstream Encoder reconstruction and Head training
costs remain paid costs; this analysis does not erase them.

The baseline has no authority to skip a Reader call, accept an answer or alter
production routing. Reader independence requirements and five formal efficacy
experiments remain unchanged. A cheap relation score still cannot prove correct
entity/event binding or a grounded final answer.

## Validation and disposition at initial publication

31 new pure arithmetic/partition/metadata/direct-CLI regression definitions and
10 cached-artifact/readout integration definitions are submitted. Existing gate,
crossed, entrypoint and SELECT inventory regressions are also required. Current
local container and Python probes returned ClientError; no local test pass or
new actual cosine/threshold result is claimed at publication. Early pure tests
and metadata resolution precede dependency installation/artifact acquisition.
If origins are not ready, the workflow records analysis_completed=false even
when its non-model contract steps pass. It does not poll or rerun an upstream.

Files: shared_gate_similarity.py, shared_gate_similarity_trial.py,
test_shared_gate_similarity.py, test_shared_gate_similarity_cache.py and
hepta-shared-gate-similarity.yml. This push does not retrigger the parent Head
training or the original crossed workflow through their scoped path filters.
