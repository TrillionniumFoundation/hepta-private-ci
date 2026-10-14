# Three controlled local-to-global FBSDE studies

Research extension to the existing Neuron Stem qualification directory, based on
`72c295742a39636ceb2c244a63a1ef3650efaa15` / PR #1526. No existing evaluator,
production owner, selected model, action authority or acceptance gate is replaced.
These runners produce evidence, not a second promotion/selection service.

## 1. An analytic boundary problem, not unrelated local objectives

The deterministic profile is `dX=Y dt`, `dY=-c X dt`, `X0=1`, `YT=g XT`.
For `r=sqrt(c)>0`, the exact flow on an interval of length h is
`F(h)=[[cos(rh),sin(rh)/r],[-r sin(rh),cos(rh)]]`. The exact initial slope is
`(g F11-F21)/(F22-g F12)`. With c=0 take its continuous limit.
The implementation uses an Euler matrix, NOT this analytic matrix, for its
monolithic and local numerical shooting solves. Backward transport of the
terminal slope supplies each earlier segment with the next segment's field.
Forward evaluation uses those interface conditions. Whole-segment shooting and
four-segment shooting therefore solve the same discrete boundary problem; the
independent analytic flow measures discretization error.

The wrong control resets every segment's terminal slope to g. Every local
terminal residual can be tiny and the final global terminal condition can hold,
while Y jumps at the interfaces. Both X and Y interface continuity are checked,
separately from local dynamics and terminal residuals. Endpoint agreement alone
never yields a pass. Tested meshes are 8,16,32,64,128,256,512.

For this positive scalar profile the first regular-field pole is
`Tcrit=(pi/2-atan(g/r))/r`, or `1/g` at c=0. Admission checks the global horizon,
positive denominator floor and maximum field slope BEFORE selecting a local
mesh. Near-pole failures remain failures at 16,256,4096 steps. Beyond this regular
field interval the profile reports unsupported; it does not falsely assert that
all possible nonregular boundary-value formulations have no solution.

A separate nonzero-diffusion test uses `dX=Ydt+0.3dW`, `dY=ZdW`, `YT=XT`, T=.6.
Writing q=1-T+t gives `Y=1/q0+sigma*integral(1/q dW)`, `X=qY`, `Z=sigma/q`.
Each finest interval samples the exact joint Gaussian law of dW and this weighted
integral, including its Brownian-bridge component. Coarse increments aggregate
the SAME noise. We report path-coupled terminal RMSE and the global BSDE defect
for the left-point stochastic-integral rule. This is a finite seeded numerical
experiment, not a universal strong-convergence proof.

### Exact counterexample to local-uniqueness → global-solution inference

\`fbsde_global_obstruction.py\` and \`test_fbsde_global_obstruction.py\`
use a separate exact-rational degenerate coupled boundary-value case:

\`\`\`text
dX_t = Y_t dt,  dY_t = 0,  X_0 = x0,  Y_T = g X_T
(1 - g T) Y_0 = g x0.
\`\`\`

Every short interval of width \`h\` with \`0 < g*h < 1\` has a uniquely
solvable local terminal-field problem. Yet with \`T=1, g=1, x0=1\`
the global boundary has **no solution**; with \`x0=0\` it has
**infinitely many** solutions. In the no-solution case, independently
resetting two half-interval fields yields \`(X,Y): (1,2)→(2,2)\`
and \`(2,4)→(4,4)\`: both local terminal residuals and the last
terminal residual are exactly **zero**, but the interface \`Y\` jump
is **2**. Thus good local residuals, a matching leaf and a final
boundary residual do **not** certify a global solution.

A regular \`T=4/5,g=1,x0=1\` case carries the SAME global terminal
decoupling field backwards: \`Y_0=5\`, and exact forward stitching
retains zero \`X\` and \`Y\` interface jumps. With \`T=3/2\`, the
algebraic boundary value is unique (\`Y_0=-2\`) yet the regular
decoupling field crosses a pole, so the registered global-field
admission remains **false**. These are different mathematical
dispositions and should not be conflated.

Reproduce under the existing \`fbsde_study.py\` dispatcher:

\`\`\`bash
PYTHONPATH=qualification/neuron-stem \
  python3 -m unittest -v test_fbsde_global_obstruction
PYTHONPATH=qualification/neuron-stem \
  python3 qualification/neuron-stem/fbsde_study.py \
    --profile global_obstruction_v1 --output /new/global-obstruction
\`\`\`

The new exact-mechanisms research CI lane retains the complete
\`report.json\` as raw study evidence. This is a deterministic
counterexample and admission check, **not** stochastic numerical
convergence, independently learned capability or production authorization.

## 2. Complete information-set policy enumeration and local BSDE sweep

The finite task asks for the conjunction of two hidden bits. Choices include
stop, submit true/false, and pay to observe either bit. Once both observations
are present the deterministic AND node requires both obligations; it is not an
OR or a choice among successful children. Conditional laws are exact rational
Bayesian updates of the public history. The policy sees only that history.

There are 5 root choices and 4 choices at each of four one-observation histories:
all `5*4^4=1280` legal deterministic policies are enumerated against all four
hidden worlds. Sixteen frozen prior/cost configurations give 20,480 complete
policy evaluations. The independent local sweep uses the registered one-step
BSDE `U=(1-p)U0+pU1-cost`, `Z=U1-U0`, `DeltaM=observed_bit-p`.
Every successor satisfies `Uchild=U+cost+Z*DeltaM`; exact rational residuals
are checked and the full policy value must equal exhaustive enumeration.

An injected policy selecting different root actions for different unrevealed
worlds is rejected by the common-history condition. Probability-max substitution,
missing AND obligations, malformed probabilities and repeated observations have
negative tests. Stopping is an actual legal action. Modeled acquisition costs
and measured solver CPU/wall costs have DIFFERENT fields and units. A realized
lucky path is never substituted for ex ante expected utility.

This is a discrete finite-state forward-belief/backward-utility SPECIAL CASE,
not a proof or implementation of a general continuous fully coupled FBSDE.

## 3. Real shared Encoder plus strong cheap controls

`fbsde_encoder.py` reuses `four_gate_pretrained.load_pinned` and the existing
publisher data loader. There is no random-weight fallback. It loads exact
mmBERT-small revision `abc32620dd4f6ab06f5fbe905dc25f310618e09f`, verifies physical
weight/config/tokenizer bytes and freezes the Encoder. Public CLINC150 intent
labels are fixed to the existing immutable publisher revision. The task uses
alarm/calendar/weather/time utterances, NOT gold domain supplied at inference.
All selected utterance splits are disjoint by original text digest; overlap
rejects the run rather than being silently removed.

Composite Boolean questions over those utterances are GENERATED, not human
reasoning annotations. Training/validation/calibration use 2-3 leaves, testing
uses held-out 4-leaf read-once formula structures. Text, target intent and syntax
are identical across arms. A common learned semantic Head is supervised only
on training utterances; EVERY root model receives its predicted probabilities
as well as the same frozen features, targets and formula syntax. No test intent
or Boolean truth is passed in the predictor's public input record.

Controls: light gated Head; shared recurrent network at depths 1/4/12; best fixed
depth from validation over 1/2/4/8/12; calibration-selected confidence stopping;
finite belief-tree BSDE; exact read-once probability algebra. The last control
receives the SAME predicted semantic probabilities, not gold leaf labels. In the
registered independent-leaf f=0 model it is algebraically equivalent to the BSDE.
Their outputs must agree; a lower solver residual cannot create extra information.
This can demonstrate a null incremental BSDE benefit rather than presupposing one.

All arms have the same available data, common Encoder and declared resource
ceilings. All real training/search/inference costs are retained. Actual costs
need not be equal: the result explicitly checks a 5% actual-cost condition and
never interprets a common cap as equal work. No dummy padding wastes cheap
controls' unused budget. Cost-adjusted superiority is not automatically granted.
Repeated simple-router retries charge all executed depths, not just the final
selected depth. Actual recurrent depth and deterministic scenario nodes differ.
The training/selection jobs are physically counted once; standalone cost views
include inherited common work once per hypothetical standalone arm, not in the
physical aggregate. Migration is not executed and energy/GPU are not measured.

The decoder is a SHARED deterministic two-sentence language grammar. All decoded
predictions are written create-only before the scorer reads test truths. Exact
sentence accuracy and probability Brier are both reported. Invalid language or
language contradicting the latent decision fails. This is not open-ended neural
language generation, proof checking or a claim about long-form answer quality.
Tasks reuse source utterances: 192 prompts are not 192 independent clusters.
Public pretraining contamination, true future generalization and Hepta production
no-change comparisons remain outside this controlled study.

## Reproduce

```sh
export PYTHONPATH=qualification/neuron-stem
python3 -m unittest discover -s qualification/neuron-stem -p 'test_*.py' -v
python3 qualification/neuron-stem/fbsde_study.py --output /new/exact-study
python3 -m unittest fbsde_tensor_checks -v
python3 qualification/neuron-stem/fbsde_encoder.py \
  --source-root "$PWD" --model-dir /approved/pinned-mmbert --output /new/real-study
```

The tensor suite's explicit fixture features test gradients, parameter sharing,
input isolation, train/select/infer/decode and accounting code; they are never
reported as pretrained execution. Hosted jobs separately archive exact head and
prospective-merge sources and execute physical weights. An exception, budget
exhaustion or missing dependency fails the job and preserves earlier records.
No claim is made for a queued run or a different SHA. Existing Four-Gate source
floors, lifecycle gates, signatures, native recovery and release rules remain.

## Mathematical context (primary sources)

Fromm & Imkeller, *Existence, Uniqueness and Regularity of Decoupling Fields to
Multidimensional Fully Coupled FBSDEs*, arXiv:1310.0499v2, describes local fields
and concatenation under regularity assumptions. Han & Long, *Convergence of the
Deep BSDE Method for Coupled FBSDEs*, arXiv:1811.01165, treats conditional a
posteriori theory. Neither work grants arbitrary global solvability or semantic
correctness merely from a small loss. The analytic fixtures here are derived
directly from their declared linear equations; they do not require a learned
solver to rediscover an available exact answer.
