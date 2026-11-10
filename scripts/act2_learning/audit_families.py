"""Independently read retained physical filesystem effects and the full panel."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

from diagnose import require


def audit(directory):
    frozen = json.loads((directory / "FROZEN_MANIFEST.json").read_text())
    with gzip.open(directory / "episodes.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    tasks = {t["id"]: t for t in frozen["tasks"]}
    expected = {
        (seed, arm, task)
        for seed in frozen["seeds"]
        for arm in frozen["arms"]
        for task in tasks
    }
    keys = [(row["seed"], row["arm"], row["task_id"]) for row in rows]
    require(
        len(keys) == len(expected) and set(keys) == expected,
        "incomplete or duplicate family panel",
    )
    checked = 0
    with tarfile.open(directory / "destination-bytes.tar.xz", "r:xz") as archive:
        members = {m.name: m for m in archive if m.isfile()}
        require(
            len(members) == sum(m.isfile() for m in archive.getmembers()),
            "duplicate archive member",
        )
        for row in rows:
            task = tasks[row["task_id"]]
            require(
                0 <= row["primitive_calls"] <= row["budget"],
                "primitive budget exceeded",
            )
            require(
                task["family"] == row["family"] and task["version"] == row["version"],
                "panel binding mismatch",
            )
            prefix = "destinations/" + row["destination_member"]
            if task["family"] != "composition":
                groups = [(prefix, row, task, list(range(len(task["goals"]))))]
            else:
                groups = []
                for offset, family in enumerate(("filesystem", "browser")):
                    indices = list(range(offset, len(task["goals"]), 2))
                    child_task = dict(
                        task,
                        id=task["id"] + "/component/" + family,
                        goals=[task["goals"][i] for i in indices],
                    )
                    groups.append(
                        (
                            prefix + "/" + family,
                            row["children"][family],
                            child_task,
                            indices,
                        )
                    )
            all_actual = {}
            for path, facts, child_task, indices in groups:
                actual, seen = {}, set()
                for record in facts["effect_records"]:
                    invocation = record["invocation"]
                    key = record["key"]
                    require(
                        type(key) is int
                        and 0 <= key < len(child_task["goals"])
                        and record["task_id"] == child_task["id"]
                        and record["version"] == child_task["version"],
                        "effect task or version binding mismatch",
                    )
                    require(
                        key not in seen
                        and invocation == child_task["id"] + ":" + str(key),
                        "duplicate or foreign effect",
                    )
                    seen.add(key)
                    name = (
                        path
                        + "/effects/"
                        + hashlib.sha256(invocation.encode()).hexdigest()
                    )
                    intent = json.loads(
                        archive.extractfile(members[name + "/intent.json"]).read()
                    )
                    raw = archive.extractfile(members[name + "/value"]).read()
                    require(
                        intent == record
                        and hashlib.sha256(raw).hexdigest() == record["sha256"],
                        "retained effect digest mismatch",
                    )
                    goal = (
                        raw.decode()
                        if child_task["version"] == 1
                        else json.loads(raw)["content"]
                    )
                    require(
                        goal == child_task["goals"][key],
                        "retained effect goal mismatch",
                    )
                    actual[key], all_actual[indices[key]] = goal, goal
                    checked += 1
                require(
                    sum(
                        n.startswith(path + "/effects/") and n.endswith("/intent.json")
                        for n in members
                    )
                    == len(seen),
                    "unreported effect",
                )
                require(
                    facts["effect_count"] == len(actual)
                    and facts["duplicate_effects"] == 0,
                    "effect accounting mismatch",
                )
            complete = all(
                all_actual.get(i) == goal for i, goal in enumerate(task["goals"])
            )
            require(
                complete == row["complete"]
                and not (row["claimed_success"] and not complete),
                "false completion report",
            )
    return {
        "status": "RETAINED_EFFECT_AUDIT_PASS",
        "episodes": len(rows),
        "effect_payloads_checked": checked,
        "controlled_probe_tasks": len(tasks),
        "new_independent_real_tasks": 0,
        "archive_sha256": hashlib.sha256(
            (directory / "destination-bytes.tar.xz").read_bytes()
        ).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), indent=2))
