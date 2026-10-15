# P2s — Physically executed selected-Head Top-1 vs dense-after-compute routing

**DRAFT · RESEARCH · DENY_ALL.** Child of the exact original equal-parameter
Granite97 study [#2180](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2180),
source `51e685f1ec4debf33b0bd3cbae6ba39cfd04944a`.
This branch adds no native Neuron/Worker, owner, selected artifact, Codex,
Final-use, CNS route or physical Cell Split. Its objective is narrowly to
distinguish *logical Top-1 selection* from *physical one-Head execution*.

## Critical source-backed observation

The original `TwoHeads.forward(x)` evaluates **both** 7,434-parameter Head
slices via `torch.einsum(...)` on every input. The original
`routing(model(x), x, ...)` then selects Head 0 or Head 1. This is a
legitimate causal/classification router experiment, but it does **not**
sparsify the executed Head arithmetic. A post-hoc `Top-1` output mask
is not an operator-level or hardware speedup.

## Research control implemented

`p2_real_cell_split_sparse_probe.py` consumes the *same complete,
unscored original P2 report* after its one shared 224-input physical
Encoder stage. It does **not** call the Stem again, open labels, train
Head weights, change the original model or create an external effect.
For the exact 96 original calibration/test input-only records, it:

1. Rejects unknown, incomplete, oversized, symlinked, nonfinite,
   changed-on-read or authority-upgraded JSON. Reconstructs exact
   384D Q24 heldout features, the original train-only median threshold
   and both Head parameter tensors from the sealed FP32 bytes.
2. Reproduces the original `fixed_two_cell` and
   `adaptive_train_only` route IDs. For each Head, slices **only**
   matching rows and runs that Head's own residual+gate+output matrices.
   If adaptive splitting was not triggered, only Head 0 runs.
   It never forwards the other Head on those same selected rows.
3. Recomputes the original dense two-Head logits from the *identical*
   parameters. Requires dense, physically sparse and original frozen
   96-row predictions to agree within `4e-5`; otherwise fail closed.
4. Actually executes 13 paired, alternating one-thread CPU rounds
   after warmup. Retains measured process CPU nanoseconds for both
   methods, without declaring either faster or deducing target-host
   RSS/GPU/p95/p99/energy, batching/scheduler savings or end-to-end
   latency.

The row-accounting distinction for every 96-case P2 heldout panel is:

| Work unit | Original dense-after-selection | New selected-only probe |
| --- | ---: | ---: |
| Logical decisions | 96 | 96 |
| Head-specific forward rows computed | 192 | 96 |
| Physically resident two-Head model parameters | 14,868 | 14,868 |
| Physical Head dispatch groups | dense full-batch | 1 or 2 selected batches |
| Qualified service FLOP / latency saving | **No** | **No** |

A 50% reduction in **executed Head-row instances** is not necessarily a
50% reduction in FLOPs, CPU time, energy or whole service cost. Input
grouping/index/scatter and smaller matmul dimensions may defeat the
benefit on tiny CPU batches. All negative timings are preserved.

## Independently reviewed, not self-awarded

The reviewer `p2_real_cell_split_sparse_review.py` contains **no Torch
or sparse-producer import**. It first requires the original P2 independent
human-label/NumPy study verdict, replays the 96 source-ordered Q24
vectors, independently recomputes both output logits from the original
FP32 Head weights with the original independent NumPy equations,
checks exact route mask and group sizes and refuses all false claims
about execution, cost parity or independent model/task utility.
The physical operator invocation/CPU counters are still producer
observations, *not independently signed hardware measurements*.

The original hosted workflow performs physical selected-Head execution
**before** opening the original heldout human labels. Only after the
original P2 independent label/weight scorer succeeds does the new
Torch-free sidecar reviewer execute. Only a **sanitized aggregate**
review is uploaded; no raw texts, shared feature vectors, per-case
logits or trained Head weights are published as artifacts.

## Reproduction / strict gates

- Source/merge CI: `hepta-p2-physically-sparse-selected.yml` must
  pass with its *exact new child SHA* against both source-head and
  prospective base-merge. It reruns the original P2 real Torch mock
  tests and new physical/safety tests both normally and under `-O`.
- New local **operator-only PyTorch sanity check** (not original P2)
  used seeds 7347/41/47. Fixed/adaptive split and unsplit cases
  computed exactly 96 selected-Head rows vs 192 dense-Head rows; FP32
  maximum discrepancy was about `3.7e-9`–`7.5e-9`. Original P2
  full mocked/pretrained integration tests remain **unverified** until
  exact hosted CI executes them.
- The original #2180 real pinned Granite97 training and independent
  scoring job remains required; an offline/queued/failed job cannot
  become a real-model claim from this sidecar.
- True future-time/OOD/source-independent tasks, matched actual active
  FLOPs and *total* lifecycle resource cost, strong unsplit Reader,
  NDU/negative-transfer, native 64/256/1024/4096 Worker metrics,
  original signed CAS→migration→CNS→Supervisor, durable Evidence
  reconciliation and Final-use all remain separate nonwaivable gates.

`production_admission=BLOCKED`, `eligible_model_selection=false`,
`physical_cell_split_authorized=false`,
`codex_effect_authorized=false`, `authority_posture=DENY_ALL`.

**Do not auto-merge, select/promote, fork Codex or execute production effects.**
