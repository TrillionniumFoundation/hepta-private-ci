# Continue the frontier instead of repeating the root

Base research source: `d1de6065edf846874ba2ff25a0f5ec81183dc8b1` (PR #1546).
The import-only repair is `b7ecedff22311b3af7dea76696d20287ac732352`.
No default policy, Reader, Riccati solver, native NDU API, or production gate changes.

## What actually failed in the parent

Hosted run 38201676369 did NOT execute the observed-return experiment. Its full
regression log records 1,130 passes and two skips (1,132 total), then F401 for an
unused `torch` import in `system2_budget_trial.py`. Artifact 11725848372 has ZIP
SHA256 `9589216b699c47b484e7112aef2bed143ce7a074d9d6086427961cde10b30c9c`.
The experiment step was skipped. Removing that single import preserves all
training, policy, price, dataset and lint rules; it does not waive static checks.

Local runtime recovered in this turn. The failed artifact's 15 manifest entries
and the original critic artifact's 27 entries were checked. The local execution
uses the exact repository dependency source files, including their original
training, proof verifier and archive parser: no replacement model/dataclass ports.
It is a SOURCE SLICE with Python 3.13.5 / torch 2.10.0+cpu / safetensors 0.7.0,
not the full repository's pinned hosted torch 2.5.1 environment.

## Completed local observed-return run

The unchanged parent runner completed 1,536/1,536 episodes, zero execution failures.
Only fourteen failed-probe training contexts were available. On the previously
registered next 48 tasks:

| Budget | Direct heuristic proofs | Learned gate proofs | Perfect choice among existing restart tails |
| --- | ---: | ---: | ---: |
| 256 | 34 | 30 | 30 |
| 1024 | 41 | 39 | 40 |

The last column is a POST-HOC upper bound on choosing among the three observed
controls (stop, heuristic restart, value restart), not an online policy and not
a bound on every possible solver. It never feeds the new runtime search. At 1024,
`(1,3,4,6)` is lost by both restart tails, so a better selector alone cannot recover
all direct-heuristic successes. Probability calibration and NDU improvement remain
unestablished; disposition stays `stop_no_controlled_budget_value_gain`.

## Resumption semantics and evidence

`SearchSession` reuses the existing rational successor generator, state features,
terminal proof checker and frozen model. Its heap, visited set, partial child
batch, stable tie counter and generator cursor survive a budget boundary. Complete
a node's batch before ranking it, so pausing cannot change batch shape or greedy
selection. `advance(B)` increases a CUMULATIVE allowance, never restarts the root.

This is an in-memory, single-task, single-policy, non-thread-safe cursor, not a
serialized checkpoint or a general adaptive controller. Policy/weights cannot be
changed while paused. Failed sessions are unusable. Eager terminal proof checking
remains mandatory. Cooperative successor limits still exclude some generator
option-preparation overhead; counters are not FLOPs, and wall time is separate.
The old `search()` interface and old two-stage `episode()` remain unchanged.

The new runner reads the sealed observed-return journal, diagnoses the restart
menu separately, and compares 96 tasks x two budgets x two fixed policies = 384
conditions. Each condition compares one uninterrupted session and one split at
one quarter of the budget, and checks both against the existing direct-run proof
and generated-successor count. The legacy implementation drains queued nodes
when generation is exhausted; that useless post-limit work is not resumed.
No new training, evaluation reachability oracle, Encoder or Reader is invoked.

All 384 local conditions matched: identical proofs, generated successors, and
all session counters between split and uninterrupted execution. Heuristic results:

| Next 48 tasks | Root restart proofs / successors | Resume proofs / successors |
| --- | ---: | ---: |
| Budget 256 | 30 / 8,887 | 34 / 7,355 |
| Budget 1024 | 39 / 15,612 | 41 / 13,105 |

This RESTORES the direct baseline; it does not beat it. The 324-parameter gate was
trained for root restart, so it is deliberately NOT applied to a resumed frontier.
A future gate needs actual resumed outcomes and frontier-conditioned features.
Riccati's previous memory/latency tradeoff and negative language results are unchanged.

## Qualification

Sixteen new tests plus sixteen existing budget tests passed locally (32/32).
Tests include single-successor and irregular cuts, all seven legacy policies,
exact proof parity, critic mutation/mode rejection, oracle exclusion, partial
cursor retention, accounting, failed census preservation and the real runner.
Local compilation and YAML parsing passed. The broader source-slice bootstrap
initially lacked a review module, then a broad rerun timed out; neither is a full
repository pass. `just fmt` was attempted but `just` is absent; installing local
Ruff/just was unavailable. Hosted regression and static gates remain required.

The existing budget workflow retains all MemoryCell tests and lint, executes the
unchanged observed-return experiment, then runs resumption comparisons. It keeps
raw decisions, hashes, partial results and source identity. Local overlay outputs
explicitly record their overlay parent and executing file hashes. A hosted run
must report its actual generating head separately; a queued run is not a pass.
