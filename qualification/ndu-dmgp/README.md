# NDU-DMGP shadow reference: six blockers and A0–A5

**Scope:** research-only, no model provider calls, no production writes, no authority, no promotion, no real multimodal generation. This folder is a **standalone Python standard-library reference**, not a new Hepta runtime owner. Do not treat synthetic benchmarks as production evidence.

Pinned inspected baseline: `TrillionniumFoundation/hepta-private-ci` `f8c9419df6ddeb36ff8b522a50219981fb8d9345`. Existing owners: `utility.ndu`, `neuron.runtime`, `learning.eval`, `learning.ledger`, `learning.artifacts`, CNS/TaskFlow. Read `docs/learning/NDU_FBSDE_SPEC.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md`, `docs/learning/NEURAL_BIOMIMICRY_SPEC.md` before production integration.

## Run

```sh
python3 -m unittest discover -s qualification/ndu-dmgp -p 'test_*.py' -v
python3 qualification/ndu-dmgp/synthetic_matrix.py
```

## Reference invariants and remaining blockers

| Research blocker | Implemented fail-closed shadow check | Missing **production** acceptance evidence |
|---|---|---|
| Independent NDU reward | Frozen objective/observer identity, source kind, observed costs, train/future/retention split isolation, minimum paired support | Authenticated independent Observer signatures; real task outcomes; objective-scope proof; critic/actor disjoint evaluation |
| Cross-modal agreement | Shared entities, audio/video event alignment, independent cross-modal cycle probes, false self-consistency rejection | Actual text/image/audio/video feature and output manifests, scene/time/entity validators, real AV sync and third-party human outcome checks |
| Joint conditional covariance | Conditional paired returns, known **joint** propensities, ESS, shrinkage, Jacobi eigenpairs, low-rank + diagonal residual, condition/eigen checks, conservative unsupported fallback | Real joint rollout collection, calibration under selection/interference, out-of-time covariance drift tests, measured low-rank approximation loss |
| Control compute benefit | A0–A5 measure **actual Python controller wall-time**, synthetic action costs and a proxy for total latency separately | Actual GPU Decoder wall-time, peak RSS, energy, p95/p99 with identical device/batch/task/quality; controller overhead must be lower than savings |
| Stable learning | Frozen critic digest, bounded KL trust region, next-generation-only proposal, future lower-vs-baseline upper confidence bound, retention check | Independent evaluator certificate, real trainable heads and rollback, multiple future windows, negative transfer, policy-deployment receipts |
| Global-to-local credit | Exact Shapley decomposition for fully observed counterfactual coalitions; missing subsets fail closed | Real matched counterfactual support, interference-aware causal credit/propensity, whole-Circuit NDU improvement and conservation receipts |
| Compressed-state sufficiency | Train-versus-future conditional next-state prediction with/without history | Statistical confidence/perturbation closure tests on real trajectories, state-enrichment/adaptation, no unsupported Markov/HJB claim |

**Never** replace the existing NDU objective, legal action constraints or observer; never sum already cost-adjusted NDU and the same resource cost a second time. A policy recommendation does not execute an effect or authorize promotion. The reference has no external I/O except its synthetic CLI output.

## Fixed ablation table

| Arm | Baseline/control | Status |
|---|---|---|
| A0 | Frozen single-decoder/no-change | Toy oracle executed; real Decoder absent |
| A1 | Fixed routing and budget | Toy oracle executed; real Decoder absent |
| A2 | Ordinary Top-k router (frozen heuristic stand-in) | Toy stand-in executed; learned MoE not trained |
| A3 | Frozen one-step NDU advantage | Toy expected-utility stand-in executed |
| A4 | Conditional covariance Merton-style risk portfolio | Tested small-profile optimizer; no real joint rollouts |
| A5 | Finite-horizon recursive routing, verification, stopping | Toy recursion executed; **not** stochastic FBSDE or full generated outputs |

The synthetic generator has the **same 256 future episodes for every arm**, a separate 256-episode training split and a frozen synthetic cost coefficient, and never supplies held-out outcome labels to the policies. Its full-information oracle is intentionally synthetic and cannot identify causal effects for real observational data. A2 is an explicit fixed heuristic stand-in: do not label it a trained MoE benchmark.

## Required production closure order

1. Bind immutable model/encoder/decoder versions, objective, legal set and independent observers; freeze exactly matched real text+image task datasets and train/future/retention splits.
2. Get real A0/A1/A2 paired baseline evidence at equal hardware/data/train budget; record actual time, FLOPs, RSS, GPU/energy, quality and refusal/OOD.
3. Run A3 with independently observed external NDU and a frozen critic. Reject self-rating and unknown propensities.
4. Run A4 with paired joint rollouts, conditional ESS, well-conditioned covariance, low-rank approximation residual and deterministic fallback. Cache by exact profile/generation; evaluate controller overhead end-to-end.
5. Run A5 with bounded-duration Circuit controls, real decoder and continuation state, independently evaluated recursive utility and verified optimal stopping (not an assumed HJB solution).
6. Perform state-sufficiency history ablation, real semantic/time/cycle metrics, complete/global causal credit checks, retention and future-window confidence tests; only the existing Hepta independent authority/evidence plane may adopt a later snapshot.

**Exit condition for marking all blockers closed:** real typed Decoder outputs and admission receipts; artifact digests and current revocation; independent external labels; supported covariance + calibration; matched A0–A5 real hardware evaluation; controller savings or validated quality-cost Pareto improvement; future utility candidate LCB > frozen baseline UCB with retention and safety gates; full Rust CI and fault-replay tests; signed independent evaluator and next-generation promotion receipt. Until all are present, this is `SHADOW_REFERENCE_PASS / PRODUCT_BLOCKED`.

Research comparison context: Zhang et al., *R-C2* (CVPR 2026), https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_R-C2_Cycle-Consistent_Reinforcement_Learning_Improves_Multimodal_Reasoning_CVPR_2026_paper.html ; Cao et al., *T2AV-Compass* (ICML 2026), https://proceedings.mlr.press/v306/cao26v.html . These works motivate consistency testing; neither independently validates NDU-DMGP.
