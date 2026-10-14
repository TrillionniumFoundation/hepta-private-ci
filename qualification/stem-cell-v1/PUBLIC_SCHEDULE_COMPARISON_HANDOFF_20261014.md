# Fixed-update versus fixed-formula-budget public learning

Remote parent: `c67a589d936be7d060d56220c9c2921087da6bd0` (#1873).
Tested code branch: `research/shared-stem-public-schedule-comparison-20261014`.
Code head before evidence files: `14decc2e575264efa4a51d07110b9017c11c7133`.
Research-only change. No main merge, model selection, deployment, production approval,
historical-result rewrite, matrix-NDU activation or native topology installation.

## Why this comparison is needed

The earlier public experiment held update count and nominal minibatch exposure fixed,
but its dense and sparse banks consumed very different formula work. The subsequent
study held observed training formula work within one percent, but allowed each arm
to complete as many whole updates and see as many repeated examples as its update
cost permitted. Those are different estimands:

- fixed update count is not fixed compute;
- fixed compute is not fixed data exposure;
- neither design by itself identifies a pure topology effect.

`public_schedule_comparison.py` consumes two already sealed studies. It performs no
training, retry, quality stopping or winner selection. It requires the same fixed
sample selection, input identities, frozen feature bytes, training-label digest,
model snapshot, selected material, seed and all non-schedule controls. It then
rescored both studies with one label vector through the existing sealed scorer.

For each topology it retains update count, repeated example exposure, observed
training work, accuracy, Brier score, and exact per-row recovered/lost answers,
both overall and by class. Failed arms remain unavailable with their denominator;
they are not converted to zero-quality successful models. Mutated weights,
predictions, selection, features, labels, model material or external seal IDs are
rejected. Aggregate class totals from old artifacts are not reverse-engineered
into fictitious paired rows.

The hosted workflow now runs the prospective schedule comparison immediately after
both public studies and uploads its sealed comparison. The comparison does not add
a third training run or load another Encoder.

## Actual earlier fixed-budget observation recovered

Workflow `38527514995`, job `115746324658`, artifact `11881136088` completed on
source head `3b3077c3a7e17ac0c7c9ad99c9e456ca0e31f91d` and actual checkout
`2a2ca5dfac440018a598ff509bd28d0db2b7aa5e`. The original artifact ZIP SHA256 is
`7b27b0e781da31ba932168b27012e68cf90ece69408c197cfdd15e22da2ee49e`.
Inner seals, study files, selected input identities, feature and label digests and
per-arm work records were checked. The run used one frozen ModernBERT checkpoint,
64 training rows, 64 held-out rows, seed 7347 and a five-billion formula-work cap
per arm.

| Topology | Fixed 32 updates | Fixed formula budget | Budget updates | Repeated examples | Observed train work |
|---|---:|---:|---:|---:|---:|
| dense16 | 39/64 | 44/64 | 77 | 1,212 | 4,967,050,046 |
| sparse16 | 38/64 | 42/64 | 452 | 7,217 | 4,964,303,557 |
| direct32 | 38/64 | 51/64 | 681 | 10,874 | 4,964,192,428 |

The budgeted arms' observed training work differs by about 0.0575%, with no dummy
padding. Direct32 improved by 13 answers relative to its own fixed-update result,
but also performed 649 more updates and 10,362 more repeated sample exposures.
Sparse16 gained four answers while its Brier score worsened. These observations
show that schedule matters; they do not isolate topology, prove statistical
superiority, or establish independent generalization. One seed and 64 held-out
rows are insufficient for those claims.

The original hosted artifact did not upload raw labels or retained bank weights,
so this retrospective evidence records verified aggregate outcomes and costs only.
It does not invent exact recovered/lost row identities. The new prospective
workflow produces those paired transitions while it still has the common label
vector and sealed predictions.

## Cost interpretation

The five-billion limit covers measured bank initialization/training work under the
registered CPU FP32 formula profile. Shared train/test feature encoding, initial
control predictions, final inference, scoring, publication, Python work, memory,
energy and service latency remain separately scoped. A fixed-budget Head result
therefore is not a full-system fixed-budget result. More updates under the same
Head budget are a legitimate fixed-compute estimand, not a fixed-exposure ablation.

## Verification actually performed

The implementation-equivalent local source passed 494 distinct planned/executed
tests twice in four complete partitions: 188 + 69 + 197 + 40. Both inventories
were identical, with zero failures, errors, skips, expected failures or discovery
errors. Before publication, the exact remote module/test/workflow bytes were
reconstructed locally and their Git blob IDs matched:

- `public_schedule_comparison.py`: `1e58abe147bbc11f5c6e45c778b5c0b1e341c5ac`;
- `test_public_schedule_comparison.py`: `045691015cfd0fe51441f3dda3cee62f4b0b2599`;
- workflow: `0cb7c4384e9ab31f1532ff5c61ecb68f05deacaf`.

The seven new tests on those exact bytes passed twice. Compileall, YAML parsing and
trailing-whitespace checks passed. Two foreground whole-suite attempts were cut off
by the execution wrapper and are retained as interrupted attempts, not successful
runs. A later parallel exact-byte whole-suite attempt was likewise interrupted;
it is not added to the 494-test evidence. Hosted CI on the published exact bytes
is the remaining exact-environment confirmation and must be read against its own
head and checkout.

## Acceptance boundaries

This change adds descriptive cross-schedule evidence, not another learner. It does
not establish causality, noninferiority, contamination freedom, independent
replication, energy savings, equal total service cost, longitudinal retention,
multigeneration splitting, NDU/SYSTEM2 benefit, multimodal generation, or
1024/4096-Cell scale. Public-data research-use terms are not production approval.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/nonexisting/tests.json
```
