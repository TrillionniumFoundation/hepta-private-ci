# Fixed block TRAIN result: useful updates increased, readiness failed

The single registered1:1 alternating joint/heads-only candidate **failed TRAIN
readiness**. Saving encoder-backprop work really funded more content-head
updates, but the selected model lost utility/joint success to standard joint
training and to the strong original dense A. The original additive contribution
remained positive within both recipes. No frequency sweep, replacement build,
formal test, old formal result read or rejected-refiner/gate expansion occurred.

The protocol and implementation were committed before scores: source identity
`356acf5624312e8f9e01dd6f44fcba18a365b2cc`, freeze/execution commit
`4693f47b30ee800a51978c224a4bcb5e95632f21`, on the same isolated
`research/content-control-budget-20261023` branch descending from0aca16714390.
Source and input identities remain in [frozen-train-v1.json](frozen-train-v1.json).
The freeze was pushed before the sole TRAIN command.

## Implementation and checks

The two recipes were exactly joint/joint and joint/heads-only in complete
two-update rounds, each with matched H/A0.2-CE anchors and the unchanged additive
decoded utility. Both content heads update on every step; encoder/bias update
only on joint steps. A heads-only step computes its real encoder forward, but
does not compute head-to-hidden/tanh/encoder derivatives or encoder gradients.
It omits encoder/bias Adam operations instead of supplying zero gradients.

Encoder/bias moments and clocks remain byte-identical on skipped steps. Active
groups alone determine clipping and bias-correction powers. The native kernel
uses the original Adam expressions with floating-point contraction disabled.
Five hand-array tests passed in0.275 seconds: finite-difference H/A gradients,
bitwise NumPy parameter/moment/clock agreement over alternating steps, inactive
state preservation even before any encoder moment exists, atomic budget/set
rejection, and standard-joint parity with the original saved native optimizer.
The [original unit log](../runs/content-block-unit-v1-20261023.txt) is retained.

The post-build saved-artifact audit verified all36 candidates: actual first
joint/head parameter deltas agree with Adam (error<1e-12), final movements
agree with base/model files, moments are finite, clocks equal executed update
counts, and all18 first-head inactive-state hashes match before/after. All
decoders stayed unchanged. The exact sum of executed joint and heads-only
kernel inventories equals each group's charged search_train units. No skipped
encoder-backprop work was billed. Twelve actual external hand-RGB PNG/caption
outputs passed independent byte/hash/base64/pixel/template/text observation;
all12 depict red-square-right. This is a smoke check, not generalization.

## Fixed opportunities, result and complete budgets

The immutable saved bases and TRAIN tensors were hash-verified and reused,
avoiding repeated data/base training. There are144 fit/48 inner physical sources,
16 grouped instructions/variants per source,2304/768 rows. No generator or
formal-evaluation entry point was called. All groups used seeds11/23/47 and
LRs.001/.003/.01, nine candidates each,36 total; all chose.01/full.

| Group | Utility | Joint success | Complete CPU seconds | Complete declared units | Selected head updates/seed | Selected encoder updates/seed |
|---|---:|---:|---:|---:|---:|---:|
| H_joint | .97330503 | .97182908 | 5.796900304 | 11,625,527,853 | 394 | 394 |
| A_joint | .97582976 | .97444595 | 6.131584913 | 11,645,004,069 | 386 | 386 |
| H_alt | .97185217 | .97029510 | 6.404051246 | 11,650,130,073 | 528 | 264 |
| A_alt | .97405636 | .97252979 | 6.748299155 | 11,647,940,121 | 512 | 256 |

Every complete group remains below10 CPU seconds AND12B units, including all
nine candidates/search/observations/exports/services. These are equal ceilings,
not equal measured spending. The one ledger per group and all stage/kernel
inventories are in [build.json](../runs/content-block-train-v1-20261023/build.json).

Inherited shared preparation is charged fully to EACH group:2.075925876 CPU
seconds/3,486,924,537 units, including all original data, three-seed decoder/base
training and compiler work, despite reuse. New actual shared work adds.304192745
CPU seconds, including imports, verification/read/copy, observer preparation,
the actual new masked-Adam compilation(.080825690 CPU seconds), and64-fit-row
pre-selection base11 service calibration. Total common attribution per group is
2.380118621 CPU seconds/3,488,571,225 units. Actual scheduler/setup.001793314
CPU seconds is additionally charged in full to EVERY group. All active group
candidate/tail CPU is separately accumulated, excluding another group's work.

Each group's training-only allowance was `(12B-common_units-500M)/9` and
`(10s-common_CPU-2s)/9`, with complete two-step admission. The500M/2s tail
reserves are estimates, never consumed padding or additional free allowances.
Candidate setup/objective preparation, all nine trainings and validation,
gradient/moment evidence, every model export, selected PNG/hash/JSON service,
decoder corruption and external reload checks are actually paid in the same
ledger/CPU account. Observation work is outside the narrower service timer but
inside build cost. Byte/memory primitives have actual CPU, not invented FLOPs.
Final administrative receipt writing/statistics are separately reported and
never used as budget credits.

Per heads-only step,462848 MACs plus inactive derivative/optimizer work were
actually omitted. Across all candidates, H_alt performed4752 real head updates
versus3546 for H_joint; A_alt4608 versus3474 for A_joint. Selected A head updates
increased32.64% (386→512), while encoder updates decreased386→256. More useful
head updates therefore did not guarantee better generation. The fixed schedule
also changes Adam clocks/clipping/optimization paths, so this does not causally
prove that encoder frequency alone explains the loss.

## Prespecified TRAIN contrasts

All intervals are descriptive crossed three-seed/48-source bootstrap2000,
seed77431. The same inner rows selected LR, so these are not independent
confirmation p-values or formal alpha expenditures.

| Contrast | Utility difference | Descriptive95% interval | Joint-success difference |
|---|---:|---|---:|
| A_joint−H_joint | +.00252472 | [+.00066970,+.00412903] | +.00261687 |
| A_alt−H_alt | +.00220419 | [+.00055706,+.00399166] | +.00223469 |
| A_alt−A_joint | −.00177340 | [−.00638365,+.00243211] | −.00191616 |
| H_alt−H_joint | −.00145287 | [−.00631950,+.00258858] | −.00153398 |
| A_alt−old strong A | −.00194200 | [−.00683354,+.00247096] | −.00209432 |
| H_alt−old strong H | −.00150486 | [−.00628366,+.00243434] | −.00158866 |

A_alt-H_alt utility was positive for all three seeds. A_alt-A_joint utility
was negative for all three. H_alt-H_joint was mixed: seed11 **+.000893954733**,
seed23 -.002661160182, seed47 -.002591397032 (mean -.001452867494).
The previous report sentence claiming H was negative for every seed was a
reporting error, corrected from the unchanged saved arrays; no model, endpoint,
interval, budget or readiness decision was changed. Maximum required greedy
drop.00390625 stayed within.02, and all12 corruption drops were positive;
neither can substitute for the failed raw utility/success requirements.

Current-wave complete CPU-net A_alt−A_joint was **−.00198287**, conditional on
one timing wave. Whole-group nine-candidate build cost is divided among three
selected models/H100000 and priced at.02. Old CPU prices belong to another
wave and are not compared for a cross-wave win. Strong old A/H quality endpoints
were reused from their saved raw arrays without re-evaluating those models.

The sole builder exited0 (execution/cap success); the prespecified analysis
exited**2**, `train_readiness=false`. The scientific terminal result is failed
readiness, not a qualified generation improvement. No replacement run occurred.

## Retained evidence and scope

Actual commands ran in `/workspace/hepta-private-ci/qualification/joint-generation`:

```sh
python3 -m content_block.run freeze --out content_block/frozen-train-v1.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m content_block.run train --out runs/content-block-train-v1-20261023 --freeze content_block/frozen-train-v1.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m content_block.analyze runs/content-block-train-v1-20261023
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. python3 runs/content-block-train-v1-20261023/audit_saved.py
```

Original command argv, stdout/stderr, source commits, execution0 and analysis2
exits are retained beside the run. Environment: cloud hostnameaa01407f34e9,
Python3.12.14/NumPy2.3.5, one BLAS/OMP/MKL thread, GCC14.2.0. Physical new build
CPU was15.905149941 seconds before final receipt; inherited preparation is not
double-counted as newly executed research. Separate descriptive analysis CPU
.917913537 and read-only evidence audit.486874992 are retained. Unit/test/tool
setup and uninstrumented authoring/administrative costs are not called equal
cumulative research spending. The run retains about17.7 MB, with no duplicate
base/data tensor copies. `just fmt` found no applicable formatting group;
`git diff --check` passed. No Rust source changed.

Review [protocol](PROTOCOL.md), [full budget/candidates](../runs/content-block-train-v1-20261023/build.json),
[raw TRAIN outputs](../runs/content-block-train-v1-20261023/train-result.json),
[analysis](../runs/content-block-train-v1-20261023/analysis.json), and
[gradient/moment/unit/PNG audit](../runs/content-block-train-v1-20261023/evidence-audit.json).
Every candidate model, first/last gradient by block type, actual delta, all
losses and final moments/clocks is preserved in its candidate directory. This
state evidence does not export the RNG or promise resumable training.

There is no runtime/permission blocker. The failed fixed1:1 recipe is not
expanded or retuned. Earlier refiner rejection, r2 dynamic failures and consumed
CORE c1 formal failure remain unchanged. Further scientific design/confirmation
is for the parent alongside NDU review; no new formal look is authorized here.

The later [saved-state mechanism diagnosis](MECHANISM_DIAGNOSIS.md) corrects the
H seed11 sign, compares all36 saved candidates, supplies TRAIN curves and
clearly labeled final inner LR endpoints, and limits encoder-bottleneck claims
to a hypothesis. It proposes one unrun weak head-anchor candidate under standard
joint updates. No new model execution accompanied that analysis.
