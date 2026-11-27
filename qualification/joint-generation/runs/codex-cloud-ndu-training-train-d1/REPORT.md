# NDU training contribution — one TRAIN-only diagnostic

The single frozen run completed with exit **0**. Both systems respected the
original complete **10 CPU second / 12B declared-operator-unit caps**. This is
TRAIN mechanism evidence, with no validation or formal confirmation. The sole
CORE c1 formal result remains failed and consumed; r2 remains unconfirmed.

## Exact provenance and fixed scope

- Cloud cwd: `/workspace/hepta-private-ci/qualification/joint-generation`.
  Initial cloud checkout was `f8c9419df6ddeb36ff8b522a50219981fb8d9345`, not research.
- Exact starting commit `0aca16714390ca045a53cece9644992b7990fc9c` was fetched and
  independently matched to PR #3451's head using Git branch transport.
- Branch: `research/ndu-training-budget-20261023`. The first post-run probe of
  `codex/joint-generation-prototype-20261023` resolved to `0aca167…`; a later
  final remote probe observed `2e7b08c86b2694727d7c989113a59ccfc8779a72`.
  This concurrent remote drift was not used as a research starting point.
  This task's pushes targeted only its independent research branch, and no
  other experiment source in this checkout was modified.
- Numerical/protocol commit `7dc5718f30`, runner commit `5c03061859`, prospective
  freeze commit `456ef38b3b`. See [the immutable source receipt](../../ndu_training/frozen-train-d1.json)
  and [protocol, including future confirmation draft](../../ndu_training/PROTOCOL.md).
- Only r2 TRAIN was constructed: generator seed 130101, 192 physical sources,
  3072 requests, grouped instructions and two sensor variants. The exact
  reconstruction profile and source/input hashes are in `train-manifest.json`.
  There was no validation, old formal-test or new formal-test construction.
- Fixed seeds 11/23/47, decoder300, dense base500, hidden32, CE anchor .2,
  rho1.5, LR .003, batch64, mixed views .5. Two estimator candidates only:
  original IID and unbiased proportional target-class stratification, for BOTH A/N.
  No rho/LR/observer/endpoint search. No candidate was selected after this run.

The fixed target is mean over requests of each request's joint entropic value.
It is not modality-loss logsumexp. Fixed constant rho is compatible with an
appropriately conditioned entropic tower/Bellman recursion. This implementation
does not learn a temporal continuation function or replace a dependent path
joint with averaged independent marginals. The original decoded reward is intact.
Scope is two modalities, synthetic scenes and a twelve-code RGB decoder; typed
AV reservation has no accepted generation backend.

## Useful matched and complete-budget comparisons

At 128 updates all six A/N matched-prefix stream hashes agreed. Parameter/Adam
snapshots were retained. Thereafter A obtained **626** real updates per candidate
and N **623**; cheaper A used its saved work. Each complete system pays for both
estimators and all three seeds. Both stopped because the next complete round
plus the unchanged prospective tail reserve would exceed the unit cap.

| Complete cost | A | N |
|---|---:|---:|
| Attributed CPU seconds | 9.152018195 | 9.160336413 |
| Declared units | 11,662,222,245 | 11,657,544,633 |
| Actual candidate updates, six models total | 3,756 | 3,738 |

Each system includes the full shared **4.025272465 CPU seconds / 4,546,132,125
units**: data, native compilation and compiler-child CPU, all bases, base
scoring, gradient diagnostics and real PNG service. All final TRAIN scoring,
corruption observations, candidate setup/training, matched/final exports and
one full-service measurement per model are included. Shared scheduler CPU
**0.129539644 seconds** is attributed in full to both systems. No unused critic,
padding, larger N cap or hardware-FLOP equivalence is claimed.

The physical process used 14.158432862 CPU seconds before final receipt writing;
the command's terminal receipt reports 14.172893129 including its output writing.
Shared attribution explains why the sum of system costs exceeds physical CPU.
Development, browsing, tool installation, handmade tests and the later integrity
audit are separate R&D, with no matched lifetime-cost claim. The audit measured
0.236820121 CPU seconds before its output write. Total historic R&D CPU is not
available and is not invented.

| Sampler | Seed | N−A utility at 128 matched steps | N−A final utility | N−A final joint success | N−A descriptive complete CPU-net |
|---|---:|---:|---:|---:|---:|
| IID | 11 | +.008794531 | +.003037053 | +.003097535 | +.013333635 |
| IID | 23 | +.005253159 | +.005430238 | +.005636589 | +.004177572 |
| IID | 47 | +.007346272 | +.002920022 | +.002976014 | **−.002736904** |
| Stratified | 11 | +.008649501 | +.003007685 | +.003103093 | +.003998610 |
| Stratified | 23 | +.007499639 | +.004709766 | +.004861956 | +.012385367 |
| Stratified | 47 | +.006391436 | +.004305857 | +.004457864 | +.002456430 |

Mean final N−A raw utility was +.003795771 (IID) and +.004007769 (stratified).
Stratification also helped A: the increase in the mean N−A contrast is only
.000211998. It is not evidence that variance reduction uniquely benefits NDU.

The strongest additive raw-utility candidate was stratified for every seed;
the corresponding N-stratified contrasts are therefore unchanged above.
Against the stronger *endpointwise per-seed upper envelope* of both A candidates,
N-stratified complete CPU-net deltas were +.003998610 / +.007013253 / +.002456430.
This TRAIN-derived envelope is a descriptive reference, not a new inference rule.
CPU-net uses full TRAIN expected utility, the fixed 96-TRAIN-request service
panel, price .02, horizon100000, all-candidate build attribution B/(3H), and the
pre-candidate base-service reference of 89276.333333 ns/request. It is conditional
on one service wave; no independent timing repetitions or confidence intervals
were obtained. The negative IID seed47 CPU-net result is retained.

N-stratified greedy joint accuracy declined relative to its matching A in seeds
11/23 by .000325521/.000651042, and improved in seed47 by .000325521. It did not
uniformly improve greedy generation. Every selected decoded corruption drop was
positive, with all twelve final values in [.972694,.979376].

## Gradient mechanism and numerical evidence

Existing N already exactly enumerates the 12×12 joint output law. A new sampled
output estimator would add variance. The experiment instead changed request
sampling and importance-weighted the whole request, CE included, preserving the
same original TRAIN objective.

The fixed 64-physical-source/1024-request TRAIN panel includes both views. Each
variance estimate uses only twelve predetermined minibatches, so these point
estimates have unresolved sampling uncertainty and are not formal intervals.

| Seed | IID N gradient variance trace | Stratified N trace | Reduction | A trace reduction | Risk/raw utility gradient cosine |
|---|---:|---:|---:|---:|---:|
| 11 | .051019863 | .043718207 | 14.31% | 8.98% | .950194 |
| 23 | .055355961 | .047383356 | 14.40% | 2.48% | .962614 |
| 47 | .048663417 | .043329613 | 10.96% | 4.67% | .918430 |

N's unstratified minibatch noise was larger than A's; stratification reduced the
measured trace in all seeds. N's direction was closely, but not perfectly,
aligned with external raw utility at these bases. The utility/CE-anchor gradient
norm ratios were N=4.662/4.740/3.915 and A=3.645/3.831/3.258. Thus objective scale
and direction both differ even with the same fixed CE anchor; the data do not
identify curvature alone as the cause of N−A gains.

All measured gradients, saved weights and moments were finite. The minimum
shifted entropic kernel was .142566; cached versus independent log-domain logit
gradient maximum errors were 8.13e−18 / 8.02e−18 / 9.11e−18. There is no evidence
of an exponential underflow/overflow failure in this measured profile. This does
not explain the old formal CORE failure or prove numerical stability elsewhere.
All twelve models changed all six content parameter groups. Their image decoders
remained byte-identical to their seed's shared base. Saved Adam clocks match
128 for matched snapshots and 626/623 for final A/N snapshots.

## Verification and remaining decision

Initial handmade/learning/accounting tests passed 30/30; after adding actual
parameter-gradient parity, 31/31 passed in .396 seconds. Logs preserve both runs
and an earlier incorrect shell path plus a corrected Ruff E741 lint finding.
Ruff checks passed. Required `just fmt` exited 0 and reported no owned changed
files; the qualification Python files were formatted explicitly with Ruff.
No full repository/Rust or formal-data tests ran. The independent artifact audit
passed digest, decoder immutability, all six parameter deltas, finite optimizer
state/clocks, stream-prefix identity, stage-cost conservation and service-cap
checks. See `audit.py`, `audit.json`, `result.json` and the artifact hash inventory.

The predeclared TRAIN screen was met: all three measured N variance reductions
and final same-sampler N−A raw/joint contrasts were positive. That is a candidate
worth parent review, not generalization or scientific confirmation. No next
candidate, rerun, validation or formal test was executed. There is **no execution
blocker**. Any later confirmation requires the parent's complete cross-task
history, new independent physical sources, immutable one-shot markers and an
honest repeated-confirmation error budget. The draft in PROTOCOL.md explicitly
does not retroactively restore the previously spent .05 or reclassify CORE c1.
