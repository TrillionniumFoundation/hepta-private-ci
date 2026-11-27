# R17 actual results — rigorous nonproduct symmetry and solver failures

The complete positive-entropic-risk two-step mathematical certificate proves an exact global optimum set `a=b=±sqrt(t*)`, product in `(0.69620266886932,0.69620266886935)`, with candidate `a=b=0.834387601099952`. The 10^65 outward rational gradient interval gives global parameter-component error `<8.352e-16`, population objective excess `<3.934e-31`, one-weight b=0 excess `>0.3926055`, nonzero-risk shift from the risk-neutral optimum `>0.00484464`, and strict negative-curvature saddle at origin. The nonproduct forward offset is `(a-b)^2/4` and costs vary even for fixed `ab`; the theorem relies on the *distinct* input symmetry and entropic convexity.

All **64/64 actual child fits** completed, zero fit execution failures. Exact paired fixed starts, CPU cap .75 seconds each. Verified outcome counts by solver (denominator 8 each):

| Solver | Nonproduct certified-set accuracy | Product-only ablation |
| --- | ---: | ---: |
| Adam | **0/8** | **1/8** |
| BFGS | 5/8 | 5/8 |
| L-BFGS-B | 5/8 | 5/8 |
| trust-exact | 7/8 | 7/8 |

A numeric solver at a stationary origin returns success yet the exact Hessian has negative eigenvalue; other adverse opposite-sign starts also fail. Under this short CPU cap Adam fails all new nonproduct cases despite several having nearly correct costs, because the fixed **parameter-distance** criterion of 1e-6 was not reached. No seed/optimizer or checkpoint was selected post hoc. This refutes an effortless NDU/curvature general superiority claim for this implementation.

The audit verified all **3,820 checkpoint values**, with cost replay maximum **0.0**, and independent pure-Python complete stochastic-leaf scorer agrees with the primary evaluator within `3.3306690738754696e-16`. Same eight initial vectors were confirmed bit-identical across both architectures and all four solvers. Exact same risk law and training setup within paired comparisons. All 64 candidate transfer panels include switched noise, biased input, and product-only variant; none becomes a certified new distribution just by evaluation.

**Regression/tamper:** 18 new tests pass, 7 actual-artifact adversarial tests under python -O pass, and unmodified R16 math 14/14, R15 math 25/25, R14 certified 20/20 and R13 certified 15/15 regressions pass when separately invoked. These constitute **99 distinct** current-and-historical test cases (18+7+14+25+20+15=99); separate development reruns are not extra tests. Unsupported initial launch and the two development audit errors remain as logs, none altered fitted weights or outcomes.

Whole sweep `83.26265331399918` wall / `81.552002` child CPU seconds, including imports/startup; independent audit around 6.584 CPU seconds. Fitting CPU across all 64 cases and peak RSS are listed individually; CPU timing is not hardware-attested, and preliminary/publishing/tests/package cost is additional. No GPU, energy, complete FLOPs or full physical TCO claim.

This is a restricted two-parameter symmetry-supported nonconvex proof, NOT a general multistep nonlinear FBSDE or LLM/world-model-training performance theorem. No main merge, production gating or native contract change. Exact-source PR-specific hosted CI is separate, and may be queued/unverified when read.
