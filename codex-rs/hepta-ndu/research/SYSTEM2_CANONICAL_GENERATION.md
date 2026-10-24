# Canonical successor generation: avoid useless repeated arithmetic work

Stacked under PR #1546, parent `3e834a473a6c0454526092adf764ef50939c5329`.
Research-only; default `SearchSession` retains `generation_profile="reference"`.
No NDU Rust, Riccati, frozen critic, Reader, or production policy change.

## Why this is the next action experiment

The full frontier-return run from parent **38212628537**, generating head
`3e834a473a6c0454526092adf764ef50939c5329`, completed **2016/2016**
episodes, zero failures. The artifact `11730516794` has reported ZIP SHA256
`54852d8cde1caad65471d6918e23f3cff4c80d6bbc0108d64a126ab28de0d3b7`.
Local audit verified 70 manifest entries and the archived prediction seal.
Hosted regression: 1181 passing tests, two skipped (1183 total).

For the new 48 fixed arithmetic multisets:

| Budget | Direct/fixed resume proof count | Full 562-parameter frontier head | Root-only head | Shuffled head |
| --- | ---: | ---: | ---: | ---: |
| 256 yielded successors | 23 | 20 | 23 | 21 |
| 1024 yielded successors | 38 | 38 | 38 | 34 |

At 256, the full head stopped 13 times: ten were cost-saving, three lost a
proof. At 1024 it stopped zero times, although nine no-proof contexts had
strictly better realized stop utility. The post-seal best-action headroom is
~0.0099875 and ~0.0101917 respectively; these are synthetic within-menu
ceilings, not achievable online policies or confidence intervals. The head's
Brier score on next-48 attempted continuation decisions was ~0.3345 / ~0.3725.
No frontier-specific control advantage or probability calibration was established.

## New hypothesis: generation action space is wasting raw arithmetic

Original `successors` enumerates indistinguishable operand pairs even when
multiple remaining expressions have EXACTLY the same rational value. It also
computes both directions of subtraction/division for equal-valued operands.
All yield the same numeric successor multiset. The existing global `seen` set
rejects duplicate states, but only AFTER the generator emitted and charged
the redundant successor.

`canonical_successors` retains the first expression-tree representative for
identical value pairs and suppresses reversed subtraction/division when equal.
It avoids the redundant rational operations BEFORE generation; every actually
yielded successor still costs one unit. The proof verifier still receives the
full postfix expression and validates original operand identity and goal.
No oracle or training labels select generations. A test exhaustively compares
one-step reachable numeric states for every 2-, 3- and 4-value multiset in
{0,1,2,3}, and checks original references and pause/resume parity. Identity-
only provenance differences are irrelevant for existence of an arithmetic
completion but remain in the retained representative's proof.

Canonical filtering has costs of its own: pair comparisons, hash operations,
set construction and changed queue order. Each canonical run separately records
pair checks, suppressed operand pairs, symmetric variants, emitted successors,
CPU seconds and proof validity. A successor cap does NOT mean FLOPs or equal
wall time; any timing conclusion requires repeated comparable timings.

## Strict comparison

No hyperparameter search. Compare only `reference` versus `canonical_pair`
under the same budgets 256/1024 and the SAME heuristic priority. An uninterrupted
run is paired with quarter-budget pause and full-budget resumption; their final
proofs and every counter must match. Default reference must match the original
`search()` proof and successor count exactly. Every failure stays in the full
census, never converted to a zero label or a free operation.

Two groups are fixed before any final execution:
- `previous_204`: catalogue positions 0:204, all previously exposed to research;
- `next_48_tasks`: positions 204:252 of the original fixed hash-order catalogue,
  disjoint at the numeric multiset level (not guaranteed disjoint intermediate
  states, unrelated pretrained data or independent natural-language domains).

**Exploratory LOCAL pre-freeze results, not held-out confirmation:** one-prong
completion lookahead and two-term synergy ranking both regressed relative to
the frozen heuristic and were not promoted. Canonical pair pruning on the first
108 exposed tasks gave one extra proof at budget 256 without a lost proof and
fewer emitted successors. An exploratory 156:204 slice likewise had one gain
and no loss; that slice was therefore classified as exposed and is included in
`previous_204`. Only 204:252 is reserved for the new hosted diagnostic, and even
it is a correlated synthetic task family.

The registered pass check is not just one extra proof: require no proof losses
versus the reference in next-48 at both budgets; at least one real extra proof or
strictly lower emitted work for same proofs; verify extra filter work and elapsed
wall time before any claim about lower actual compute. An improvement in this
symbolic task does NOT qualify learned NDU, shared Encoder, FBSDE or natural
language reasoning; it only tests whether making the action set less wasteful is
worth exploring before another more complicated value model.

Run with `HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD)` and:

```sh
python scripts/memory_cell/system2_canonical_trial.py /new/canonical-output
```

The exact-head workflow retains full MemoryCell regression, scoped static checks,
the original budget/stop experiment and frontier-resumption trial. It then runs
this read-only comparison, sealing raw predictions before the final paired
contrast. The plan includes complete question/budget/policy positions and
source identity. No main merge or production activation is authorized.
