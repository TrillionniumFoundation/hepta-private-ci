# System2: distinguish search correctness from Riccati solver savings

Parent research source: `bb78e061a7b35b19e817dce6862d3be1a5481e5f`, PR #1546.
No default, NDU Rust API, Reader, Encoder, historical profile or label changes.
Two deliberately separate experiments answer different questions. A smaller
numerical residual is never used as an arithmetic correctness label.

## 1. Exact Riccati replacement on its admitted domain

`riccati_lq.py` admits finite-horizon deterministic-coefficient, risk-neutral LQ
models with PSD state/terminal costs, uniformly positive control costs and
additive independent unit-covariance noise. It computes value matrices, feedback
gains and scalar noise costs. The backward variable in the separate Hamiltonian
boundary system is a costate, not the scalar NDU utility.

Nine fixed zero-noise problems (three horizons, three seeds) compare the entire
control/state trajectory and cost against an independently assembled dense
Hamiltonian boundary solve. Matrices and initial states are saved. A solve error
or mismatch fails the numerical run after retaining its case. Measured backend
time and solve dimensions are reported; cold-start order and dense assembly are
not hidden. This is not a tuned comparison with every efficient FBSDE algorithm.

Tests additionally compare the existing `finite_tree_bsde.solve_path` to its
affine Riccati special case and integrate every outcome of a four-step additive
noise tree against the quadratic value including its trace offset. Different
initial states can share gains only when coefficients and terminal conditions
match. Random coefficients, nonlinear dynamics, risk-sensitive generators,
constraints and discrete actions are NOT silently reduced to this profile.
The inherited zero-coupling deterministic evaluator is also tested for
same-depth ranking invariance and cost-driven stopping under a flat critic.

## 2. Explicit-state arithmetic process search

Use every input number exactly once and legal +, -, *, / to reach 24. Fractions
are exact. Actions build postfix programs; a separate stack verifier checks
operators, division, operand use and final equality without Python eval.
There is no free-form text, pretrained Encoder, Reader or generated external
knowledge. This is a controlled program-search reference, NOT evidence of
language reasoning emergence, multimodal differentiation or production efficacy.

A fixed identity hash selects twelve training and twenty-four evaluation number
multisets, without outcome filtering. Up to 128 states per training task teach a
shared 225-parameter (12->16->1) process critic. Labels describe whether a valid
completion EXISTS; they do not estimate on-policy, budget-conditioned success.
A label-permutation control uses identical features, initialization and updates.
Both models freeze before evaluation; intermediate arithmetic states may overlap
between tasks, so the split is task-multiset-disjoint, not state-disjoint.

Seven arms: one-path greedy; BFS; hand-written heuristic search; learned value
search; the same critic with registered discounted utility; shuffled-label value
search; constant-value discounted utility. All use the same legal successor
function and exact runtime terminal verifier. Two ceilings (64 and 256 popped
states) schedule 336 predictions. Generated successors, critic examples,
verifier calls, time and failed records are retained. These are not equal FLOPs
or equal wall costs. A failed execution's unobserved counters remain explicitly
incomplete. No proof found is not a certificate that the puzzle is impossible.

All predictions are sealed before a separate exact reachability pass labels the
evaluation tasks. The latter supplies a diagnostic candidate-coverage ceiling,
never a runtime oracle, training update or retrospective answer replacement.
This experiment can reveal the effect of search, state-dependent evaluation and
supervision. It cannot imply that the NDU aggregator itself improved equal-depth
rankings. No learned stopping calibration or nonlinear Riccati routing is claimed.

## Validation and reproduction

The new scoped workflow runs ALL MemoryCell tests, static diagnostics, nine LQ
cases and 336 search attempts without staging pretrained models. It separately
verifies the completed matched3 archive (run 38195447470, artifact 11723737889,
SHA256 b98de07cf0bfb2de460bc656747f601ee156dedd25f87a28089c31e90a5f9a7e)
and copies its recorded summary; those historical answers remain attributed to
bb78e061..., not the new numerical/search source.

Local container and Python services failed before execution in this turn. Code
publication does not establish tests or outcomes; exact-head hosted results are
required and partial outputs are uploaded on failure. Existing model workflows
and independent repository gates remain unchanged.

```sh
python -m unittest discover -s scripts/memory_cell -p 'test_system2_riccati_lq.py' -v
python -m unittest discover -s scripts/memory_cell -p 'test_system2_verified_search.py' -v
python codex-rs/hepta-ndu/research/riccati_lq.py /new/lq-output
python scripts/memory_cell/system2_verified_search.py /new/search-output
```

`production_accepted=false`; no independent natural-task gain, no learned NDU
calibration and no claim that a general nonlinear FBSDE is a Riccati equation.
