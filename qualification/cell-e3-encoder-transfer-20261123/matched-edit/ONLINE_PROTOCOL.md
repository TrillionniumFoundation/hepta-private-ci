# Resident update episodes (2026-11-24)

This extends the existing matched-edit experiment, without changing its original
results or claiming new users. All teacher data and confirmation outcomes have
already been published. The encoder is the exact pinned MiniLM from `assets.py`;
the parent, target mean, regularizer 0.2 and train/confirmation split are unchanged.

The initial history has 192 old rows and 16 rehearsal rows. Eight arriving batches
of 32 rows exhaust the original 256 new training rows. This is a sequential replay
of recorded data, not eight people. Three rotated rounds compare four policies:

1. `reload_direct`: reload the encoder and re-encode current train and confirmation
   inputs, then solve the entire same-objective ridge problem.
2. `resident_direct`: keep one encoder and a bounded identity-bound feature cache;
   still solve the entire ridge problem each time.
3. `resident_rls`: the same encoder/cache; append the batch with a block Schur
   complement (kernel recursive least squares), without forgetting old rows.
4. `resident_bp`: the same encoder/cache and a warm-started autograd L-BFGS head,
   with the original iteration/evaluation limits and tolerances.

Every episode is independently timed from load through all eight updates. Each
update includes feature lookup/extraction, residual construction, optimization,
stationarity and historical quality checks, local artifact write/hash/reload and
prediction equality after reload. The RLS initialization is charged to its first
update. Imports and one-time optimizer import warmup precede every policy; the
original-fit data reconstruction is reported separately. An episode's wall span
is measured directly, not reconstructed by adding medians or overlapping stages.
The cache holds at most 2048 unique observable inputs and RLS at most 1024 rows.
Cache keys bind encoder file identity, feature source, query and both candidates;
labels never affect keys. The encoder remains immutable for the cache's lifetime.

Retain all 96 update records and 12 episode records. Do not select batch size,
rounds, solver settings or stopping by measured speed or confirmation accuracy.
Require identical answers for all 272 historical inputs at every corresponding
step across every policy and round, final agreement with the original published
mixed head, and relative stationarity below 1e-6. Failure preserves the result and
exits nonzero. Count old parent-passing tasks lost rather than merely aggregate
retention. Published poor mixed-head quality is not repaired by a speed improvement.

This measures **local update service cost**, including local artifact handoff.
It does not include teacher acquisition, model download, WAN distribution, new
independent evaluation/adoption or Chain settlement. Production end-to-end time,
independently adopted gain per total cost, user scaling and Circuit superiority
remain unmeasured. No candidate is adopted and no learning reward is authorized.

Run with the original pinned runtime and one BLAS/OpenMP thread:

```sh
python -m unittest discover -s matched-edit -p 'test_resident.py' -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python matched-edit/online.py /absolute/pinned-encoder /absolute/online.json
```
