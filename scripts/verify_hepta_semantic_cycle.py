#!/usr/bin/env python3
"""Independently check semantic evidence without executing models or task source."""

import argparse
import json
from pathlib import Path

import numpy as np

from verify_hepta_maintenance_cycle import (
    canonical,
    require,
    review as review_originals,
    sha,
)


def fixed_cold_task():
    return dict(
        id="fixture_D_cold",
        entry="fixture_D_cold",
        source="def fixture_D_cold(x)\n    return x + 409\n",
        checks=[dict(args=[x], expected=x + 409) for x in (-13, 2, 23)],
        provenance=dict(
            origin="controlled-generated-template",
            family="expected ':'",
            split="D-cold",
        ),
    )


def review_rows(plan, rows):
    require(plan["cold_task"] == fixed_cold_task(), "predeclared cold task changed")
    tasks = {task["id"]: task for panel in plan["panels"].values() for task in panel}
    tasks[plan["cold_task"]["id"]] = plan["cold_task"]
    require(
        len(tasks) == 25
        and len({sha(task["source"].encode()) for task in tasks.values()}) == 25,
        "cross-phase source or task identity overlap",
    )
    bindings = {}
    for task in tasks.values():
        phase = task["provenance"]["split"]
        binding = dict(
            input_source_sha256=sha(task["source"].encode()),
            checks_sha256=sha(
                canonical({key: task[key] for key in ("entry", "checks", "provenance")})
            ),
            provenance=task["provenance"],
        )
        bindings.setdefault(phase, {})[task["id"]] = binding
    require(
        bindings == plan["task_contracts"], "task behavior/source/split binding changed"
    )
    for row in rows:
        require(row["task"] in tasks, "outcome belongs to an unfrozen task")
        task = tasks[row["task"]]
        phase = task["provenance"]["split"]
        require(
            row["phase"] == phase or (row["phase"] == "A-retention" and phase == "A"),
            "observed outcome crossed a declared data split",
        )
        require(
            sha(row["source"].encode()) == row["source_sha256"],
            "candidate source digest differs",
        )
        allowed = {task["source"]}
        for action in range(4):
            lines = task["source"].splitlines()
            if action == 0 and not lines[0].endswith(":"):
                lines[0] += ":"
            elif action == 1:
                lines[-1] += ")"
            elif action == 2:
                lines[-1] += '"'
            elif action == 3:
                lines[-1] = "    " + lines[-1].lstrip()
            allowed.add("\n".join(lines) + "\n")
        require(
            row["source"] in allowed,
            "observed source is outside the frozen repair actions",
        )
        semantic = row["semantic"]
        require(
            all(
                semantic[key] == value
                for key, value in bindings[phase][task["id"]].items()
            ),
            "semantic outcome is bound to another source or checks",
        )
        require(
            type(row["compile_success"]) is bool and type(row["success"]) is bool,
            "ambiguous success value",
        )
        if not row["compile_success"]:
            require(
                semantic["status"] == "not_run_compile_error"
                and semantic["success"] is False
                and row["success"] is False,
                "compile failure was promoted to semantic success",
            )
            continue
        require(
            semantic["source_sha256"] == row["source_sha256"],
            "executed candidate differs",
        )
        for field, maximum in (("stdout", 65536), ("stderr", 4096)):
            raw = semantic[field].encode()
            require(
                semantic[field + "_bytes"] <= maximum
                and len(raw) == semantic[field + "_bytes"]
                and sha(raw) == semantic[field + "_sha256"],
                "raw semantic output missing or changed",
            )
        passed = False
        if "child" in semantic:
            child = json.loads(semantic["stdout"])
            require(
                child == semantic["child"]
                and semantic["returncode"] == 0
                and child["status"] == semantic["status"]
                and semantic["child_source_compile_attempted"]
                is child.get("compile_attempted"),
                "child original differs from outcome",
            )
            observed = child["checks"]
            require(
                len(observed) <= len(task["checks"]), "unexpected semantic check count"
            )
            for actual, expected in zip(observed, task["checks"]):
                require(
                    actual["passed"]
                    is (
                        canonical(actual["observed"]) == canonical(expected["expected"])
                    ),
                    "semantic pass does not match actual output",
                )
            passed = (
                child["status"] == "passed"
                and child["compile_attempted"] is True
                and len(observed) == len(task["checks"])
                and all(check["passed"] for check in observed)
            )
            require(
                (child["status"] == "passed") is passed,
                "incomplete checks claimed success",
            )
        require(
            semantic["success"] is passed and row["success"] is passed,
            "compile pass or unverified child was promoted to semantic success",
        )


def review_served(row, cell, task):
    """Bind the decision and executed repair to the original native response."""
    require(
        type(row["action"]) is int and 0 <= row["action"] < 4, "invalid served action"
    )
    receipts = row["receipts"]
    outputs = [receipt["output"]["cell"] for receipt in receipts]
    if len(receipts) == 1 and "action" in outputs[0]:
        require(
            receipts[0]["request_id"] == task["id"] + "-diagnostic",
            "diagnostic request differs",
        )
        chosen = outputs[0]["action"]
    else:
        count = 4 if cell == "predictor" else 1
        require(len(receipts) == 3 + count, "temporal prediction schedule differs")
        require(
            [receipt["request_id"] for receipt in receipts]
            == [task["id"] + f"-event-{index}" for index in range(3)]
            + [task["id"] + f"-predict-{index}" for index in range(count)],
            "prediction request order or task binding differs",
        )
        logits = np.asarray(
            [output["logits"] for output in outputs[3:]], dtype=np.float64
        )
        require(
            logits.shape == ((4, 2) if cell == "predictor" else (1, 4))
            and np.isfinite(logits).all(),
            "invalid original native logits",
        )
        if cell == "predictor":
            probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
            chosen = int(np.argmax(probabilities[:, 1] / probabilities.sum(axis=1)))
            expected_action = np.eye(4)[chosen].tolist()
            expected_logits = logits[chosen].tolist()
        else:
            chosen = int(np.argmax(logits[0]))
            expected_action, expected_logits = [0.0], logits[0].tolist()
        require(
            row["predict_action"] == expected_action
            and row["chosen_logits"] == expected_logits,
            "chosen prediction differs from original native logits",
        )
    require(
        row["action"] == chosen, "served action differs from original native output"
    )
    lines = task["source"].splitlines()
    if chosen == 0 and not lines[0].endswith(":"):
        lines[0] += ":"
    elif chosen == 1:
        lines[-1] += ")"
    elif chosen == 2:
        lines[-1] += '"'
    elif chosen == 3:
        lines[-1] = "    " + lines[-1].lstrip()
    require(
        row["outcome"]["source"] == "\n".join(lines) + "\n",
        "executed repair source differs from selected native action",
    )


def review_training_data(plan, rows, data):
    """Reconstruct A features and labels from the original, task-bound observations."""
    tasks = plan["panels"]["A"]
    expected_ids = {task["id"] for task in tasks}
    require(
        all(
            set(data[key]) == expected_ids
            for key in ("observations", "episodes", "labels")
        ),
        "training data contains non-A task identities",
    )
    tokens = (
        "expected ':'",
        "was never closed",
        "unterminated string",
        "expected an indented block",
    )
    for task in tasks:
        originals = [
            row
            for row in rows
            if row["task"] == task["id"]
            and row["arm"] == "observation"
            and row["phase"] == "A"
        ]
        acquired = [
            row
            for row in rows
            if row["task"] == task["id"] and row["arm"] == "acquisition"
        ]
        require(
            len(originals) == 1
            and len(acquired) == 4
            and originals[0]["source"] == task["source"],
            "training observation/acquisition schedule differs",
        )
        original = originals[0]
        require(
            data["observations"][task["id"]] == original
            and data["labels"][task["id"]] == [row["success"] for row in acquired],
            "training labels do not match original semantic outcomes",
        )
        source = task["source"]
        features = [
            len(source) / 128,
            len(source.splitlines()) / 4,
            (source.count("(") - source.count(")")) / 4,
            source.count('"') % 2,
            source.count(":") / 4,
            int(source.splitlines()[-1].startswith("    ")),
            0,
            0,
            0,
            0,
            1,
            0,
            0,
        ]
        expected = [
            features,
            [0.0] * 6
            + [float(token in original["error"]) for token in tokens]
            + [0, 1, 0],
            [0.0] * 12 + [1.0],
        ]
        require(
            data["episodes"][task["id"]] == expected,
            "training features are not the original A-only observations",
        )


def review(directory):
    result = review_originals(directory, semantic=True)
    result["base_verifier_sha256"] = result["verifier_sha256"]
    result["verifier_sha256"] = sha(Path(__file__).read_bytes())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.directory), sort_keys=True, indent=2, allow_nan=False))
