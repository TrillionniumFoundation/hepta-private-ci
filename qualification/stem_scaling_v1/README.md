# P5: five-axis Stem/Cell scaling falsification (research only)

**Posture:** `DRAFT / DENY_ALL / NO_MODEL_SELECTION / NO_10T_OR_100T_EQUIVALENCE`.

This is a strictly additive child of [P4 original 15-process physical CPU/RSS audit PR #2260](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2260), which must retain its entire original original-weight/head/route negative-control lineage. This small evaluator **does not** execute a new pretrained Encoder, train a new Head, read external labels, verify GitHub-host attestations, or make a production / capability claim.

## What actually executes

`scaling_frontier.py` accepts a bounded, strict JSON candidate series and audits five **independent one-axis experiments**:

| Varied axis | Required 4-level profile |
| --- | --- |
| logical_cells | 64, 256, 1024, 4096 |
| active_cells | 1, 2, 4, 8 |
| reasoning_depth | 1, 2, 4, 8 |
| train_rows | 32, 64, 128, 256 |
| compute_budget_ns | 250000, 500000, 1000000, 2000000 |

For each axis, every other resource axis, model SHA, sealed source and original held-label source SHA, evaluator SHA, arm, seed, denominator and distinct source-group count must stay **identical**. A complete four-level panel is required; missing or altered stages are omitted, not imputed. Unique trial identities cannot repeat, and inconsistent or duplicate axis levels are rejected.

For a valid full panel it fits a purely descriptive linear quality-on-log-axis relation on the first three recorded levels and evaluates the fourth observed level, retaining its error and *actual submitted* training CPU, inference CPU, Encoder-forward and peak-RSS series. It does **not** extrapolate to parameter counts, 10T/100T, unmeasured tasks or prospective outcomes.

The producer-provided `physical_work_observed` and `independent_score_receipt` boolean fields are **necessary candidate-shape checks but NOT cryptographic signatures**. Original measured process reports and real held labels must be independently authenticated by their own owners. In particular, using synthetic fixture rows to pass these contract tests is not evidence of model efficacy.

## Commands

```sh
PYTHONPATH=qualification/stem_scaling_v1 python3 -m unittest discover \
  -s qualification/stem_scaling_v1 -p 'test_scaling_frontier.py' -v
PYTHONPATH=qualification/stem_scaling_v1 python3 -O -m unittest discover \
  -s qualification/stem_scaling_v1 -p 'test_scaling_frontier.py' -v
python3 qualification/stem_scaling_v1/scaling_frontier.py \
  --input /independently/assembled/original-scores.json \
  --output /new/create-only/descriptive-scale-review.json
```

No training, evaluation label, source group, provenance SHA, RSS, or energy value may be filled by guesses. The original P4 report is **only a 15-process synthetic-feature physical resource observation** and contains no four-level, independently scored **new** full P5 scaling panel. Missing genuine panels remain **unproven**, never zero-effect passes.

## Subsequent acceptance (not claimed)

- Independent real pretrained original-source issuer + withheld-label scorer for all 4 points of each preregistered axis; separately measured model-load, training, inference, storage, queues and GPU/energy where claimed.
- Comparable no-change, matched-wide-Head, shared-Sparse, fixed Top-1, adaptive Split and independent-model controls; equal total budget and robust question/source-family grouping.
- Prespecified future OOD windows, retention/forgetting, independent teacher model outcomes and paired uncertainty. Three repeated seeds are not three independent source families.
- Source-HEAD and merge-tree CI, protected runtime owner security/FinalUse/revocation and separate human model selection if any improvement is eventually demonstrated.

Every output deliberately retains `source_outcomes_authenticated_externally=false`, `task_quality_winner_certified=false`, `complete_cost_pareto_certified=false`, `model_or_teacher_equivalence_certified=false`, `can_extrapolate_to_unmeasured_10t_100t=false`, `production_accepted=false` and `authority_posture=DENY_ALL`.

## 2026-10-15 held-scale uncertainty and plateau discipline

The fourth-point outcome now retains an explicitly **iid-only Wilson 95% descriptive interval**, an un-clipped forecast and an `prediction_outside_unit_interval` warning, the signed fourth-versus-third quality difference, and `plateau_claim_admitted=false`. Real candidate answers from the same question, shared passage or episode are correlated; the Wilson interval **does not** supply a valid independent passage/task-family confidence bound. A proper held-out cluster bootstrap or a preregistered randomization design on independent sources remains necessary. Even a zero fourth-minus-third observed gain does **not** establish a statistical plateau. New adversarial tests cover these claims; hosted checks on their *new* exact SHA are required and must not inherit old green status.
