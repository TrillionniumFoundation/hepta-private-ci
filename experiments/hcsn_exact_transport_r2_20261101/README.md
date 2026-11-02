# Exact addressed Flow execution, R2

`adapter.py` supplies a callable `ExactAddressedAdapter(original)` with the
single final `integrated` backend. It scripts the original separate content
and relation recurrence together with its original per-time decoder. The same
reference CTMC preparation is called; every decoder input stays contiguous
with the original batch shape. The loop retains propagation, read, remap and
write in their original order. Every original time-step logit is returned.
There is no tensor cache, new information, scalar approximation, new physical
process or learned parameter. The global cache contains executable code only.

```python
from experiments.hcsn_exact_transport_r2_20261101.adapter import ExactAddressedAdapter

wrapped = ExactAddressedAdapter(original_flow_model)
logits = wrapped(x, dt, observed)
# wrapped.parameters() are the original live Parameter objects.
```

The supported profile is the original `AddressedModel("flow")` and its
pointwise Linear/GELU/Linear decoder. Typed eligibility and either occupancy
normalization setting are covered. The original owner/decoder must retain its
unmodified hook-free profile; instrumentation can be attached to this wrapper.
The ordinary baseline and its default call path remain available.

## Evidence and identity

Scientific baseline: PR #4548, commit
`a793d55c23a7742378b081b162252da428a9fdb2`. Audit tooling and the two original
trained development checkpoints are reused from the finalized R1 tree at
`experiments/hcsn_propagation_perf_20261101`; every dependency and checkpoint is
hash-bound in `CANDIDATE_FREEZE.json`. No new fit or checkpoint selection occurs.

`PROTOCOL.json` fixes both tasks, all five batch/sequence workloads, numerical
and gradient gates, randomized interleaving, warmups/repeats and the all-twenty
timing predicate. `results/development005` qualifies the final implementation
before its candidate/source lock. Fresh timing confirmation uses only seed
972603 after remote source publication and readback. The protocol's inherited
scope phrase "decoder batching" refers to an earlier rejected candidate; the
final implementation preserves per-time decoder GEMMs and removes dispatch.
This remains a same-core implementation comparison. It cannot establish an
analytical-model advantage over ordinary cores, which could receive similar
implementation work.

All earlier source versions, failed runs and negative timings are retained:

- `development001`: process exit120 with a partial timing line; no final
  summary or qualifying candidate. The cause is not established.
- `development002`: joint22-channel candidates passed numerical tests in
  their declared samples but had mixed timing.
- `development003`: joint transport was refused at the fixed numerical gate.
  `V3_READ_LAYOUT_DIAGNOSIS.json` traces a small feature difference from the
  regrouped moment GEMM; no tolerance was widened.
- `development004`: separate two-pass script matched outputs but added
  featurestack/copy overhead and retained negative timings.
- `source_v1` through `source_v4`: exact byte snapshots corresponding to these
  runs. Restore their mapped paths in an isolated original checkout to rerun;
  the nested snapshots are not directly runnable Python packages.

## Reproduce the frozen calls

Use the recorded Python, CPU PyTorch, NumPy and SciPy runtime, with one thread
per worker. Keep the existing source freeze and original results.

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_exact_transport_r2_20261101.audit confirmation --out NEW_CONFIRM
python -m experiments.hcsn_exact_transport_r2_20261101.cold_campaign --out NEW_COLD --workers 2
```

`cold_campaign` uses fresh independent processes for every arm and workload.
No numerical-engineering warmup precedes its four actual calls. It records
constructor/script cost, imports, first-use forward/backward and paired output
arrays. Cold costs and any conditional amortization calculation are separate
from steady warmed timing. Wrap commands with the inherited `meter` module;
count the outer campaign CPU once, not its nested worker receipts again.

These are finite synthetic content tasks and shared-CPU reference programs.
Optimizer-update equivalence is checked, but a complete training campaign,
production tail latency, GPU and device joules are not measured here.
