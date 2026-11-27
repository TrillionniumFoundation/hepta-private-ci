# HCSN P1 — contextual horizon rank repair is NOT independent risk information

2026-10-31. Strict **RESEARCH_ONLY / DENY_ALL / NO_GO**. Stacked on Draft #4527 exact HEAD `039c31aea3d0b359f602367b27d41662f8f75caf`, base #4517 HEAD `d29bfc22844d0ea202ab20aa9bf8eec51e6bf686`. Protected `main` observed `732e934ba496d90fbe042b8d41d479ef901643e5`. New namespace only. Historical #4517 P1 negative 192-run observations, #4527 rank-one result, financial/PDE equations, production and CI untouched.

## New mathematical result and negative finding

With fixed GBM `(r, payout, sigma)`, let `x=log(V/K)`, `s=log K`, `t=log T`, `b=K*beta/(beta+1)` and `m=log(V/b)`. The preexisting normalized channels `(Call/K,Put/K,m)` depend on `x` alone; their Jacobian in `(x,s,t)` has rank at most one. Adding an **observed** absolute scale `s` and observed finite first-hit probability `Q(T)` creates `(m,s,Q(T))`. For `m>0`, `sigma>0`, `0<T<infinity`, the Jacobian has determinant

`T * m / (sigma*sqrt(2*pi*T^3)) * exp(-(m+nu*T)^2/(2*sigma^2*T)) > 0`, where `nu=r-payout-sigma^2/2`.

This gives mathematical rank three on the stated open domain, NOT a uniform numerical conditioning theorem. It is **not** three independent stochastic states: `Q(T)` is strictly increasing in T because the derivative is the positive first-hit density, so on a non-saturated interval it is invertible and supplies no information beyond the ordinary baseline `(m,s,log T)`. The genuinely independent contextual risk variable and equal-parameter/equal-local-slope/equal-real-CPU causal comparison remain unimplemented and P1 stays OPEN. The original #4527 normalized rank-one blind spot persists unless absolute scale is explicitly retained.

## Executed and preserved evidence

- Local Python 3.13.5, Torch 2.10.0+cpu, SciPy 1.17.0: `python -m unittest -v experiments.hcsn_p1_contextual.test_contextual_rank` — **8/8 PASS, 0 skipped**, latest rerun ~0.064 s. Tests include 180 bounded structural rank cases, 100 independent Torch-autograd/closed-form first-hit-density time derivatives, four Jacobian/SVD/determinant cases, five ordinary-horizon inversions, common-mode scaling, STOP-region, saturated and invalid-domain refusals. These are not trained neural experiments.
- Deterministic 24-row observational raw panel: `python -m experiments.hcsn_p1_contextual.run_contextual_panel --output panel.json` — 24/24 present, **14/24 flagged numerically inadmissible** at a predeclared local `1e-8` scale/conditioning screen. This threshold is solely a numerical diagnostic, not a relaxed P1 scientific acceptance threshold; no efficacy conclusion is taken from accepted rows.
- Full raw newline-terminated JSON is committed as a gzip(mtime=0)+base64 file. Recover with `base64 -d < CONTEXTUAL_PANEL_20261031.json.gz.b64 | gzip -d > panel.json`. Full raw SHA256 `db488838c52897f25d350c6de8a5bff25899732b3764f33d4d4522b8da0ea835`; canonical no-newline payload SHA256 `27821c950fb169c5aa00cbab7727818948d792ee872b020e36742522d933eece`. Compressed raw SHA256 `c1a896703af17caf5009c3f5a7210c6f1414279548f59e080026b1e977115f6d`. Local raw restored and hash verified before publishing.
- The first locally authored test invocation failed due to Python relative-import discovery; an intermediate eight-test run had two failures caused by exact binary64 common-scale comparison and `exp(log(100))` representational overshoot. They were corrected *without changing any P1 quality threshold*: scaled values compare within `3e-15`, and the accepted `log T <= log(100)` representation snaps the exponential overshoot back to T=100. The final executed source/test match published Git blobs; no full-repo CI claim.

### Machine identities (source and tested bytes)

| File | SHA256 |
| --- | --- |
| `contextual_rank.py` | `5445c0c2cc19a038c15db75cff86b25b62d1fb6093f5623c61df6f6ab819081a` |
| `test_contextual_rank.py` | `3290bc9b950b073ae2027daca76f7638bf78737b916cfaf0404906110b3f6220` |
| `run_contextual_panel.py` | `b80cfdecce5454cf23fa202327384257ec68e7280d6acd90be98c6a15cf30e13` |
| `CONTEXTUAL_PANEL_20261031.json.gz.b64` | `2b7fe0c726ed6bbc613dea0d9fddc901d6312d72e97e2f5c370d0922153a01f8` |

## Seven-stage strict research ledger (new naming overrides historical numbering)

- **P0 OPEN**: actual original coupled HX financial kernel, simplified analytic kernel, regeneration QVI, whole-domain obstacle, interval/low precision/implicit gradients.
- **P1 OPEN**: independent contextual risk state and equal-parameter/signed-slope/total-resource causal Call/Put/Margin advantage. This PR only repairs conditional *coordinate* rank and proves absence of new information; #4517 and #4527 negative findings remain active.
- **P2 OPEN**: actually trained Selective Copy/MQAR/joint recall, irregular physical time, multiple FIRE, independent native crash recovery and OOD.
- **P3 OPEN**: actual text/speech/vision/video encoders (not synthetic proxy only).
- **P4 OPEN**: real temporal alignment, entity consistency, missing modality, cross-modal retrieval.
- **P5 OPEN**: fusion operators/CDF/sparse scheduling and measured actual CPU/GPU/Joules/RSS/p95/p99 for 64–4096 Cells.
- **P6 BLOCKED**: medium Encoder distillation/continued pretrain/long context and frozen equal-budget quality-cost frontier after all required precursors.

Old research-ledger P4 hardware maps to **new P5**; old P5 matched scaling maps to **new P6**; the new P4 multimodal fusion/alignment gate must not disappear.

`production_activation=false`, `all_scientific_blockers_closed=false`. Do not merge/deploy as production or claim scientific P1 utility benefit. Next candidate must have a genuine independently evolving risk variable, matched ordinary context inputs/signed slopes/parameters, frozen unseen tasks and actual process-CPU/GPU+energy costs with full raw paired evidence.
