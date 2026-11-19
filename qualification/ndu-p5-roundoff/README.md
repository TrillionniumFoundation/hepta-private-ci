# P5: independent outward-rounded full-tree action-gap replay

**RESEARCH / SHADOW / DENY_ALL.** Stacked on PR #2034. No modification of the selected
Neuron/Encoder, shared Critic, NDU Q32, model runner, grant, FinalUse, or release.
Does not touch the queued real pretrained Stem experiments on PR #1923.

## What is new

The predecessor's **nominal** FP64 intervals already chose one of three actions
(or abstention) for each of 192 registered synthetic binary-tree fully coupled
FBSDE tasks. This second independent implementation re-evaluates the *same
presealed Y vectors and controls*. It does not train, reselect, or change the
source/terminal objective. It uses exact IEEE binary64 input values as rationals
and 112-bit integer fixed-point intervals with outward floor/ceil for each
addition, multiplication, division, and square root. `tanh` is enclosed via
`(e^(2x)-1)/(e^(2x)+1)`, a positive 96-term Taylor sum for `exp(2x)`, and
an upper geometric tail bounded by `term_(N+1)/(1 - 2x/(N+2))`. The series
uses only nonnegative coefficients for `x>=0`; oddness handles `x<0`.

For the **registered discrete law only**:

```
X(child)=X(parent) + a*(T/K)*Y(parent) + sigma*sqrt(T/K)*eps
Y(parent)=(E[Ychildren]+(T/K)*beta*tanh(Xparent))/(1+(T/K)*lam)
Yterminal=tanh(Xterminal),  eps in {-1,+1} equiprobable
```

The independent backward operator is enclosed node-by-node for the same
complete public-information tree. This profile has a sufficient maximum-norm
contraction constant `q = a*T*(1+beta*T)` from the 1-Lipschitz `tanh`, a
nonnegative discount denominator, and the forward path difference bound
`max|delta X| <= a*T*max|delta Y|`. All 192 frozen profiles satisfy `q<0.95`.
For a candidate exact-float vector y, compute the outward residual upper bound
`R >= ||y-F(y)||_infinity` and thus the *discrete* fixed-point error bound
`||y-y*||_infinity <= R/(1-q)`. The root utility interval for each fixed control
is `[y0-cost-radius,y0-cost+radius]`. Abstain is a zero-value action. A winner
is admitted only if its lower bound strictly exceeds every competitor's upper
bound. Zero gap, invalid model domain, unknown input, exhausted work, or a
missing choice never create a certificate. The audit replays reported Picard
work against the existing independent prefix-indexed reference **for accounting
only**; it never imports the predecessor's solver operator for numerical bounds.

The above is an implementable analytic argument plus integer interval code, **not
mechanically verified software**. The action statement is conditional on the
registered discrete model, exact interpretation of supplied IEEE binary64
coefficients, input authenticity, and correctness of this auditable reference.
It is **not** a proof for the true continuous-time stochastic FBSDE, general
state/utility laws, a Markov abstraction, source legitimacy, multimodal reasoning,
or safe deployment. No label or future outcome is an inference feature.

## Actually executed: 2026-10-14 local host

The original #2034 plan/predictions/independent score were byte-pinned and
replayed, then a **new fresh plan -> prediction seal -> independent score ->
outward-rounded audit** was completed without retrospective model selection.

| Complete 192-case comparison | Result |
|---|---:|
| Original nominal decisions | 192/192 |
| Independently outward-rounded admissible decisions | **192/192** |
| Original adaptive Picard calls | 1,511 |
| Uniform full-precision Picard calls | 6,119 |
| Minimum rigorous positive action gap | ~0.00001974539 |
| Original online adaptive CPU (earlier completed source) | ~35.36 ms |
| Uniform Picard reference CPU (earlier completed source) | ~137.31 ms |
| **Full independent integer interval audit CPU (fresh local run)** | **~3,449.48 ms** |

The expensive mathematical audit is **~25.1x the full Picard reference cost** on
this local process/host comparison (not same-process paired end-to-end online
telemetry). Therefore there is **NO cost-adjusted online improvement claim** from
adding this strict certification to each decision. Initially use it as a slow
independent qualification/audit path. No language, actual Stem, Reader, natural
future outcomes, energy, GPU, signed host or cell learning were executed here.
The existing cheap exact single-branch/noncoupled BSDE controls remain valid
and are not replaced by a full FBSDE when algebra suffices.

## Reproduce on exact stacked source

```
python -m pip install mpmath==1.3.0
python -m unittest discover -s qualification/ndu-p5-roundoff -p 'test_roundoff.py' -v
python -O -m unittest discover -s qualification/ndu-p5-roundoff -p 'test_roundoff.py' -v
mkdir -p /tmp/ndu-p5
python qualification/ndu-p5-decision-cert/study.py plan --output /tmp/ndu-p5/plan.json
PLAN_SHA=$(sha256sum /tmp/ndu-p5/plan.json | cut -d' ' -f1)
python qualification/ndu-p5-decision-cert/study.py predict --source /tmp/ndu-p5/plan.json --source-sha256 "$PLAN_SHA" --output /tmp/ndu-p5/sealed.json
SEAL_SHA=$(sha256sum /tmp/ndu-p5/sealed.json | cut -d' ' -f1)
python qualification/ndu-p5-decision-cert/independent_score.py --source /tmp/ndu-p5/plan.json --source-sha256 "$PLAN_SHA" --sealed /tmp/ndu-p5/sealed.json --sealed-sha256 "$SEAL_SHA" --output /tmp/ndu-p5/score.json
SCORE_SHA=$(sha256sum /tmp/ndu-p5/score.json | cut -d' ' -f1)
python qualification/ndu-p5-roundoff/audit.py --source /tmp/ndu-p5/plan.json --source-sha256 "$PLAN_SHA" --sealed /tmp/ndu-p5/sealed.json --sealed-sha256 "$SEAL_SHA" --independent-score /tmp/ndu-p5/score.json --independent-score-sha256 "$SCORE_SHA" --output /tmp/ndu-p5/roundoff.json
```

The workflow implements these commands with create-only outputs and exact source
hashes and uploads logs/complete original and independent research observations
**even if a job fails**. Source and new report never confer authority:
`p5_accepted=false`, `production_accepted=false`, `authority=DENY_ALL`.

Related original research: PR #1550 (local/global obstruction), PR #2003
(registered discrete coupled reference), PR #2034 (nominal early stop),
PR #2014 (real mmBERT finite BSDE negative control). Preserve independent
observer and existing blocking-ci; do not auto-merge production.
