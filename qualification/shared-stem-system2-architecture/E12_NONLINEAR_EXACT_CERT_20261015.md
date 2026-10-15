# E12: finite nonlinear stochastic FBSDE with a global rational error bound

**2026-10-15 -- research only, DRAFT, DENY_ALL.** This work is stacked on
E11 [#2134](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2134),
which inherits the E9/E10 real Granite/mmBERT **NO_GO** and E6/E8 shadow
contracts. Nothing here selects a model, alters Neuron or NDU production code,
Q24/Q32 transport, objective, original evidence owner, revocations, blocking
CI, checkpoint, or signed FinalUse.

## Why it is a genuine next mathematical experiment

E11 studied a random **affine** forward-backward law. The cheap exact affine
solution was already as good as the dense whole-tree solve, so E11 established
no incremental capability or cost-adjusted gain. E12 replaces the affine
coefficient with a globally bounded nonlinear rational response:

```text
phi(v) = v / (1+v*v)
X_(k+1) = X_k + a*h*phi(Y_k) + sigma*m_(k+1)
(1+lambda*h)*Y_k = E[Y_(k+1) | public F_k] + beta*h*phi(X_k)
Y_T = g*phi(X_T)
m_(k+1) = +/- s, equal conditional probability, s>0, sigma>0
```

This is nonzero-noise, forward-backward **coupled** when `a>0`, **nonlinear**,
finite, discrete and exactly representable as rational arithmetic. Time is
event horizon, not Transformer depth. One unique public-prefix X/Y/Z is
required per tree node. It is not a continuous Brownian FBSDE theorem,
neural coefficient fit or emergent language reasoning result.

### Mathematical basis and admission region

For real v, `|phi(v)| <= 1/2` and `|phi'(v)| <= 1`, including outside the
registered data region. For a fixed internal Y proposal with sup-norm
difference D, the induced forward-state difference at any node is bounded
by `a*T*D`. The terminal Y difference is bounded by `g*a*T*D` and the
recursive backward generator adds at most `beta*T*a*T*D`; dividing by
`1+lambda*h >= 1` does not enlarge it. Hence the complete nonlinear
whole-tree map `F` obeys the conservative global Lipschitz bound

    q = a*T*(g+beta*T).

Our six registered profiles use depth `{1,2,3}` and coupling `{0,1/3}`
with fixed `T=3/4`, `g=1/2`, `beta=1/4`, `lambda=1/5`, `sigma=1/3`,
`driver_scale=1/2`, `X0=1`. More generally only bounded profiles with
`q < 3/4` are admitted. The output map lies within
`[-(g+beta*T)/2, (g+beta*T)/2]` on each internal Y coordinate. In the
registered full-tree finite-dimensional space, Banach's fixed-point theorem
gives a unique *discrete model solution*, with the exact valid bound

    ||Y - Y_star||_inf <= ||Y - F(Y)||_inf / (1-q).

This bound is re-computed from exact rationals, not inferred from floating
residuals, test counts, a local leaf condition or self-issued proof flags.
Sixteen-bit fixed-point rounding is used only between iteration steps;
the independent reviewer recomputes the **true unrounded rational operator**
at the last state and independently checks the resulting global bound.
Non-convergence or a mismatched public tree must reject; it cannot return
an approximate "success" based only on terminal values.

### Independent exact source review

The executor stores full forward X states, internal and terminal Y,
conditional Z and the original cost/time counters. The standalone reviewer
uses a DIFFERENT prefix-dictionary algorithm and a different rational
implementation of `phi`: `n*d/(n*n+d*d)`. It checks every branch and leaf,
initial/forward/backward/terminal equations, `Z*Sigma=B` (here `Sigma=s*s`),
zero orthogonal martingale residual for this two-support complete driver,
all prefix bindings, the same registered contraction and exact full-map
error radius. It **replays every fixed-point iteration from zero** with an
independently coded ties-to-even quantizer; altered iterations, simulated
CPU flags, residuals or source bytes are rejected.

Source SHA256 sealed BEFORE a separate independent review process. A digest
is not an original-source authenticator or hardware signature. The recorded
CPU/wall nanoseconds are real observations on the assistant test container,
**not** the user's dot host, production fleet, independent metering, or GPU.
The independent reviewer verifies the cost-record shape and identity, not
that a malicious executor's timer was externally attested.

### Six actual local execution outcomes (six repetitions per arm)

| Depth | Coupling a | Single-map CPU median | Certified-solver CPU median | Full map calls | Single map sufficient? |
|---:|---:|---:|---:|---:|---|
| 1 | 0 | 0.067 ms | 0.312 ms | 2 | Yes: direct exact when a=0 |
| 1 | 1/3 | 0.103 ms | 0.355 ms | 3 | No |
| 2 | 0 | 0.097 ms | 0.375 ms | 2 | Yes: direct exact when a=0 |
| 2 | 1/3 | 0.124 ms | 0.582 ms | 3 | No |
| 3 | 0 | 0.184 ms | 0.596 ms | 2 | Yes: direct exact when a=0 |
| 3 | 1/3 | 0.171 ms | 1.694 ms | 4 | No |

The one-pass baseline measures only **one operator invocation** and does
not include the independent verification expense. Its exact mathematical
qualifiability is established separately. The certified arm includes
repeated complete-map evaluation and trace creation; both reported time
series are measured but hardware conditions are not matched/attested.
Since a=0 makes F independent of Y, a single direct backward map gives
the exact solution. It should **not** be replaced with a needlessly
expensive general solver. For a>0, one map did not reach the registered
`1/10000` finite-tree error requirement, so the costlier solve was necessary
*for that numerical requirement only*. No language-task gain or positive
System2 action-utility margin was observed.

This is a mathematical negative-control/proof-of-correctness study, not
natural-task quality; time/energy ratios MUST NOT be extrapolated to a
real 97M Encoder, 421M control, Reader, training or multi-modal system.

## Current reproducibility

```sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
python -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
mkdir -p /tmp/hepta-e12
python "$ROOT/e12_study.py" execute --output /tmp/hepta-e12/sealed.json
SHA=$(sha256sum /tmp/hepta-e12/sealed.json | cut -d' ' -f1)
python "$ROOT/e12_study.py" audit --source /tmp/hepta-e12/sealed.json \
  --sha256 "$SHA" --output /tmp/hepta-e12/independent.json
```

Local execution and optimized mode each passed 26 unittest cases in this
candidate. Newly committed GitHub Actions must independently run on exact
source HEAD and synthetic merge; do not inherit an earlier workflow green.

### Hard remaining blockers

Original independently authenticated source and outcome; sufficiency-tested
Reader and real multimodal/code/memory tasks on future observation-time
windows; equal actual cost 97M vs shared421 vs independent421, and inexpensive
Bellman/direct BSDE/Critic and real worker alternatives; learned coefficient
identifiability, filtration and model uncertainty, negative transfer,
source-controlled old-task retention; nonlinear continuous stochastic FBSDE
well-posedness and discretization-error proof; original signed FinalUse,
CAS/revocation, three genuine generations and passing source+merge
blocking/architecture CI. Neither E10's AG News NO_GO nor E11's simple-
linear negative is waived by this synthetic nonlinear result.

**production_accepted=false; model_selected=false; online_gain=false;
continuous_time_fbsde_proven=false; natural_reasoning_gain=false;
authority=DENY_ALL.**
