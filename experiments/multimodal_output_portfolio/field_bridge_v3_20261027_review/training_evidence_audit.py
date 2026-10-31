"""Read-only full reference/bank integrity and cost audit; no source-role loading."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from .training_audit_common import (SCIENCE, bound, check_close, checkpoint, cost_check, digest, expected_pairs,
                                    expected_schedule, hard_output, inventory, journal, paired_block, read,
                                    read_registry, require)


def common_checks(directory, freeze_path, phase, seed, source):
    protocol = read(Path(source) / "PROTOCOL.json")
    p = protocol["training"]
    complete, start, freeze = inventory(directory, freeze_path, phase, seed, source)
    registry, allocation = read_registry(source)
    require(digest(Path(source) / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"]
            and allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Protocol allocation changed")
    expected_roles = ["fit_gradient", "fit_rehearsal", "fit_probe", "fit_guard"]
    if phase == "reference":
        expected_roles += ["reference_task", "reference_clean"]
    require(start["requested_roles"] == complete["source_roles"] == expected_roles, "Phase source-role access differs")
    assets = read(Path(directory) / "ASSET_IDENTITIES.json")
    require(assets["loaded_observers"] == ["reward"] and set(assets["models"]) == {str(seed)}, "Unexpected observer/model access")
    baseline = np.asarray(complete["baseline_guard"]["values"], dtype=float)
    identities, _ = expected_pairs(registry, "fit_guard", ["clean"])
    require(complete["baseline_guard"]["source_ids"] == identities and baseline.shape == (len(identities),)
            and np.isfinite(baseline).all(), "Original guard panel identity differs")
    check_close(complete["baseline_guard"]["mean"], baseline.mean(), "Original guard mean differs")
    records, hashed = journal(Path(directory) / "decisions-and-outcomes.jsonl.gz")
    decisions = {bound(row): row for row in records if row["kind"] == "decision_before_update"}
    outcomes = [row for row in records if row["kind"] == "block_outcome"]
    require(len(outcomes) == len(decisions) and len({row["decision_sha256"] for row in outcomes}) == len(outcomes),
            "Missing or repeated decision/outcome correspondence")
    receipts = {}
    for outcome in outcomes:
        require(outcome["decision_sha256"] in decisions, "Outcome lacks its prior committed decision")
        receipts[outcome["decision_sha256"]] = paired_block(decisions[outcome["decision_sha256"]], outcome, baseline, seed, p)
    return protocol, p, complete, freeze, registry, records, hashed, decisions, receipts


def audit_reference(run, seed, freeze_path, source=SCIENCE):
    directory = Path(run) / "reference" / str(seed)
    protocol, p, complete, freeze, registry, records, hashed, decisions, receipts = common_checks(directory, freeze_path, "reference", seed, source)
    require(Counter(row["kind"] for row in records) == {"decision_before_update": 24, "block_outcome": 24}, "Reference chronology coverage differs")
    reference = read(directory / "REFERENCE.json")
    require(reference["seed"] == seed and reference["training_configuration_sha256"] == bound(p)
            and reference["fixed_output_action"] == p["fixed_actions"][str(seed)], "Reference identity/configuration differs")
    require(complete["reference_sha256"] == digest(directory / "REFERENCE.json"), "Reference receipt identity differs")
    originals = {name: hard_output(directory / f"original-{name}.npz", registry, "reference_" + name, conditions)
                 for name, conditions in (("task", p["conditions"]), ("clean", ["clean"]))}
    eligible, values, initial, bases = [], [], [], set()
    require([row["action_index"] for row in reference["candidates"]] == list(range(4)), "Ordinary candidate family changed")
    for candidate in reference["candidates"]:
        action = candidate["action_index"]
        path = sorted((row for row in decisions.values() if row["trajectory"] == action), key=lambda row: row["step"])
        require([row["step"] for row in path] == list(range(0, 288, 48)), "Constant schedule omitted a decision")
        previous = None
        for decision in path:
            require(decision["stage"] == "reference" and decision["action_index"] == action
                    and decision["schedule_id"] == p["reference_schedule_id"] and decision["policy"] == "preregistered_constant",
                    "Reference does not use its constant policy/common schedule")
            receipt = receipts[bound(decision)]
            if previous is not None:
                require(receipt["before"] == previous, "Reference optimizer path is discontinuous")
            previous = receipt["after"]
        initial.append(path[0]["before"])
        endpoint = checkpoint(directory / f"constant-{action}.pt", protocol, seed)
        bases.add(endpoint["frozen_base_sha256"])
        require(endpoint["identity"] == previous
                and candidate["checkpoint"]["file_sha256"] == endpoint["file_sha256"]
                and {name: candidate["checkpoint"][name] for name in ("parameters", "optimizer")} == previous,
                "Reference terminal checkpoint differs from its complete path")
        for name, conditions in (("task", p["conditions"]), ("clean", ["clean"])):
            score = hard_output(directory / f"constant-{action}-{name}.npz", registry, "reference_" + name, conditions)
            stored = candidate["scores"][name]
            require(stored["file_sha256"] == score["file_sha256"] and stored["rows"] == score["rows"], "Candidate hard-output receipt changed")
            check_close(stored["means"]["reward"], score["mean"], "Ordinary endpoint mean differs")
            delta = float((score["values"] - originals[name]["values"]).mean())
            check_close(stored["paired_delta"], delta, "Reference paired delta differs")
            if name == "clean":
                allowed = delta >= p["reference_clean_min_delta"]
                require(candidate["eligible"] == allowed, "Reference clean eligibility differs")
                if allowed:
                    eligible.append(action)
            else:
                values.append(score["mean"])
            if action == 0:
                require(score["hashes"] == originals[name]["hashes"]
                        and np.array_equal(score["values"], originals[name]["values"]), "No-update reference changed hard outputs")
    require(len(bases) == 1 and all(value == initial[0] for value in initial), "Reference candidates did not share one initial model/optimizer")
    require(eligible, "No eligible ordinary reference")
    winner = max(eligible, key=lambda index: (values[index], -index))
    require(reference["selected_action_index"] == winner, "Reference selected the wrong admissible constant")
    resources = cost_check(complete["resources"], "reference", seed, list(receipts.values()), registry, p)
    return {"passed": True, "seed": seed, "phase": "reference", "all_four_candidates_checked": True,
            "selected_action_index": winner, "journal_records": len(records), "checkpoints_checked": 4,
            "hard_outputs_checked": sum(originals[name]["rows"] for name in originals) * 5,
            "cost_audit": resources, "complete_sha256": digest(directory / "COMPLETE.json"),
            "reference_sha256": digest(directory / "REFERENCE.json")}


def audit_bank(run, seed, freeze_path, source=SCIENCE):
    root, directory = Path(run), Path(run) / "bank" / str(seed)
    protocol, p, complete, freeze, registry, records, hashed, decisions, receipts = common_checks(directory, freeze_path, "bank", seed, source)
    require(Counter(row["kind"] for row in records) == {"branch_set_before_outcomes": 24, "decision_before_update": 360,
        "block_outcome": 360, "terminal_branch_outcome": 96}, "Terminal-bank chronology coverage differs")
    bank = read(directory / "BANK.json")
    reference_path = root / "reference" / str(seed) / "REFERENCE.json"
    reference = read(reference_path)
    require(bank["seed"] == seed and bank["training_configuration_sha256"] == bound(p)
            and bank["reference_sha256"] == digest(reference_path)
            and bank["reference_action_index"] == reference["selected_action_index"], "Frozen continuation reference differs")
    for name in ("REFERENCE.json", "COMPLETE.json"):
        path = root / "reference" / str(seed) / name
        require(freeze["artifacts"].get(str(path.relative_to(root))) == digest(path), "Reference was not frozen before terminal targets")
    require(complete["bank_sha256"] == digest(directory / "BANK.json") and bank["resources"] == complete["resources"],
            "Bank/completion identity or resource accounting differs")
    require([(row["trajectory"], row["step"]) for row in bank["records"]] ==
            [(trajectory, step) for trajectory in range(4) for step in range(0, 288, 48)], "Exploration-state grid differs")
    terminal_rows = {(row["trajectory"], row["step"], row["action_index"]): row for row in records if row["kind"] == "terminal_branch_outcome"}
    paths, initial, bases, output_rows = {}, [], set(), 0
    for row in bank["records"]:
        trajectory, step = row["trajectory"], row["step"]
        prefix, schedule_id = f"trajectory-{trajectory}-step-{step}", p["fit_schedule_ids"][trajectory]
        parent = hashed[row["branch_set_commit"]]
        require(parent["kind"] == "branch_set_before_outcomes" and parent["trajectory"] == trajectory
                and parent["step"] == step and parent["seed"] == seed and row["schedule_id"] == schedule_id,
                "Branch set commitment scope differs")
        require(parent["reference_action_index"] == bank["reference_action_index"] and parent["reference_sha256"] == bank["reference_sha256"]
                and parent["complete_future_schedule_sha256"] == bound(expected_schedule(seed, schedule_id, step, 288 - step, p)),
                "Reference policy or complete continuation schedule changed")
        snapshot = checkpoint(directory / (prefix + "-state.pt"), protocol, seed)
        bases.add(snapshot["frozen_base_sha256"])
        require(snapshot["identity"] == parent["before"] and snapshot["file_sha256"] == row["state_checkpoint"]["file_sha256"]
                and snapshot["metadata"] == row["state_checkpoint"]["metadata"], "Common branch-state checkpoint differs")
        require(snapshot["metadata"]["trajectory"] == trajectory and snapshot["metadata"]["step"] == step
                and snapshot["metadata"]["schedule_id"] == schedule_id, "Branch-state checkpoint schedule differs")
        if step:
            require(parent["before"] == paths[(trajectory, step - 48)], "Executed exploration path is discontinuous")
        else:
            initial.append(parent["before"])
        current = hard_output(directory / (prefix + "-current.npz"), registry, "fit_probe", p["conditions"])
        output_rows += current["rows"]
        state = np.asarray(row["state"], dtype=float)
        require(state.shape == (30,) and np.isfinite(state).all() and parent["state"] == row["state"], "Common field vector differs")
        check_close([state[0], row["current_value"]], [current["mean"], current["mean"]], "Current hard-value feature differs")
        check_close(state[6], step / 288, "Field time coordinate differs")
        check_close(state[5], snapshot["momentum_rms"], "Field momentum norm differs from checkpoint")
        features = parent["feature_receipt"]
        require(features["before"] == parent["before"] and features["state_grad_rng_invariant"] and features["names"] == bank["feature_names"],
                "Feature measurement invariance/name contract differs")
        measured = features["measured"]
        check_close(measured["momentum_l2"], snapshot["momentum_l2"], "Directional momentum differs from complete optimizer")
        check_close(state[7], measured["gradient_l2"] / snapshot["parameter_count"] ** .5, "Clipped-gradient RMS feature differs")
        denominator = measured["gradient_l2"] * measured["momentum_l2"]
        cosine = np.clip(measured["gradient_momentum_dot"] / denominator, -1., 1.) if denominator > 0 else 0.
        check_close(state[8], cosine, "Gradient/momentum angle feature differs")
        require(measured["gradient_l2"] <= p["gradient_clip"] + 1e-5, "Directional gradient was not clipped")
        selected = p["exploration_paths"][trajectory][step // 48]
        require(row["selected_action_index"] == parent["selected_exploration_action"] == selected, "Exploration action was selected after outcomes")
        require([branch["action_index"] for branch in row["branches"]] == list(range(4)), "A terminal action was omitted")
        first_receipts = {}
        for action, branch in enumerate(row["branches"]):
            branch_decisions = sorted((decision for decision in decisions.values() if decision["stage"] == "reference_tail"
                and decision["trajectory"] == trajectory and decision["branch_start_step"] == step
                and decision["branch_action_index"] == action), key=lambda decision: decision["step"])
            require([decision["step"] for decision in branch_decisions] == list(range(step, 288, 48)),
                    "A Qref label did not continue to terminal288")
            previous = parent["before"]
            for index, decision in enumerate(branch_decisions):
                expected_action = action if index == 0 else bank["reference_action_index"]
                require(decision["action_index"] == expected_action and decision["schedule_id"] == schedule_id
                        and decision["branch_set_commit"] == row["branch_set_commit"]
                        and decision["record_index"] > parent["record_index"], "Counterfactual branch changed its action/tail")
                receipt = receipts[bound(decision)]
                require(receipt["before"] == previous, "Counterfactual branch optimizer is discontinuous")
                previous = receipt["after"]
                if index == 0:
                    first_receipts[action] = receipt
            terminal = terminal_rows[(trajectory, step, action)]
            require(terminal["branch_set_commit"] == row["branch_set_commit"]
                    and terminal["record_index"] > branch_decisions[-1]["record_index"]
                    and all(terminal[key] == value for key, value in branch.items()), "Terminal branch receipt differs")
            require(previous == branch["terminal"] and first_receipts[action]["after"] == branch["first_block_after"]
                    and first_receipts[action]["accepted"] == branch["first_block_accepted"], "Terminal label used the wrong optimizer state")
            score = hard_output(directory / f"{prefix}-action-{action}-terminal.npz", registry, "fit_probe", p["conditions"])
            output_rows += score["rows"]
            check_close([row["action_values"][action], branch["terminal_value"], branch["output"]["means"]["reward"]],
                        [score["mean"]] * 3, "Terminal target arithmetic differs")
            require(branch["output"]["file_sha256"] == score["file_sha256"] and branch["output"]["rows"] == score["rows"],
                    "Terminal hard-output artifact differs")
        selected_decisions = [decision for decision in decisions.values() if decision["stage"] == "exploration_path"
                              and decision["trajectory"] == trajectory and decision["step"] == step]
        require(len(selected_decisions) == 1, "Executed prefix omitted or repeated")
        decision = selected_decisions[0]
        require(decision["action_index"] == selected and decision["predetermined_path"] == p["exploration_paths"][trajectory]
                and decision["branch_set_commit"] == row["branch_set_commit"], "Executed path departed from its predeclared choice")
        actual, expected = receipts[bound(decision)], first_receipts[selected]
        require(actual["before"] == parent["before"] and all(actual[key] == expected[key]
                for key in ("candidate", "after", "guard_output_sha256", "guard_values", "accepted")), "Selected prefix is not the exact cloned candidate prefix")
        require(row["selected_after"] == actual["after"], "Exploration path advanced to a terminal tail instead of the prefix")
        paths[(trajectory, step)] = actual["after"]
    require(len(bases) == 1 and all(value == initial[0] for value in initial), "Fit trajectories lack a common initial state")
    for trajectory in range(4):
        terminal = checkpoint(directory / f"trajectory-{trajectory}-terminal.pt", protocol, seed)
        require(terminal["identity"] == paths[(trajectory, 240)] and terminal["frozen_base_sha256"] in bases,
                "Executed path terminal checkpoint differs")
    resources = cost_check(complete["resources"], "bank", seed, list(receipts.values()), registry, p)
    return {"passed": True, "seed": seed, "phase": "bank", "branch_sets": 24, "terminal_actions": 96,
        "all_selected_prefixes_exact": True, "full_reference_tails_checked": 96, "journal_records": len(records),
        "checkpoints_checked": 28, "hard_output_rows_checked": output_rows, "cost_audit": resources,
        "complete_sha256": digest(directory / "COMPLETE.json"), "bank_sha256": digest(directory / "BANK.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("reference", "bank"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--seed", type=int, choices=(17, 29, 43), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SCIENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.resolve().is_relative_to((args.run / args.phase / str(args.seed)).resolve()),
            "Audit report must be new and outside the completed stage")
    started = time.perf_counter_ns()
    result = (audit_reference if args.phase == "reference" else audit_bank)(args.run, args.seed, args.freeze, args.source)
    result.update(schema="hepta.field-bridge.v3.independent-training-integrity.1", script_sha256=digest(__file__),
        helpers_sha256=digest(Path(__file__).with_name("training_audit_common.py")),
        verification_wall_ns=time.perf_counter_ns() - started, actual_source_roles_loaded=[],
        verification_gradient_microsteps=0, original_scientific_evidence_modified=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
