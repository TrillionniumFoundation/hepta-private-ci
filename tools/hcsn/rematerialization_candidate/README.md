# Isolated B rematerialization candidate

This directory is an additive candidate for PR #4873. It does not edit or
activate any change in the frozen baseline. `CANDIDATE.json` hashes the baseline
source and full configuration; the checker refuses a mismatch.

## Mechanism

`qualification/hcsn/rematerialization.py` subclasses the original B encoder.
The original parameters, buffers, physical grid and state transition remain
unchanged. Each segment receives all five evolving state tensors and its
original input slice explicitly. It returns the complete differentiable state
and filtered outputs. Non-reentrant activation checkpointing recomputes internal
activations during backward. There is no detach, truncation, precision change,
new sampling, or microbatching.

The intended integration is opt-in with an explicit recorded `segment_steps`.
The original benchmark factory and full configuration are not changed here.
Full-batch training remains batch64 × sequence64 × hidden64 × bins32 for 400
optimizer updates. Rematerialization trades additional computation for reduced
activation storage; cost, energy and actual peak memory must be measured with
the new source/configuration identity.

The implementation uses `checkpoint(..., use_reentrant=False,
preserve_rng_state=True)`. The non-reentrant API supports parameters receiving
gradients even when the initial state and data inputs do not require gradients;
this is exercised by the paired fixture.

Reference: [PyTorch 2.8 checkpoint API](https://docs.pytorch.org/docs/2.8/checkpoint.html).

## Static diff

`rematerialization-additive.patch` adds only the 59-line candidate module. It
does not change `baselines.py`, `population_torch.py`, the benchmark or any
frozen data/budget configuration. State dictionaries have the same names and
shapes as the inherited baseline.

## Validation command

From the baseline repository root, run the checker by its actual filesystem
path; output paths must be new to preserve previous receipts:

```sh
python ../remat-candidate/check_rematerialization.py \
  --repo-root . --device cpu --output ../remat-candidate/parity-cpu-01.json
```

The default fixture compares FP32 and FP64, recovery on/off, segment sizes 1/4,
and inputs with/without `requires_grad`. Its sequence length 9 exercises a final
partial segment. It compares all forward traces and predictions exactly, then
raw parameter/input gradients, clipping norms, one Adam update, optimizer
moments and no-grad evaluation after the update. Gradient/update tolerances
are fixed before execution: FP32 atol=1e-6/rtol=1e-5; FP64
atol=1e-12/rtol=1e-10. They do not define a research quality threshold.

The small shape is an implementation-equivalence fixture. It is not a reduced
budget substitute for any full research run. `--batch-size`, `--length`, and
`--hidden-size` may be set to 64 for an explicit full-shape parity attempt only
after original B memory feasibility is known. Neither script nor candidate
automatically lowers a requested shape or substitutes CPU for CUDA.

## Portable operator diagnostic

`diagnostics/probe_population_grid.py` is an external read-only experiment.
Run it from the baseline repository root (or specify `--repo-root`):

```sh
python ../remat-candidate/diagnostics/probe_population_grid.py \
  --repo-root . --output ../remat-candidate/numpy-grid-01.json
```

The original diagnostic result and original runner are preserved separately
with SHA256 hashes in `numeric-audit/ORIGINAL-RECEIPT.json`. The diagnostic does
not replace the trained-checkpoint grid audit.

## Remaining qualification

Prepared code is not tested correctness or a measured memory saving. Required
evidence is CPU parity, actual original-shape CUDA forward/backward, peak
memory, and the full unchanged training/validation/test budget with all
recomputation costs included. Keep original OOM/failure outcomes with their
original source identity. No current or historical B task/resolution result is
upgraded by this candidate.
