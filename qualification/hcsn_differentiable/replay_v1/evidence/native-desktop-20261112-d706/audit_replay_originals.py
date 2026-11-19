"""Read-only independent accounting of the fixed six-checkpoint native replay.

This validates the retained diagnostic state and receipts, not C2 completion.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def reject(value):
        raise ValueError("nonfinite JSON token: " + value)

    def number(value):
        decoded = float(value)
        require(math.isfinite(decoded), "nonfinite JSON number")
        return decoded

    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=reject, parse_float=number)


def file_identity(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "nonregular evidence: " + str(path))
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    import torch

    torch.set_num_threads(1)

    def same(left, right):
        if torch.is_tensor(left):
            return (torch.is_tensor(right) and left.dtype == right.dtype
                    and left.shape == right.shape
                    and left.contiguous().numpy().tobytes() == right.contiguous().numpy().tobytes())
        if isinstance(left, dict):
            return (type(left) is type(right) and left.keys() == right.keys()
                    and all(same(left[key], right[key]) for key in left))
        if isinstance(left, (list, tuple)):
            return (type(left) is type(right) and len(left) == len(right)
                    and all(same(a, b) for a, b in zip(left, right)))
        return type(left) is type(right) and left == right

    root = Path(args.root).resolve()
    execution = root / "execution"
    plan_path = execution / "PREEXECUTION.json"
    plan = read_json(plan_path)
    plan_sha = file_identity(plan_path)["sha256"]
    summary = read_json(execution / "SUMMARY.json")
    launch = read_json(root / "LAUNCH.json")
    terminal = read_json(root / "EXIT.json")
    selection_path = root / "source/qualification/hcsn_differentiable/replay_v1/SELECTION.json"
    require(file_identity(selection_path)["sha256"] ==
            "6271b8dd1859b8a124f5ecd06ba307c0f9ebcdc5e6f86a9d164c4ac374cdbd55",
            "selection changed from #6130")
    selection = read_json(selection_path)
    require(len(plan["fits"]) == len(selection["fits"]) == 6, "wrong fit denominator")
    require([row["fit"] for row in plan["fits"]] ==
            [row["fit"] for row in selection["fits"]], "fit order/identity differs")
    require(summary["plan_sha256"] == plan_sha, "summary plan differs")
    require(terminal["returncode"] == 0 and terminal["timed_out"] is False
            and terminal["source_unchanged"] is True, "outer invocation did not succeed")
    require(summary["new_independent_complete_training_replays"] == 0
            and summary["original_c2_completion_claimed"] is False
            and summary["scientific_admission"] == "HOLD_NO_GO", "qualification overclaim")
    for relative, expected in launch["source_identities"].items():
        actual = file_identity(root / "source" / relative)
        require(actual == {key: expected[key] for key in actual}, "source snapshot changed")
    evidence = {}
    source_inputs = {}
    for entry in plan["fits"]:
        for path, expected in entry["inputs"].items():
            require(path not in source_inputs or source_inputs[path] == expected,
                    "inconsistent bound-input identity")
            source_inputs[path] = expected
    source_inputs.update(plan["program_inputs"])
    for path, expected in source_inputs.items():
        require(file_identity(path) == expected, "input changed: " + path)

    def checkpoint(path):
        evidence[str(path.relative_to(root))] = file_identity(path)
        return torch.load(path, map_location="cpu", weights_only=True)

    def adam_steps(state):
        values = [entry["step"].item() for entry in state["optimizer"]["state"].values()]
        require(values and len(set(values)) == 1, "mixed/empty Adam counters")
        return values[0]

    rows = []
    counted = 0
    for index, (entry, selected) in enumerate(zip(plan["fits"], selection["fits"])):
        require(entry["checkpoint_identity"] == selected["identity"], "origin differs")
        require(file_identity(selected["path"]) == selected["identity"], "original checkpoint changed")
        initial = checkpoint(Path(entry["checkpoint"]))
        require(initial["epochs_completed"] == selected["epoch"]
                and initial["main_updates"] == selected["logical_main_updates"], "origin cursor differs")
        fit_root = execution / entry["fit"]
        states = {}
        reports = {}
        for mode, steps in (("reference", 2), ("producer", 1), ("resume", 1)):
            where = fit_root / mode
            report_path = where / "RESULT.json"
            report = read_json(report_path)
            evidence[str(report_path.relative_to(root))] = file_identity(report_path)
            exit_path = fit_root / (mode + ".EXIT.json")
            exit_receipt = read_json(exit_path)
            require(exit_receipt["returncode"] == 0 and exit_receipt["fit"] == entry["fit"],
                    "worker exit differs")
            require(report["fit"] == entry["fit"] and report["mode"] == mode
                    and report["plan_sha256"] == plan_sha, "worker lineage differs")
            require(type(report["new_optimizer_steps"]) is int
                    and report["new_optimizer_steps"] == len(report["steps"]) == steps,
                    "worker optimizer count differs")
            require(report["source_and_input_identities_unchanged"] is True, "worker input mutation")
            payload = checkpoint(where / "state.pt")
            require(file_identity(where / "state.pt") == report["checkpoint"], "worker state bytes differ")
            require(payload["origin"] == selected["identity"] and payload["plan_sha256"] == plan_sha,
                    "worker state lineage differs")
            total_steps = 1 if mode == "producer" else 2
            require(payload["state"]["main_updates"] == initial["main_updates"] + total_steps
                    and adam_steps(payload["state"]) == adam_steps(initial) + total_steps,
                    "decoded optimizer/logical counters differ")
            require(payload["cursor"]["next_batch"] == total_steps, "decoded next-batch cursor differs")
            states[mode] = payload
            reports[mode] = report
            counted += steps
        require(same(states["reference"], states["resume"]), "bitwise full-state replay differs")
        require(reports["reference"]["steps"] ==
                reports["producer"]["steps"] + reports["resume"]["steps"], "batch/loss/gradient receipts differ")
        rows.append({"fit": entry["fit"], "origin_epoch": selected["epoch"],
                     "bitwise_full_state_equal": True, "counted_optimizer_calls": 4,
                     "model_changed_from_origin": not same(initial["model"], states["reference"]["state"]["model"]),
                     "origin_adam_step": adam_steps(initial),
                     "reference_adam_step": adam_steps(states["reference"]["state"])})
        if index == 0:
            first_states = states
            first_root = fit_root
    negative = checkpoint(first_root / "negative-omit-adam/state.pt")
    negative_report = read_json(first_root / "negative-omit-adam/RESULT.json")
    require(read_json(first_root / "negative-omit-adam.EXIT.json")["returncode"] == 0,
            "negative-control invocation failed")
    require(negative_report["new_optimizer_steps"] == len(negative_report["steps"]) == 1
            and negative_report["negative_control_omit_optimizer_state"] is True,
            "negative control count/identity differs")
    require(not same(negative["state"]["optimizer"], first_states["reference"]["state"]["optimizer"])
            and not same(negative["state"]["model"], first_states["reference"]["state"]["model"])
            and adam_steps(negative["state"]) == 1, "missing-Adam control did not fail replay")
    counted += 1
    crash_root = first_root / "crash"
    require(read_json(first_root / "crash.EXIT.json")["returncode"] == 73, "wrong crash terminal")
    require(not (crash_root / "state.pt").exists(), "crash published canonical state")
    orphan_paths = list(crash_root.glob(".c2-pending-*"))
    require(len(orphan_paths) == 1, "wrong crash temporary denominator")
    orphan = checkpoint(orphan_paths[0])
    require(same(orphan, first_states["producer"]), "decoded crash temporary differs from real producer")
    counted += 1
    require(counted == summary["actual_optimizer_steps_total"] == 26, "total optimizer count differs")
    report = {"schema": "hcsn-real-checkpoint-replay-independent-readback-v1",
              "source_commit": launch["source_commit"], "plan_sha256": plan_sha,
              "auditor_sha256": file_identity(Path(__file__))["sha256"],
              "completed_recovery_diagnostics": len(rows), "counted_optimizer_calls": counted,
              "decoded_checkpoint_files": sum(path.endswith(".pt") or "/.c2-pending-" in path for path in evidence),
              "rows": rows, "checked_distinct_bound_inputs": len(source_inputs),
              "negative_omit_adam_detected": True, "crash_unpublished_real_state_equal": True,
              "new_independent_complete_training_replays": 0, "original_c2_completion_claimed": False,
              "scientific_admission": "HOLD_NO_GO", "evidence": evidence,
              "python": sys.version, "torch": torch.__version__,
              "wall_seconds": time.monotonic() - started}
    with Path(args.output).open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("completed_recovery_diagnostics", "counted_optimizer_calls",
                                                 "decoded_checkpoint_files", "scientific_admission")}, sort_keys=True))


if __name__ == "__main__":
    main()
