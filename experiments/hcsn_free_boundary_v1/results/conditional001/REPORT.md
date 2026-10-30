# Additional conditional-threshold comparison

This report is the separately registered **additional/exploratory** comparison. It does not change the original six-contrast Holm family, original selections or predictions. Both studies completed before this analysis; no training or new model inference was performed.

## Paired result

The effect is **free_dual minus conditional_dual**. Averaging the two tasks equally within each of eight seeds gives **-0.8301 percentage points**, with nominal paired-t 95% interval **[-2.1108, +0.4507] pp** (7 df). The two-sided exact sign-flip test enumerates all 256 assignments: **p=0.17187500**, unadjusted and exploratory.

The observed mean favors **conditional_dual** under the declared CPU search budget. The nominal interval includes zero and the sign-flip test does not reject at 0.05. This does not establish superiority for either arm or equivalence. The interval describes training-seed variation on these fixed test sets, not uncertainty over new datasets or deployment populations. Sign-flip inference assumes sign exchangeability/symmetry of paired differences under the null; the t interval is nominal and not simultaneous.

| Task | Free accuracy | Conditional accuracy | Free minus conditional | Supervised positions per seed |
|---|---:|---:|---:|---:|
| selective_copy | 33.6304% | 36.1206% | -2.4902 pp | 2048 |
| multimodal_select | 16.5771% | 15.7471% | +0.8301 pp | 512 |

The two tasks receive equal weight. The selective-copy task's four supervised tokens per episode are not pooled with the other task's single query token.

| Seed | Free two-task mean | Conditional two-task mean | Paired difference |
|---:|---:|---:|---:|
| 9101 | 25.7080% | 26.7090% | -1.0010 pp |
| 9102 | 24.9512% | 26.0498% | -1.0986 pp |
| 9103 | 23.1201% | 24.5850% | -1.4648 pp |
| 9104 | 24.5605% | 26.1719% | -1.6113 pp |
| 9105 | 23.2422% | 20.7275% | +2.5146 pp |
| 9106 | 25.8057% | 28.6133% | -2.8076 pp |
| 9107 | 25.0732% | 25.8789% | -0.8057 pp |
| 9108 | 28.3691% | 28.7354% | -0.3662 pp |

## Selection, work and active parameters

Both arms use width32/depth1, batch32, LR .001/.003, and 20 training process-CPU seconds per candidate. Validation-only selection uses the common 5/10/20 CPU checkpoints; 128-only snapshots do not enter the primary selection. Both LR candidates finish before heldout evaluation. All common initialized weights are byte-for-byte numerically equal.

| Task / arm | Backbone / total parameters | Mean selected step (range) | Mean complete search CPU | Mean training CPU |
|---|---:|---:|---:|---:|
| selective_copy / free_dual | 8800 / 11272 | 124.12 (115–135) | 47.6138 s | 40.2071 s |
| selective_copy / conditional_dual | 8864 / 11336 | 139.25 (130–151) | 45.5907 s | 40.1409 s |
| multimodal_select / free_dual | 8800 / 11338 | 101.12 (56–132) | 46.2256 s | 40.1875 s |
| multimodal_select / conditional_dual | 8864 / 11402 | 113.38 (71–144) | 44.9692 s | 40.1868 s |

The conditional arm adds 64 active parameters (0.7273% of the 8800-parameter free backbone): a per-neuron gap and slope. Its frontend/readout are unchanged; no parameter padding is used.

| Across 16 searches | Actual training CPU | Complete child process CPU | Candidate update range |
|---|---:|---:|---:|
| free_dual | 643.15743 s | 750.71489 s | 112–137 |
| conditional_dual | 642.62148 s | 724.47954 s | 125–154 |

Complete CPU includes interpreter/imports, setup, both full LR searches, validation, checkpoint IO and heldout evaluation. Selecting an earlier checkpoint does not remove the rest of its search cost. These are reference single-thread CPU measurements, not energy measurements or optimized GPU/neuromorphic performance.

The comparison uses equal process-CPU budgets, not equal update counts. Consequently, an accuracy difference can reflect both threshold parametrization and training throughput. This report does not claim a matched-step advantage; missing 128-update snapshots remain missing, with no extra training or extrapolation. Runs used different scheduling windows, so CPU timing is descriptive for this shared host.

## Prediction and pairing audit

All **16 task-seed pairs** passed independent checks against the frozen data labels. Saved logits were checked for finite values; argmax predictions, labels, supervision masks and row coordinates cover every supervised position exactly once. Accuracy and cross entropy were recomputed and matched the original summaries. Prediction archive hashes, selected checkpoint hashes and run receipts are retained in COMPARISON.json.

All **32 actual LR minibatch-prefix pairs** match through their common update prefix (112–137 updates). This compares the original main update logs with the additional logs, rather than relying only on nominal seed equality. Common initialized state-dict arrays also match exactly.

## Separate OOD description

For selective-copy OOD length64, mean accuracy is 30.8167% for free and 32.9102% for conditional. This is descriptive, is not mixed into the primary two-task pairing, and has no new significance claim.

## What this addresses

The original direct_dual has a learned but input-static per-neuron threshold, whereas free_dual's boundary changes with input-dependent mu. A free-versus-static-direct result therefore mixes the boundary formula with the ability to adapt the threshold to the input. It cannot by itself establish a special benefit of the endogenous free-boundary mechanism.

The added control uses b_t=K+softplus(raw_gap+slope*mu_t), with slope initialized to zero. It reuses the exact same mu mapping, content network, own-policy J/G and mean-state reset/refractory update. It addresses that conditionality gap while remaining a restricted softplus-affine function, not a universal learned threshold network. The two arms also couple their learned dynamics parameters to the threshold differently.

Both arms retain the known frozen-local mean-closure limitation; this comparison does not certify exact stochastic propagation or global optimality. It is evidence about two small tasks and a declared search budget, not a foundation-model, Transformer or SNN superiority claim. No primary Holm conclusion is rewritten by this additional result.

## Reproduction and identities

Run `python -m experiments.hcsn_free_boundary_v1.conditional_analysis` from the repository with the supplied scientific Python dependencies. The command refuses to replace existing COMPARISON.json or REPORT.md; use a separate output directory for a repeat analysis. It reads existing evidence and performs no training or model forward pass.

```json
{
  "conditional_analysis.py": "522f3448b4012b631a62cf51f1d7596727ad66895842530a23c31d3507ebaeac",
  "conditional_analysis_tests.py": "0c892cd6da68ef7438aa92dd55c19e37b89547172da111caca8bf71919ed3b3c",
  "conditional_complete": "d8370beb151b08e1117b7fe1be9ac894f3c0149f85f2a3f8dad01ee7fc20bb62",
  "conditional_protocol": "0462f1bf58f7c409b215098a440eb8d4ab30af41188af6591403a741864aa191",
  "main_complete": "81513d67b039b2cbc0ae619f075453e95882240c3a6c7308a23159ffd41ea352",
  "main_protocol": "0b684b1f3030ff9bcdb4f673ae26eb653c1ead868ed6edf8a8803ba735af4ff2"
}
```
