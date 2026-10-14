# Completed saved-Reader nonempty-content audit

Date: 2026-10-14. PR #1697.
Exact executed implementation: 7a94d9e5e6bd2f6c6e516405f115abe65428073f.
Tree: a163af53093e762e4d94347db1740722b22ee3cc.
Run38493158981 / job115622846069 completed SUCCESS. Complete decoded hosted
logs and final job status were inspected. This result note changes no executable
source, checkpoint, criterion or production selection.

## 1. Completed source validation and exact saved-model execution

All12 focused suites passed:14 matrix +54 contracts +29 native +61 Group
+28 response +33 adapter/counter/replay +17 Encoder +26 paired invocations
+25 source-time +25 fit audit +20 projection +27 new content-control tests.
That is359 passing invocations,356 distinct identities,zero skips. Three imported
NativeAdapterTests repeat in the paired suite and are not extra independent tests.
All27 newly defined tests passed, including the three official tiny-model tests.
Compilation, environment checks and all three external archive SHA checks passed.
This is not a full-repository, Rust, target-device or prospective-merge verdict.

The runner verified every listed member of the two fixed historical result
archives before extracting them. No source code from those archives was imported.
The original model archive was separately verified and staged through its prior
strict material path. Four previously saved adapters were attached to fresh
verified bases through the existing composition owner. All five final model
integrity checks passed; adapter tensor equality and base preservation passed.

There were120 planned free-generation rows:100 successful ACTUAL model calls
and20 unavailable donor conditions. The latter remain in the denominator.
No model execution error occurred. Five saved models reuse four TRAIN and four
SELECT questions under own-source, donor-source and empty conditions, not120
independent tasks. All20 unavailable conditions are the four SELECT donor cases
repeated across five arms. Own-source and empty SELECT inputs still executed.

Teacher forcing has14 planned TRAIN recipient comparisons and3 reference-bearing
SELECT comparisons per model. Only13 TRAIN comparisons were scoreable; all three
SELECT comparisons lacked an eligible donor. Each model executed52 audit forwards,
260 total. The free-generation counter records2,801 observed decoder forwards.
No optimizer was invoked:ZERO new fitting updates. Archive verification, staging,
model loading, tests, generation and teacher forcing remain paid work, not free
reuse. Missing energy, FLOPs and process peaks remain unknown.

## 2. Observed TRAIN content sensitivity; SELECT contrast is unavailable

For fixed recipient question q, own annotation a, donor annotation b, own
nonempty source E and donor nonempty source D, report:

I = [l(a|q,E)-l(b|q,E)] - [l(a|q,D)-l(b|q,D)].

Both contexts use the same local citation IDs S1,S2,... and same source count.
Bodies and source-session metadata remain verbatim. Scores use exact uncited
annotation bodies only AFTER free generations seal. l is mean response-token
log probability, not correctness probability. Additive evidence-independent
answer preferences cancel. Topic, source length and dates can still affect this
interaction; positive I does not prove semantic understanding or grounding.
The donor annotation is not independently certified false for the recipient.

Every model has the same13 scoreable TRAIN comparisons from six recipient
families. One of14 planned TRAIN rows remains unavailable. Means below condition
on scoreability; no confidence interval is asserted because directed donor edges
reuse observations and the sample is small and already exposed.

| Saved model | TRAIN family-macro I | TRAIN task-mean I | Positive I among13 scored pairs |
| --- | ---: | ---: | ---: |
| Frozen |2.259858|2.253816|13/13|
| Aligned2 |2.456448|2.415212|12/13|
| Shuffled2 |2.186110|2.151241|12/13|
| Aligned8 |3.316990|3.473899|11/13|
| Shuffled8 |1.672459|1.718765|11/13|

Aligned8 has a higher TRAIN mean than frozen and shuffled8, providing a bounded
training-data content-interaction signal worth distinguishing from the earlier
empty/nonempty proxy. But its positive-sign count is LOWER than frozen: this is
not uniform per-question improvement. The mean difference is not a demonstrated
independent transfer, semantic-answer accuracy gain or globally optimal candidate.
All SELECT interaction means are NULL, with0/3 comparisons scored. This is NOT
zero measured interaction and NOT evidence of failed transfer: the comparison
was unavailable under the registered cross-family/equal-cardinality donor rule.
The fourth selected question lacks a reference-bearing pair as in prior studies.

The new donor constraint was not relaxed after observing this absence, no TRAIN
source was borrowed as a SELECT donor, no TEST source was read, and no recipient
was replaced. The green workflow means the bounded execution and accounting
completed, not that every scientific comparison obtained eligible data.

## 3. Actual free-generation readout remains limited

Both8-epoch saved models produced prescribed refusal on4/4 empty TRAIN inputs
and4/4 empty SELECT inputs. They produced no prescribed refusal on own-source
inputs or the four available TRAIN donor-source inputs. Frozen and both2-epoch
models emitted no prescribed refusals in the executed conditions. This preserves
the earlier observation of a strong empty/nonempty behavioral split, but does
not show that content is ignored: the likelihood interactions above are nonzero.
It also does not establish semantic adequacy of the nonempty answers.

Registered exact-body matches remain0 across all executed cases. Aligned8 has
one syntactically valid TRAIN own-source citation; all other format counts are0.
This cannot be turned into zero semantic accuracy or independent grounding.
Raw answers are sealed and retained, not normalized into a new favorable grade.
The neutral local citation representation differs from previous E-hash labels,
so its generation readout is a new controlled representation, not a claim of
old-output byte equality. Every compared model received the same change.

## 4. Projection mismatch scope is now exhaustive, with the original gate retained

The previous projection qualification38441421072 had stopped at its first
saved-tensor tolerance failure. This run compared ALL120 saved adapter tensors
(230,400 elements), without a new model call or any optimization, under the SAME
atol2e-6 and rtol2e-4 and the pinned original archived plan.

ExactlyTWO elements failed the combined tolerance, in two different tensors:
- layers.26.self_attn.q_proj.lora_B.weight: one failing element; tensor maximum
  absolute difference2.5566841941326857e-6.
- layers.6.self_attn.q_proj.lora_A.weight: one failing element; tensor maximum
  absolute difference4.1620805859565735e-6.

Other tensors can have larger absolute differences while satisfying the combined
relative-plus-absolute test; absolute difference alone is not that gate. The full
per-tensor inventory is retained. This does not diagnose the numerical cause or
prove practical functional equivalence. The original qualification is still
FAILURE, projection_qualified=false, and full-logits-v1 remains the default.
No tolerance was increased, no element was discarded and no old failure relabelled.
The previously measured reduction in vocabulary-output bytes remains a scoped
measurement, not whole-process memory/energy or accepted replacement evidence.

## 5. Exact evidence and next unresolved comparison

Artifact11863371125, name hepta-saved-reader-content-not-confirmation.
GitHub reports1,586,065 bytes /502 files. ZIP SHA256:
963f86da6c4a0601ce539698b10f0461b1dc6a7b0a59be16a64ae16f8f150097.
Plan SHA256:
eaa232deffc4008321bde619c0efea28ee476af82e4728c0a1408349c24fd0eb.
Raw generation SHA256:
458241ad321abe270b77e776e263faa542a2b9960543b85f1268fc27dbb86e45.

The artifact retains source, all test logs, model composition identities,
comparison/public-input plans, donor/compilation censuses, raw answers and seals,
four-score comparisons, original-tolerance tensor census and costs. Original
pretrained weights and historical input-archive contents remain outside export.
No local artifact rehash or local model execution is claimed in this increment:
local execution probes returned ClientError. Hosted input-archive/member checks
are distinct from local verification of the NEW output artifact.

A future validation-content comparison needs a separately registered eligible
same-partition donor inventory, without changing recipient/checkpoint/TEST
boundaries or relabelling absent data as scores. The new TRAIN mean signal must
not be used to select a candidate as if validation had been measured. Learned
Group/NDU improvements still require an independent external-outcome signal,
not just the now-satisfied answer/refusal proxy or this TRAIN interaction.
Independent sufficient evidence, semantic review, genuine new task families,
shared/replicated lifecycle costs, multimodal/split transfer and native production
ownership remain separate. None of the five formal efficacy experiments is
promoted to complete by this successful research workflow.
