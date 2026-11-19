# CTRL-1: strong cheap controls and action coverage

This is an **exploratory post-pilot diagnostic** against the frozen pilot at
`b2646b4cbf19817145c9cb680d95333a267d19f4` (PR #5374). The original outcomes
were known before these controls were designed. Nothing here is a new holdout
experiment or a production selection decision.

The old fixed rule stopped at every confirmation prior. The old highest-mean
hybrid consistently chose repair followed by execute. This package adds three
explicit controls: execute if legal, repair then execute, and choose the better
of stop/execute using the public terminal kernel. Each decision pays the
existing one-credit fast price; terminal-kernel forecasts, mask calls and
measured CPU are recorded separately. All rules share the old hard resource
and time limits. Actual physical consumption is not equated by this price.

## Native observations

96 new exact rule evaluations cover 3 rules x 4 profiles x 8 scenarios. The
864 original comparison rows are read after byte and roster checks. A rule is
evaluated once per scenario, then compared with three historical training
seeds; those repeated comparisons do not create independent task samples.

| Profile | Old hybrid mean | Repair rule mean | Rule minus hybrid |
| --- | ---: | ---: | ---: |
| risk 0, no explicit prices | 0.715778 | 0.737915 | +0.022137 |
| risk 0, priced | 0.494564 | 0.582643 | +0.088079 |
| risk 0.25, no explicit prices | 0.701334 | 0.723025 | +0.021691 |
| risk 0.25, priced | 0.480043 | 0.567673 | +0.087630 |

The repair rule has 24 positive paired differences per profile, from eight
distinct scenarios. Per-profile objectives differ; these values must not be
pooled into one cross-profile NDU gain.

The learned actor, hybrid and learned router have zero observe/recall/verify
occupancy in these original confirmation rows. Only the hand-written VOI
uses those three information actions. The result does not demonstrate learned
memory-decision-verification coordination. The next prospective study needs
strong cheap controls and independently useful information-action scenarios.

## Integrity and validation

The diagnostic rejects duplicate or incomplete original rosters, changed
consumed artifact bytes, nonfinite values and missing/duplicate new results.
Selection of the best rule is retrospective at profile-mean level, never an
oracle choosing a different baseline after seeing each task result.

Eight new rule/denominator regressions passed on Linux. The native Mac source
projection included these eight tests and the companion continuation's nine:
17 passed in normal Python and 17 in optimized Python. `just fmt`, Ruff
0.15.13 and whitespace checks passed with tested ASTs unchanged. The source
receipt explicitly describes that combined projection; it is not a claim that
this smaller PR independently ran 17 tests or a full workspace suite.

`native/diagnostic/` retains the plan, 96 results, 192 attempt events, descriptive
report and byte manifest. Its measured evaluation batch excludes initial input
reads, source hashing and final report writes; nested timers are not additive.
The original campaign and old source remain unchanged.

## Reproduce

```sh
PYTHONPATH=scripts python3 -B -m unittest discover -s scripts/ndu_ctrl1_s1 -t scripts -p 'test_*.py' -v
PYTHONPATH=scripts python3 -B -m ndu_ctrl1_s1.diagnostic \
  --retained qualification/ctrl1-decision-cell-20261108/primary_repeat_2 \
  --output /absolute/new/diagnostic-directory
```

Scientific qualification remains **HOLD** and adoption **NoUpdate**. There is
no new training, model call, native tool effect or real-task confirmation.
