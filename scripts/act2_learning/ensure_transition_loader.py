"""Read original ACT2 TRAIN ensure transitions; no effects, oracle or field claim.

Only the fixed original archive is admitted. An ensure is the existing stage/apply
option, not a learned multi-skill hierarchy. Labels come from subsequent original
actor readback. Missing readback stays censored even when a final oracle knew more.
"""

import argparse
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile


ORIGIN = "0584b3344f70ed51d9e09224e105bfa4d1a4635f"
PINS = {
    "SHA256SUMS.json": "16de01ad186843a08f115562ba6c3ade48ca43fe42b6c437399958d8cafb44df",
    "FROZEN_MANIFEST.json": "041b2b472a9ea366abacce273de43f19a59271c3d784328d4c5623d6f8436da9",
    "training-trajectories.jsonl.gz": "5512824dc9706ef8c5735eb94c6d500ec0a60ad42ea084db448398ab878b6eec",
    "source-postimages.zip": "8b2c18bbddf915e6f143d26871864d0ef27c657738d9f19198b4859f6e46d75c",
}
MAX_FILE = 262144
MAX_TRAIN = 524288


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def constant(_):
        raise ValueError("nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def event_witness(events, index):
    event = decode(canonical(events[index]))
    return {"index": index, "sha256": sha(canonical(event)), "event": event}


def _observation(value, count):
    if value is None:
        return
    require(
        isinstance(value, dict)
        and set(value) == {"complete", "index", "matched", "staged"},
        "readback fields differ",
    )
    require(
        type(value["complete"]) is bool and type(value["staged"]) is bool,
        "readback booleans differ",
    )
    require(
        all(
            type(value[k]) is int and 0 <= value[k] <= count
            for k in ("index", "matched")
        ),
        "readback index/count differ",
    )
    require(
        value["index"] <= value["matched"]
        and value["complete"] == (value["matched"] == count)
        and value["complete"] == (value["index"] == count),
        "inconsistent readback",
    )


def _episode(row, task, source):
    """Validate the pinned B1 execution grammar without using terminal score fields."""
    require(
        row.get("task_id") == task["id"] and row.get("arm") == "B1_macro",
        "original TRAIN identity or arm differs",
    )
    for key in ("schema", "destination", "composition", "fault"):
        require(row.get(key) == task[key], "TRAIN task metadata differs")
    events, decisions, features = (
        row["events"],
        row["decisions"],
        row["policy_visible_features"],
    )
    require(isinstance(events, list) and 1 <= len(events) <= 128, "event bound")
    require(
        isinstance(decisions, list)
        and 1 <= len(decisions) <= 128
        and isinstance(features, list)
        and len(features) == len(decisions),
        "decision bound",
    )
    require(
        type(row["primitive_calls"]) is int
        and row["primitive_calls"] == len(events)
        and row["policy_decisions"] == len(decisions),
        "observed call count differs",
    )
    previous_time = -1
    for event in events:
        require(
            isinstance(event, dict)
            and event.get("action") in ("inspect", "stage", "apply"),
            "unsupported original primitive",
        )
        keys = (
            {"action", "at_ns", "observation"}
            if event["action"] == "inspect"
            else {"action", "at_ns"}
        )
        require(
            set(event) == keys
            and type(event["at_ns"]) is int
            and event["at_ns"] >= max(0, previous_time),
            "event fields or order differ",
        )
        previous_time = event["at_ns"]
        if event["action"] == "inspect":
            _observation(event["observation"], len(task["goals"]))
    cursor, failed, ensures = 0, 0, []
    view, last, initiation = None, "start", None
    for decision_index, action in enumerate(decisions):
        feature = features[decision_index]
        expected = [
            int(view is not None),
            int(bool(view and view["complete"])),
            int(bool(view and view["staged"])),
            int(last == "ensure"),
            int(last == "inspect"),
            int(last == "stage"),
            int(last == "apply"),
            view["matched"] / len(task["goals"]) if view else 0,
            min(failed, 2) / 2,
            1,
        ]
        require(
            isinstance(feature, list)
            and len(feature) == 10
            and all(type(x) in (int, float) and math.isfinite(x) for x in feature)
            and feature == expected,
            "pre-decision feature is not the original actor view",
        )
        expected_action = (
            "stop"
            if failed >= 2
            else (
                "inspect"
                if last in ("ensure", "apply") or view is None
                else ("stop" if view["complete"] else "ensure")
            )
        )
        require(
            action == expected_action, "decision differs from the original fixed macro"
        )
        if action == "ensure":
            require(
                view is not None and not view["complete"] and initiation is not None,
                "ensure has no observed initiation",
            )
            primitives = ["apply"] if view["staged"] else ["stage", "apply"]
            require(
                [e["action"] for e in events[cursor : cursor + len(primitives)]]
                == primitives,
                "ensure primitive boundary differs",
            )
            key = view["index"]
            ensures.append(
                {
                    "schema": "hepta.act3.observed-ensure-transition.v1",
                    "purpose": "procedural_skill_transition",
                    "split": "train",
                    "task_id": task["id"],
                    "decision_index": decision_index,
                    "invocation_id": task["id"] + ":" + str(key),
                    "invocation_derivation": "pinned_destination_apply_task_id_colon_index",
                    "invocation_id_observed_directly": False,
                    "goal_sha256": sha(task["goals"][key].encode()),
                    "initiation_features": list(feature),
                    "source": dict(source),
                    "initiation": event_witness(events, initiation),
                    "primitives": [
                        event_witness(events, i)
                        for i in range(cursor, cursor + len(primitives))
                    ],
                }
            )
            cursor += len(primitives)
            last = "ensure"
            # The frozen source invalidates its actor view after the first lost ACK.
            # This validates subsequent input features; it never supplies a label.
            if task["fault"] == "lost_reply" and len(ensures) == 1:
                view = None
        else:
            require(
                cursor < len(events) and events[cursor]["action"] == "inspect",
                "original readback event missing",
            )
            view = events[cursor]["observation"]
            failed = failed + 1 if view is None else 0
            initiation, last = cursor, "inspect"
            cursor += 1
            if action == "stop":
                require(
                    decision_index == len(decisions) - 1, "events after original stop"
                )
    require(
        cursor == len(events) and decisions[-1] == "stop", "incomplete original episode"
    )
    for i, transition in enumerate(ensures):
        begin = transition["primitives"][-1]["index"] + 1
        end = (
            ensures[i + 1]["primitives"][0]["index"]
            if i + 1 < len(ensures)
            else len(events)
        )
        readbacks = [event_witness(events, j) for j in range(begin, end)]
        require(
            all(item["event"]["action"] == "inspect" for item in readbacks),
            "later effect crossed the readback boundary",
        )
        observed = next(
            (item for item in readbacks if item["event"]["observation"] is not None),
            None,
        )
        key = transition["initiation"]["event"]["observation"]["index"]
        observation = observed["event"]["observation"] if observed else None
        transition["readbacks"] = readbacks
        transition["target"] = {
            "goal_observed": observation["index"] > key
            if observation is not None
            else None,
            "task_complete_on_readback": observation["complete"]
            if observation is not None
            else None,
            "censoring": None
            if observed
            else ("readback_unavailable" if readbacks else "no_subsequent_readback"),
            "evidence_event_index": observed["index"] if observed else None,
        }
        transition["measurements"] = {
            "primitive_calls": len(transition["primitives"]),
            "readback_calls": len(readbacks),
            "option_duration_ns": None,
            "event_start_gap_ns": (
                readbacks[0]["event"]["at_ns"]
                - transition["primitives"][0]["event"]["at_ns"]
            )
            if readbacks
            else None,
            "event_start_gap_semantics": "first mutation call start to first subsequent read call start; not skill completion latency",
        }
        transition["record_sha256"] = sha(canonical(transition))
    return ensures


def load_transitions(archive):
    """Load only frozen TRAIN, manifest and source evidence; never instantiate a tool owner."""
    raw = {}
    for name, digest in PINS.items():
        with (Path(archive) / name).open("rb") as stream:
            value = stream.read(MAX_FILE + 1)
        require(
            len(value) <= MAX_FILE and sha(value) == digest,
            "original archive pin differs: " + name,
        )
        raw[name] = value
    sums, manifest = decode(raw["SHA256SUMS.json"]), decode(raw["FROZEN_MANIFEST.json"])
    require(
        all(
            sums.get(name) == PINS[name]
            for name in ("FROZEN_MANIFEST.json", "training-trajectories.jsonl.gz")
        ),
        "source manifest pins differ",
    )
    sources = manifest["source_files_sha256"]
    require(
        set(sources) == {"models.py", "run.py", "sqlite_destination.py"},
        "original source set differs",
    )
    with zipfile.ZipFile(io.BytesIO(raw["source-postimages.zip"])) as source:
        entries = source.infolist()
        require(
            len(entries) == 3
            and {e.filename for e in entries} == set(sources)
            and all(0 < e.file_size <= 65536 for e in entries),
            "source archive bound",
        )
        for name, digest in sources.items():
            require(sha(source.read(name)) == digest, "original source bytes differ")
    with gzip.GzipFile(
        fileobj=io.BytesIO(raw["training-trajectories.jsonl.gz"])
    ) as stream:
        decoded = stream.read(MAX_TRAIN + 1)
    require(
        len(decoded) <= MAX_TRAIN and decoded.endswith(b"\n"),
        "TRAIN expansion or line boundary",
    )
    lines, tasks = decoded.splitlines(keepends=True), manifest["train_tasks"]
    require(len(lines) == len(tasks) == 80, "original TRAIN denominator differs")
    require(
        len({t["id"] for t in tasks}) == 80
        and all(t["id"].startswith("train/") for t in tasks),
        "duplicate or non-TRAIN original task",
    )
    records, episodes = [], []
    for number, (line, task) in enumerate(zip(lines, tasks), 1):
        require(len(line) <= 16384 and line.endswith(b"\n"), "TRAIN line bound")
        row = decode(line)
        witness = {
            "line_number": number,
            "line_sha256": sha(line),
            "row_sha256": sha(canonical(row)),
            "task_sha256": sha(canonical(task)),
            "train_sha256": PINS["training-trajectories.jsonl.gz"],
            "source_zip_sha256": PINS["source-postimages.zip"],
        }
        transitions = _episode(row, task, witness)
        records.extend(transitions)
        episodes.append(
            {
                "task_id": task["id"],
                **witness,
                "ensure_decision_indices": [r["decision_index"] for r in transitions],
            }
        )
    require(
        len({r["invocation_id"] for r in records}) == len(records),
        "duplicate original invocation",
    )
    result = {
        "schema": "hepta.act3.observed-ensure-dataset.v1",
        "provenance": {
            "origin_commit": ORIGIN,
            "archive_sha256": dict(PINS),
            "source_files_sha256": sources,
            "loader_sha256": sha(Path(__file__).read_bytes()),
            "confirmation_definitions_present_in_frozen_manifest": True,
            "confirmation_trajectories_read": False,
            "destination_databases_read": False,
            "terminal_oracle_fields_used_for_labels": False,
            "timestamp_semantics": "primitive call entry, before execution",
        },
        "summary": {
            "original_train_episodes": len(episodes),
            "ensure_transitions": len(records),
            "episodes_without_ensure": sum(
                not e["ensure_decision_indices"] for e in episodes
            ),
            "goal_observed_true": sum(
                r["target"]["goal_observed"] is True for r in records
            ),
            "goal_observed_false": sum(
                r["target"]["goal_observed"] is False for r in records
            ),
            "censored": sum(r["target"]["goal_observed"] is None for r in records),
            "task_complete_true": sum(
                r["target"]["task_complete_on_readback"] is True for r in records
            ),
            "task_complete_false": sum(
                r["target"]["task_complete_on_readback"] is False for r in records
            ),
            "new_independent_real_tasks": 0,
            "production_authority": False,
        },
        "episodes": episodes,
        "records": records,
    }
    result["dataset_sha256"] = sha(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = load_transitions(args.archive)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
