# Hepta NDU-DMGP shadow qualification (A0–A5)

**Scope:** deterministic, dependency-free research reference; **no** provider/model calls, trained decoder, effect authority, production writer, artifact promotion or verified NDU-FBSDE solution. Generated quality, decode time, covariance observations, and the nominal “independent observer” in `experiment.py` are **synthetic**. They are not independent real-world evidence. `measured_on_host=False` must be used for all simulated physical work.

This is intentionally **not** a new NDU Subject class or NDU owner. It is a candidate portfolio control and falsification surface for existing `utility.ndu`, `neuron.runtime`, `learning.eval` and circuit owners. The canonical NDU owner retains feasibility/Pareto, objective freeze, observer provenance and promotion authority boundaries.

## Run

```bash
cd qualification/ndu-dmgp-shadow
python3 -m unittest discover -v
python3 experiment.py > synthetic-results.json
```

Python 3.11+ standard library only. The output declares `kind=synthetic-shadow-only`, `model_training=false`, `neural_decoding=false` and `gpu_benchmark=false` regardless of synthetic gains. `mean_local_controller_us` is a local process measurement not comparable with the fabricated decoder costs. The exploratory bound `mean - 2.5*SE` is **not** a production confidence interval or a guaranteed anytime bound.

## A0–A5 predeclared contrasts

| Arm | Synthetic policy and limitations |
| --- | --- |
| A0 | fixed text decoder path |
| A1 | fixed text+image route and full budget |
| A2 | context-conditioned top-one route (MoE proxy) |
| A3 | one-step cost-aware NDU advantage (known synthetic oracle) |
| A4 | centered conditional covariance, shrinkage, finite-grid Merton proxy; route probabilities, never mixed output tensors |
| A5 | deterministic bounded Bellman-style continuation, stop and pair interactions; **not** full stochastic NDU/FBSDE |

A0/A1/A2/A3/A4/A5 must run against the same frozen prompt split and simulated observer. Real external validation requires grouped train/future splits, full model executions and an independently authenticated evaluator. This demonstration does **not** establish A5 improves over A1: the current synthetic task often makes both choose identical outputs while A5 incurs extra controller overhead. Preserve unfavorable results.

## Six scientific gates plus Markov closure

1. **NDU reward truth:** `Freeze`, independently named actor/critic/outcome observer; immutable objective and critic digest; physical work deduplication; paired future-only utility. Synthetic declared identities do not establish real independence; cross-service auth and actual observation remain unqualified.
2. **Cross-modal consistency:** shared timeline/entity/event plan, forward completeness, reverse hallucination rejection, observer-linked claim digests. Real text/image/audio/video extraction and cross-modal perceptual validation remain unqualified.
3. **Covariance identifiability:** paired within-context, centered covariance, independent episodes, raw Cholesky support check, shrinkage and optional bounded eigen-factor+diagonal fit. Rank failure explicitly goes to deterministic routing. This does not identify causal joint outcomes without experimental support.
4. **Efficiency:** instrument decoder, controller, verifier and peak RSS; pair equivalent cases, no duplicated physical work, require measured-on-host evidence for production efficiency. The A0–A5 synthetic cost numbers cannot satisfy this gate.
5. **Learning stability:** frozen critic, future-window lower versus baseline upper, KL/trust-region, retention bound and next-generation-only update. No parameter optimizer or artifact selection occurs in this reference.
6. **Global utility attribution:** complete coalition counterfactual table, explicit randomization/support requirement, interaction residual rejection and Shapley conservation; strong synergy is handled at the global circuit level, never manufactured as additive local Cell reward.
7. **Closure audit:** held-out linear diagnostic comparing compressed state to state+history prediction. Detecting residual historical information rejects the Markov approximation; passing one bounded diagnostic is not a sufficiency proof.

All `Unavailable` failures should be propagated to fallback / slow path. Never interpret unavailable as zero risk, zero cost or successful learning.

## Next implementation gates (OPEN)

- Register versioned source/consumer port schemas and bind source digests to actual Rust `codex-hepta-ndu` / `codex-hepta-neuron` owner runtime; no V1 field redefinition.
- Replace synthetic evaluator with an independently authenticated outcome observer, objective compiler snapshot and real dataset split/holdout manifest; include external utility, real resource accounting and long-term retention.
- Implement a true multimodal decoder adapter with causal shared semantic plan and perceptual reverse reconstruction, synchronized timestamps and typed media ranges.
- Qualify covariance conditional-support estimation across actual paired candidate rollouts; negative OOD, intervention, missingness and identifiability tests.
- Measure end-to-end GPU, host, energy, memory, p95/p99 and controller overhead on a named hardware/profile, equal quality and equal compute budgets.
- Train and evaluate a policy/critic on frozen snapshots with next-snapshot candidate selection and full regression/rollback evidence.
- Upgrade the bounded Bellman shadow policy to validated recursive NDU/FBSDE semantics and independent full-circuit credit, including non-Markov closure review.

Until all these gates pass, keep `production_activation=false`, `selection=false`, `release=false`.
