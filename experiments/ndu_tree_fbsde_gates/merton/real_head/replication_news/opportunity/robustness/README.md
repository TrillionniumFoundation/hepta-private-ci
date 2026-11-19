# Ambiguity sensitivity of NDU–Merton compute investment

**RESEARCH / DENY_ALL.** Additive to PR #2319's nested record-held source-slice study. No selected model, production worker or source owner is altered.

A finite learned opportunity model may fit a held dataset while remaining non-identifiable for future task families. This study builds a *separate, exact mathematical stress test* to expose that limitation instead of claiming a transfer win.

With a fixed distribution over latent learning curves, the TV-ball worst-case expectation is calculated by moving at most `epsilon` probability mass from the largest utility outcomes to the smallest. The risk-sensitive special case evaluates `(1-alpha)*worst_mean + alpha*min_supported`. This is a finite robust decision proxy, not a general NDU FBSDE or a statistically calibrated ambiguity radius. No new-source label data are used to select epsilon; the sweep is explicitly a **scenario sensitivity**, not adaptive proof of safety.

A constructed two-world example has indistinguishable early observations. One world benefits from further training and the other is harmed. Nominal Bayesian continuation changes to robust stopping under wider ambiguity. The fact that both worlds share the same observable history means no policy can always choose their separate optimal actions. Tests rederive the finite TV result with an independently enumerated probability grid. This demonstrates a limitation, **not** live-model failure or new-task improvement.

A one-shot pre-prior admission bound rejects fitting a paid opportunity model if `H - cost_prior <= guaranteed_fallback_floor` even if every future prediction could become perfect. If the bound admits, positive expected ROI is still unproven. No replacement of the current dynamic guard is activated.

The retrospective nested summary (`transfer/local_observation.json`) is consumed **only for post-seal audit**. Its 64 historical unique record IDs, 49/64 matched fixed8/NDU results, and 0.099826 mean absolute forecast error do not establish independent families, a future confidence interval or a supported production transfer. This study does NOT refit the current Head or open the 32 original HOLDOUT labels.

## Run

```bash
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news/opportunity
export NESTED_SUMMARY="$D/transfer/local_observation.json"
python -m unittest discover -s "$D/robustness" -p test_robust.py -v
python -O -m unittest discover -s "$D/robustness" -p test_robust.py -v
python "$D/robustness/robust.py" --nested "$NESTED_SUMMARY" --output /tmp/hepta-ndu-robustness.json
```

Neither scalar mathematical correctness nor retrospective diagnostics qualify neural preference learning, unseen-source task utility, calibration guarantees, FBSDE global existence, whole-service cost parity, independent acceptance or model promotion. Preserve all existing blocking CI and DENY_ALL gates.
