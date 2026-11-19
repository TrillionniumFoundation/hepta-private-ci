# R14 completed: a certified, two-step, nonzero-risk, two-weight forward Stem

**Execution:** 15/15 fresh-process fits complete, zero execution failures; 20/20 new algebraic/independent high-precision tests and 6/6 adversarial real-file tamper tests pass. Audit recomputes 15 selected weights, 1,355 optimization checkpoints, all five matched method initializations and exact rational proof, with zero final-cost replay difference. All outcomes (including the strongest conventional control and the changed-law failure) are retained.

## Exact mathematical result — *finite five-atom X*, not continuous X

A unique globally optimal pair exists by \(\nabla^2J\succeq(117/160)I\) for the fully enumerated two-step entropic population. Fixed rational candidate

\[
(\widehat a,\widehat b)=(1.4790233104650800,-1.0033907548161366).
\]

The exact rational interval-enclosed gradient has upper L1 bound about **1.15640053e-16**. Hence the **rigorously certified** distance to the unique global optimum is at most **1.58140244e-16** and true full-population excess cost at most **9.14367306e-33**. Constraining the second forward coefficient to \(b=0\) incurs strictly **more than 0.36810869** in optimal cost, whatever the remaining real a. Nonzero risk changes the optimum relative to the exactly solved zero-risk full-law control: the a-shift is greater than **0.00100870939**.

The proof uses rational expectation of all 40 branches, outward dyadic interval operations, explicit exponential/log Taylor remainders, exact preference bookkeeping and global convexity. High-precision mpmath comparisons are separate diagnostics, not proof inputs. This certifies a fixed two-weight, parameter-affine nonlinear-in-X state recursion, not arbitrary multi-layer nonconvex NDU.

## Actual from-scratch optimizer controls

Five frozen initialization seeds: 11,23,47,59,83. All three methods receive the **same initial weights, full enumerated law, objective and nominal 3-second fit CPU cap**. The numerical optimum candidate is **not provided as a training target**; the strict rational candidate/radius is used only to stop the same-quality monitoring check.

| Method | Joint parameter-quality successes | Median first observed fit CPU | Range of first observed CPU | Mean accepted updates |
| --- | ---: | ---: | ---: | ---: |
| Adam | 5/5 | 1.386849 s | 1.106837–1.426537 s | 260.4 |
| Full backward-gradient Newton | 5/5 | 0.035169 s | 0.031725–0.037451 s | 3.0 |
| **L-BFGS-B** | **5/5** | **0.031331 s** | **0.028415–0.044504 s** | **4.6** |

This supports an efficiency gain of structure-aware full-law gradients over this Adam configuration but **does NOT establish an NDU-exclusive method advantage**, because strong generic L-BFGS-B reaches the same target just as quickly (and has a slightly smaller median). Times are real CPU measurements of the fitting/quality phase, not hardware-attested, exact-FLOP, energy or total process speeds. Whole fresh-process execution takes **27.075776 child CPU seconds**, much more than total optimizer-only work because imports, initialization and serialization are paid.

## Important contrary result: this strict certificate does not transfer to another law

Changing X from the five-atom law to the continuous uniform [-1,1] distribution while keeping everything else fixed gives a separate, uncertified floating numerical optimum near \((1.357064906118,-1.346789884846)\). Reusing the certified five-atom weights on that changed law incurs about **0.03788989** additional cost in the 48-point Gauss–Legendre diagnostic. Its continuum gradient norm is not zero. **The proved discrete-law parameter/cost error bounds cannot be used for this different law.**

## Verification, provenance and limitations

The exact signed/unsigned preference state switches, Bernoulli martingale coefficients and two-step cost/gradient/Hessian were independently checked. Read-only audit verifies every training identity, selected and initial SHA-256, each first-observed success time, full history, numerical objective/gradient/Hessian and proof output. Six real-file attack tests reject missing runs, changed weights, rehashed false costs/times, altered source plan and forged certificate even with Python `-O`.

This is assistant CPU/FP64 execution, not the user's cloud, native Neuron target or a full Rust/Bazel CI run. Only two forward parameters are learned; the stochastic plant and preferences are known, and the second step is affine in those parameters despite nonlinear dependence on X. It does not show deep general FBSDE/viscosity or LLM/world-model superiority. Energy, GPU and complete FLOPs are unmeasured.

No historical PR outcome or main, CURRENT, native contract, production model or operational acceptance is modified. This is research-only and remains Draft until exact-head hosted checks pass.