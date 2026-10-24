"""Print the frozen sequential, alternating paired order; execute nothing."""

import hashlib
import json

import pack

SEED = "hepta-native-codex-ab-20261024-v1"


def order_key(kind, identity):
    return hashlib.sha256(f"{SEED}\0{kind}\0{identity}".encode()).hexdigest()


def assignment():
    grouped = {}
    for task in pack.read_index()["tasks"]:
        grouped.setdefault(task["family_id"], []).append(task)
    if len(grouped) != 4 or any(len(tasks) != 2 for tasks in grouped.values()):
        raise ValueError("registered assignment requires four two-task families")
    result = []
    for family in sorted(grouped, key=lambda value: order_key("family", value)):
        tasks = sorted(grouped[family], key=lambda task: order_key("task", task["task_id"]))
        for within_family, task in enumerate(tasks):
            arms = ["native", "codex"] if within_family == 0 else ["codex", "native"]
            pair = 1 + len(result) // 2
            for arm in arms:
                result.append({"ordinal": len(result) + 1, "pair": pair,
                               "family_id": family, "task_id": task["task_id"],
                               "slug": task["slug"], "arm": arm})
    return {"schema": "hepta.native-ab.assignment.v1", "seed": SEED,
            "sequential_only": True, "attempts": result,
            "decisions_depend_on_model_outputs": False}


if __name__ == "__main__":
    print(json.dumps(assignment(), sort_keys=True, separators=(",", ":")))
