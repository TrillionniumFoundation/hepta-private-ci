# HCSN P1 — semigroup-consistent generator research comparator

This is a **separate, unadopted numerical proposal** stacked from frozen HCSN
draft #5856 (`b908827abcf60b7ce22fe1b8b299206a31484550`). No historical
P0–P5 result or C2 checkpoint is updated by this experiment.

## Purpose

The archived finite-grid QPR map is a projection `Q P_dt R`, not an exact
semigroup. Repeating its tiny-gap projection forever can fail even when each
single step preserves mass. To investigate that structural failure, this
independent experiment builds a *fixed* active killed-diffusion generator
`A` with exponentially fitted, nonnegative neighbor rates, absorbing exit
on the left and an explicitly **reflecting artificial right boundary**.
Its finite-state substochastic evolution satisfies `exp(A s) exp(A t) =
exp(A (s+t))` in exact arithmetic and the discounted first-hit transform
is computed by the resolvent `(rho I - A)^(-1) k`.

This is **not** a full HCSN replacement: no returning exponential tail,
deterministic refractory delay, reset, probability observation update,
content memory, learned parameters, fixed-cost differentiable operator,
rare log-risk bound or endogenous free boundary. The right-edge reflection
has its own measurable truncation bias. A CTMC generator with a fixed
reflected boundary should **not** be claimed to be the true infinite-domain
Brownian semigroup.

## Actual local execution and reproducibility

From the repository root, with PyTorch available:

```sh
python -m unittest -v proposals.hcsn_semigroup_v1.test_semigroup_candidate
python -m proposals.hcsn_semigroup_v1.semigroup_candidate
```

The four tests were executed and passed in the assistant's isolated CPU
Python container (Python 3.13.5; torch 2.10.0+cpu), **not** on the original
heptaruntime native owner. Exact raw result: [LOCAL_PROBE.json](LOCAL_PROBE.json).

- Code SHA256: `e3362ef21bb9961726bc91ec8fcd454fe2f15b2fab0b753a8b89ef26c97220f6`
- Test SHA256: `35bba72a96edc34a18d48cac787b519aa1fe6de5b1bbce5c6487e8e37396adb6`
- The GitHub stored blobs were independently read back and matched the exact local
  `git hash-object` identities `2ba27880089b63f7c32684826b9ee25d9cc67c89`
  and `e22b3f46d097f56c0ab655f9c021f5adaff23c9f`.

At 128 cells, endpoint 4.8, sigma 0.35, discount 0.15 and five
drifts `-0.8,-0.12,0,0.12,0.8`, the largest **absolute** transform error
for midpoint starting distances `x<2` is `0.000425617`; the largest
whole-grid error is `0.004547347`. The 16-cell two-step matrix exponential
composition residual is `1.0403123e-11` for two `0.001` steps.

Independent local test of 256-cell interior refinement passes at
`<0.0002` absolute error across these five drift regimes. These are
selected fixed-parameter *Laplace transform* fixtures, not a uniform or
certified relative tail error bound; no source/model/posterior fitness is
implied. Far-edge errors can remain or grow at fixed endpoint.

## Correct next gates

1. Add an honest returning-tail and deterministic age/refractory extension,
   preserving positivity and exact semigroup/renewal semantics where claimed.
2. Prove and test differentiability through actual learnable
   `mu,sigma,b,x_r` and add 80-digit high-precision gradient/tail references.
3. On **separately trained** C2 final checkpoints, compare this candidate to
   original QPR on the *same recorded posteriors* and all original tiny-gap
   pressure cases without moving their thresholds or deleting failures.
4. Charge boundary quadrature, dense factorization, matrix exponential,
   source conversion, cache, memory, failed trials and all retraining costs.
5. Only after P1 and adequate P2 evidence should a candidate be considered
   for real asynchronous use, QVI boundary learning, or native adoption.

**Disposition:** research comparator only; P1 full-training, P2 scientific
benefit, P3 QVI mechanism, P4 multimodal and P5 hardware/adoption remain HOLD.
