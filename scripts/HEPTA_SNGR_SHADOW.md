# SNG-R: bounded FBSDE shooting and DAG backup (shadow research)

This is an **authority-free numerical research fixture**, not a production Hepta System 2, a trained Laya DecisionCell, a learned FBSDE, a validated multimodal model or evidence of longitudinal task improvement. It preserves the selected NDU evaluator, runtime, ownership, artifacts and production protocol boundaries unchanged.

## Mathematical domain

The fully coupled scalar manufactured example is

\[
dX_t = Y_t\,dt + \sigma\,dW_t,\qquad dY_t=Z_t\,dW_t,
\qquad X_0=x_0,\quad Y_T=aX_T+b.
\]

The affine decoupling field (on its **regular positive-denominator** domain) is

\[
Y_t=A(t)X_t+B(t),\quad
A(t)=\frac{a}{1-a(T-t)},\quad B(t)=\frac{b}{1-a(T-t)},
\quad Z_t=\sigma A(t).
\]

For a local slice of duration \(h\), a right-side affine continuation field \((a_+,b_+)\) induces the left-side field
\((a_-,b_-)=(a_+,b_+)/(1-a_+h)\). The correct multiple-shooting comparison backs up the *next* slice's continuation field; the deliberately incorrect baseline resets the original terminal field at every slice. The code rejects singular and crossed decoupling domains; it does not silently claim all pointwise two-point boundary problems are insoluble.

The stochastic fixture uses a **known analytic** \(Z_t\), pseudorandom Brownian increments and Euler state steps. This tests coordinate conventions and discretization residuals only; final terminal equality is manufactured and **does not prove the learned/numerical stochastic FBSDE solver converges**. No future terminal outcome is revealed to a live learned predictor because there is no live predictor.

The separate DAG backup is deliberately **finite, additive and deterministic**: controlled actions maximize supported `task_reward - compute_cost + continuation_value` while chance nodes use normalized probability-weighted expectation. This does **not** implement the general nonlinear NDU preference aggregator. It rejects illegal/unavailable actions, cycles, missing nodes, unnormalized probabilities and oversized graphs. Repeated descendants are memoized by exact node identity, not by unsafe embedding similarity; no external effects are permitted.

## Reproduce

From the repository root with Python 3.10+:

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr_shadow.py'
python3 scripts/hepta_sngr_shadow.py --demo
```

The demo emits labeled **synthetic analytic fixtures**, never real-model performance receipts. Expected main results in the two-slice example (\(x_0=1,T=1,a=1/2,b=0\)):

- Correct matching: \(U_0=1\), \(X_T=2\), interface/terminal residual near zero.
- Incorrect local resets: \(U_0=2/3\); terminal residual near zero **but** interface jump \(2/9\), so reject.
- Infeasible global BVP: \(x_0=0,T=1,a=1,b=1\) has individually regular short slices but no regular global decoupling solution.
- DAG reference: inspect action yields \(0.5\cdot5+0.5\cdot1-0.5=2.5\), rather than taking the maximum chance outcome.

## Integration criteria and explicit non-claims

1. Before Rust integration, independently verify numerical formulas, well-posedness assumptions, quantization, conditional covariance conventions and disagreement under larger/non-affine states. Match `docs/learning/NDU_FBSDE_SPEC.md`, including `Z Sigma = B` and the distinction between stochastic \(Z\) and parameter gradient.
2. Build a *separate* trained continuation-value/Z estimator; independently label observations; prevent future-outcome leakage and use immutable model versions. Evaluate held-out episodes and OOD calibration against an equal-budget deterministic Bellman/tree-search baseline.
3. Keep the shared frozen Stem/organ/cell parameter bundle in `inference.control` and `neuron.runtime`, with per-scope state isolation. Graph evaluation belongs to existing TaskFlow/Neural Circuit ownership; new structural changes require next-snapshot candidates and explicit qualification.
4. Prove or bound interface/global errors on the supported operating domain; measure real compute, throughput, latency, memory, failure/abstention and longitudinal external outcomes before capability claims.

These fixture tests establish only arithmetic correctness and selected failure semantics of this narrowly specified experimental algorithm.

## Next tranche: Rust affine reference and nonlinear-terminal comparison

The authority-free Rust shadow reference in `codex-rs/hepta-ndu/src/sngr_affine_shadow.rs`
implements the scalar affine characteristic using correct backward continuation
fields, forward shooting, independently checked terminal/interface/forward
residuals, and a deliberately incorrect terminal-reset negative control.
Its synthetic digest is not an independent outcome or selection receipt.
The regression suite also links the manufactured affine diffusion sensitivity
to the **existing** native centered covariance solver (`Z Sigma = B`),
including a rate-per-second covariance profile, without changing that solver.

The non-affine terminal fixture in `scripts/hepta_sngr_nonlinear_shadow.py` uses

```text
dX = U dt, dU = 0, U_T = slope*tanh(X_T) + intercept
V(t,x) = slope*tanh(x + (T-t)*V(t,x)) + intercept.
```

The entire horizon is restricted to `|slope|*T < 0.95`, so the explicit
Picard iteration is a contraction in the declared profile. Other cases
**fail closed rather than being declared unsolvable**. It counts each
`tanh` oracle evaluation and has a strict shared per-arm evaluation ceiling.
A segmented continuation arm, single-interval reference, and an intentionally
wrong terminal-reset arm use the same budget ceiling but report **actual**
oracle calls separately. They are *not* equal actual-compute arms.

Reproduction:

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr_shadow.py'
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr_nonlinear_shadow.py'
python3 scripts/hepta_sngr_nonlinear_shadow.py --demo
python3 scripts/hepta_sngr_nonlinear_shadow.py --sweep
cd codex-rs && just test --locked -p codex-hepta-ndu
```

On the author's Python environment the combined Python suite had 30 passing
tests, including 24 deterministic heterogeneous synthetic cases. This is
local source/fixture evidence, not a checked GitHub CI receipt, Rust build,
real Laya training, real task uplift, stochastic solver convergence or a
multimodal generation claim. An actual *equal work* Bellman vs NDU
comparison and held-out independent task outcomes remain open gates.

## Optional analytic-field learning pilot (PyTorch CPU)

`scripts/hepta_sngr_learned_shadow.py --demo` trains a 1,218-parameter
two-headed MLP on **1024 synthetic analytical labels** of the affine
continuation field `U(t,x)` and known analytic `Z(t)`, evaluated on 512
independently sampled inputs, with a simple fitted linear baseline and
explicit out-of-support measurements. Four local fixed-seed runs (17–20)
achieved held-out `U` MAE from approximately 0.0043 to 0.0071
and `Z` MAE from approximately 0.0010 to 0.0024. The synthetic labels
come from a known solution; they do not establish true BSDE learning.

PyTorch is an **optional** manual research dependency. The Python unittest
module `test_hepta_sngr_learned_shadow.py` checks preflight independent
of PyTorch and explicitly skips optional fitting if it is unavailable.
No PyTorch dependency was introduced into the Rust workspace or mandatory
runtime. Training CPU wall time, train/eval sample counts, parameter count
and explicit OOD rejection labels are reported; the linear comparator is not
matched for trainable parameter count, FLOPs or lifecycle cost.

```bash
python3 scripts/hepta_sngr_learned_shadow.py --demo
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr_learned_shadow.py'
```

Do not interpret this fixture's smaller supervised prediction error as
real System 2 reasoning gain, general FBSDE convergence or an equal-compute
advantage over traditional Bellman recursion.
