# One authorized TRAIN reconstruction/variance/timing diagnostic

This extends 34b16fc7d7 on its isolated branch. It does not execute the large
confirmation proposal or train/change any model. All original files remain.

## Exact denominators and inventory

The same hash-bound 192-source/3072-row TRAIN is reconstructed exactly once;
validation/test are never constructed. All 12 existing final models and three
existing bases are read, never updated. All 3072 rows are retained. Four physical
sources (16 rows each) form each 64-row cohort: 48 cohorts, four per source class.
Source order is (source class, SHA256("reinfer-d1-cohort:"+source_id)); within
each four-source cohort retain original request order. Cohorts then sort by
SHA256("reinfer-d1-order:"+colon-joined row source IDs). No outcome-based ordering.

12 models * 48 cohorts * 4 waves = **2304 actual native/PNG batch calls**;
multiply by64 = **147456 actual service requests**, **73728 per A/N system** and
12288 per model. Bases receive no extra service requests: their 6144-view-row
CE references are a different explicitly charged phase, not hidden in that
denominator. Service stays always-full, original native and PNG/JSON code.
There are separately55296 base-reference forward rows (three dense forwards per
6144-view-row base) and24576 final-model gradient-forward rows; reference cached
pullbacks add24576 gradient rows without new encoder forwards. Wave0 service
p/q supply the final row readout; no redundant extra3072-row prediction pass.
Total encoder/head forward-row evaluations are227328, of which147456 emit PNG.

Before model results, the entry computes kernel inventories from actual
geometry and original WorkLedger prices. Reservation upper bounds per A/N:

| Stage | Declared units bound | CPU reservation, seconds |
|---|---:|---:|
| Complete shared three-base reference, independent dense mean, reward support | 1,437,297,240 each | 2.5 each |
| Six final models, 32 fixed batches each, original + cached reference + CV + statistics | A632,099,328; N633,438,720 | 1.0 each |
| 73728 full outputs | **1,418,231,808 each** | 9.5 each |
| Full per-request readout (reservation upper bound) | 36,052,992 each | recording/readout 1.5 each |
| Complete shared scheduler/closing | actual CPU, not padding units | .5 each |
| Sum | A3,523,681,368; N3,525,020,760 | **15 each** |

Bounds are reservations, never charges for unexecuted work. Actual derivative
kernels contain no Adam step/clipping, and no unused objective is applied.
The original 19236-unit full request includes decoder/output arithmetic; PNG,
JSON, hashing, copies and bookkeeping also consume measured CPU. Additional
finite/variance bookkeeping has room in the ~475M operator headroom; actual
atomic ledger admission remains authoritative. Shared preparation is physically
executed once and attributed in full to BOTH A/N, including imports and source
hashes. It is not divided per model. Paired attributed caps are 8B; physical
CPU cap30s, complete per-system CPU15s. The CPU phase reservations above have
physical sum27s because common work is duplicated only in attribution. These
are conservative admission forecasts, not a promise about a noisy host.

Initial shared work must fit2.5s. After all gradient measurements, both arms
must still admit9.5s service +1.5s evidence +.5s shared closing. Runtime checks
and a physical CPU watchdog reserve final evidence writing; observed cap excess
is a sealed failure, never relabeled success. All serialization/output recording
is counted, including final receipts; final-execution.json is authoritative.

## Reference and CV measurements

Fixed minibatch seed742019 (new, not97013), 32 batches of64 per sampler; identical
draws/views/importance weights for A/N and the three model seeds. These are
paired diagnostic draws, not independent seed replications. View law remains
.5 full/.5 low. The existing sampler/weights are unchanged.

For each saved base, cache full TRAIN's full/low hidden states, CE logits and
hidden pullbacks, including all sources. Compute its full unweighted CE mean.
Independently call the public dense forward/gradient route and require all six
groups rtol1e-10, atol1e-12. Explicit population coefficients check that target
stratification and the view law still give weight1/6144 to each row/view.
This deterministic reference-mean validation, NOT a noisy 32-batch sample mean,
is the predeclared mean check. A failed mean check rejects CV and seals the run.

For every final model, measure g_B and g'_B=g_B+.2*(H_ref-h_ref,B). Both A/N use
the same paid correction. No reference refresh/coefficient search. Welford
mean/M2 for every parameter coordinate, batch norms and full-vector hashes are
saved for original/CV/reference gradients; all batch indices/weights/views,
input tensors, base cache and original model hashes permit exact reconstruction.
Large redundant full gradient histories are not duplicated in the archive.
Pre-clip unbiasedness does not imply Adam-update unbiasedness, and total
variance can increase. Reject CV if ANY of six N seed/sampler points does not
strictly reduce the 32-batch total variance. This semantic rejection does not
discard the rest of the already declared readout/service diagnostic or authorize
new training; finish only its fixed schedule while resource/numerical caps hold.

## Timing and complete new row evidence

For each seed/cohort/wave, order four candidates A_i,A_s,N_i,N_s using Williams
rows (0,1,3,2),(1,2,0,3),(2,3,1,0),(3,0,2,1), row index
(wave+seed_index+cohort_index)%4. Seed/cohort/wave loops are frozen in that order.
No competing jobs from this task during measured windows; other research need
not stop. One-thread variables/actual environment are retained. All four waves
and every cohort remain; no faster-wave replacement or stopping at significance.

Native generation + original _outputs PNG/hash/base64/JSON/ledger are the timed
service path. Per-request payload retention hashing is after service timers but
inside the arm's complete CPU. Record native/output components, wall/CPU,
choices, hashes and byte sizes. Identical-output cohort strata are descriptive
only; primary timing always uses ALL48 cohorts. Williams ordering does not
eliminate arbitrary time drift or establish independent training-block variation.

Wave0 p/q are retained for all rows; other waves must match them within fixed
numerical tolerance. Save each head's true probability/top-two and true-vs-other
margins, exact per-request Z=E_pq exp(-1.5R), CE_rho, negative reward mass and
expectation, original reward components, raw/joint/consistency/pixel metrics,
greedy codes/reward and attribute errors. These are **new reconstructions**, not
backdated original logs. Check original full TRAIN aggregate means at the fixed
rtol/atol. Complete source map/input hashes and all-source comparisons are saved.
Request mean CE is never replaced with log of a cross-request mean.

Inputs/cache/model references and payload dictionary are deduplicated. All
numeric evidence is lossless float64, NPZ ZIP_STORED; shared source IDs plus
row indices replace repeated strings. Per-request choices/hashes preserve every
output, dictionary retains every unique original payload/PNG. Planned retained
raw arrays are below60MiB; enforce64MiB on the entire output directory. No
unfavorable source is removed to fit storage. Models/native binary reference
the original immutable files instead of copying them.

## Launch and terminal policy

Commit all source/protocol/sample/order bytes, freeze their hashes, then run
the real module's smoke action. Smoke verifies inventory, original file hashes,
NPZ/load and native ABI preparation with dataset and trained forward explicitly
forbidden. It produces no TRAIN/model results and no diagnostic opening marker.
Fixing a pure zero-result launch defect requires a new recorded technical
identity; never erase earlier evidence. The actual run takes an exclusive
experiment-wide TRAIN diagnostic marker before reconstruction and an output
directory that must not exist. First trained base inference writes a separate
results-started receipt. Any later code/numeric/resource failure seals this
attempt: retain partial arrays and original status, do not retry/tune under a
different directory or technical name. No held-out opening marker is touched.
