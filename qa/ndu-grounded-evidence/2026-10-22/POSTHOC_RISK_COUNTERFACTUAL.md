# Post-hoc NDU risk/covariance mechanism replay (not outcome evidence)

**Status:** Replayed offline on 2026-10-23 against the **unchanged** final-test checkpoint journal from the 2026-10-22 pilot. This is exploratory, *after* seeing held-out outcomes. **It must not be used to choose a risk weight, revise the original pilot, claim an efficient-frontier gain, or support a confirmatory hypothesis test.**

## Frozen inputs and reproducibility

- Original final-test execution: 64 source images × 12 method arms = 768 episodes; selected \`risk_weight=0.0\`.
- Frozen train-fitted policy checkpoint: \`training/policies.pt\`, SHA256 \`8d4918001e86c863edad47fb9c99d522aaadf7c1a3cba27482615b06ca2d4a06\`.
- Original final-test journal: \`raw/test.episodes.jsonl\`, SHA256 \`b9e7e0a53622b9b87e29507684684389aaf798e97bf53b0d4e93f44570786e39\`.
- Frozen policy implementation: \`code/policies.py\`, SHA256 \`1076fdcd89b150862192d72363143cdd2aeae5049f7175c674542e3e9a1fd78f\`.
- All files above are in the pinned portable evidence ZIP named in [RESULTS.md](RESULTS.md). Extract the ZIP; the model weights and original JPEGs are **not** needed for this replay.
- The counterfactual implementation is \`qa/ndu-grounded-generation/posthoc_policy_counterfactual.py\`. It uses PyTorch, the frozen learned policy weights, recorded **reference-free** state features, recorded action-wise local covariance penalties, and the original sampled-action seeds. It does not use \`score\`, reference boxes, images or terminal labels.

From \`qa/ndu-grounded-generation\`, run:

\`\`\`sh
python -m unittest -v test_posthoc_policy_counterfactual
python posthoc_policy_counterfactual.py \
  --policy /path/to/extracted/bundle/training/policies.pt \
  --episodes /path/to/extracted/bundle/raw/test.episodes.jsonl \
  --output /path/to/new/directory/posthoc-risk-counterfactual.json
\`\`\`

The output contains the full per-checkpoint probability arrays, the sampled counterfactual decisions, and aggregated diagnostics. Always write it **outside** the original evidence directory. The program refuses to proceed if its \`risk_weight=0\` action/probability replay differs from the original logged decision; all **139/139** real NDU decision checkpoints reproduced on the frozen CPU policy, with no mismatch.

## Observed mechanism-only diagnostics

The following grid was selected **after final test**, solely to characterize a mechanism at fixed historical prefixes. It is not a dev-selected replacement protocol.

| Counterfactual risk weight | Checkpoints with covariance TV > 1e-8 | Sampled actions changed by covariance | Mean covariance/no-covariance TV | Mean expected local penalty (with / without covariance) |
| ---: | ---: | ---: | ---: | ---: |
| 0 (original) | 0 / 139 | 0 / 139 | 0.000000 | 0.212320 / 0.212320 |
| 0.5 | 77 / 139 | 3 / 139 | 0.012518 | 0.200298 / 0.223285 |
| 1 | 77 / 139 | 5 / 139 | 0.024842 | 0.188744 / 0.234415 |
| 2 | 77 / 139 | 6 / 139 | 0.047741 | 0.167547 / 0.254262 |
| 5 | 77 / 139 | 16 / 139 | 0.089874 | 0.130621 / 0.282989 |

**Interpretation:** the *implemented* local logit-disagreement covariance proxy has a genuine **policy-distribution** effect when risk weight is forced nonzero. At the original dev-selected risk weight zero, the action probability and executed action are unaffected. Nonzero weights would sometimes change sampled actions, and within these fixed states the expected **proxy penalty** decreases. None of these numbers measures a realized quality change, calibrated terminal tail risk, true independently estimated terminal-loss covariance, or net control benefit. All 139 states are conditioned on the original \`risk_weight=0\` trajectory, so sequential interventions would change later states and the table cannot be treated as a counterfactual episode rollout.

## Blocker disposition

- **Closed as a mechanistic unit test:** a nonzero risk weight and recorded local covariance penalty change frozen policy probabilities as mathematically implemented; original zero-risk replay matches precisely.
- **Not closed:** original pilot's zero dev-selected weight; a scientifically warranted positive weight; quality/risk benefit with nonzero weight under real feedback; action-dependent terminal covariance estimation; 8-16 real decisions per episode; freely generated independent language/image modalities; hard per-episode deadlines; matched realized cost and coverage; independently held-out confirmatory cohort and multiple seeds.
- Required next experiment: pre-register a nonzero-risk candidate and zero-risk control **using train/dev only**; retrain/roll out each arm under a new frozen protocol and new, untouched test cohort; measure all actions, real outputs, severe events, CVaR, coverage and cost with predeclared comparison and multiplicity control.

**Original scientific verdict remains unchanged: \`experiment_pass=false\`, \`production_pass=false\`; no established NDU frontier advantage.**
