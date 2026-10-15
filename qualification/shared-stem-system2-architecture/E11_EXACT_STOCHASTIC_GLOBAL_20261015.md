# E11 — exact stochastic whole-tree FBSDE, cheap affine control, independent dense reference

2026-10-15. **DRAFT / SHADOW / DENY_ALL.** Child of #2121 → #2101 → #2082.
No selected model, original Worker, NDU owner, Q24/Q32 wire, signed FinalUse,
blocking CI or production effect changes.

## Registered finite random law

For K=1..3, h=T/K, public prefix filtration F_k and equiprobable, independent
epsilon in {-1,+1}, m=s*epsilon:

    X_(k+1) = X_k + a*h*Y_k + sigma*m_(k+1)
    (1+lambda*h)*Y_k = E[Y_(k+1) | F_k] + beta*h*X_k
    Y_T = g*X_T

This law is **genuinely random** (sigma>0) and **coupled** (a>0 cases),
but is **linear, discrete, finite and fully registered**: it is not a
continuous Brownian/neural FBSDE theorem or natural language reasoning.

The admitted exact decoupling field is

    A_K = g
    A_k = (A_(k+1)+beta*h) / (1+lambda*h-a*h*A_(k+1))
    Y_k = A_k X_k

All backward denominators must be strictly positive in the *same global
region*; local segments and a final leaf alone never qualify. The full-tree
verifier checks the original initial X, both forward successors at each
public prefix, one adapted Y and Z per prefix, conditional backward
expectation, global field consistency, every terminal leaf and exact
centered conditional covariance Z*Sigma=B. It independently checks the
pointwise martingale representation in each sign. A 3-support explicit
negative control gives covariance 2/3 and Z=0 but orthogonal residual
(1/3, -2/3, 1/3): full-rank covariance by itself is not completeness.
The **original inherited #1923 conditional_moments.py** is called as a
second mathematical oracle on every new binary prefix. Zero residual
means this registered discrete law only, NEVER unrestricted existence
or identifiability.

## Equal-function controls and paid execution

1. An O(K) exact affine recursion returns the **root Y only**.
2. The same affine field can enumerate the entire public-prefix trace.
3. An entirely separate exact rational Gauss-Jordan implementation
   simultaneously solves 2*(2^(K+1)-1) unknown X/Y values by assembling
   original initial, two forward, backward expectation and all leaf
   terminal equations. It imports neither affine_trace, gains, nor
   the verifier. Both algorithms must agree bit-exactly, not merely in
   a tolerant floating residual.

The research executor runs 6 preregistered depth×coupling profiles with
6 real Python invocations per algorithm/profile, records raw actual
CPU and wall clock samples and counts complete equation/elimination
work. Its output is create-only. A separate independent re-audit
process recomputes all original mathematical results and rejects fake
roots, incomplete work, changed profiles, missing/bogus times, forged
source hashes and a non-DENY_ALL promotion. CPU values are self-reported
*local Python exact arithmetic* and are not independently authenticated
production hardware, energy, real Encoder, Reader, Decoder, or network costs.

The independent audit may additionally bind the existing unchanged
**E10 negative** receipt: on a single historical AG News family, all
4-fold crossfit policies selected Granite-only and all 4 preregistered
other fixed model routes were retrospectively Pareto dominated. That
NO-GO cannot be silently overwritten with positive synthetic math.

Crucially, a cheap root recursion computes the **same exact root value**
for this registered linear stochastic problem: extra full-tree FBSDE
effort is not a demonstrated *semantic* or *cost-adjusted* gain.
If the task requires a full tree, use the cheap full-tree arm rather
than unfairly comparing only the cheap root vs the dense whole tree.

## Reproduce in this branch

    ROOT=qualification/shared-stem-system2-architecture
    export PYTHONPATH="$ROOT"
    python -m unittest discover -s "$ROOT" -p 'test_e11_*.py' -v
    python -O -m unittest discover -s "$ROOT" -p 'test_e11_*.py' -v
    mkdir -p /tmp/hepta-e11
    python "$ROOT/e11_study.py" execute --output /tmp/hepta-e11/sealed-execute.json
    SHA=$(sha256sum /tmp/hepta-e11/sealed-execute.json | awk '{print $1}')
    python "$ROOT/e11_study.py" audit --input /tmp/hepta-e11/sealed-execute.json \
      --input-sha256 "$SHA" --output /tmp/hepta-e11/independent-review.json \
      --e10 "$ROOT/observations/E10_EXACT_PAIRED_PARETO_LOCAL_20261015.json"

Dedicated source-head CI separately executes normal and python -O tests,
the original #1923 covariance parity, actual mathematical runs,
create-only SHA sealing and the independent E10-linked audit. The
workflow must **actually succeed** before a green claim.

## Remaining gating evidence (cannot be self-issued)

Original authorized independent source, outcome and signed Worker receipt;
genuine time-forward and source-disjoint memory/code/multimodal task
success with sufficient independent Reader; matched real 421M/97M/second
Encoder, Cell/Graph/Decoder/training/certification cost and no-change/
cheap Bellman/BSDE/Critic controls; neural coefficient identification,
OOD, rollout and retention; qualified general nonlinear stochastic
FBSDE with justified filtration/driver, global stability, discretization
and error enclosure; 3 independent future generations, lifecycle
revocation, CAS, checkpoint/recovery, original FinalUse and blocking-ci.
No source-local test can waive these.

model_selected=false; continuous_stochastic_fbsde_certified=false;
natural_reasoning_gain=false; cost_adjusted_online_gain=false;
production_accepted=false; authority=DENY_ALL.
