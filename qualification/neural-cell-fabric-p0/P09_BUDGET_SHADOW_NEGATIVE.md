# P0.9: Negative result for a budgeted, label-blind Cell decision portfolio

**RESEARCH ONLY · DRAFT · DENY_ALL · HOLD_NO_GO · NO MODEL SELECT · NO MAIN MERGE · NO FINALUSE · NO PHYSICAL CELL SPLIT.**

## Immutable evidence and relation to P0.8

This is an **additive stacked shadow control** on P0.8. It does **not** edit the
queued real P0.8 cross-publisher mmBERT producer, selected Stem, existing Rust
Neuron/Worker/NDU/Control/CAS/CNS/FinalUse owners or global CI gates.

P0.8's fresh 564 MB pinned mmBERT and 87.3 MB original HuffPost source run
must finish independently; **P0.9 does not run that model**. P0.9 reuses the
byte-pinned historical mmBERT-small AG News original 128×384 FP32 feature
archive `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`
from hosted run `38546717991` and the existing P0.6 source/reviewer implementation.
The original Encoder physically computed those features in an earlier study,
not here. P0.9 physically reruns P0.6 Head training and independently replays
its arithmetic in the reviewer. The original 32 test labels were historically
exposed before the new P0.9 heuristic was designed; this is **not a
preregistered prospective test** despite the local producer/reviewer isolation.

## Fixed shadow policy

A training-label-blind decision procedure examines the original **prelabel**
P0.6 probabilities for `centroid_train_loo`, `split` and `shared_one` and selects:

* `centroid_fast` if centroid max probability >=0.65;
* `split_shadow` if split max >=0.55 and exceeds centroid max by more than 0.08;
* `shared_shadow` if shared max >=0.55 and exceeds centroid max by more than 0.10;
* `stop_shadow` if centroid max <0.38;
* otherwise `centroid_uncertain`.

It never consumes the original heldout gold or uses any capability/permission.
All thresholds, permitted arms and status are hashed into the policy lineage.
They are a *post-hoc illustrative choice*, not NDU coefficients and not
optimized on future observations. The external task objective cannot change.

## Actual local historical original result

Original P0.6 64 FIT, 32 heldout, 32 excluded CAL. Three seeds each pay 512
SGD updates for the independent original trained Head arms. In the P0.9
counterfactual selection the actual prior study already evaluated every
available Head. The reported optional per-request Head counts are **logical**
and no measured CPU latency, new Encoder forwards, GPU energy, JIT or MCP calls
may be subtracted from them.

| Seed | Chosen correct / 32, STOP wrong | Centroid baseline correct / 32 | Answered / 32 | Optional logical Head requests | Paired shadow-only vs centroid-only |
|---|---:|---:|---:|---:|---:|
| 101 | 22 | **28** | 32 | 17 | 1 vs 7 (nominal p 0.0703125) |
| 211 | 20 | **28** | 22 | 0 | 0 vs 8 (nominal p 0.0078125) |
| 307 | 20 | **28** | 22 | 0 | 0 vs 8 (nominal p 0.0078125) |

These three seeds share the *same correlated 32 cases*, so they are not
96 independent test items. A high selective accuracy after stopping is not a
higher complete-task success rate. The policy did **not** outperform the strong
train-only calibrated centroid under the declared stop-as-incorrect score.
No cross-publisher, future source family, human/source gold issuer or independent
physical resource advantage is established. Scientific disposition stays
`HOLD_NO_GO` regardless of CI color.

## Reproducible three-process local protocol

From `qualification/neural-cell-fabric-p0` after authentic material download:

```
python matched_router_p06.py source --archive /private/original.zip --output /private/source.json
python matched_router_p06.py producer --source /private/source.json --prelabel /private/prelabel.json --seal /private/prelabel-seal.json
python p09_budgeted_shadow.py propose --source /private/source.json --prelabel /private/prelabel.json --seal /private/prelabel-seal.json --shadow /private/shadow.json --shadow-seal /private/shadow-seal.json
python p09_budgeted_shadow.py review --archive /private/original.zip --source /private/source.json --prelabel /private/prelabel.json --seal /private/prelabel-seal.json --shadow /private/shadow.json --shadow-seal /private/shadow-seal.json --out /private/anonymous-summary.json
```

The shadow proposer verifies the P0.6 original model prelabel SHA before
computing any action. A separate reviewer verifies the immutable shadow receipt,
reproduces the decisions, reopens the original 128 authentic features and
independently replays 12 learned Head forward sets (672 numerical probabilities)
before opening the historical heldout original publisher labels. Source-only
unit fixtures are never called original inference. The hosted workflow exports
only the aggregate report, not labels, features, case IDs or model weights.

## Next scientific acceptance

Finish P0.8's **actual same-weights AG News/HuffPost original CPU inference**,
check its cross-publisher label ontology and published after-seal results, and
only then test any genuinely preregistered policy on a separately sourced
future-time cohort with independent outcome custody and actual incremental
CPU/GPU energy + latency receipts. No learned NDU/System2 or physical Cell Split
can be selected from this post-hoc negative baseline.
