# Posthoc cross-run source-supervision decomposition

**This is a POSTHOC saved-aggregate analysis—not a preregistered primary result, new blind replication or new NDU success.**

The earlier mask experiment held source supervision fixed and isolated input masking. This complementary analysis holds instruction visibility fixed and subtracts direct-target-supervised results from instruction-visible source-supervised results. Both use the same seeds 103/107, FIT groups/noise, held-out corruption realizations, architecture, decoder training, batch schedule, optimizer, target-aligned adaptation and FIT calibration. The numerical training intervention is whether the 500 pretraining steps supervise source-scene or edited-target labels. Visible input copying was separately tested exactly equivalent to raw JointModel forward/gradients; it adds allocation cost, not a numerical model intervention.

This attribution uses source inspection plus hash-bound completed records, not just output assertions. Eight shared masked/source model digests, four base digests, all their metrics and calibrated profile keys match exactly across the two runs. Dataset manifests and all metric inventories are checked. No weights or per-request predictions were read, no model or metric was rerun, and no arms, folds, seeds or noises were selected. Extra source labels are real supervision information—not a free architecture improvement. All class templates and these finite groups/noises were already known.

## Descriptive result

Visible-source minus direct-target, after identical FIT-only calibration, partial-command full/low macro:

| Fold | Seed | Noise | Objective | Δ CE | Δ greedy text | Δ pixel MSE | Meets old thresholds descriptively |
|---:|---:|---:|---|---:|---:|---:|---|
| 0 | 103 | 3701 | additive | +0.181245 | +0.182584 | -0.005858 | Yes |
| 0 | 103 | 3702 | additive | +0.179889 | +0.177903 | -0.006148 | Yes |
| 0 | 103 | 3701 | ndu | +0.173088 | +0.171348 | -0.005745 | Yes |
| 0 | 103 | 3702 | ndu | +0.173333 | +0.172285 | -0.005970 | Yes |
| 0 | 107 | 3701 | additive | +0.170875 | +0.173221 | -0.005521 | Yes |
| 0 | 107 | 3702 | additive | +0.165274 | +0.167603 | -0.005204 | Yes |
| 0 | 107 | 3701 | ndu | +0.160941 | +0.164794 | -0.005048 | Yes |
| 0 | 107 | 3702 | ndu | +0.154593 | +0.160112 | -0.004868 | Yes |
| 1 | 103 | 3711 | additive | +0.125383 | +0.122024 | -0.004752 | Yes |
| 1 | 103 | 3712 | additive | +0.134441 | +0.137897 | -0.004893 | Yes |
| 1 | 103 | 3711 | ndu | +0.126549 | +0.130952 | -0.004808 | Yes |
| 1 | 103 | 3712 | ndu | +0.135299 | +0.137897 | -0.004966 | Yes |
| 1 | 107 | 3711 | additive | +0.125851 | +0.129960 | -0.004759 | Yes |
| 1 | 107 | 3712 | additive | +0.128563 | +0.138889 | -0.004694 | Yes |
| 1 | 107 | 3711 | ndu | +0.127318 | +0.129960 | -0.004828 | Yes |
| 1 | 107 | 3712 | ndu | +0.125260 | +0.132937 | -0.004528 | Yes |

All sixteen calibrated contrasts meet the old thresholds descriptively: CE +0.125260 to +0.181245, greedy text +0.122024 to +0.182584 and pixel MSE decreases throughout. All sixteen uncalibrated contrasts also meet them; those and all pooled descriptions remain in SUMMARY. There are **48 total contrast records**, with every full/low/macro and all/partial metric retained.

These results separate an observed source-label supervision contribution from the separately measured mask contribution in this fixed setup. They do not establish universal causality, independent significance or natural-image performance. The comparison was proposed after seeing preceding results; it must not be relabelled prospectively registered. Threshold flags are descriptive only: `new_primary_gate` is null and both earlier overall gates remain false. Neither source-label nor mask gains are NDU-specific gains.

## Cost and reproducibility

Three handmade aggregate fixtures passed; the new fully waited child used **0.118041 CPU seconds**, 0.123947 wall seconds and 19512 KiB RSS under 5 CPU / 30 wall / 512 MiB / 4 MiB, CPU 0, one thread and the existing synthetic lock. No retries. Counts: 48 aggregate subtraction records; **0 model restores, 0 training updates, 0 forwards, 0 dataset generation, 0 metric evaluations**. All parsing, fixtures and checks are included.

The two source runs cost 24.010599 + 23.036013 CPU seconds separately. Older research, development/review and unknown supervisor tails remain additional, not zero. This analysis saves retraining; it is not a claim of zero analysis cost or identical runtime across model architectures.

`decompose.py` consumes already authenticated aggregate records and frozen model identity metadata, supplied here as `INPUT_IDENTITIES.json` (digests/protocol metadata only, no weights). The published sibling SUMMARY files contain the same result dictionaries under `replication` and `ablation`. The executed local worker also verified their exact original raw result hashes and full-wait receipts before invoking the helper. Passing expected hash strings to `analyze` alone is not content authentication; use the published validation/provenance bindings when reproducing.

```sh
python -B -m unittest -v test_decompose
```

Only portable analyzer/tests/plan, identity metadata and aggregates are public. No private runtime paths, input payloads, model weights or per-request predictions. This does not enable a new scientific runner or change defaults/deployments.
