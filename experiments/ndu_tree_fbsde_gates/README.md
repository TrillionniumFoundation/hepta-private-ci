# Shared Stem / Cell / NDU Tree-FBSDE P0–P6 qualification

**RESEARCH ONLY; DENY_ALL.** Exact rational controls, not pretrained execution, certified global FBSDE existence, native Neuron integration, or production release. No mutation of Neuron V1 Q24, NDU Q32, selected artifacts or authority.

| Stage | Candidate | Required independent acceptance |
|---|---|---|
| P0 | Pinned Laya 421M / Granite 97M / mmBERT-small / EmbeddingGemma 2 | Same tasks, Reader, source groups, actual pretrained checkpoints and full work; no missing-model fallback |
| P1 | Shared Encoder, frozen/no-change/gated Heads | Actual 64/256/1024/4096 Cell runs with scope fences, physical forward counts, queue/p95/p99, resident and transient memory, CPU/GPU, energy if measured, and one physically shared Laya 421M control |
| P2 | Native multimodal vs separate frozen towers + fitted bridges | Source-disjoint visual/acoustic/temporal tasks, ablations, causal truth flips, independent labels, token/patch/frame detail and old-task retention |
| P3 | Shared System2 Critic and bounded OR/AND/CHANCE DAG | Same proposer/Reader/verifier; no-search, fixed-depth, plain search, learned-Critic arms, sealed external success and actual complete compute costs |
| P4 | Exact finite BSDE / global obstruction / regular coupled reference | No future-label access, two-sided state/value interfaces, global terminal condition, Z Sigma=B, decoupling-field domain, stable error-vs-mesh and cheap Bellman comparator |
| P5 | Qualified nonlinear NDU/FBSDE | External time-disjoint outcomes, actual cost-adjusted superiority, covariance-driver representation, independent risk and global regularity qualification |
| P6 | Distilled Cell/Organ Head candidate | Count teacher costs; future-task improvement and old-task retention, independently evaluated and rollback-safe |

Mandatory failure: **do not infer global solvability from zero local terminal residuals or correct final leaf**. The coupled deterministic boundary `dX=Ydt; dY=0; X0=x0; YT=gXT` satisfies `(1-gT)Y0=g*x0`. For `T=g=x0=1` there is **no global solution**, although local half-horizon resets produce Y=2 and Y=4 with zero local residuals and an interface jump of 2. For x0=0, same g,T, solutions are non-unique. For T=4/5,x0=g=1 there is a regular global solution Y=5. For T=3/2, algebraic uniqueness does not admit a globally regular decoupling field under this reference profile.

`belief_tree()` is an exact public-filtration two-bit finite decision problem, not a general FBSDE or artificial model benefit. A cheap Bellman/rational evaluator is a mandatory comparator. Real model weights, 4096 physical Cells, genuine multimodal outcomes, calibrated NDU and distillation were **not executed by this PR**. Eight local exact-rational unit tests passed. No production acceptance.

Run: `python3 -m unittest discover -s experiments/ndu_tree_fbsde_gates -p 'test_*.py' -v`

Reuse existing owners: `codex-rs/hepta-neuron`, `codex-rs/hepta-infer-core`, `codex-rs/hepta-ndu`, `docs/learning/NDU_FBSDE_SPEC.md`. PR #1550 is the upstream negative-control theory and experiment. PRs #1885/#1775/#1897/#1760 are distinct research candidates and cannot have their CI or efficacy inherited. Existing `blocking-ci`, FinalUse, provenance, rollback, Writer and independent Evaluator remain mandatory.
