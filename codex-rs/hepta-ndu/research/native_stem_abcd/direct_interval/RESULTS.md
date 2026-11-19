# R20: direct rational full-risk interval B&B with no strong-convex auxiliary

This is an exploratory R19 continuation; pilot and numerical scouting preceded the remote-frozen protocol at commit `402a0f29a04819755fd8c78c392b34c7cc651ab6`. In contrast with R19, the **proof uses the direct 16-branch entropic objective**, exact rational parameter-box enclosures and a global analytic lower/upper bound for `log cosh`, without a globally strong-convex auxiliary. The model adds an individually signed rational forward coupling to the already nonlinear two-step Stem.

## Frozen global cost certificates, each within max 50,000 splits

| Architecture | Exact candidate weights (a,b) | Actual splits | Active frontier boxes | Verified global cost regret upper |
| --- | --- | ---: | ---: | ---: |
| Signed new coupling | (1.54696889,0.44887401) | 2,985 | 2,043 | <0.010 |
| R19 control | (1.64044199,0.42331392) | 4,890 | 3,416 | <0.010 |

Original exact rational fractions and entire frontier inventories are in the accompanying evidence. These are **rigorous global cost upper bounds for the nominated candidates**, not precise regrets, a parameter-distance certificate or an exact global optimum. Every final frozen fitted endpoint was also independently assessed with exact rational interval upper costs against the common arm-specific global lower bound; no float-only success flags.

## Actual 80-process matched experiment

Five methods across eight initial tensors and two architectures, with 0.75 seconds fit-CPU cap each, all 80 fresh-process fits completed, no technical failures, and all 4,556 optimizer checkpoints retained. Success in the frozen strict 0.010 **global cost regret upper** rule (not gradient stationarity):

| Solver | Signed new coupling | R19 control |
| --- | ---: | ---: |
| Adam | 3/8 | 3/8 |
| BFGS | 3/8 | 3/8 |
| L-BFGS-B | 4/8 | 4/8 |
| Analytic trust-exact | **5/8** | 4/8 |
| Ordinary AD trust-exact | **5/8** | 4/8 |

Totals: **20/40 new,18/40 control;38/80** globally cost-qualified under this conservative certificate. Equal solution-set success counts for explicit and ordinary AD trust-exact in both arms do **not** imply a unique analytic NDU advantage. Several stable but suboptimal minima and CPU-budget-censored Adam cases are retained. The new and control architectures are different model classes even though the input law and target are the same; descriptive success counts are not a causal generalization guarantee.

**Source math and independent audit:** 20/20 new mathematical/gradient/AD/interval tests, 25 unchanged R18 tests, 18 unchanged R19 tests, 6 genuine optimized-Python artifact-tamper tests; **69 distinct checks, zero skips.** There was an invalid test runner invocation before any test execution; corrected and reran. A separate initial multi-tamper subprocess exceeded its outer shell time budget after tests 1–3 had passed; remaining tests 4–6 were rerun separately and passed. All original logs are retained; the two groups of real tamper checks form six distinct tests, no skipped failures. No fitting or outcomes were retried.

The independent read-only audit verifies all 80 original plans/source hashes, 16 five-way initial groups, all saved initial/final tensors, 4,556 checkpoints, leaves and reported cost/gradient/Hessian. Checkpoint replay max error is **0.0**; direct independent finite-tree cost error max **4.440892098500626e-16**. It independently recomputes both exact full-risk global certificates and matches retained frontiers. The six tamper tests reject missing cases, rehashed false weights, rehashed checkpoint costs, forged success claims, changed global certificate and altered initial weights.

**Resources:** whole sweep 183.337103248 wall and 180.845664 child CPU seconds, including fresh Python/PyTorch process imports. Fitting alone 17.702496724 CPU seconds, *within* whole-child CPU; independent audit 18.552882479 wall seconds including two repeat global-bound proofs. Tests/tamper, packaging and GitHub connector time are extra. Peak observed per-fit process RSS ~294 MB, including Python/Torch allocator. No full FLOP, energy or GPU metrics. This is assistant local CPU source-slice research, not project cloud or native Neuron hardware, Rust CI or production activation.

## Cautions and next causal test

The pure-rational risk enclosure is conservative: the first completed certificate gaps are close to .010, so some models with near-global floating final costs may remain **censored under the registered certificate gate**. A tighter future gate/proof could change the descriptive counts, but no rule was changed post-run here. Distinct local optima remain in full exposure; the results do not confer generic nonconvex NDU superiority or unrestricted multi-parameter global guarantees. Further work should improve bound tightness/complexity and test real dimensional growth, comparing *certified* total solve+proof cost against strong AD and quasi-Newton baselines.
