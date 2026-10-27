"""Execute the single prespecified V3 complete-tail replay after bank completion."""

import argparse
import json
from pathlib import Path
import time
import traceback

import numpy as np

from .training_audit_common import SCIENCE, bound, check_close, digest, journal, read, require


REPLAY_PROTOCOL = Path(__file__).with_name("TRAINING_REPLAY_PROTOCOL.json")
REPLAY_PROTOCOL_SHA256 = "f911a26a63b6a909b0a9d95bfd26fbf89296197765ab767dd807584911993013"


def compare_receipt(actual, expected):
    exact = ("start", "end", "action_index", "multiplier", "schedule_id", "schedule_sha256", "before", "candidate", "after",
             "accepted", "guard_delta", "guard_values", "guard_output_sha256", "clock_advances_on_rejection", "resources")
    require(all(actual[key] == expected[key] for key in exact), "Replayed block differs in exact state, optimizer, guard, schedule, or cost")
    for edge in ("first_gradient", "last_gradient"):
        require(actual[edge]["optimizer_advanced"] == expected[edge]["optimizer_advanced"], "Replayed optimizer advancement differs")
        check_close([actual[edge]["loss"], actual[edge]["unclipped_gradient_norm"]],
                    [expected[edge]["loss"], expected[edge]["unclipped_gradient_norm"]], "Replayed gradient diagnostics differ")


def compare_score(score, path):
    with np.load(path, allow_pickle=False) as saved:
        require(score["output_sha256"] == saved["output_sha256"].tolist(), "Replayed hard pixel/UTF8 bytes differ")
        require([list(pair) for pair in score["source_ids"]] == saved["source_ids"].tolist()
                and score["conditions"] == saved["conditions"].tolist(), "Replayed source-pair/condition identity differs")
        expected = saved["values_reward"]
        require(np.array_equal(score["values"]["reward"], expected), "Replayed hard utilities differ")
        return {"rows": len(expected), "output_identity_sha256": bound(score["output_sha256"]),
                "maximum_value_error": float(np.max(np.abs(score["values"]["reward"] - expected))),
                "expected_file_sha256": digest(path)}


def validate_plan(path=REPLAY_PROTOCOL):
    require(digest(path) == REPLAY_PROTOCOL_SHA256, "The prespecified replay sample or tolerance changed")
    plan = read(path)
    sample = plan["sample"]
    require(sample["seed"] == 17 and sample["trajectory"] == 0 and sample["start_step"] == 0
            and sample["candidate_action_indices"] == [0, 1, 2, 3] and sample["terminal_step"] == 288
            and sample["candidate_block_steps"] == 48, "Replay sample differs from the pre-outcome selection")
    require(plan["allowed_source_roles"] == ["fit_gradient", "fit_rehearsal", "fit_probe", "fit_guard"], "Replay requested an unregistered role")
    return plan


def execute(args):
    from ..field_bridge_v3_20261027.training_common import Journal, verify_freeze, write_json
    from ..field_bridge_v3_20261027.training_run import source_files
    plan = validate_plan(args.replay_protocol)
    protocol_path, root, out = SCIENCE / "PROTOCOL.json", Path(args.run).resolve(), Path(args.out).resolve()
    protocol = read(protocol_path)
    frozen = verify_freeze(args.freeze, protocol_path, "bank", root)
    required = source_files()
    require(all(frozen["source_files"].get(name) == value for name, value in required.items()), "Replay source differs from the bank freeze")
    completions = {}
    for seed in protocol["seeds"]:
        path = root / "bank" / str(seed) / "COMPLETE.json"
        require(path.is_file() and not path.with_name("FAILED.json").exists(), "All three successful bank completions are required")
        complete, start = read(path), read(path.with_name("START.json"))
        require(complete["seed"] == seed and complete["stage"] == "bank"
                and start["freeze_sha256"] == digest(args.freeze)
                and start["source_files"] == required, "Bank completion/freeze provenance differs")
        completions[str(seed)] = digest(path)
    require(not out.exists() and not out.is_relative_to(root / "bank"), "Replay output must be new and outside all bank inventories")
    marker = root / "TRAINING_REPLAY_STARTED.json"
    require(not marker.exists(), "The single registered replay was already started; preserve it and request an explicit recovery receipt")
    out.mkdir(parents=True)
    start = {"schema": "hepta.field-bridge.v3.single-replay-start.1", "replay_protocol_sha256": REPLAY_PROTOCOL_SHA256,
             "script_sha256": digest(__file__), "bank_freeze_sha256": digest(args.freeze),
             "bank_complete_sha256": completions, "source_files": required, "output": str(out),
             "started_monotonic_ns": time.monotonic_ns(), "verification_only": True}
    write_json(marker, start)
    write_json(out / "START.json", start)
    context, progress, started = None, [], time.perf_counter_ns()
    try:
        import torch
        from ..field_bridge_v3_20261027.assets import load_assets
        from ..field_bridge_v3_20261027.source_roles import load_corpus_roles
        from ..field_bridge_v3_20261027.learning import (clone_state, guarded_block, hard_panel, load_checkpoint,
                                                        make_context, state_identity)
        from ..field_bridge_v3_20261027.training_features import measure_state
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        originals, observers, assets = load_assets(args.assets, [17], ["reward"])
        corpus = load_corpus_roles(Path(args.assets) / "ndu-data", plan["allowed_source_roles"])
        require(corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"], "Replay source-role allocation changed")
        context = make_context(originals[17], corpus, observers, 17, "fit", protocol)
        directory = root / "bank/17"
        bank, complete = read(directory / "BANK.json"), read(directory / "COMPLETE.json")
        row = next(row for row in bank["records"] if row["trajectory"] == 0 and row["step"] == 0)
        require(bank["reference_sha256"] == digest(root / "reference/17/REFERENCE.json"), "Frozen continuation reference changed")
        records, by_hash = journal(directory / "decisions-and-outcomes.jsonl.gz")
        decisions = {bound(value): value for value in records if value["kind"] == "decision_before_update"}
        outcomes = {value["decision_sha256"]: value["receipt"] for value in records if value["kind"] == "block_outcome"}
        checkpoint_path = directory / "trajectory-0-step-0-state.pt"
        require(digest(checkpoint_path) == row["state_checkpoint"]["file_sha256"], "Replay initial complete optimizer checkpoint changed")
        model, optimizer, checkpoint = load_checkpoint(checkpoint_path, originals[17], 17, protocol)
        require(state_identity(model, optimizer) == by_hash[row["branch_set_commit"]]["before"], "Replay initial state differs")
        require(context.baseline_guard["values"]["reward"].tolist() == complete["baseline_guard"]["values"]
                and context.baseline_guard["output_sha256"] == complete["baseline_guard"]["output_sha256"]
                and [list(pair) for pair in context.baseline_guard["source_ids"]] == complete["baseline_guard"]["source_ids"],
                "Replayed original clean-guard baseline differs")
        vector, current, features = measure_state(context, model, optimizer, 0, row["schedule_id"])
        check_close(vector, row["state"], "Replayed initial richer30 field differs", atol=plan["feature_absolute_tolerance"])
        expected_features = by_hash[row["branch_set_commit"]]["feature_receipt"]
        for key in ("gradient_sha256", "momentum_sha256", "direction_sha256"):
            require(features["measured"][key] == expected_features["measured"][key], "Replayed weighted direction bytes differ")
        current_receipt = compare_score(current, directory / "trajectory-0-step-0-current.npz")
        with Journal(out / "replayed-blocks.jsonl.gz") as stream:
            for action in plan["sample"]["candidate_action_indices"]:
                branch, branch_optimizer = clone_state(model, optimizer, protocol, context.costs)
                selected = sorted((value for value in decisions.values() if value["stage"] == "reference_tail"
                    and value["trajectory"] == 0 and value["branch_start_step"] == 0
                    and value["branch_action_index"] == action), key=lambda value: value["step"])
                require([value["step"] for value in selected] == list(range(0, 288, 48)), "Sampled reference tail is incomplete")
                for step, decision in zip(range(0, 288, 48), selected, strict=True):
                    expected_action = action if step == 0 else bank["reference_action_index"]
                    require(decision["action_index"] == expected_action, "Sampled branch used an unexpected continuation action")
                    receipt = guarded_block(context, branch, branch_optimizer, step, expected_action, row["schedule_id"])
                    compare_receipt(receipt, outcomes[bound(decision)])
                    stream.append({"kind": "verified_reference_tail_block", "candidate_action": action,
                                   "step": step, "expected_decision_sha256": bound(decision), "receipt": receipt})
                require(state_identity(branch, branch_optimizer) == row["branches"][action]["terminal"], "Replayed terminal optimizer differs")
                score = hard_panel(branch, context.probe, {"reward": observers["reward"]}, context.action,
                                   protocol, context.costs, "terminal_fit_label")
                evidence = compare_score(score, directory / f"trajectory-0-step-0-action-{action}-terminal.npz")
                check_close(score["means"]["reward"], row["action_values"][action], "Replayed full-horizon terminal target differs")
                progress.append({"action_index": action, "terminal_step": 288, "terminal": state_identity(branch, branch_optimizer),
                                 "hard_outputs": evidence, "all_six_guard_transactions_exact": True})
                print(f"prespecified replay seed=17 trajectory=0 action={action} terminal288 exact", flush=True)
            selected = [value for value in decisions.values() if value["stage"] == "exploration_path"
                        and value["trajectory"] == 0 and value["step"] == 0]
            require(len(selected) == 1 and selected[0]["action_index"] == protocol["training"]["exploration_paths"][0][0],
                    "Prescheduled prefix selection changed")
            prefix_model, prefix_optimizer = clone_state(model, optimizer, protocol, context.costs)
            prefix = guarded_block(context, prefix_model, prefix_optimizer, 0, selected[0]["action_index"], row["schedule_id"])
            compare_receipt(prefix, outcomes[bound(selected[0])])
            stream.append({"kind": "verified_selected_prefix", "receipt": prefix})
        require(context.costs.values["scheduled_gradient_microsteps"] == 1200
                and context.costs.values["directional_gradient_measurements"] == 1, "Verification work differs from the prescribed sample")
        require(source_files() == required, "Scientific source changed during replay")
        verify_freeze(args.freeze, protocol_path, "bank", root)
        result = {"schema": "hepta.field-bridge.v3.prespecified-terminal-replay.1", "passed": True,
            "replay_protocol_sha256": REPLAY_PROTOCOL_SHA256, "script_sha256": digest(__file__),
            "seed": 17, "trajectory": 0, "start_step": 0, "candidate_actions": progress,
            "initial_current_outputs": current_receipt, "maximum_feature_error": float(np.max(np.abs(np.asarray(vector) - row["state"]))),
            "selected_prefix_exact": True, "complete_reference_tails_exact": True,
            "verification_resources": context.costs.snapshot(), "verification_wall_ns": time.perf_counter_ns() - started,
            "verification_work_counted_as_new_training_evidence": False, "source_roles_loaded": list(corpus.splits),
            "assets": assets, "bank_complete_sha256": completions, "bank_freeze_sha256": digest(args.freeze),
            "initial_checkpoint_sha256": digest(checkpoint_path), "bank_sha256": digest(directory / "BANK.json"),
            "log_sha256": digest(out / "replayed-blocks.jsonl.gz"), "scientific_inputs_modified": False}
        write_json(out / "REPLAY.json", result)
        print(json.dumps({"passed": True, "verification_gradient_microsteps": 1200,
                          "report": str(out / "REPLAY.json"), "sha256": digest(out / "REPLAY.json")}), flush=True)
        return result
    except BaseException as error:
        write_json(out / "FAILED.json", {"passed": False, "error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "completed_candidate_replays": progress,
            "verification_resources": {} if context is None else context.costs.snapshot(),
            "replay_protocol_sha256": REPLAY_PROTOCOL_SHA256, "retry_requires_explicit_recovery_receipt": True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replay-protocol", type=Path, default=REPLAY_PROTOCOL)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
