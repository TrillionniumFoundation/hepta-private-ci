# Exact-Fraction terminal filtering: avoid pointless full proof checks

This is a strictly opt-in research change in PR #1546, stacked after
`ba6c92428f1f02b063df953f9b6268dec776f5e8`.

## Mathematical and trust boundary

The existing internal successor generator computes a terminal rational value
`v` and a postfix proof `p` from the same exact arithmetic operations.
If `v != Fraction(goal)`, the generated expression cannot solve that goal
(under the trusted in-process generator contract), so a full postfix replay
is unnecessary. Every potentially successful terminal **still invokes the
unchanged independent verifier**. No user-supplied value or external proof
bypasses validation, and no result is accepted from a critic estimate.

The new `terminal_prefilter=True` option in research-only
`SearchSession` leaves the legacy default `False`, original policies,
generation profiles, queue/seen state, prompt/Reader, FBSDE/NDU and Rust API
unchanged. It records `verification_skips` in addition to existing
`costs.verifier_calls`. For paired identical trajectories, the former plus
the latter must equal the original verifier call count. No hidden free work
is claimed; one exact Fraction equality remains charged in measured CPU time.

## Fixed experiment and gates

Use original `system2_canonical_trial.py`'s sealed prediction source,
including its exact generating commit, all 252 multiset IDs, two
successor budgets (256, 1024), both original and canonical generators, and
all historical proofs/counters. The source prediction SHA and full original
census must pass before the first timing observation.

The dedicated trial executes **seven counterbalanced repetitions** of
each combination: 252 tasks × 2 budgets × 2 generators × 2 terminal policies
× 7 = **14,112** recorded attempts. Each measurement includes session
construction and internal terminal checking. An extra verification of the
exported proof is performed *outside* the measurement window.

Acceptance checks before any performance claim:
- exact same proof, found flag, generated successors, popped states, critic
  examples and generator accounting as the historical sealed source;
- correct invariant `baseline_verifier_calls =
  filtered_verifier_calls + verification_skips`;
- independent verifier still rejects a forged invalid proof whose numeric
  value is set to the goal;
- at least **10% median CPU saving** and **5/7 favorable repeats** in BOTH
  budgets and BOTH generation profiles on the 48-task slice.

The 48-task slice is already exposed to experiments in this conversation and
is **not independent confirmation**. These seven timings are correlated;
no FLOPs/GPU/lifecycle/multimodal/semantic efficacy claim follows.

## Observed local evidence before publication

This turn's local source slice used the existing Git blobs and Python 3.13 /
PyTorch 2.10 CPU runtime. Eight new focused tests and 72 inherited research
tests passed (80/80). After sealing original canonical task outputs, a complete
**14,112/14,112** paired trial completed without an outcome or work mismatch.

Median measured CPU savings on 204 old tasks: reference generator
31.25% (256), 33.89% (1024); canonical generator 33.14% (256),
36.07% (1024). On the newer 48 tasks: reference generator 33.45%
(256), 33.38% (1024); canonical generator 34.12% (256),
35.84% (1024). All eight comparisons saved CPU in 7/7 repetitions.
Across the new 48 tasks, independent verifier calls per repetition fell
from 2,679 to 24 (reference, budget 256) and 5,461 to 34
(canonical, budget 1024).

These are LOCAL observations, not hosted qualification. The predecessor
canonical-only CPU study remained **slower** despite reduced successor
counts. This is a separate independent-target-filter comparison and should
not be presented as a canonical-generation speed win.

## Hosted validation

The existing scoped workflow retains full MemoryCell regression, F/E9
static checks, unchanged budget/stop and resume studies, canonical generation
and CPU cost trials. It then verifies and replays these two terminal policies
on the original sealed source and retains raw work records, timing journals,
the SHA manifest, environment and the actual generating commit. Any execution
failure remains unknown and causes a nonzero exit; no CI waiver or default
serving switch is made.

To reproduce in an exact checkout:

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_terminal_prefilter_trial.py \
  /path/to/sealed-canonical-output /new/prefilter-output
```

No claim is made that local proof-verification acceleration yields better
task success, general NDU/FBSDE reasoning, a Riccati speedup, or production
readiness. This is a narrower and testable computation-efficiency result.
