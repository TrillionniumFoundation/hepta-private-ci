# V6: cross-fact exchange versus an equally enlarged local Head

V5 learned most controlled ownership/storage bindings but failed its complete
128-candidate fitting gate in all three seeds. V6 tests one architecture change
without changing the Encoder, cached features, Reader state update or training
recipe. It does not lower the gate or claim that more parameters alone produce
reasoning. Hosted CI is outside this experiment.

## Families and initialization

| Family | Reader parameters | Change |
| --- | ---: | --- |
| base | 38,466 | Actual V5 baseline, historically executed |
| bridge | 42,562 | One rank-32 fact-to-fact residual attention exchange |
| wide | 42,562 | Four rank-32 matrices confined to the Head hidden vector |

Both variants add exactly 4,096 weights. The bridge computes masked means of
fact-token relations, applies bias-free Q/K/V/output projections and masked
fact attention, then broadcasts a residual back into valid relation tokens.
It runs once in `prepare`; token keys are recomputed afterwards. The wide
control applies a residual MLP after the original Head GELU, independently per
candidate and at every hop. The existing bounded recurrent state and its
transition are unchanged.

Residual output matrices start at zero. Every common tensor and initial output
matches the base for the same seed. A separate RNG initializes extra matrices
without perturbing the base initialization or caller RNG. The two extra
architectures differ in operations and cost despite equal parameter counts.
Do not treat this control as equal compute.

For seeds 41, 47 and 53, save all three initializations as sorted FP32 raw bytes
plus tensor names, shapes, offsets, lengths and hashes. A stdlib auditor can
reconstruct both named parameter-digest definitions directly from these bytes,
compare common tensors, and check all added counts and zero output matrices.
Selected trained checkpoint bytes are independently hashed; the auditor does
not claim to decode their PyTorch tensor serialization.

## Inputs and historical baseline reuse

Reuse the exact frozen Granite97M checkpoint, V4 token cache and V5 partitions.
The V5 runtime's 48 files must remain byte-identical. New V6 runtime files have
separate names and an explicit source inventory. Only official MultiRC training
data is read: natural Reader train is 64 paragraphs / 3,909 candidates, and old
internal tune is 16 paragraphs / 827 candidates. No official validation is read.

The controlled training set remains 32 complete paired-world groups / 128
candidates. V5's two unscored controlled fresh domains remain unopened for model
selection; reserved synthetic verifier-fit data remains unused. Domain semantics
and independent grammar verification are unchanged.

Reuse the three actual V5 base runs rather than execute identical training
again. The current base factory's initialization must match each original
training receipt. Bind the original weights, model/receipt/panel/gate files and
their actual historical costs by SHA. They are historical comparison evidence,
not newly performed work and not free computation. The new warmup phase trains
six models only: bridge and wide for each seed, sequentially. Order is
bridge/wide for seed41, wide/bridge for seed47, bridge/wide for seed53.

## Training and opening gates

Keep V5's Adam .001 (`foreach=False`), batch16 of four complete groups, depth3,
last-hop CE plus .5 world-pair margin, deterministic per-epoch group shuffle,
8,000-update maximum, full128 diagnostics every250, and 1,800-second call budget.
Select the earliest scheduled training diagnostic with 100% candidate and
paired-world accuracy and CE <= .10. Independently rescore saved probabilities;
logit-space CE and saved-FP32-probability CE remain separately defined.

Every arm gets its own three-seed admission result. Bridge is the preselected
primary; wide cannot replace it after observing results. Failed warmup controls
can still be evaluated as explicitly failed, frozen controls if the primary's
complete downstream gate chain passes. They cannot receive further training.
An equal maximum update limit does not imply equal actual updates or cost.

Only if all three bridge seeds fit does the primary continue from each same
frozen warmup through V5's natural-only, replay and contrastive arms. Each has
500 identical natural updates; replay/contrastive add 500 identical binding
updates with pair weights 0/.5. Diagnostics do not stop or select checkpoints.
Contrastive retention must reach >=95% candidate and paired-world correctness,
with <=5 percentage points lost from warmup, in every seed.

Only after retention passes may real/zero feedback train from the same bridge
contrastive checkpoints, with 256 natural and 256 binding updates per arm,
the original independently trained frozen V4 verifier and detached on-policy
feedback. Validate the actual four feedback-column gradients. No forced errors.
The verifier's historical training is identified, not newly charged.

Wide is not naturally continued in this protocol. Compare cross-variant warmup
results within that stage; later bridge-only natural transfer cannot establish
a cross-variant causal advantage. Natural internal tune is descriptive, not a
new generalization result or a hard opening gate.

## Fresh controls, costs and evidence

Before any fresh encoding, bind all 21 new model manifests (six warmups, nine
continuations, six revisions), all referenced weight/training-receipt bytes,
gate evidence and three historical verifiers. The three historical base models
remain bound by the design. Verify exact selected paths and architecture types,
not just a count. Record the once-only start after preflight succeeds.

If admitted, evaluate both fresh domains with frozen base/bridge/wide warmups,
three bridge continuations, depth1, depth3, state reset and evidence deletion.
Actual trained revision compares real/zero/shuffle/reset/late-fusion/verifier-only
at three Reader/two verifier calls, plus cheap fixed1 and verifier controls.
Reuse V5's public-ID derangement and physical receipts. Repeated seeds reuse the
same 32 groups per domain; they do not add independent examples.

The existing `binding_process.py` measures every child from startup through exit,
including failed attempts. Inner fit/update/diagnostic/batch costs are nested
breakdowns. Keep original baseline costs and new incremental costs separate;
do not add nested measurements twice. The shared Encoder is loaded and the
historical cache restored during current phases, while old cache generation is
historical. Any admitted new-domain encoding is measured separately. Report
actual CPU, wall time, peak RSS and exposures; full training formula FLOPs are
not available. New bridge work is inside actual prepare timers, and the wide
Head work is inside each hop timer.

Phase start files prevent silently repeating or resuming an existing neural
attempt. Preserve all failures, gates, raw probabilities, trajectories, weights,
initialization bytes and hashes. Do not edit frozen runtime or relax thresholds
after training begins. A failed primary closes subsequent phases for this run.

Invoke `bridge_campaign.py` phases `prepare`, `warmup`, `continue`, `feedback`,
`evaluate` with V5's source/model/cache paths plus `--previous-v5` and a new
`--output`. Wrap each child in `binding_process.py`. Independently inspect with
`bridge_review.py --run RUN --code CODE --natural-cases CASES --output REPORT`.
Review PASS denotes evidence consistency, not learning qualification.
