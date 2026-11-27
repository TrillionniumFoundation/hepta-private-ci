# R21 observed completion: forward weight-width scaling vs strict global certification

**Executed 120/120 fresh-process fits, zero execution failures; 120/120 changed real parameters.** Three widths (2,3,4 actual forward weights), eight identical shared initial (a,b) pairs with zeros for new coordinates, five solvers (Adam, BFGS, L-BFGS-B, analytic trust-exact, ordinary Torch-AD trust-exact); exact same 16-leaf two-step positive-risk law, terminal target and budget. For each width/seed all five methods start byte-identically.

**Pre-sweep protocol** committed at `14dbf7ffdbfac43c81dfe355f644e8b11f383266`; a logical-clarification protocol amendment `42547d4b16d0ea8c77dbdcc0108fcf5f3f289508` preceded efficacy. The original experiment core was locally frozen/tested after the protocol and before the 120 fits; exact local source hashes are included in the ZIP. Report both positive and negative certification results without posthoc expansion of node cap.

## Exact 4,000-split B&B global gap (for predeclared literal candidate)

| Width | B&B splits | Frontier boxes | Certified regret upper | <=.01 passed | B&B CPU s | Peak process RSS MB |
|---|---:|---:|---:|---|---:|---:|
| 2 | 2985 | 2043 | 0.00999390815022509 | YES | 4.066514 | 105.93 |
| 3 | 4000 | 3464 | 0.04560924840912149 | NO, capped | 5.636393 | 111.04 |
| 4 | 4000 | 3574 | 0.13207665196851925 | NO, capped | 5.079759 | 108.01 |

No gradient, Hessian or convex auxiliary function is used in the bound. Every rational split/frontier record was independently replayed, with identical exact gap. The proof is a conservative *global cost-bound*, not unique-optimum or parameter-recovery certification.

## Actual observed fit results (held fixed after training)

The best FLOAT observed terminal cost by width is 1.0787374795931406 for W2, 0.6518667565496341 for W3 and 0.6273240992459004 for W4; thus larger forward families genuinely lower observed cost on the SAME law. These are optimizer endpoints, NOT proven global optima. At W3 and W4 some solver endpoints are BETTER than the preregistered rational pilot candidates; the pilot is not described as the actual global optimum.

Audit each float64 final candidate as an EXACT dyadic rational using the same rational cost bounds. With the same fixed frozen global lower per width, certified <=.01 endpoints are 20/40 for W2 and 0/40 for W3 and W4; best W3 and W4 certified gaps are still about .03047556 and .12593658. Zero W3/W4 certifications is a bound tightness issue, not a declaration of scientifically failed optimization.

| Width | Adam | BFGS | L-BFGS-B | Analytic trust-exact | Ordinary-AD trust-exact |
|---|---:|---:|---:|---:|---:|
| W2 | 3/8 | 3/8 | 4/8 | 5/8 | 5/8 |
| W3 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| W4 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |

Analytic and ordinary-AD trust-exact have matched W2 certification counts and nearly identical W3/W4 endpoint costs, so no unique analytic/NDU solver superiority is established. W2 results are on the R20 signed architecture with the same law, but execution time/count comparisons across different sessions are not treated as hardware-controlled comparisons.

## Full independent verification and resource accounting

Eighteen new unit tests (multiple widths, state/leaf law, forward analytical first/second derivatives vs Torch AD and finite differences, exact cost intervals and split geometry), 8 actual-artifact tamper tests with python -O, 20 unchanged R20 tests, 18 unchanged R19 tests and 25 unchanged R18 tests: **89 distinct checks, zero skips**, ignoring initial mistaken test command that failed before the 18 tests and was fixed without changing the model.

Read-only audit independently verified the COMPLETE 120-case source and sealed plan hashes, initial/final tensors, all 5,979 optimizer checkpoints and 19,200 saved finite-tree scalar entries; exact original-cost replay errors and independent branch-array errors are zero. The separate B&B audit recomputed all three whole proof trees and their frontier SHA256 and exact rational regret. Eight malicious edits (missing runs, forged rehashed cost/oracle, changed tensors, leaves/checkpoints, mutated source and altered B&B frontier) were rejected.

Whole 120-case sweep **277.351759464 wall / 274.291355 child CPU seconds**, which includes Python/torch imports and per-process startup and serialization. Fitting CPU inside child **29.570819361 seconds** is part of that total. Independent audit **26.949566189 CPU**; B&B proof builds **14.782667 s CPU**, 8 tamper tests **16.314 seconds wall**, legacy tests and packaging additional. Fit-process peak RSS at most **294.785024 MB** (includes Python/torch allocator); certificate process peak varies around 106–111 MB. Complete physical FLOPs, energy, GPU not available.

This is assistant CPU source-slice research, not original project cloud/native Neuron hardware, full Rust/Bazel suite or end-to-end LLM experiment. No main merge, history rewrite, CURRENT/model/production authority change. Hosted current-head CI is not deemed successful unless separately observed.
