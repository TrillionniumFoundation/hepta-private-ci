"""Matched-capacity candidate Cell fission experiment using Hepta's real fit.

No model weights or gold heldout imported. Two Heads trained on separate
TRAIN source-family groups are compared with exactly two identical-geometry
Heads trained on all TRAIN rows under equal physical optimizer budgets.

The unsplit control retains two Heads but *does not partition tasks*: this
deliberately equalizes independent parameters and inference calls. It does not
claim that twin unspecialized Heads are a universal best unsplit architecture.
"""
from __future__ import annotations

from copy import deepcopy

import torch

from experiments.shared_stem_cell.execution import fit, parameters, measured
from amcn_core import digest, require, shadow_disposition
from amcn_learning import FeatureMatrix


def matched_fission(parent, matrix, train_labels, partition, *, steps=24, batch=2, seed=17):
    require(isinstance(matrix, FeatureMatrix)
            and isinstance(parent, torch.nn.Module), "physical shared Head required")
    require(type(steps) is int and 1 <= steps <= 256
            and type(batch) is int and 1 <= batch <= 16, "bounded matched trial")
    indices, all_labels = matrix.train_labels(train_labels)
    require(isinstance(partition, dict)
            and set(partition) == {matrix.rows[i].row_id for i in indices}
            and set(partition.values()) == {0, 1}
            and all(type(v) is int for v in partition.values()), "TRAIN-only two-family partition")
    buckets = {0: [], 1: []}
    for i in indices:
        buckets[partition[matrix.rows[i].row_id]].append(i)
    require(all(len(v) >= batch for v in buckets.values()), "each sibling must fill same minibatch")
    # A source root can never contribute to both sibling labels.
    owners = {}
    for i in indices:
        source, group = matrix.rows[i].source_root, partition[matrix.rows[i].row_id]
        require(source not in owners or owners[source] == group,
                "split cannot divide an individual source lineage")
        owners[source] = group
    require(all(len({matrix.rows[i].source_root for i in bucket}) >= 2
                for bucket in buckets.values()), "at least two independent-looking training roots per branch")
    before = parameters(parent)
    # Both arms contain exactly two same-architecture, same-initialization
    # physical Heads; only the TRAIN selection differs.
    results, receipts = {}, {}
    with measured() as total:
        for arm in ("split_by_training_group", "unsplit_equal_capacity"):
            heads, work = [], []
            for group in (0, 1):
                selected = buckets[group] if arm == "split_by_training_group" else indices
                y = torch.tensor([train_labels[matrix.rows[i].row_id] for i in selected],
                                 dtype=torch.long)
                model, cost = fit(deepcopy(parent), matrix.x[selected], y,
                                  steps=steps, seed=seed + group, batch=batch)
                heads.append(model)
                work.append(cost)
            require(all(parameters(h)["parameters"] == before["parameters"] for h in heads),
                    "candidate parameter drift")
            results[arm] = heads
            receipts[arm] = {
                "heads": [parameters(h) for h in heads],
                "physical_steps": sum(x["steps"] for x in work),
                "physical_examples_processed": sum(x["examples_processed"] for x in work),
                "work": work,
                "logical_parameter_count": 2 * before["parameters"],
                "simultaneously_live_head_bytes": 2 * before["parameter_bytes"],
            }
    for field in ("physical_steps", "physical_examples_processed",
                  "logical_parameter_count", "simultaneously_live_head_bytes"):
        require(receipts["split_by_training_group"][field] ==
                receipts["unsplit_equal_capacity"][field], "unequal-budget arms")
    require(parameters(parent) == before, "original parent must remain frozen")
    unlabeled = []
    with torch.no_grad():
        for i, row in enumerate(matrix.rows):
            output = {"row_id": row.row_id, "split": row.split,
                      "family": row.family, "input_sha256": row.input_sha256}
            for arm, heads in results.items():
                scores = (heads[0](matrix.x[i:i + 1]) +
                          heads[1](matrix.x[i:i + 1])) * 0.5
                output[arm] = float(scores.softmax(-1)[0, 1].item())
            unlabeled.append(output)
    return {
        "trained_models": results, "predictions": unlabeled,
        "receipt": shadow_disposition(
            profile="hepta.amcn.equal-head-budget-candidate-fission.v1",
            immutable_features_sha256=matrix.identity,
            immutable_parent_sha256=before["sha256"],
            training_partition_sha256=digest(partition),
            same_initialization=True, exact_trainable_parameters_equal=True,
            model_execution_calls_equal=True,
            before_any_future_task_judgment=True,
            local_source_groups_not_independently_attested=True,
            old_task_retention_independently_established=False,
            future_task_superiority_established=False,
            prediction_sha256=digest(unlabeled),
            total_meter=total, arms=receipts)
    }
