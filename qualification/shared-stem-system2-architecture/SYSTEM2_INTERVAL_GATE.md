# P5 Next: Cost-aware System 2 action admission (research only)

This increment extends the evidence-bound shared Stem study #2082 with an
isolated exact-rational **interval decision rule**, not a general FBSDE solve.
It deliberately leaves all production Neuron, NDU, original witness,
checkpoint, CAS, Q24/Q32, selected model, Reader and blocking CI unchanged.

## Contract

For candidate `a`, independent model evidence must supply a conservatively
qualified utility interval `[L_a, H_a]` and complete externally accounted
marginal resource cost `C_a >= 0` under one **fixed** objective and one
unit profile. Feasibility/hard constraints are applied first.

A candidate is selected only if for all other feasible actions `b`:

`L_a - C_a > H_b - C_b + margin`.

If candidate value intervals overlap, a legal alternative lacks sufficient
evidence/qualified bounds, the fixed baseline is missing, or any hard gate
is unresolved, the output is `NO_GO`. Even the baseline `ABSTAIN` must be
explicitly declared and qualified. Multiple competing actions and all
known feasible alternatives must be present; the code cannot attest list
completeness itself. An externally measured cost can include Encoder,
Cell, graph expansion, full FBSDE, verification and latency, with no
inferred free compute or proxy model timer. All cost units must be
converted/registered by the caller **before** providing the additive
numbers; mixed units are not caught by this numeric prototype.

The actual function returns only a *research advisory* `Decision` with
`evaluator_authority=DENY_ALL` and `model_efficacy_measured=False`.
The numeric intervals, provenance digest, and asserted `qualified_bounds`
boolean are **untrusted inputs**, not verified attestations, valid
coverage, mathematical FBSDE bounds, or independent future outcomes.

Positive source hashes in this prototype are syntactic digests only,
NOT authenticated identities. An untrusted agent could forge all values:
never compose this function into final-use/production control.

## Adversarial tests

`python3 -m unittest discover -s qualification/shared-stem-system2-architecture -p 'test_*.py' -v`

`python3 -O -m unittest discover -s qualification/shared-stem-system2-architecture -p 'test_*.py' -v`

Tests include exactly scored interval dominance; a higher nominal-score
FBSDE losing once full cost is charged; equality/overlap rejection;
missing evidence on feasible alternatives; hard-infeasible options;
multiple cost axes; strict decision margin; invalid SHA/flags/intervals,
duplicate IDs/axes, missing baseline and sample bounds; and signed
utility with nonnegative-only costs. No pretrained weights are loaded,
no FBSDE solver is invoked, and no new causal utility is observed.

## What must follow

1. Qualify separately measured Source/Reader/Stem/Head costs on complete
   future-time and OOD tasks (not synthetic feature snapshots).
2. Supply independently audited uncertainty envelopes with explicit
   calibration and complete action sets, bound to one unchangeable
   objective/profile and authorized original source/observer.
3. Compare identical scenarios against no-search, exact cheap Bellman,
   learned Critic, direct BSDE, fixed-depth tree and expensive full
   coupled Picard/FBSDE. Count training/search/certification overhead.
4. Preserve the original #1923 wrong-reset global obstruction and #2003
   global full-tree two-sided consistency checks; a small residual is not
   an existence/uniqueness theorem.
5. Distill only verified value and credit into next-snapshot Cell Head
   candidates; do not use `Y` or `Z` as parameter gradients.
6. Preserve all failures, independent future-outcome/no-change/retention,
   signed original-owner FinalUse, and exact-head plus blocking CI.
   Do not auto-merge or activate this research source.

**Status: DRAFT / DENY_ALL.**
