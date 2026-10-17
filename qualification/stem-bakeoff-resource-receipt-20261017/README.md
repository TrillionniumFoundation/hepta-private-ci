# Stem bakeoff resource receipt (shadow-only)

This qualification contract makes Stem selection measurable. It accepts target-host evaluation receipts for candidate Stems and applies hard budgets followed by deterministic Pareto filtering.

The contract records quality lower confidence bound, calibration error, OOD coverage, p95/p99 latency, observed memory, energy, modality coverage, hidden-state ABI, runtime, deterministic behavior, and adapter-hook availability. It does not load models, run inference, grant authority, or alter routing. A selected candidate is a research decision only.

Use the resulting decision to compare the existing 421M encoder path, a compact latent Transformer, and a Transformer/SSM hybrid with the same Cell-side artifacts. Do not call one candidate optimal until the target-host receipts and holdout transfer matrix are available.
