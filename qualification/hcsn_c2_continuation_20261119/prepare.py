"""Bind surviving C2 inputs and reconstruct stopping history without model execution."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
OLD_ARCHIVE = Path("/home/qian-qi/hepta-c2-readonly-evidence-20261119-d741/original-c2-journals-and-results.zip")
OLD_ARCHIVE_SHA = "7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    require(path.is_file() and not path.is_symlink(), "regular immutable input required: " + str(path))
    content = path.read_bytes()
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def stopping(history, delta):
    best, best_epoch, anchor, stale = -1.0, None, -1.0, 0
    for epoch, row in enumerate(history, 1):
        require(row["epoch"] == epoch and row["complete"] is True, "contiguous complete validation history")
        score = row["development"]["macro_f1_11_classes"]
        require(0 <= score <= 1, "finite validation score")
        if score > best:
            best, best_epoch = score, epoch
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
    return {"best": best, "best_epoch": best_epoch, "plateau_anchor": anchor, "stale_epochs": stale}


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    root = Path(request["original_root"])
    program = Path(request["original_c2_program"])
    inputs = {}

    def bind(path, expected=None):
        value = identity(path)
        require(expected is None or value["sha256"] == expected, "input hash differs: " + str(path))
        inputs[str(path)] = value
        return value

    bind(OLD_ARCHIVE, OLD_ARCHIVE_SHA)
    for name, key in (("c2_boundary.py", "original_boundary_sha256"),
                      ("c2_runner.py", "original_c2_runner_sha256"),
                      ("CONTRACT.json", "original_contract_sha256")):
        bind(program / name, request[key])
    contract = json.loads((program / "CONTRACT.json").read_text())
    require(contract["maximum_epochs"] == request["maximum_cumulative_epochs"] == 200,
            "original C2 effective epoch cap")
    probe = Path(request["cold_probe_root"])
    bind(probe / "runner.py", request["cold_probe_source_sha256"])
    bind(probe / "SOURCE_EXPECTATIONS.json", request["source_expectations_sha256"])
    bind(probe / "c2-cold-resume-exact-artifact.zip", request["cold_probe_archive_sha256"])
    cold = json.loads((HERE / "COLD_PREFLIGHT_REVIEW.json").read_text())
    require(cold["status"] == "VERIFIED_BOUNDED_COLD_RESUME" and cold["optimizer_completed_events"] == 4
            and cold["archive_sha256"] == request["cold_probe_archive_sha256"], "independent four-call preflight")
    result = {"schema": "hcsn-c2-continuation-binding-v1", "identity": request["identity"], "fits": {}}
    with ZipFile(OLD_ARCHIVE) as original_archive:
        for fit in request["fits"]:
            name = fit["name"]
            native = root / "c2-native-execution-20261110-c385-v1" / "fits" / name
            parent = root / "campaign-v2" / name
            for member in ("ADMISSION.json", "events.jsonl"):
                archived = original_archive.read("fits/" + name + "/" + member)
                bind(native / member, hashlib.sha256(archived).hexdigest())
            admission = json.loads((native / "ADMISSION.json").read_text())
            prior = json.loads((parent / "result.json").read_text())
            for path in (parent / "result.json", parent / "plan.json"):
                expected = admission["inputs"][str(path)]
                require(bind(path, expected["sha256"]) == expected, "original admitted parent input")
            initial = Path(fit["initial_checkpoint_source"])
            initial_expected = admission["inputs"][str(parent / "initial.pt")]
            require(bind(initial, initial_expected["sha256"]) == initial_expected,
                    "exact original initial bytes from surviving alternate path")
            plan = json.loads((parent / "plan.json").read_text())
            require(plan["min_epochs"] == 30 and plan["patience"] == 10 and plan["plateau_delta"] == 0.002
                    and plan["batch_size"] == 32 and plan["micro_batch_size"] == 8 and plan["threads"] == 1,
                    "original training and stopping policy")
            require(prior["memorization"]["passed"] is True, "inherited training-only diagnostic")
            history = list(admission["boundary"]["logical_epochs"])
            start = admission["boundary"]["retained_epochs"]
            require(len(history) == start and stopping(history, plan["plateau_delta"])
                    == admission["boundary"]["stopping"], "original complete parent history")
            valid_events, malformed = [], []
            for number, line in enumerate((native / "events.jsonl").read_bytes().splitlines(), 1):
                try:
                    valid_events.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed.append({"line": number, "bytes": len(line), "sha256": hashlib.sha256(line).hexdigest()})
            epoch_events = {row["epoch"]: row for row in valid_events if row["kind"] == "epoch_completed"}
            previous = None
            for epoch in range(start + 1, fit["epoch"] + 1):
                path = native / "commits" / f"epoch-{epoch:04d}.json"
                record = bind(path)
                commit = json.loads(path.read_text())
                require(commit["previous_commit"] == previous, "complete original commit hash chain")
                row = commit["epoch"]
                require(all(epoch_events[epoch][key] == value for key, value in row.items()),
                        "commit and surviving original epoch journal differ")
                history.append(row)
                require(stopping(history, plan["plateau_delta"]) == commit["stopping"], "every original stopping state")
                require(commit["logical_main_updates"] == epoch * 12, "original retained logical updates")
                previous = {"path": str(path), **record}
            require(previous["sha256"] == fit["commit_sha256"] and commit["stopping"] == fit["stopping"],
                    "pinned last complete epoch identity")
            bind(Path(commit["checkpoint_path"]), fit["checkpoint_sha256"])
            bind(Path(commit["best_path"]), fit["best_checkpoint_sha256"])
            best_commit = json.loads((native / "commits" / f"epoch-{fit['best_epoch']:04d}.json").read_text())
            require(best_commit["epoch"]["development"]["macro_f1_11_classes"] == fit["stopping"]["best"],
                    "strict best checkpoint and validation history")
            require(all(stopping(history[:epoch], plan["plateau_delta"])["stale_epochs"] < plan["patience"]
                        for epoch in range(plan["min_epochs"], len(history) + 1)),
                    "original history already crossed an earlier stopping event")
            completed = [row for row in valid_events if row["kind"] == "optimizer_completed"]
            discarded = sum(row["number"] > commit["logical_main_updates"] for row in completed)
            require(discarded == fit["old_surviving_completed_updates_replayed"], "surviving original partial work")
            result["fits"][name] = {
                "initial_checkpoint": str(initial), "best_checkpoint": commit["best_path"],
                "missing_original_initial_path": str(parent / "initial.pt"),
                "original_initial_path_exists": (parent / "initial.pt").exists(),
                "initial_bytes_equal_original_admission_identity": True,
                "last_checkpoint": commit["checkpoint_path"], "last_commit": previous,
                "best_development": best_commit["epoch"]["development"],
                "inherited_history": history, "stopping": commit["stopping"],
                "inherited_memorization": prior["memorization"], "steps_per_epoch": 12,
                "parent_retained_epochs": start, "original_surviving_completed_after_checkpoint": discarded,
                "original_malformed_journal_lines": malformed, "original_unobserved_tail_work": "UNKNOWN",
                "last_complete_epoch_cumulative_wall_lower_bound_seconds": commit["epoch"]["cumulative_process_wall_seconds"],
                "last_complete_c2_cpu_lower_bound_seconds": commit["epoch"]["phase_process_cpu_seconds"],
            }
    result["input_files"] = inputs
    result["original_controller_terminal"] = "UNKNOWN"
    result["old_c2_admission_reused"] = False
    result["forward_calls"] = result["optimizer_calls"] = 0
    with (HERE / "BINDINGS.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "BOUND", "bindings": identity(HERE / "BINDINGS.json"),
                      "fits": {name: {"history_epochs": len(value["inherited_history"]), "stopping": value["stopping"]}
                               for name, value in result["fits"].items()}}), flush=True)


if __name__ == "__main__":
    main()
