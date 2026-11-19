"""Bound surviving C2 evidence without inventing missing terminal records."""

import json
import math
from pathlib import Path
import resource
import sys
import time
import traceback

from audit_io import require, save, sha, verify_files
from replay import HERE, frozen


def main():
    started = time.monotonic()
    request = frozen()
    resource.setrlimit(resource.RLIMIT_AS, (request["limits"]["address_space_bytes"],) * 2)
    output = HERE / "RUN_OUTPUT" / "partial-chain"
    output.mkdir()
    inputs, missing = {}, []

    def budget():
        require(time.monotonic() - started < 360, "metadata deadline")
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 <= request["limits"]["rss_bytes"], "metadata RSS")

    def bound(path, expected=None):
        budget()
        path = Path(path)
        if not path.is_file():
            missing.append(str(path))
            raise FileNotFoundError(str(path))
        digest = sha(path)
        require(expected is None or digest == expected, "metadata input identity: " + str(path))
        inputs[str(path)] = digest
        return path

    def data(path, expected=None):
        return json.loads(bound(path, expected).read_bytes())

    def journal(path, expected=None):
        raw = bound(path, expected).read_bytes()
        rows, malformed = [], []
        for number, line in enumerate(raw.splitlines(), 1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed.append(number)
        return rows, malformed

    import torch
    from checks import reconstruct_journal, stopping, verify_commit
    from checkpoint_checks import model_and_groups, validate_state, validate_witness
    from bound_io import identity
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)

    def state(path, expected=None):
        return torch.load(bound(path, expected), weights_only=True, mmap=True, map_location="cpu")

    root = Path(request["original_output_root"])
    parent_root = root.parent / "campaign-v2"
    plan = json.loads((HERE / "DATA_PLAN.json").read_bytes())
    parent_final = data(parent_root / "RESULT.json", plan["original_campaign_final_sha256"])
    parents = {r["name"]: r for r in parent_final["attempts"]}
    manifest = data(Path(plan["prepared"]) / "data-manifest.json", plan["data_manifest_sha256"])
    require(manifest["confirmation_access"] is False and all(r["partition"] in ("train", "dev") for r in manifest["episodes"]), "D-only prepared data")
    episodes = [data(Path(plan["prepared"]) / r["path"], r["sha256"]) for r in manifest["episodes"] if r["partition"] == "train"]
    require(len(episodes) == 356 and all(r["id"][0] in "ABC" for r in episodes), "ABC-only train order metadata")
    commands, bad_commands = journal(root / "commands.jsonl")
    controller_present = (root / "RESULT.json").is_file()
    if controller_present:
        bound(root / "RESULT.json")
    else:
        missing.append(str(root / "RESULT.json"))
    results = []
    for fit in request["fits"]:
        name = fit["name"]
        record = {"name": name, "checks": {}, "failures": {}, "original_controller_terminal": "UNKNOWN"}
        results.append(record)
        parent, native = parent_root / name, root / "fits" / name
        def check(label, call):
            try:
                value = call()
                record["checks"][label] = True
                return value
            except Exception:
                record["failures"][label] = traceback.format_exc()
                return None
        prior = check("parent_report", lambda: data(parent / "result.json", parents[name]["result_sha256"]))
        if prior is None:
            continue
        fit_plan = data(parent / "plan.json", prior["plan_sha256"])
        events, malformed = journal(native / "events.jsonl")
        kinds = [e.get("kind") for e in events]
        record["journal_survival"] = {"rows": len(events), "malformed_lines": malformed,
            "original_finished_event_present": bool(events and events[-1].get("kind") == "finished"),
            "optimizer_started_lower_bound": sum(e.get("kind") == "optimizer_started" and e.get("phase") == "main" for e in events),
            "optimizer_completed_lower_bound": sum(e.get("kind") == "optimizer_completed" and e.get("phase") == "main" for e in events),
            "complete_epochs": kinds.count("epoch_completed")}
        original_report = check("original_producer_terminal_report", lambda: data(native / "result.json"))
        record["costs"] = {"original_parent_outer": parents[name], "surviving_C2_controller_commands": [r for r in commands if r.get("name") == name],
                           "old_controller_lifetime_CPU": None, "missing_cost_is_not_zero": True,
                           "nested_timers_are_not_added": True, "original_parent_work_refund_seconds": 0}
        initial = check("initial_checkpoint", lambda: state(parent / "initial.pt", prior["initialization_sha256"]))
        last = check("parent_last_checkpoint", lambda: state(parent / "last.pt", prior["last_checkpoint_sha256"]))
        if initial is None or last is None:
            continue
        # Tensor payloads are checked below and never serialized into JSON receipts.
        record["checks"]["initial_checkpoint"] = record["checks"]["parent_last_checkpoint"] = True
        ev0, bad0 = journal(parent / "events.jsonl", prior["events_sha256"])
        original_journal = check("parent_journal_order_and_partial_work", lambda: reconstruct_journal(ev0, episodes, fit_plan["seed"], 32, 8))
        if original_journal is None:
            continue
        record["checks"]["parent_journal_order_and_partial_work"] = {k: original_journal[k] for k in ["logged_new_updates", "logical_updates", "unclosed_optimizer_call", "unclosed_forward_backward", "possibly_unlogged_optimizer_updates"]}
        retained = last["epochs_completed"]
        work = {"retained_main_updates": retained * 12, "completed_updates_after_anchor": prior["main_updates"] - retained * 12,
                "complete_epochs_after_anchor": 0, "optimizer_step_in_flight": original_journal["unclosed_optimizer_call"],
                "unclosed_forward_or_backward": original_journal["unclosed_forward_backward"],
                "inflight_optimizer_updates_unknown_interval": original_journal["possibly_unlogged_optimizer_updates"],
                "steps_per_epoch": 12, "total_logged_main_optimizer_completions": prior["main_updates"]}
        check("resume_witness_full_model_optimizer_RNG", lambda: validate_witness(last, state(native / "resume-start.pt"),
              data(native / "RESUME-START.json"), identity(parent / "last.pt"), identity(native / "resume-start.pt"),
              parents[name]["whole_process_wall_seconds"], prior["source_before"], work))
        phase = check("original_C2_journal_order_and_partial_work", lambda: reconstruct_journal(events, episodes, fit_plan["seed"], 32, 8,
                      parent_epoch=retained, parent_updates=retained * 12, order_state=last["order_rng"], phase=True))
        if phase is not None:
            record["checks"]["original_C2_journal_order_and_partial_work"] = {k: phase[k] for k in ["logged_new_updates", "logical_updates", "unclosed_optimizer_call", "unclosed_forward_backward", "possibly_unlogged_optimizer_updates"]}
        normalized = {request["source_aliases"].get(k, k): v for k, v in prior["source_before"].items()}
        for p, digest in normalized.items():
            bound(p, digest)
        model, groups, frozen_names = model_and_groups({"source": request["model_source"]}, fit_plan, initial, normalized)
        history, previous = list(prior["epochs"]), None
        best_path, best_item = native / "inherited-best.pt", identity(parent / "best.pt")
        bound(parent / "best.pt", prior["best_checkpoint_sha256"])
        best_score = max(r["development"]["macro_f1_11_classes"] for r in history)
        commits, errors = [], []
        for commit_path in sorted((native / "commits").glob("epoch-*.json")):
            try:
                commit = data(commit_path)
                row = commit["epoch"]
                cp = Path(commit["checkpoint_path"])
                require(cp.resolve().is_relative_to(native.resolve()), "checkpoint escaped original fit")
                payload = state(cp, commit["checkpoint"]["sha256"])
                validate_state(payload, initial, groups, frozen_names, initial["model_configuration"], row["epoch"], row["epoch"] * 12,
                               fit_plan["manifest_sha256"], phase["boundary_rng"].get(row["epoch"]) if phase else None, last["torch_rng"])
                history.append(row)
                if row["development"]["macro_f1_11_classes"] > best_score:
                    best_path, best_item, best_score = cp, identity(cp), row["development"]["macro_f1_11_classes"]
                verify_commit(commit, row, identity(cp), cp, best_item, best_path, previous, history, 12)
                previous = {"path": str(commit_path), **identity(commit_path)}
                commits.append({"epoch": row["epoch"], "checkpoint_sha256": commit["checkpoint"]["sha256"]})
            except Exception:
                errors.append({"path": str(commit_path), "error": traceback.format_exc()})
        record["commit_chain"] = {"verified": commits, "errors": errors, "strict_history": stopping(history),
                                  "full_optimizer_objects_constructed_or_restored": 0}
        record["status"] = "SURVIVING_EVIDENCE_AUDITED_ORIGINAL_TERMINAL_GATE_HOLD"
        # Reports are already byte-bound; compact only the JSON output, not source artifacts.
        record["checks"]["parent_report"] = {"status": prior["status"], "complete_epochs": len(prior["epochs"])}
        if original_report is not None:
            record["checks"]["original_producer_terminal_report"] = {"status": original_report["status"], "best_epoch": original_report["best_epoch"]}
        del model, initial, last
        save(output / (name + ".json"), record)
    verify_files(inputs)
    result = {"schema": "surviving-original-C2-partial-chain-audit-v1", "fits": results, "inputs": inputs,
              "missing_artifacts": sorted(set(missing)), "controller_result_present": controller_present,
              "controller_command_malformed_lines": bad_commands, "original_controller_terminal": "UNKNOWN",
              "original_full_C2_chain_auditor_completed": False, "E_access": False,
              "original_full_training_replays": "0/6", "scientific_admission": "HOLD",
              "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time(),
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save(output / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("fits", "inputs")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
