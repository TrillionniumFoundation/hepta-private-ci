# Fixed global64 input/output risk training — source only

Qualification must have independent PASS, complete wait4 and exact source/runtime
bindings before scientific data. This proposal is NOT a rerun of the negative
static/fresh grouped experiments; it changes content-group weighting, not noise,
labels, architecture, reward, rho, anchor, update budget or serving.

Four source-masked FIT-source-supervised bases, folds0/1 x seeds103/107, original
300 decoder and500 supervised updates; own130 FIT groups and1701/1702 corruptions.
Source supervision and instruction masking remain disclosed existing mechanisms.
For each base use the byte-exact grouped schedule(seed+9000):300 batches,8 distinct
content groups x4 distinct of6 static variants x full/low=64 rows. A/groupN/globalN
share the exact schedule and initialization. No fresh corruptions, rowN arm or
hyperparameter search. Each model300 Adam steps, lr.003, ordinary aligned anchor.2.

Every arm computes unchanged all_terms four utilities and both anchors, unchanged
groupA/groupN aggregations, plus qualified globalN aggregation. A/groupN use original
selector and arithmetic order. GlobalN selects only qualified global gradients,
then adds .2 ordinary rowmean aligned anchor; the anchor is NEVER riskweighted.
Distinct global mode/schema/profile metadata and key are attached to each model
and frozen record; selection checks identity and rejects mixing. Original tensor
model digest definition unchanged, no checkpoint compatibility promised or payload
save/restore. Old A/groupN identities are legacy selectors, not global profiles.

## What changes, what does not
Cglobal=-log(mean64 exp(-rho rowCE))/rho, rho1.5. Relative to8 equally weighted
content groupCEs, the outer weight is8softmax(-rho groupCE): difficult content
receives more gradient as well as difficult views. Global<=mean_groupCE<=mean_rowCE
<=meanreward. A finite sampled-batch objective/gradient is not an unbiased estimator
of whole-FIT risk; Adam is not unbiased. This is a new surrogate, NOT a bug repair.
Independent-output training and coupled/calibrated serving mismatch remains.
The free-policy deterministic-Bayes optimum theorem applies without anchor or
network restrictions; it does not prove current regularized neural A/N optima equal.
No science benefit is guaranteed. See unchanged qualified helper PLAN for proof.

## Exact historical controls and barrier
Require all4 base and8 A/groupN final tensor digests match old grouped run, without
restoring payloads. Require their complete old FIT fit records/profile keys,
uncalibrated+calibrated11 metrics/channels/populations/noises, allbase metrics and
FIT/heldout manifests equal the frozen old JSON. Failure aborts, no retry/tolerance
repair. GlobalN is new, no digest target or model selection.
All12 models freeze, then24 heads fit with unchanged oldFIT1560 rows/head,
[.125,8],28NLL evaluations/head; all24 heads freeze before heldout regeneration.
Reuse studied3701/3702/3711/3712 and originalFIT catalog complementary groups:
per-model heldout, NOT globally fresh groups/noise, TEST remains closed.

## Evaluation and unchanged gates
Original mean-row CE of original coupled/calibrated serving, not batchCE evaluation.
72 contrasts:36 selfcalibration and36 pair contrasts including pooled descriptions.
Primary globalN-A andglobalN-groupN each8 unpooled five-gate comparisons:
CE gain>=.005, textmass/greedytext/jointsuccess no loss beyond1e-10, MSE increase<=1e-10.
Overall16-conjunction. groupN-A is descriptive control, all negatives retained;
no pooled rescue, threshold changes or selection based on results.

## Literal tests and exact work ledger
41 tests before scientific FIT generation: original37 byte-exact plus4 newly
qualified global tests byte-exact. Literal costs included in child but separate
from scientific counters. No actual data/model use by source producer.
4newbases/12clones/0restores,1200decoder+2000supervised+3600adapt updates.
14856 forward batches/1015840rows; same source-mask copy and10158400 zeros.
1208decodecalls/14496images;2FITdata+4heldoutdata+0TEST.
3600all_terms/921600four-utility rows;7200oldgroup aggregationcalls/460800rows/
57600groups PLUS3600globalcalls/230400rows/3600wholebatchCEs in allthree arms.
1200schedulebatches/9600groupchoices/38400variantchoices/76800rows reused3arms.
12FITservingcalls/18720tables;24heads/37440headrows/672NLLcalls/1048320NLLrowevals.
56evalserve calls/87360tables/12579840entries/174720CDFchecks;
37440internalcalibrationtables/74880argmax+74880supportchecks;
16baseprofile+12calprofile roundtrips. Scientific counters exactasserted.
All SHA constructions/update bytes/copies instrumented across child including
literal tests and source/model/profile/dataset hashes. Source/global profile hash
work charged; no claim fixed tensor-step count means equal actual CPU. Per-arm
adapt/evaluation CPU, baseprep, data generation, FITfit, serving and whole wait4
recorded. Failure preserves available completed adaptation costs/counts/progress;
whole child includes all partial work even if a stage does not complete.

## Bounded once-run proposal
30CPU/90wall/512MiB/4MiB CPU0 singlethread, original synthetic shared lock
nonblocking/no replacement; source audit allowlist, no payloads/network/descendants.
Full wait4 on success/failure/killed child, no retry or extension. Source/review and
supervisor tail additional notzero. Requires independent review and separate launch.
