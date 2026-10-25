"""Frozen policy selection, then offline observation of its committed outputs."""

from collections import Counter
import gzip
import json
from pathlib import Path
import time

import torch

from .control import PLANS, PLAN_INDEX, feedback_paths
from .episodes import root_frame
from .planning import mpc_actions
from .training_run import write_json
from .trees import stable_seed


@torch.no_grad()
def select_public_paths(model, public_data, bundle, *, extended, training_seed):
    """No metric or Target is read here; offline oracles are a separate function."""
    features = public_data["features"]
    n = len(features)
    selected = {
        "fixed": torch.full((n,), PLAN_INDEX[("refine_image", "refine_text")], dtype=torch.long),
        "tuned_static": torch.full((n,), bundle["static"]["plan_index"], dtype=torch.long),
        "feedback": feedback_paths(bundle["feedback"], features),
    }
    work = Counter()
    if extended:
        for name, policy in bundle["profiles"].items():
            selected[name] = feedback_paths(policy, features)
        selected["one_shot_route"] = bundle["route"].choose(features[:, 0])
        selected["semantic_couple_fixed"] = torch.full((n,), PLAN_INDEX[("refine_semantic", "couple")], dtype=torch.long)
        first = []
        for start in range(0, n, 64):
            indices = torch.arange(start, min(start + 64, n))
            frame = root_frame(public_data, indices)
            first.append(mpc_actions(model, frame, bundle["feedback"],
                                     stable_seed("planning", training_seed), work=work))
        first = torch.cat(first)
        plans = torch.zeros(n, dtype=torch.long)
        for action in range(1, 5):
            indices = torch.nonzero(first == action).flatten()
            if len(indices):
                second = bundle["feedback"].choose(features[indices, action], 1)
                plans[indices] = torch.where(second == 0, action, 5 + 4 * (action - 1) + second - 1)
        selected["independent_random_stream_MPC"] = plans
    if any(value.shape != (n,) or value.dtype != torch.long or (value < 0).any() or (value >= 21).any()
           for value in selected.values()):
        raise ValueError("A public policy returned an invalid continuation program")
    return selected, dict(work)


def offline_primary_oracles(data, action_cost=.002):
    """Finite realized diagnostic upper bounds; never used to train a policy.

    Both choices use privileged primary outcomes. Re-scoring their choices with
    the secondary observer is a useful check, not that observer's upper bound.
    Materializing all branches is a separately measured diagnostic expense.
    """
    values = data["metrics"]["primary"]["utility"].double()
    values = values - torch.tensor([action_cost * len(plan) for plan in PLANS])
    allocation = torch.tensor([all(action in {"refine_image", "refine_text"} for action in plan)
                               for plan in PLANS])
    return {"oracle_primary": values.argmax(1),
            "oracle_primary_allocation": values.masked_fill(~allocation[None], -float("inf")).argmax(1)}


def projected_rows(data, selected, *, seed, arm, tree_directory, action_cost=.002):
    """Each policy references the original actual output; replay is not a new source."""
    for name, indices in selected.items():
        if len(indices) != len(data["cases"]):
            raise ValueError("Policy choice does not cover the full source/view/scenario census")
        for i, node in enumerate(indices.tolist()):
            path = PLANS[node]
            metrics = {observer: {key: float(value[i, node]) for key, value in fields.items()}
                       for observer, fields in data["metrics"].items()}
            for fields in metrics.values():
                fields["net_utility"] = fields["utility"] - action_cost * len(path)
            yield {"seed": seed, "arm": arm, "policy": name, "case": data["cases"][i],
                   "view": data["views"][i], "scenario": data["scenarios"][i],
                   "source_ids": data["source_ids"][i], "path": list(path), "continuation_actions": len(path),
                   "tree_directory": str(tree_directory), "tree_row_index": i, "plan_index": node,
                   "selection_is_privileged_offline_oracle": name.startswith("oracle_"),
                   "observers": metrics}


def intervention_rows(data, *, seed, arm, directory, action_cost=.002):
    for i in range(len(data["cases"])):
        metrics = {observer: {key: float(value[i]) for key, value in fields.items()}
                   for observer, fields in data["metrics"].items()}
        for fields in metrics.values():
            fields["net_utility"] = fields["utility"] - action_cost * len(data["path"])
        yield {"seed": seed, "arm": arm, "policy": data["profile"], "case": data["cases"][i],
               "view": data["views"][i], "scenario": data["scenarios"][i],
               "source_ids": data["source_ids"][i], "path": data["path"],
               "continuation_actions": len(data["path"]), "intervention_directory": str(directory),
               "tree_row_index": i, "selection_is_privileged_offline_oracle": False, "observers": metrics}


def save_selection(path, selected, work):
    write_json(path, {"schema": "hepta.abc.frozen-public-policy-choices.v1",
                     "selection": {name: values.tolist() for name, values in selected.items()},
                     "MPC_actual_planning_work": work,
                     "oracle_choices_must_be_written_separately": True})
