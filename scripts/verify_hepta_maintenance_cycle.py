#!/usr/bin/env python3
"""Read-only consistency review of retained controlled maintenance evidence.

Does not import the candidate, call native code, train, compile a fixture, or
establish producer authenticity. SQLite is opened immutable/read-only after
the owning processes close. Actual runtime transport needs its outer protocol.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct

import numpy as np


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def arrays_hash(arrays):
    return sha(
        canonical(
            [
                [key, value.dtype.str, list(value.shape), sha(value.tobytes())]
                for key, value in sorted(arrays.items())
            ]
        )
    )


def checkpoint(path, manifest):
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    model = manifest["model"]
    parameters = {
        key[2:]: value for key, value in arrays.items() if key.startswith("p_")
    }
    heads = {
        key: value
        for key, value in parameters.items()
        if key in ("Wh", "bh", "Wy", "by")
    }
    kernel = {key: value for key, value in parameters.items() if key not in heads}
    optimizer = {
        key: value for key, value in arrays.items() if key.startswith(("m_", "v_"))
    }
    optimizer["steps"] = np.asarray(arrays["steps"], dtype=np.int64)
    for group, name in (
        (parameters, "weights"),
        (heads, "heads"),
        (kernel, "kernel"),
        (optimizer, "optimizer"),
    ):
        require(
            arrays_hash(group) == model[name + "_sha256"],
            "checkpoint " + name + " differs",
        )
    require(
        json.loads(str(arrays["config"])) == model["config"],
        "checkpoint configuration differs",
    )
    return arrays


def fixed_panels():
    panels = {}
    for phase, offset in (("A", 0), ("B", 100), ("C", 200)):
        rows = []
        for index in range(8):
            name, number = f"fixture_{phase}_{index}", offset + index + 3
            programs = (
                f"def {name}(x)\n    return x + {number}\n",
                f"def {name}(x):\n    return (x + {number}\n",
                f'def {name}(x):\n    return "tag_{number}\n',
                f"def {name}(x):\nreturn x + {number}\n",
            )
            rows.append(dict(id=name, source=programs[index % 4]))
        panels[phase] = rows
    return panels


def inspect_journal(directory, receipts, manifests, image_hash):
    path = directory / "owner.sqlite"
    require(
        not Path(str(path) + "-wal").exists(),
        "uncheckpointed WAL cannot be independently reviewed",
    )
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        require(
            connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
            "SQLite integrity failed",
        )
        calls = connection.execute("SELECT * FROM hia_cell_calls").fetchall()
        intents = {
            (r["partition"], r["request"]): r
            for r in connection.execute("SELECT * FROM intents")
        }
        indexed = {(r["partition_digest"], r["request_id"]): r for r in receipts}
        require(
            len(calls) == len(intents) == len(indexed) == len(receipts),
            "missing/duplicate served receipt",
        )
        elapsed, native = [], []
        for call in calls:
            key = (call["partition"], call["request"])
            intent, receipt = intents[key], indexed[key]
            require(
                call["phase"] == "completed" and call["error"] is None,
                "native continuation not completed",
            )
            require(
                intent["status"] == "committed"
                and json.loads(intent["receipt"]) == receipt,
                "owner receipt differs",
            )
            binding = json.loads(call["binding"])
            manifest = manifests[binding["candidate_sha256"]]
            inner_identity = manifest["inner_identity"]
            inner_digest = sha(canonical(inner_identity))
            wrapper = dict(
                implementation="hepta.hia-cell.v1",
                bundle_digest=inner_identity["bundle_digest"],
                effectful=inner_identity["effectful"],
                configuration_digest=sha(
                    canonical([inner_digest, binding["candidate_sha256"], image_hash])
                ),
            )
            require(
                binding["cell_sha256"] == inner_digest, "inner Cell identity differs"
            )
            require(
                binding["input_sha256"] == sha(intent["payload"].encode()),
                "native input differs",
            )
            require(
                binding["request_sha256"]
                == sha(canonical([*key, intent["generation"], intent["fingerprint"]])),
                "native request differs",
            )
            require(
                call["fingerprint"] == intent["fingerprint"],
                "native fingerprint differs",
            )
            require(
                json.loads(intent["identity"]) == wrapper,
                "owner wrapper identity differs",
            )
            require(
                sha(canonical(wrapper))
                == call["identity"]
                == receipt["identity_digest"],
                "receipt wrapper digest differs",
            )
            state, inner_raw = bytes(call["state"]), call["inner_result"].encode()
            require(
                len(state) == 256 and state[:8] == b"HCLSTA01",
                "native state extent/magic differs",
            )
            require(
                struct.unpack_from("<3Q", state, 8) == (1, 2, binding["sequence"]),
                "native terminal/sequence differs",
            )
            for offset, field in (
                (32, "candidate_sha256"),
                (64, "cell_sha256"),
                (96, "request_sha256"),
                (128, "input_sha256"),
            ):
                require(
                    state[offset : offset + 32].hex() == binding[field],
                    "native state binding differs",
                )
            require(
                state[192:224].hex() == sha(inner_raw) and state[224:] == bytes(32),
                "native retained result digest differs",
            )
            require(
                struct.unpack_from("<Q", state, 176)[0] == len(inner_raw),
                "native result length differs",
            )
            inner, wrapped = json.loads(inner_raw), json.loads(call["result"])
            require(
                wrapped["state"] == inner["state"]
                and wrapped["work_units"] == inner["work_units"],
                "inner state/work changed",
            )
            require(
                receipt["output"] == wrapped["output"]
                and wrapped["output"]["cell"] == inner["output"],
                "served output differs",
            )
            hia = wrapped["output"]["hia"]
            require(
                hia["binding"] == binding and hia["terminal_action"] == "COMPLETE",
                "completion receipt differs",
            )
            require(
                hia["candidate_sha256"] == binding["candidate_sha256"]
                and hia["image_sha256"] == image_hash,
                "receipt candidate/image differs",
            )
            require(
                hia["native_state_sha256"] == sha(state), "receipt native state differs"
            )
            require(
                receipt["state_digest"] == sha(canonical(inner["state"])),
                "owner state digest differs",
            )
            require(
                receipt["status"] == "committed"
                and receipt["state_applied"] is True
                and not receipt["requires_recovery"],
                "owner terminal state differs",
            )
            require(
                receipt["elapsed_ns"] >= call["native_ns"] > 0
                and hia["native_wall_ns"] == call["native_ns"],
                "native invocation cost missing",
            )
            elapsed.append(receipt["elapsed_ns"])
            native.append(call["native_ns"])
        return dict(
            native_completed=len(calls),
            unresolved=0,
            native_wall_ns=sum(native),
            component_call_p95_ms=float(np.quantile(elapsed, 0.95)) / 1e6,
            component_call_p99_ms=float(np.quantile(elapsed, 0.99)) / 1e6,
            logical_parameter_work=sum(r["work_units"] for r in receipts),
            latency_scope="component invocation only; excludes owner admission/settlement and task compile",
        )
    finally:
        connection.close()


def review_cell(root, cell, plan, result, manifests, compile_rows):
    directory = root / cell
    evaluation, decision = (
        read(directory / "EVALUATION.json"),
        read(directory / "DECISION.json"),
    )
    training, a_served, c_served = (
        read(directory / "TRAINING.json"),
        read(directory / "A_SERVED.json"),
        read(directory / "C_SERVED.json"),
    )
    require(len(a_served) == len(c_served) == 8, "A/C serving count differs")
    counts = {
        arm: sum(row["outcome"]["success"] for row in rows)
        for arm, rows in evaluation["B"].items()
    }
    retained = {
        arm: sum(row["outcome"]["success"] for row in rows)
        for arm, rows in evaluation["A-retention"].items()
    }
    require(
        set(counts) == set(plan["arms"])
        and all(len(rows) == 8 for rows in evaluation["B"].values()),
        "B arms/counts differ",
    )
    admitted = (
        all(
            counts["candidate"] > counts[arm]
            for arm in ("frozen", "no_learning", "deterministic")
        )
        and retained["candidate"] >= retained["frozen"]
    )
    require(
        decision["decision"] == ("Adopt" if admitted else "NoUpdate"),
        "selection rule differs",
    )
    require(
        decision["B_successes"] == counts and decision["A_retention"] == retained,
        "reported B/retention counts differ",
    )
    require(
        decision["ordinary_adopt"] == decision["ordinary_no_update"] == 0,
        "ordinary authority claim differs",
    )
    parent_id, candidate_id = (
        decision["parent_candidate_manifest_sha256"],
        decision["trained_candidate_manifest_sha256"],
    )
    require(parent_id != candidate_id, "candidate reused parent manifest")
    selected_id = candidate_id if admitted else parent_id
    require(
        selected_id == decision["selected_candidate_manifest_sha256"],
        "selected manifest differs",
    )
    parent, candidate = (
        checkpoint(directory / "parent.npz", manifests[parent_id]),
        checkpoint(directory / "candidate.npz", manifests[candidate_id]),
    )
    live = checkpoint(directory / "live.npz", manifests[selected_id])
    selected = candidate if admitted else parent
    require(
        all(
            np.array_equal(live[name], selected[name])
            for name in selected
            if name != "cell_state"
        ),
        "selected parameters/optimizer differ after C",
    )
    require(
        any(
            not np.array_equal(parent[name], candidate[name])
            for name in parent
            if name.startswith("p_")
        ),
        "candidate parameters never changed",
    )
    require(
        int(parent["steps"]) == 0 and int(candidate["steps"]) == 16,
        "optimizer schedule differs",
    )
    require(
        training["requested_updates"] == training["validated_updates"] == 16
        and training["learning_rate"] == 0.003
        and len(training["losses"]) == 16,
        "training receipt schedule differs",
    )
    with np.load(directory / "A_TRAINING.npz", allow_pickle=False) as archive:
        data = {name: archive[name] for name in archive.files}
    require(
        arrays_hash(data) == training["data_sha256"], "training data digest differs"
    )
    a_data = read(root / "A_DATA.json")
    expected_episodes, actions, allowed = [], [], []
    for task in plan["panels"]["A"]:
        for action in range(4) if cell == "predictor" else (0,):
            expected_episodes.append(a_data["episodes"][task["id"]])
            actions.append(np.eye(4)[action] if cell == "predictor" else [0.0])
            label = a_data["labels"][task["id"]]
            allowed.append(
                np.eye(2, dtype=bool)[int(label[action])]
                if cell == "predictor"
                else label
            )
    require(
        np.array_equal(data["episodes"], expected_episodes)
        and np.array_equal(data["actions"], actions)
        and np.array_equal(data["allowed"], allowed),
        "fitting data is not the fixed A-only dataset",
    )
    cold, cold_request, cold_process = (
        read(directory / "COLD_RESULT.json"),
        read(directory / "COLD_REQUEST.json"),
        read(directory / "COLD_PROCESS.json"),
    )
    require(
        cold_process["returncode"] == 0
        and cold["matches_pre_restart"] is True
        and cold["pid"] != plan["parent_pid"],
        "fresh process cold restore failed",
    )
    require(
        cold["candidate_manifest_sha256"]
        == cold_request["candidate_manifest_sha256"]
        == selected_id,
        "cold candidate differs",
    )
    require(
        cold["wrapper_identity_digest"]
        == cold_request["wrapper_identity_digest"]
        == decision["selected_identity"],
        "cold wrapper identity differs",
    )
    require(
        cold["receipt"]["output"]["cell"]["logits"]
        == cold_request["expected_logits"]
        == c_served[-1]["chosen_logits"],
        "cold inference logits differ",
    )
    require(
        sha((directory / "live.npz").read_bytes()) == cold_request["model_hash"],
        "cold checkpoint file differs",
    )
    require(
        json.loads(str(live["cell_state"])) == cold_request["checkpoint"]["state"],
        "cold owner and model state differ",
    )
    rows = (
        a_served
        + c_served
        + [
            row
            for panel in evaluation.values()
            for arm_rows in panel.values()
            for row in arm_rows
        ]
    )
    known_outcomes = {canonical(row) for row in compile_rows}
    for row in rows:
        if "outcome" in row:
            require(
                canonical(row["outcome"]) in known_outcomes,
                "served compile outcome absent from raw log",
            )
        require(
            row["candidate_manifest_sha256"] in manifests,
            "served version manifest missing",
        )
        require(
            all(
                r["identity_digest"] == row["wrapper_identity_digest"]
                for r in row["receipts"]
            ),
            "served version wrapper differs",
        )
    receipts = [receipt for row in rows for receipt in row["receipts"]] + [
        cold["receipt"]
    ]
    journal = inspect_journal(
        directory, receipts, manifests, plan["native"]["image_sha256"]
    )
    require(
        journal["native_completed"] == (265 if cell == "memory" else 457),
        "fixed native serving schedule changed",
    )
    reported = result["cells"][cell]
    require(
        reported["decision"] == decision
        and reported["training"] == training
        and reported["cold"] == cold,
        "top-level report differs from raw originals",
    )
    c_successes = sum(row["outcome"]["success"] for row in c_served)
    require(
        reported["C_successes"] == c_successes
        and reported["local_no_update_complete"] is (not admitted),
        "C/no-update report differs",
    )
    for kind in ("parent", "candidate"):
        require(
            sha((directory / (kind + ".npz")).read_bytes())
            == reported[kind + "_npz_sha256"],
            "reported model file hash differs",
        )
    return dict(
        decision=decision["decision"],
        B_successes=counts,
        A_retention=retained,
        C_successes=c_successes,
        denominator=8,
        cold_exact=True,
        training_updates=training["validated_updates"],
        training_wall_seconds=training["wall_seconds"],
        training_cpu_seconds=training["process_cpu_seconds"],
        cold_whole_wall_ns=cold_process["wall_ns"],
        cold_whole_child_cpu_seconds=cold_process.get("whole_child_cpu_seconds"),
        **journal,
    )


def review(directory):
    root = Path(directory).resolve(strict=True)
    plan, result = read(root / "PLAN.json"), read(root / "RESULT.json")
    plan_hash = sha((root / "PLAN.json").read_bytes())
    require(plan["panels"] == fixed_panels(), "predeclared A/B/C fixtures changed")
    require(
        (
            plan["seed"],
            plan["hidden_dim"],
            plan["optimizer"],
            plan["learning_rate"],
            plan["updates"],
            plan["wall_budget_seconds"],
        )
        == (7641, 4, "Adam", 0.003, 16, 120),
        "predeclared schedule changed",
    )
    require(
        result["plan_sha256"] == plan_hash
        and result["status"] == "CONTROLLED_FIXTURE_COMPLETE",
        "run did not complete against retained plan",
    )
    require(
        result["fixture_only"] is True
        and result["ordinary_daemon_qualification"] is False
        and result["native_hia_enabled"] is True,
        "qualification scope differs",
    )
    require(result["wall_seconds"] <= 120, "whole-run wall limit exceeded")
    for name, expected in plan["source_sha256"].items():
        require(
            sha((root / "executed-source" / name).read_bytes()) == expected,
            "executed source original missing/changed: " + name,
        )
    native = plan["native"]
    for name, key in (
        ("cell_bridge.so", "image_sha256"),
        ("continuation.hepta", "source_sha256"),
        ("transport.py", "worker_sha256"),
        ("build.json", "build_record_sha256"),
    ):
        require(
            sha((root / "native" / name).read_bytes()) == native[key],
            "native original differs: " + name,
        )
    build = read(root / "native/build.json")
    for key in (
        "image_sha256",
        "source_sha256",
        "compiler_commit",
        "compiler_implementation_sha256",
    ):
        require(build[key] == native[key], "native build identity differs")
    if plan.get("runtime_pins") is not None:
        pins = plan["runtime_pins"]
        require(
            sha((root / "RUNTIME_PINS.json").read_bytes()) == pins["sha256"]
            and read(root / "RUNTIME_PINS.json") == pins["identity"],
            "runtime pins original differs",
        )
    manifests = {}
    for path in (root / "versions").glob("*.json"):
        require(
            sha(path.read_bytes()) == path.stem, "candidate manifest digest differs"
        )
        manifest = read(path)
        require(
            manifest["plan_sha256"] == plan_hash
            and manifest["source_sha256"] == plan["source_sha256"],
            "candidate source/plan differs",
        )
        require(
            manifest["native"] == native
            and manifest["numeric"] == plan["numeric"]
            and manifest.get("runtime_pins") == plan.get("runtime_pins"),
            "candidate native/numeric/runtime binding differs",
        )
        manifests[path.stem] = manifest
    require(
        len(manifests) == 6,
        "fixed parent/candidate/deterministic version count differs",
    )
    compile_rows = [
        json.loads(raw) for raw in (root / "compile.jsonl").read_text().splitlines()
    ]
    require(
        len(compile_rows) == result["compile_calls"] == 208,
        "fixed compile schedule differs",
    )
    for row in compile_rows:
        require(
            sha(row["source"].encode()) == row["source_sha256"],
            "compile source digest differs",
        )
    cells = {
        cell: review_cell(root, cell, plan, result, manifests, compile_rows)
        for cell in ("memory", "predictor")
    }
    return dict(
        schema="hepta.controlled-maintenance-readonly-review.v1",
        status="READ_ONLY_CONSISTENCY_PASS",
        root=str(root),
        verifier_sha256=sha(Path(__file__).read_bytes()),
        result_sha256=sha((root / "RESULT.json").read_bytes()),
        plan_sha256=plan_hash,
        native_image_sha256=native["image_sha256"],
        native_transport_sha256=native["worker_sha256"],
        source_modules=len(plan["source_sha256"]),
        version_manifests=len(manifests),
        compile_calls=len(compile_rows),
        cells=cells,
        wall_seconds=result["wall_seconds"],
        parent_cpu_seconds=result["parent_cpu_seconds"],
        energy_joules=result["energy_joules"],
        peak_rss_bytes=result["peak_rss_bytes"],
        actual_runtime_transport_verified=False,
        scope="retained originals consistency only; no model/native reexecution, producer authentication or real-task benefit claim",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.directory), sort_keys=True, indent=2, allow_nan=False))
