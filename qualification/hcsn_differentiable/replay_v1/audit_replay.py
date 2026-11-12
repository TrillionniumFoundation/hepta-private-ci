"""Independently audit the six real frozen recovery states without training."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import torch


def identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs)


def exact(left, right):
    if type(left) is not type(right):
        return False
    if torch.is_tensor(left):
        return left.dtype == right.dtype and left.shape == right.shape and torch.equal(left, right)
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact(left[k], right[k]) for k in left)
    if isinstance(left, (tuple, list)):
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    root = Path(args.run)
    selection_path = Path(args.selection)
    require(identity(selection_path)["sha256"] == args.selection_sha256, "selection identity mismatch")
    selection = read_json(selection_path)["fits"]
    require(len(selection) == 6 and len({r["fit"] for r in selection}) == 6, "six selections required")
    plan_path = root / "PREEXECUTION.json"
    plan = read_json(plan_path)
    plan_sha = identity(plan_path)["sha256"]
    require(plan["schema"] == "hcsn-real-checkpoint-replay-plan-v1"
            and plan["steps"] == 2 and plan["workers"] == 2
            and plan["threads_per_worker"] == 1 and plan["worker_wall_seconds"] == 300
            and plan["confirmation_access"] is False, "frozen scope mismatch")
    require(torch.__version__ == plan["torch_version"]
            and torch.version.git_version == plan["torch_build"], "runtime mismatch")
    summary = read_json(root / "SUMMARY.json")
    require(len(plan["fits"]) == len(summary["rows"]) == 6, "incomplete real-result roster")
    require(summary["completed_recovery_diagnostics"] == 6
            and summary["actual_optimizer_steps_total"] == 26
            and summary["new_independent_complete_training_replays"] == 0
            and summary["original_c2_completion_claimed"] is False
            and summary["scientific_admission"] == "HOLD_NO_GO"
            and summary["plan_sha256"] == plan_sha, "summary scope mismatch")
    bindings = dict(plan["program_inputs"])
    rows = []
    verified_calls = 0
    for selected, entry, summary_row in zip(selection, plan["fits"], summary["rows"]):
        fit = selected["fit"]
        require(entry["fit"] == summary_row["fit"] == fit, "fit order mismatch")
        require(entry["checkpoint_identity"] == selected["identity"]
                and entry["original_checkpoint"] == selected["path"], "origin mismatch")
        require(identity(selected["path"]) == selected["identity"], "original checkpoint changed")
        require(identity(entry["checkpoint"]) == selected["identity"], "frozen checkpoint changed")
        origin = torch.load(entry["checkpoint"], map_location="cpu", weights_only=True)
        for name, expected in entry["inputs"].items():
            require(name not in bindings or bindings[name] == expected, "conflicting input commitments")
            bindings[name] = expected
        base = root / fit
        reports, states = {}, {}
        for mode, count in (("reference", 2), ("producer", 1), ("resume", 1)):
            report = read_json(base / mode / "RESULT.json")
            require(report == read_json(base / (mode + ".stdout")), "stdout/report mismatch")
            require((base / (mode + ".stderr")).read_bytes() == b"", "unexpected worker stderr")
            require(read_json(base / (mode + ".EXIT.json"))["returncode"] == 0, "worker failed")
            state_path = base / mode / "state.pt"
            require(identity(state_path) == report["checkpoint"], "worker checkpoint digest mismatch")
            state = torch.load(state_path, map_location="cpu", weights_only=True)
            require(state["schema"] == "hcsn-real-checkpoint-replay-state-v1"
                    and state["plan_sha256"] == plan_sha
                    and state["origin"] == selected["identity"], "state lineage mismatch")
            require(report["mode"] == mode and report["fit"] == fit
                    and report["new_optimizer_steps"] == count == len(report["steps"])
                    and report["plan_sha256"] == plan_sha
                    and report["restored_state_equal"] is True
                    and report["negative_control_omit_optimizer_state"] is False
                    and report["source_and_input_identities_unchanged"] is True
                    and report["whole_worker_wall_seconds"] <= 300, "worker result mismatch")
            expected = selected["logical_main_updates"] + (1 if mode == "producer" else 2)
            require(state["state"]["main_updates"] == expected
                    and state["state"]["epochs_completed"] == selected["epoch"], "update/epoch mismatch")
            increment = 1 if mode == "producer" else 2
            previous_optimizer = origin["optimizer"]["state"]
            optimizer = state["state"]["optimizer"]["state"]
            require(optimizer.keys() == previous_optimizer.keys(), "Adam slots mismatch")
            require(all(float(optimizer[k]["step"]) == float(previous_optimizer[k]["step"]) + increment
                        for k in optimizer), "actual Adam increments mismatch")
            verified_calls += count
            reports[mode], states[mode] = report, state
        require(exact(states["reference"], states["resume"]), "full decoded continuation differs")
        require(reports["reference"]["steps"] == reports["producer"]["steps"] + reports["resume"]["steps"],
                "batch/loss/gradient receipts differ")
        require(summary_row["worker_reports"] == reports
                and all(summary_row[k] is True for k in
                        ("full_state_equal", "model_equal", "optimizer_equal", "rng_and_cursor_equal")),
                "summary not supported by originals")
        rows.append({"fit": fit, "origin_epoch": selected["epoch"],
                     "original_checkpoint": selected["identity"],
                     "reference": reports["reference"]["checkpoint"],
                     "producer": reports["producer"]["checkpoint"],
                     "resume": reports["resume"]["checkpoint"],
                     "reference_and_restored_full_state_equal": True,
                     "actual_adam_increment_verified": 2,
                     "actual_optimizer_calls": 4})
    first = root / selection[0]["fit"]
    reference = torch.load(first / "reference/state.pt", map_location="cpu", weights_only=True)
    negative_path = first / "negative-omit-adam"
    negative = torch.load(negative_path / "state.pt", map_location="cpu", weights_only=True)
    negative_report = read_json(negative_path / "RESULT.json")
    require(negative_report == read_json(first / "negative-omit-adam.stdout")
            and negative_report["new_optimizer_steps"] == 1
            and negative_report["negative_control_omit_optimizer_state"] is True
            and read_json(first / "negative-omit-adam.EXIT.json")["returncode"] == 0
            and identity(negative_path / "state.pt") == negative_report["checkpoint"]
            and not exact(negative["state"]["model"], reference["state"]["model"])
            and not exact(negative["state"]["optimizer"], reference["state"]["optimizer"]),
            "missing-Adam control not established")
    require((first / "negative-omit-adam.stderr").read_bytes() == b"", "negative worker stderr")
    require(not (first / "crash/state.pt").exists()
            and read_json(first / "crash.EXIT.json")["returncode"] == 73, "crash publication mismatch")
    orphans = list((first / "crash").glob(".c2-pending-*"))
    require(len(orphans) == 1 and identity(orphans[0])["bytes"] > 0, "crash state missing")
    orphan = torch.load(orphans[0], map_location="cpu", weights_only=True)
    producer = torch.load(first / "producer/state.pt", map_location="cpu", weights_only=True)
    require(exact(orphan, producer), "actual crash artifact differs from one-step state")
    require((first / "crash.stderr").read_bytes() == b"", "crash worker stderr")
    require(summary["negative_omit_adam_detected"] is True
            and summary["crash_before_publication_rejected"] is True, "control summary mismatch")
    verified_calls += 2
    require(verified_calls == 26, "incomplete optimizer accounting")
    for path, expected in bindings.items():
        require(identity(path) == expected, "bound source or data changed: " + path)
    result = {"schema": "hcsn-independent-real-recovery-audit-v1", "passed": True,
              "audit_source": identity(__file__), "plan": identity(plan_path),
              "summary": identity(root / "SUMMARY.json"), "rows": rows,
              "verified_unique_bound_files": len(bindings), "actual_optimizer_calls": verified_calls,
              "missing_adam_control_verified": True, "actual_crash_temporary_decoded": True,
              "new_optimizer_calls_in_this_audit": 0, "new_independent_complete_training_replays": 0,
              "scientific_admission": "HOLD_NO_GO", "python": sys.version,
              "torch": torch.__version__, "torch_build": torch.version.git_version,
              "wall_seconds": time.monotonic() - started}
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
