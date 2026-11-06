# Reject the root-influence candidate as a classical scheduler equivalent

**Disposition: NO_GO for this candidate; stop before random calibration or an
LLM experiment.** The proposed score—optimistic root influence times frontier
interval width divided by expansion cost—is exactly the classical
optimistic-policy occupancy score on this expected-utility Bellman graph. Both
implementations have the same early action certificate, shared-state cache,
incremental value backups, deterministic ties and warm starts. Their expansion
traces, calibration decisions, stopping decisions and declared costs coincide.
The classical comparator uses an **O(E) forward DAG algorithm**, not exponential
path enumeration.

The new finite task has positive decision headroom. That does not make the
scheduler new or better than its qualified comparator. The old JAC negative
results and old `.01` fee contract were not changed or reused with a different
amortization horizon.

## Concrete contract

A persistent sensor information law has unknown accuracy/orientation
`p in {.1,.3,.7,.9}` with a declared uniform prior. The controller knows this
finite catalog and observes calibration results, not the true member. A cold
fixture needs one paid preparation before labeled calibration. Fast calibration
returns one correctness bit in one model-time unit; paired calibration returns
the count from two bits in two units. The fixture stays ready after calibration.
The deadline is a pathwise limit on consumed model time, not a sample-count
substitute. The reference uses deadlines 0, 1, 2, 3, 4 as five finite boundary
checks; no random banks or new tasks are drawn.

After calibration the controller handles a fixed batch of **four** independently
scored deployment tasks. It may stop and guess (expected score `4*.5=2`), follow
the sensor, or reverse its label. Each used deployment pays `.1`; the external
score is correctness and does not change with internal state. The objective is
expected total external score minus all declared fees and time charges. There
is no entropic-risk parameter or risk-semantics substitution.

| Item | Declared synthetic resource charge | Declared model duration |
| --- | ---: | ---: |
| Fixture preparation | `.04` | 1 |
| Fast calibration, including one label | `.03` (`.02` execution + `.01` label) | 1 |
| Paired calibration, including two labels | `.05` (`.03` execution + `.02` labels) | 2 |
| Calendar opportunity price | `.01` per actual model-time unit | — |
| Computation | `1e-6` per declared work unit | `1e-6` model-time units per work unit |
| Certificate validation | `.001` per evaluated episode | Certificate checks are included in declared computation work; no provider call |

There is no uncharged reset: the fixture's continued readiness is an explicit
physical assumption of this constructed contract. A `.5` model-time reserve
covers computation; every enumerated execution verifies computation stays
within it and total clock stays within `calibration_deadline + .5`. Raw
acquisition fees, consumed calibration time, planning work/time/charges,
validation fee and deployment fees are retained separately. Scientific audit
execution is measured separately and is not passed off as a physical task.
These tariffs are not measured provider money or an established hardware cost.

## Strong controls and headroom

`exact_solver.py` supplies both a memoized sufficient-statistic DP and an
independent full-history solver carrying four raw likelihood masses. They agree
exactly. The full DP computes once per episode and then reuses its cached policy;
it is not forced to redo a full sweep after each observation.

The best no-calibration decision is STOP at value 2. A perfect-information
oracle that already knows the law has value 2.8, giving headroom **.8**. Against
the weaker fixed-follow action at 1.6 one would incorrectly report headroom 1.2.
At deadlines 0 and 1, no informative calibration can finish, so the attainable
same-information value remains 2 despite the perfect-law oracle's .8 gap.

| Calibration deadline | Exact same-information value before planning/validation charges | Candidate net under the declared ledger | Classical anytime net | Cached full-DP net |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 2.0000 | 1.998990910 | 1.998990910 | 1.998993940 |
| 1 | 2.0000 | 1.998990910 | 1.998990910 | 1.998983840 |
| 2 | 2.3100 | 2.308936370 | 2.308936370 | 2.308961620 |
| 3 | 2.4000 | 2.398831330 | 2.398831330 | 2.398911120 |
| 4 | 2.4504 | 2.449031047 | 2.449031047 | 2.449230017 |

At deadline 4, calibration uses an expected 2.3 labels and 3.3 model-time units,
pays .099 acquisition fees and .033 time charges, and produces 2.4504 before
planning/validation. Candidate and classical anytime work are both 365.3
expected declared units; cached full DP uses 168.3. The candidate therefore
has **zero gain over the qualified classical scheduler**, and is worse than
cached full DP by `.000198970` in this declared small-model ledger. No measured
runtime or lifecycle advantage is claimed.

## Why the candidate is identical

Let `a+(s)` be the same tie-broken optimistic action in a partial graph. Its
upper backup is

\[
 U(s)=r(s,a^+)+\sum_{s'}P(s'\mid s,a^+)U(s').
\]

Reverse differentiation through these selected max branches gives

\[
 g(root)=1,\qquad
 g(s')=\sum_{s:s'\text{ child of }s}g(s)P(s'\mid s,a^+(s)).
\]

This is precisely forward occupancy propagation under the optimistic policy.
At a max tie, the rule uses the specified active-branch subgradient rather than
claiming a unique derivative. Shared descendants sum all incoming probability
contributions in both algorithms. Consequently

\[
 g(s)\,[U(s)-L(s)]/c_{\rm expand}(s)
 =d^{a^+}(s)\,[U(s)-L(s)]/c_{\rm expand}(s)
\]

for every frontier. Given the same tie rule they expand the same node. Identical
local updates and caches give identical next bounds, so induction gives the
same entire trace and the same certificate

\[
 LQ(root,a)\ge\max_{b\ne a}UQ(root,b).
\]

Both can stop computing at this certificate and retain the cache after an
observation. Calling one quantity “internal influence” does not produce a new
control or stopping rule. More efficient incremental implementations can be
used by either side without breaking the identity.

The ordinary bound/uncertainty-directed planning ingredients have clear
predecessors, including [Smith–Simmons, HSVI (2004)](https://www.cs.cmu.edu/~reids/papers/hsvi.pdf)
and [Barenboim–Indelman, anytime deterministic POMDP guarantees (2026)](https://anpl-technion.github.io/Publications/Barenboim26ai.pdf).
The rejection here rests on the explicit identity above and executable checks,
not on treating those papers as identical to every detail of this implementation.

## Exact checks, corrections and clock distinctions

The final run passed **510 deterministic assertions**. It checks five deadline
cases, both independent exact solvers, complete conditional-hypothesis
trajectory mass, every actual paid action and clock, certificates, warm-cache
traces and costs. Of 128 subsets of seven expandable states, 34 partial caches
are ancestor-admissible; all have identical candidate/classical influences and
priorities, with valid intervals against the exact oracle.

The first verifier required a merging descendant in the economic cases' chosen
optimistic subgraphs, but none occurred. That real coverage failure is preserved
in `history/initial_verifier`. Rather than change prices, batch size or task
laws, the verifier added a separate four-node diamond: incoming probabilities
`2/5` and `3/5` merge into one frontier, giving exact influence 1 and priority 2
for both O(E) algorithms. This is an additional structural test, not a new task
result. A later reporting amendment distinguishes perfect-law headroom from the
tighter admissible-planning bound at deadlines 0/1; it changed no policy, value,
price or outcome. The first completed record remains in
`history/first_completed_audit`.

Three clocks are distinct:

The retained JSON objective's phrases “actual model-clock charge” and
“measured-contract computation” refer only to consumed **declared model-clock
units and declared computation-unit charges**. Neither phrase denotes a
physical measurement. This wording clarification changes no retained result
or execution receipt.

- **Declared task model clock:** integer preparation/calibration durations and
  `work * 1e-6` computation duration, with the `.5` reserve. These are exact
  contract quantities used for feasibility and synthetic charges.
- **Measured host execution:** `timing_receipt.json` records about `.24510 s`
  wall, `.237761 s` user CPU and `.004195 s` system CPU for replaying the entire
  exact audit, including all cases and validation. This replay only instruments
  CPU; all scientific and declared-ledger fields match the primary record.
- **Actual external task/provider clock:** not measured; no LLM, external tool
  task or provider call was run. No real-clock deployment conclusion follows.

The preparation counterexample is also retained: with deadline one and a cold
fixture, the valid value is 2; falsely ignoring preparation duration predicts
2.31 despite charging its fee. Preparation is not an information-free clock
refinement—it is a real paid transition and must consume its modeled time.

## Reproduce and disposition

Run from the parent directory of this package:

```bash
python -m root_influence_candidate.verify --output /tmp/ndu-root-influence-new.json
```

The runner refuses to overwrite evidence. `PROTOCOL.json` contains the local
source freeze and disclosed amendments; `result.json` contains exact fractions,
all partial-cache states and finite trajectories; `execution_receipt.json` and
`timing_receipt.json` bind actual runs and source identities.

The candidate passes a meaningful-headroom check and a finite correctness
check, but **fails the structural-difference gate against its strong baseline**.
Stop this candidate here. Do not run random calibration, add an LLM task,
change the batch size, or reprice the old study to manufacture superiority.
