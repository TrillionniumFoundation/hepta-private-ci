# F/L/R execution checkpoint: engineering complete, scientific HOLD

## Delivered changes

The three review stages preserve S5's original execution-identity deduplication:

1. Unsealed or unverified retained-model declarations remain unresolved. A
   complete authenticated NoUpdate remains an observed non-improvement.
2. A frozen F/L/R plan, source partitions, lineage and budget checks, originals
   bound to the complete plan, complete denominators, and sealed A/B/C/D order.
3. Actual multi-generation CPU training, learner-distribution updates, retained
   artifacts and cold readback, with durable failure registrations and a D reader
   that replays the entire original search prefix before opening data.

The detailed design and native boundary are in [PROTOCOL.md](PROTOCOL.md).

## Exact source identities

| Evidence                      | Commit                                     | Tree                                       | Scope                                                        |
| ----------------------------- | ------------------------------------------ | ------------------------------------------ | ------------------------------------------------------------ |
| Original regression execution | `326a7df9073945c3dc682a96733b92c5c04096ab` | `c757193f2339bca634b8a038a0ac526621c7456e` | 74 tests, clean before and after                             |
| Formatted experiment source   | `29ef370999d3f4beb9b6efdf98d142ff0e5e6fe3` | `2ae06f03aca3eb068a8609ffa551b12f740257f7` | All three actual reference campaigns, clean before and after |
| Frozen upstream               | `4d5ffd79302da50ca2de87ec203905f7b4683de6` | `8fb46bb725eeac65575275bbce15d2150fd73e53` | #5411, including original-identity rejection                 |

All seven affected Python modules preserve identical normalized ASTs after the
required `just fmt`. The exact before/after byte identities are retained in
`raw/format-receipt.json`. Tests were not rerun after formatting; their source
identity is the first row, not silently changed to the experiment source.
Ruff 0.15.13 fatal-error checks passed on the formatted files. Hosted checks
must be assessed on their own actual final head; local records do not substitute
for them. Later evidence-only commits are archive carriers, not new executions.

The original CI execution helper first rejected a development invocation for a
missing source identity, before running any tests. That rejected record remains
in `raw/flr-tests-rejected.json`. The successful invocation used the published,
clean exact source above. Earlier NoUpdate red/green development logs are also
retained and are not added to the 74-test total.

## What actually ran

Python 3.12.14 / NumPy 2.3.5, seeds 41, 67 and 101, three generations, three
ordinary candidate attempts per learning arm per generation, eight A-only
learner-search trials per R generation. The batch seed list and horizon were
saved before its first dispatch in `PREREGISTRATION.json`.

| Recorded operation                              |               Count |
| ----------------------------------------------- | ------------------: |
| Generation/arm rounds                           |                  27 |
| Ordinary model candidate attempts and B queries |             54 each |
| R learner-search trials                         |                  72 |
| Reference C cold-readback uses                  |                  27 |
| Final reference D evaluations                   |                   9 |
| L decisions                                     | 6 Adopt, 3 NoUpdate |
| R decisions                                     | 5 Adopt, 4 NoUpdate |
| F decisions                                     |   9 frozen controls |
| Retained original files in the three archives   |                 298 |

Every campaign completed the descriptive protocol. Candidate and learner-search
training totals are 3,456 and 1,152 SGD updates respectively. These operation
counts are not independent tasks, trained Cell competencies or RSI generations.

## Descriptive final D results

Scores are accuracies on 256 synthetic examples per seed. D is a same-process
reference panel opened after search; independent external custody is **not**
established.

| Seed        |          F |            L |          R |     R minus L |
| ----------- | ---------: | -----------: | ---------: | ------------: |
| 41          |  0.5078125 |   0.99609375 | 0.95703125 |    -0.0390625 |
| 67          |    0.46875 |   0.97265625 |   0.984375 |    0.01171875 |
| 101         | 0.46484375 |    0.9765625 | 0.96484375 |   -0.01171875 |
| Repeat mean | 0.48046875 | 0.9817708333 |    0.96875 | -0.0130208333 |

R is lower than L in two of three repeats. The results do not support a stable
R advantage, a better subsequent improver, or RSI. No thresholds, selections,
learner parameters or candidate counts were changed after inspecting this D
panel. All earlier C scores and negative final results remain in the originals.
This is one synthetic generator family with three random repeats: **zero verified
independent real task sources**, no confidence intervals or significance claim.

R's discovery work is included in the recorded CPU/wall lower bounds. Energy,
provider charges, imports and final publication remain incompletely metered;
all complete cost totals are null. The experiment therefore establishes no
complete resource-adjusted net benefit. Shared overhead is charged fully to each
standalone arm and must not be summed across arms as physical campaign cost.

## Original evidence and reproduction

`SUMMARY.json` is the compact qualification boundary; `COMPACT_RESULTS.json`
retains all generation scores and cost lower bounds. `ORIGINALS.json` lists every
retained file with SHA-256, plus archive byte counts and hashes. Each archive
contains the frozen plan, actual A/B/C/D sample bytes, models, learner versions,
original evaluator/selection/use records, complete journal and report:

- `seed-41-originals.tar.gz`
- `seed-67-originals.tar.gz`
- `seed-101-originals.tar.gz`

`raw/` retains original command logs, source-bound execution receipts, formatting
identities and the separate current-native-chain inspection. Verify an archive
against `ORIGINALS.json` before extracting it. Reproduce execution at the exact
experiment source using the commands in `PROTOCOL.md` and a new output directory.
The workflow retains the same artifact family outside the checkout and enforces
non-skipped suite minima of 25 / 20 / 3 / 19 / 7.

## Unclosed product and research requirements

No real ordinary Adopt chain, ordinary complete NoUpdate chain, or whole daemon
plus Root cold recovery was established here. Current native owners still need
one compatible source/profile, original capabilities and real terminal outcomes.
Independent B/D custody, new source provenance, complete costs, and same-solver
improver transfer on later unseen tasks remain required. No production selection,
merge, deployment or scientific admission is authorized by this checkpoint.
