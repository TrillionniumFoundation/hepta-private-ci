# Reproduce the six-stage evidence

The immutable protocols, model sources and descriptive reports are ordinary repository files. Large numeric evidence is transported byte-for-byte in ASCII base64 parts, each below the repository's existing 512000-byte blob limit. The allowlist is unchanged. These are transport parts of the original files, not re-encoded arrays or new checkpoints.

## Recorded environment

Experiments used Python3.12.14 on Linux x86_64, Torch2.8.0+cpu, NumPy2.3.5 and SciPy1.17.0. Plotting used Matplotlib3.10.8. All training workers set OMP_NUM_THREADS, MKL_NUM_THREADS and OPENBLAS_NUM_THREADS to1. CPU wall timings came from a shared host and are not guaranteed on another machine. No GPU or energy result exists.

## Restore original bytes

Run from the repository root. The transport and archive utilities require only the Python standard library. They verify every part and complete logical file, reject escaping paths and symlinks, and refuse to overwrite different existing content.

```bash
python -m experiments.hcsn_sixstage_v1.transport restore --index experiments/hcsn_sixstage_v1/transport_indexes/initial_text_bounded.json
python experiments/hcsn_real_av_v1/data/transport/restore_train.py
python -m experiments.hcsn_sixstage_v1.transport restore --index experiments/hcsn_sixstage_v1/transport_indexes/content_text_bounded.json
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/content002_complete.json --destination experiments/hcsn_distributional_v2/results/content002
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/content002_analysis.json --destination experiments/hcsn_distributional_v2/results/content_analysis002
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/lif_supplement001_complete.json --destination experiments/hcsn_distributional_v2/results/lif_supplement001
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/lif_supplement001_analysis.json --destination experiments/hcsn_distributional_v2/results/lif_analysis001
```

Additional completed studies are grouped under `artifacts/extensions`. After that cohort's index is present, restore it and then its three manifests to the repository root:

```bash
python -m experiments.hcsn_sixstage_v1.transport restore --index experiments/hcsn_sixstage_v1/transport_indexes/extensions_text_bounded.json
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/extensions/risk_and_cost_complete.json --destination .
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/extensions/real_av_complete.json --destination .
python -m experiments.hcsn_free_boundary_v1.archive restore --manifest experiments/hcsn_sixstage_v1/artifacts/extensions/memory_preflights_complete.json --destination .
```

See the final evidence index for later completed fixed-update, sampling and vector-cost cohorts. Restored generated numeric files can remain untracked; their identities are already bound by the transport and archive manifests.

## Rerun audits and training

Source hashes in each protocol bind the actual program version. Preserve them: modifying an implementation is a new experiment. The package READMEs and `--help` provide each registered run and analysis command. Use a new empty output directory. Some reference receipts contain absolute paths from the execution host; these are provenance records, not credentials or required local mount points.

Original heldout predictions, all candidates, validation selection locks, failures and costs are retained. A strict original audit failure is not erased by a later numerical diagnosis. Training-only preflight, same-update, same-training-CPU and quality-conditioned operating-point results answer different questions and must not be pooled as interchangeable replicates.
