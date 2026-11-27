# Controlled generation v2: confirmed finite result and remaining blockers

## Disposition

The source-frozen local CPU confirmation **passes all seven preregistered primary gates**. Independent recomputation and direct checkpoint replay confirm the result. **All research and execution blockers are not closed:** meaningful iterative refinement, continuation advantage, robustness under changed error dependence, native HEPTA integration and externally verified cloud execution remain open.

Source commit: `c5c6b9df0a83a9a2f95d5583b95909829a982b06`. Protocol SHA256: `2a5a206024c3837223e1db83a4515a4d2ba0a0416d48c482989cc5130bdf97cf`. The original preregistration and matched-baseline amendment precede development smoke and registered heldout. A later, disclosed chronology-only wording correction does not change any scientific parameter or gate. Old v1/v1.1 source and negative evidence remain unchanged.

The model has 660,488 parameters, eight synthetic concepts and four learned raw-modality encoders/decoders. The concepts, synthetic renderer and canonical target space are shared across splits; independent draws do not constitute unseen-concept or natural-data foundation-model validation.

## Registered comparison

The sole confirmatory comparison is **joint NDU minus matched supervised static, IID, budget 12 after initial text**. Three seeds (17/29/43) each evaluate 1,536 paired worlds. Values below average per-seed statistics; CVaR is the mean of the worst 10% loss mass within each seed, including fractional boundary weighting.

| Measure | Matched supervised static | Joint NDU | Difference or ratio |
| --- | ---: | ---: | ---: |
| CVaR90 external loss | 0.702617 | 0.577467 | **-0.125150** |
| Mean external loss | 0.098817 | 0.119560 | **+0.020743** |
| Mean joint-semantic correctness | 0.881510 | 0.879774 | -0.001736 |
| Ambiguity proxy | 0.000000 | 0.038303 | **+0.038303** |
| Mean online ideal Linear MAC | 572,654 | 523,498 | **0.914160** |

The independent hierarchical paired bootstrap gives the primary CVaR difference a 95% interval of **[-0.140570, -0.108222]**. The required reduction was at least 0.02 with an interval upper bound below zero. Quality's point difference exceeds its registered -0.02 margin, the MAC ratio is below 1.05, all three seeds are present, and the oracle/output/budget gates pass.

This is a tail/mean tradeoff. The mean-loss deterioration also has an interval above zero, [0.017605, 0.023828]. The ambiguity proxy increases by about 3.83 percentage points; it measures a narrow nearest-prototype margin, not failure to emit a modality. The protocol did not place a hard gate on this proxy. A primary pass therefore does not establish improvement across all output-quality measures.

## What the controls establish

Secondary intervals are unadjusted and descriptive, not additional confirmatory discoveries.

| Joint NDU minus comparator, IID budget 12 | CVaR90 difference | Descriptive 95% interval | Interpretation |
| --- | ---: | --- | --- |
| Supervised NDU | -0.100925 | [-0.109397, -0.087684] | Supports an effect of the NDU-conditioned parameter updates within this task. |
| Joint static | -0.006459 | [-0.019175, 0.005814] | Additional tail benefit from dynamic control is not established; online MACs are lower. |
| Joint myopic | +0.001895 | [-0.004229, 0.009662] | Long-horizon continuation superiority is not established. |
| Joint fixed risk | -0.003409 | [-0.007464, 0.000493] | Additional benefit of the bounded preference update is not established. |
| Joint risk neutral | -0.136342 | [-0.162217, -0.112318] | Shows the expected influence of risk-sensitive selection on tail loss. |

The primary combines generator training and control. Its success cannot be attributed entirely to dynamic continuation or preference evolution; most of the tail improvement is also present with the jointly trained model's static strategy.

## Refinement and gradient attribution

All 4,608 primary worlds use depth 0, for every arm. Thus the primary MAC saving comes from input acquisition rather than deeper or adaptively shortened generation. Across all joint-NDU budgets/scenarios there are 24,192 evaluations: 24,156 at depth 0 and 36 at depth 1, with none at depths 2/3. The 36 depth-1 cases all occur for seed 29 at budget 8 (13 IID and 23 correlation-shift worlds).

The negative-utility component has finite nonzero gradients to the initial latent map and all four decoders at all six recorded first/last-update points. Its refinement gradient is zero in five of those six records; seed 43's first update has a small norm, `7.05265e-6`, with depth-1 calibration path mass `5.33752e-6`. All three final recorded refinement gradients are zero. Intermediate updates do not have this diagnostic, so the evidence does not establish that refinement never received NDU credit.

Anchor gradients to refinement are nonzero. Parameter movement, shared-group hashes or a nonzero aggregated initial-latent/refinement gradient cannot by themselves establish NDU credit to the residual field. Raw encoders are frozen during both fine-tuning arms. The result supports NDU-conditioned generator fine-tuning, not all-parameter end-to-end NDU training or learned latent-state feedback inside refinement.

## Stress-test failures

| Budget-12 scenario | Joint static CVaR90 | Joint NDU CVaR90 | Joint NDU correctness |
| --- | ---: | ---: | ---: |
| IID | 0.583926 | 0.577467 | 0.879774 |
| Changed error correlation | **0.770293** | **0.981852** | **0.097222** |
| All sources share a wrong report | 0.983085 | 0.983085 | **0.000000** |

Under changed dependence, dynamic selection has materially worse tail loss than the same model's static selection. With a common wrong report, every arm's semantic correctness is zero. A smaller reconstruction loss does not establish recovery of correct content. Exact control under a calibrated finite law does not make that law correct under distribution shift or supply missing independent information.

## Verification and costs

- 23 unit/integration tests pass. Under `-W error`, pinned PyTorch's temporary-directory finalizer emits a shutdown `ResourceWarning` after unittest reports OK; the processes exit zero. The development review preserves this dependency lifecycle issue.
- Fifteen independent bottom-up audits check 14,298 reachable states each: **214,470 comparisons**, zero action/portfolio/depth mismatches, maximum value error `3.71925e-15`. Selection uses a `1e-12` depth/action improvement tolerance.
- The completed run contains **8,064 distinct seed/scenario worlds**, each evaluated for 7 arms and 3 budgets: **169,344 evaluations**, not 169,344 independent samples.
- Independent review checks every trace, budget deduction, ideal Linear MAC count, paired ID, portfolio-support constraint and emission contract; all violations are zero.
- Direct evaluation of saved weights reproduces every raw output hash and independently recomputed metric for **9,216 primary-arm evaluations**, without importing the experiment's scorer, rollout or reporting code.
- Twenty source hashes and 241 artifact hashes match. No source dependency changed during the run.
- Each final training arm receives 40 optimizer updates and **18,252,410,880** ideal dense Linear forward MACs, from the same checkpoint. Total training costs differ: supervised fine-tuning took 3.98/4.14/4.28 seconds, while NDU fine-tuning took 19.20/20.30/23.14 seconds on this host. Backward/optimizer FLOPs are not measured. Controller compilation, diagnostics and validation are reported separately.
- The entire registered local run took **276.073 seconds wall / 449.735 process CPU seconds**. Independent confirmation auditing adds 7.117 seconds wall / 8.279 process CPU seconds, with about 1.065 seconds further descriptive processing. These are receipts, not a controlled hardware latency benchmark.

## Reproducibility and execution status

The complete original run data is delivered as `hepta-v2-confirmation-data.zip` (24,960,067 bytes), SHA256 `f5b8ac9425c7296a28ef16beff645c0b64c5fcfba7b2c3b363fbd0c8c1834b23`. It contains nine checkpoints, calibration and loss tables, the per-world CSV, output hashes, gradient evidence and the original artifact manifest. Source code is available at the pinned commit rather than duplicated in the data package.

The reproducible independent audit is `evidence/audit_confirmation.py`; use `--repo`, `--run` and a new `--output` path. `review_confirmation.json` contains its full findings, and `evidence/confirmation-001-summary.json` provides compact machine-readable results.

The cloud request pins the same implementation and protocol: [Actions run 39899251197](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39899251197). At the timestamp in `evidence/cloud-status.json`, both jobs are queued, have runner ID 0 and no steps. Neither hosted verification nor dedicated execution is verified. The prior dedicated request was cancelled without an assigned runner. Queueing and local success do not close the cloud-execution gate.

## Next scientific requirements

`BLOCKER_LEDGER.json` keeps closure criteria and current evidence separate. The next experiment must use a new preregistration and fresh confirmation draws if objectives, tasks or selection rules change. The open questions are useful latent-dependent iterative generation, continuation/preference benefit beyond the controls, robustness to dependence shift, and independent evidence when all modalities share an error. Native DecisionCell integration, learned identifiable preference dynamics, continuous stochastic FBSDE solving and natural-data foundation-model validation remain separate implementation and research tasks.
