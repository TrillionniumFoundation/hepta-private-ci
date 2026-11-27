"""Strict optimizer-boundary restoration of an existing partial C2 epoch."""

import copy
import math


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_partial_state(state, fit, bound, train_rows, plan):
    """Validate the persisted work cursor without drawing RNG or executing a model."""
    require(isinstance(state, dict), "checkpoint mapping required")
    required = {"model", "model_configuration", "optimizer", "torch_rng", "order_rng",
                "epochs_completed", "main_updates", "data_manifest_sha256", "continuation_cursor"}
    require(set(state) == required, "complete partial checkpoint fields required")
    require(type(state["epochs_completed"]) is int and state["epochs_completed"] == fit["epoch"],
            "last complete epoch differs")
    require(type(state["main_updates"]) is int and state["main_updates"] == fit["main_updates"],
            "last completed optimizer age differs")
    optimizer = state["optimizer"]
    require(isinstance(optimizer, dict) and set(optimizer) == {"state", "param_groups"}
            and optimizer["state"] and optimizer["param_groups"], "complete AdamW state required")
    slots = [key for group in optimizer["param_groups"] for key in group["params"]]
    require(len(slots) == len(set(slots)) and set(slots) == set(optimizer["state"]),
            "every trainable parameter needs its unique AdamW slots")
    for item in optimizer["state"].values():
        require({"step", "exp_avg", "exp_avg_sq"} <= set(item)
                and float(item["step"]) == state["main_updates"], "AdamW moment/age missing or inconsistent")
    cursor = state["continuation_cursor"]
    require(cursor == bound["partial_cursor"], "partial cursor differs from archived terminal")
    require(cursor["schema"] == "hcsn-c2-mid-epoch-continuation-v2" and cursor["complete_epoch"] is False,
            "partial epoch schema required")
    require(type(cursor["current_epoch"]) is int and cursor["current_epoch"] == fit["epoch"] + 1,
            "partial epoch must follow the last complete epoch")
    order = cursor["episode_indices"]
    require(all(type(index) is int for index in order) and sorted(order) == list(range(len(train_rows))),
            "partial order must be a permutation of the full original population")
    require(cursor["episode_ids"] == [train_rows[index]["id"] for index in order],
            "partial order and original episode identities differ")
    require(cursor["batch_size"] == plan["batch_size"]
            and cursor["micro_batch_size"] == plan["micro_batch_size"], "original batch policy differs")
    completed = cursor["completed_effective_batches"]
    require(type(completed) is int and 0 < completed < bound["steps_per_epoch"],
            "strictly interior completed batch count required")
    require(type(cursor["next_episode_offset"]) is int
            and cursor["next_episode_offset"] == completed * plan["batch_size"] < len(order),
            "cursor must point to the next complete effective batch")
    require(state["main_updates"] == fit["epoch"] * bound["steps_per_epoch"] + completed,
            "optimizer age and partial batch count disagree")
    losses = cursor["completed_batch_objectives"]
    require(len(losses) == completed, "all completed batch objectives required")
    for number, loss in enumerate(losses):
        ids = order[number * plan["batch_size"]:(number + 1) * plan["batch_size"]]
        require(type(loss["events"]) is int and loss["events"] == sum(len(train_rows[i]["y"]) for i in ids),
                "completed objective population differs")
        require(all(math.isfinite(loss[name]) for name in
                    ("loss", "target_weight_sum", "weighted_loss_numerator"))
                and loss["target_weight_sum"] > 0
                and loss["weighted_loss_numerator"] == loss["loss"] * loss["target_weight_sum"],
                "completed weighted objective is incomplete")
    return copy.deepcopy(cursor)


def with_cursor(snapshot, cursor):
    snapshot["continuation_cursor"] = copy.deepcopy(cursor)
    return snapshot
