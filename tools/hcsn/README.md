# HCSN follow-up probes

These are prepared research probes, not completed CUDA or full-budget results. Their current observations are in `qualification/hcsn/evidence/desktop-20261105/`.

The original baseline package must be materialized from commit `28a61d14ea7d4c3b3c515ab57b29c98de22e5673`; do not run the pinned original probes against a modified research package. The original full config SHA256 is `7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a` and its recursive Python source-map SHA256 is `13860b933a93966e880e64840efa0ac26b70ab62cbe7e38bf71587575d9831a3`.

| Tool | Scope |
| --- | --- |
| `cuda_preflight.py` | Original full-shape CUDA A/B/Mamba-2 single training step, no held-out evaluation, no contribution to the 170 completed-run count. |
| `cuda_preflight_rematerialized.py` | Candidate-only full-shape B step; external original-resource and CPU/CUDA parity gates remain mandatory. Fixed segment length 1. |
| `rematerialization_candidate/check_rematerialization.py` | Fixed 16-case small-shape forward/gradient/optimizer parity fixture, separately on CPU and CUDA. |
| `audit_population_separable.py` | Original three smoke B checkpoints; full original 48-record receipt and 23 source hashes required. Separate spatial/time sensitivity and final-prediction RMS. No retraining or selection. |
| `probe_numpy_separable.py` | Untrained FP64 constant-drive operator diagnostic; not trained-model qualification. |
| `execution-candidate.patch` | Reviewable isolated implementation proposal. Not automatically applied by any probe. |
| `artifact-retention.patch` | Workflow repair retaining smoke `.runs/` weights and immutable attempt journals with JSON. |

Example original probe, using an already validated CUDA environment:

```sh
python tools/hcsn/cuda_preflight.py --repo-root ORIGINAL_ROOT --model hx_dual --device cuda:0 --max-memory-fraction 0.5 --output NEW_OUTPUT.json
```

Candidate parity uses `--repo-root ORIGINAL_ROOT --device cpu` or `--device cuda:0`, a fresh `--output`, and the adjacent frozen `CANDIDATE.json`. The candidate-only CUDA probe additionally requires `--remat-root tools/hcsn/rematerialization_candidate`. Successful provenance rejection tests do not imply parity or CUDA execution.

The original smoke receipt and checkpoint paths are listed in the evidence `smoke-checkpoint-origin.json`. Preserve that complete receipt and its original `.runs/` relative layout; do not replace it with a three-record denominator. Missing physical energy stays missing, and an allocator fraction is not a GPU reservation or a limit on all driver allocations.
