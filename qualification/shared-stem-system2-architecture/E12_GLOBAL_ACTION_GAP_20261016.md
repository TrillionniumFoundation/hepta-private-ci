# E12 global action-gap certificate over neural Cell continuation (research only)

## Scope and lineage

Child of frozen `research/hepta-e12-learned-continuation-ci-20261016` / #2521,
`198eb10f60d8b5ce522396cf49f11daa87eb86e5`. This additive child neither
rewrites the original E12 finite-tree solver and neural SGD nor edits the native
Neuron/NDU/Worker, reader, credential authority, CAS/CNS, main or FinalUse.

The pilot uses exactly the registered E12 **nonzero-noise nonlinear discrete**
root-to-leaf law on a complete binary *public-prefix adapted* tree:

    X_child = X_parent + a*h*phi(Y_parent) +/- sigma*s
    (1 + lam*h)Y_parent = E[Y_child | public-prefix] + beta*h*phi(X_parent)
    Y_leaf = g*phi(X_leaf), phi(x) = x/(1+x*x)

The law admits a global finite-tree contraction `q=a*T*(g+beta*T)<3/4`
within the invariant box. This is NOT a theorem for general continuous-time
FBSDEs, learned or real-world dynamics, arbitrary Tree Graphs, or natural-task
success. Every action uses the same root information and objective proxy.

## Executed mechanism

- Original E12 root `Y_0` is a **toy synthetic utility proxy**, not independent
  natural language ground truth. Legal controls: `direct` (`a=0`, no penalty),
  `coupled` (`a=1/3`, penalty `1/512` synthetic utility), and `stop` (`0`).
  A penalty represents a prescribed utility tariff, not measured CPU price.
- The proposer runs whole-prefix forward/backward maps and never consumes the
  held reference solution. It accepts a frozen neural continuation initial
  vector from the **existing** original train-only head (#2519/#2520) or a
  declared zero control. No original E12 `solve` or `operator` calls in the
  proposer. Only this bounded decision experiment uses the new independent map.
- After each exact rational map, outward-round `||Y-F(Y)||_infty/(1-q)` up to
  Q16. A candidate value interval is
  `[Y_0 - eps - tariff, Y_0 + eps - tariff]`. The Q16-projected
  continuation messages are used for the next step. STOP has `[0,0]`.
- Publish a decision only if one lower bound is STRICTLY greater than every
  alternative upper bound. Otherwise refine the widest *competitive* interval,
  with bounded deterministic tie-breaking, or return `HOLD_UNRESOLVED`. There
  is no automatic 'solve to zero' assumption and no tied-choice selection.
- The independently run reviewer checks original E12 registered `operator`,
  original prefix-dictionary `audit`, every interim guess and Q16 message,
  every interval bound, scheduled arm, source/plan SHA, original terminal law,
  action agreement, work counts and original independent full-reference solve.
  It does not treat a matching selected choice as sufficient without checking
  whole-tree equations. The review may reject an artifact even with a valid
  author-computed outer SHA.

## Source and experiment identity

Plan freezes 6 value-disjoint **synthetic x0 variants**
`[-117,-79,-37,37,79,117]/128` across depth 1/2/3: 18 cases, 36 effectful
candidate actions. They are not external source families or prospective time
windows. Frozen controls: one-map unverified ranking, no-search STOP and the
original mathematically accepted full-tree solve. Maximum 32 action map calls
per case, Q16 approximation; full scope includes all training/certification
costs and independent evaluator costs when claiming a cost comparison.

Protocol: `train-only -> blind propose -> independent review`, three separate
CI jobs per exact source-profile (source HEAD and GitHub synthetic merge).
Training reuses #2520's frozen/train-group mathematical data and actual fitted
145-parameter neural head. Blind proposer receives only original training
artifact, never held source labels or original E12 teacher solves. Review job
opens the original solver after proposal SHA is frozen. Raw source, audit and
negative evidence are retained; workflow has only `contents: read`.

## Local source-only diagnostics (not hosted original-E12 qualification)

Local Python 3.13 stdlib smoke case, **zero** initializer:

- 18/18 finite synthetic decision certificates, with STOP 9, coupled 8,
  direct 1; 80 whole-tree map evaluations. Cheap first-map action differs on
  8/18 decisions, but these differences are **not task-utility wins**.
- 11/11 ordinary tests and 11/11 with `python -O` passed locally before the
  research branch is advanced. Tests include an **independently written
  local compatibility review fixture**. That fixture is explicitly not the
  original upstream E12 math, original pretrained inference or independent
  publication-grade validation. Only hosted exact-head workflow can run the
  original registered code on this branch.

## NO-GO gates

Remain `DRAFT / SHADOW_ONLY / DENY_ALL / NO_MAIN_MERGE / NO_FINALUSE`.
No 97M/140M/421M pretrained Cell reasoning result; no genuine new multimodal
source; no human/independent real-task success; no continuous-time theorem; no
complete target-host CPU/GPU p99, calibration, energy or lifetime-cost win.

Especially, changing a cheap one-map choice is **not** evidence that a more
expensive FBSDE route is better: historical real-task E13/E14 routes were
negative. The novel gate is a conditional *mathematical* decision certificate.
Use a genuine future task with an independently sufficient Reader, named target
host and equal-resource Bellman/cheap-Critic/Reader controls before considering
any System2, Cell Split, or shared-Stem promotion.

### Local source-only commands

```bash
PYTHONPATH=qualification/shared-stem-system2-architecture python3 -m unittest \
    discover -s qualification/shared-stem-system2-architecture -p 'test_e12_action_gap.py' -v
PYTHONPATH=qualification/shared-stem-system2-architecture python3 -O -m unittest \
    discover -s qualification/shared-stem-system2-architecture -p 'test_e12_action_gap.py' -v
PYTHONPATH=qualification/shared-stem-system2-architecture python3 \
    qualification/shared-stem-system2-architecture/e12_action_gap_study.py \
    propose --output /tmp/hepta-gap-zero-control.json
```

Do not label local tests a production or genuine neural reasoning result.
