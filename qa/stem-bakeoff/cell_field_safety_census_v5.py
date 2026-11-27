"""Validate V5 verification on every sealed V4 development pressure slot.

No validation or final labels are inputs. This is development replay, not a new
independent task evaluation. The old warmup probe thresholds remain unchanged.
"""

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_io import deny_withheld_labels, write_json
from cell_field_features import file_hash
from cell_field_safety_v5 import verify_action
from cell_field_state import CellTrainingState
from cell_learning_models import normalize_features


PROTOCOL_SHA256 = "30880ddaae978f622cf6a99cf3888771daa954777e6f9ce2a75c25f01f166280"
SEAL_SHA256 = "9a3fdbd2e7f4d15cbffa2bcb7c95e80c2ec53e0ad79cbdc331fec5cf7b3bef9e"


def census(v4_run, protocol, output):
    sys.addaudithook(deny_withheld_labels)
    root, protocol, output = (Path(p).resolve() for p in (v4_run, protocol, output))
    if output.exists() or output.is_relative_to(root):
        raise ValueError("fresh output outside the immutable V4 run required")
    seal_path = root / "pre_evaluation_seal.json"
    if file_hash(protocol) != PROTOCOL_SHA256 or file_hash(seal_path) != SEAL_SHA256:
        raise ValueError("original V4 protocol and run seal required")
    seal, plan = json.loads(seal_path.read_bytes()), json.loads(protocol.read_bytes())
    used = set()

    def read(relative):
        path = root / relative
        expected = seal["files"][str(relative)]
        payload = path.read_bytes()
        if (path.is_symlink() or len(payload) != expected["bytes"]
                or hashlib.sha256(payload).hexdigest() != expected["sha256"]):
            raise ValueError("sealed development input changed: " + str(relative))
        used.add(str(relative))
        return payload

    def arrays(relative):
        with np.load(io.BytesIO(read(relative)), allow_pickle=False) as archive:
            return {key: archive[key] for key in archive.files}

    if json.loads(read("protocol.json")) != plan:
        raise ValueError("canonical run copy differs from original protocol")
    source = json.loads(read("executed_source.json"))
    for name in ("cell_field_state.py", "cell_learning_models.py", "cell_field_action_io.py"):
        if file_hash(Path(__file__).parent / name) != source[name]:
            raise ValueError("original nonlinear execution implementation changed")
    manifest = json.loads(read("run.json"))
    if len(manifest["fits"]) != 12 or {f["fit_id"] for f in manifest["fits"]} != {
            f"{task}-seed{seed}-{head}" for task in ("uci", "newsgroups")
            for seed in (7, 17, 29) for head in ("linear", "gated")}:
        raise ValueError("complete original twelve-fit census required")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    rows, counts = [], Counter()
    for task in ("uci", "newsgroups"):
        training = arrays(f"{task}/training.npz")
        if set(training) != {f"{role}_{axis}" for role in
                ("old_train", "old_probe", "current_train", "current_probe") for axis in ("x", "y")}:
            raise ValueError("only registered training/probe arrays may enter replay")
        development = {role: (training[role + "_x"], training[role + "_y"])
                       for role in ("current_train", "old_probe")}
        normalized = normalize_features(development["old_probe"][0])
        for seed in (7, 17, 29):
            for head in ("linear", "gated"):
                fit = f"{task}/seed{seed}-{head}"
                search = json.loads(read(f"{fit}/pressure/search.json"))
                warm = json.loads(read(f"{fit}/warmup/result.json"))
                anchor = warm["old_anchor"]
                if search["old_anchor"] != anchor:
                    raise ValueError("pressure threshold was re-anchored")
                for phase in ("prevention", "recovery"):
                    prefix = f"{fit}/pressure/{phase}"
                    metadata = json.loads(read(f"{prefix}/initial/manifest.json"))
                    read(f"{prefix}/initial/state.npz")
                    state = CellTrainingState.load(root / prefix / "initial", metadata["bindings"],
                        expected_protocol=plan["optimizer"], expected_contexts=metadata["contexts"],
                        expected_state_digest=metadata["state_sha256"])
                    before = state.digest()
                    plans = json.loads(read(f"{prefix}/frozen_plans.json"))["plans"]
                    original = json.loads(read(f"{prefix}/results.json"))
                    if len(plans) != 31 or len(original) != 31:
                        raise ValueError("complete 31-slot pressure anchor required")
                    for index, (candidate, old) in enumerate(zip(plans, original)):
                        if candidate["candidate_id"] != old["candidate_id"] or candidate["old_anchor"] != anchor:
                            raise ValueError("original candidate identity or threshold changed")
                        frozen = arrays(f"{prefix}/plans/{index}.npz")
                        status = "qualified" if candidate["status"] == "planned" else candidate["status"]
                        # Unresolved solvers may retain diagnostic trial arrays;
                        # those bytes are not an authorized executable candidate.
                        action = frozen.get("actions") if status == "qualified" else None
                        if action is not None and hashlib.sha256(action.tobytes()).hexdigest() != candidate["actions_sha256"]:
                            raise ValueError("original frozen action differs")
                        result = verify_action(state, development, action, anchor,
                            action_bound=candidate["budget_multiplier"], candidate_status=status, commit_steps=8)
                        record = result["record"]
                        row = {"fit_id": f"{task}-seed{seed}-{head}", "phase": phase,
                            "candidate_id": candidate["candidate_id"], "original_status": candidate["status"],
                            "original_v4_predicted_feasible_actual_violation": old.get(
                                "predicted_feasible_actual_violation", False), "safety": record}
                        rows.append(row)
                        counts["registered"] += 1
                        counts[record["status"]] += 1
                        if status == "qualified":
                            actual = arrays(f"{prefix}/actual/{index}.npz")
                            first = record["attempts"][0]
                            if (not np.array_equal(first["old_losses"], actual["observations"][:, 1])
                                    or first.get("terminal_state_sha256") != old["terminal_state_sha256"]):
                                raise ValueError("original nonlinear path does not replay exactly")
                            counts["original_exact_replays"] += 1
                            counts["original_strict_safe" if first["status"] == "certified" else "original_strict_unsafe"] += 1
                            if old.get("predicted_feasible_actual_violation"):
                                counts["v4_false_feasible"] += 1
                                counts["v4_false_feasible_repaired" if record["certified"] else "v4_false_feasible_rejected"] += 1
                            if record["certified"]:
                                replay = state.clone()
                                for k, u in enumerate(result["arrays"]["actions"]):
                                    receipt = replay.advance(*development["current_train"], intervention=plan["h"] * u)
                                    value = replay.head.loss_gradients(normalized, development["old_probe"][1], 0.)[0]
                                    if (receipt != result["receipts"][k] or value > anchor
                                            or not np.array_equal(replay.vector(), result["arrays"]["states"][k + 1])):
                                        raise ValueError("certified sequence failed independent actual replay")
                                if replay.digest() != result["state"].digest():
                                    raise ValueError("certified terminal state failed independent replay")
                                counts["accepted_trajectory_exact_replays"] += 1
                                counts["accepted_backtracked" if record["accepted_scale"] < 1 else "accepted_original"] += 1
                            elif result["state"].digest() != before or record["committed_optimizer_steps"] != 0:
                                raise ValueError("rejected plan advanced or changed its original state")
                        if state.digest() != before:
                            raise ValueError("common pressure checkpoint changed")
    for relative in tuple(used):
        read(relative)
    if counts["registered"] != 744 or counts["original_exact_replays"] != 551:
        raise ValueError("incomplete registered V4 pressure census")
    report = {"schema": "hepta.cell-field-v5-safety-development-census", "status": "passed",
        "scope": "all original V4 development pressure slots; no held-out retention or global feasibility claim",
        "protocol_sha256": PROTOCOL_SHA256, "v4_seal_sha256": SEAL_SHA256,
        "source_sha256": {name: file_hash(Path(__file__).parent / name) for name in
            ("cell_field_safety_v5.py", "cell_field_safety_census_v5.py")},
        "counts": dict(counts), "sealed_inputs_verified": len(used), "withheld_label_hook_installed": True,
        "false_certificates": 0, "committed_optimizer_steps": 0,
        "verified_optimizer_steps": sum(r["safety"]["verified_optimizer_steps"] for r in rows),
        "verification_cpu_ns": sum(r["safety"]["cpu_ns"] for r in rows),
        "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - began,
        "rows": rows, "authority": "DENY_ALL", "production_authority": False}
    write_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v4-run", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    summary = census(**vars(parser.parse_args()))
    print(json.dumps({key: summary[key] for key in ("status", "counts", "cpu_ns", "wall_ns")}))
