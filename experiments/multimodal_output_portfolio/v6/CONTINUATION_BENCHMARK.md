# V6 continuation study on recovered trained generators

This stage supplies an executable seven-policy continuation experiment. It reuses the six full-002 trained generators and independent reward/audit observers, verified against the original archive and checkpoint manifests. The existing no-update decision is preserved.

## Frozen comparison

- The first 120 original test pairs belong to the previous full-001/full-002 evaluations. New fit pairs are 120–215, dev pairs 216–263, and final test pairs 264–359. Original pixel identities are checked for overlap. These are held-out historical MNIST sources, not chronologically future observations or natural multimodal samples.
- All policies start with the same strict encoder-only state. The decision bank is STOP or one of the four native content actions followed by `refine_image`, at most two real transitions. STATIC uses text then image; DEV selects one fixed bank entry before TEST.
- The remaining causal arms are a mean continuation head, a finite search over the five bank entries under a fitted terminal forecast, and the existing entropic continuation head. Empirical support rejection falls back to DEV without weakening the original check.
- The seventh arm uses hidden test labels to select the best bank entry. It is an explicitly separate clairvoyant diagnostic, not a fair deployable comparator.
- All generated PNG/caption bytes, actual actions, CPU/wall time and independent observer scores are retained. Audit scoring is separated from online execution; oracle label queries are charged inside its selection envelope. Offline head fitting and development selection are retained separately. CPU tariff 0.01 utility/CPU-second is illustrative; energy and monetary benefit remain unmeasured.

## Execution

```bash
python -B -m experiments.multimodal_output_portfolio.v6.continuation_benchmark --inputs /path/to/recovered-inputs --output /new/output --source-sha EXACT_COMMIT
```

The inputs contain `ndu-data/` and `ndu-runs/full-002/` from archive `ndu_v6_full002_evidence.tar.gz` (62,166,608 bytes, SHA-256 `ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e`). An optional mechanical smoke uses `--fit-pairs 6 --dev-pairs 6 --test-pairs 6`; its sources are wholly inside the later development range and never touch the final TEST panel.

A successful execution is not production qualification. The generator training axis is inherited from the old experiment; this is a new continuation-head fit and execution study, not a fresh generator-training factorial. It does not close full Rust generator equivalence, repeated replanning, conditional calibration, unknown-input rejection, authenticated lifecycle ownership, audio/video, or temporal validation.

## Pre-execution review corrections

An independent source and recovery audit identified a search-ranking error before the new TEST outcomes were generated. The finite-search arm now subtracts only remaining emission cost after constructing all five candidate states; every actual candidate transition remains charged in the measured online envelope. The quality oracle is an upper bound only within this fixed plan bank, not an upper bound on measured net return. Descriptive gamma=2 certainty equivalent, bottom-decile net return and utility-below-0.5 frequency are frozen alongside means. Three original metadata hashes and both observer hashes bind the recovered input chain, and source hashes are checked again at completion. The CLI admits only the registered full panel or the separate 6/6/6 mechanical smoke.

The six full-002 generators have hidden width 96, so the newly fitted continuation heads have 398 features. Historical 78-feature, two-row Torch/Rust agreement does not qualify these new heads. Any later native head comparison must be reported separately from this Torch generator experiment. Offline head fitting and development selection are measured, but not amortized into per-row online net return; original model training, recovery, energy and deployment costs remain outside it.
