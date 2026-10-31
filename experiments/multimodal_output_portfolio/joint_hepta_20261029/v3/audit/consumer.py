"""Audit only the additional 256 first-choice continuations, without reruns."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ...mechanism_data import batch
from ...model import ACTIONS
from ..model import JointGenerator, State
from .core import Audit, digest, read, sha, tensor_digest, trajectory
from .diagnostic import restore_npz
from .matrix import paired


def run(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    v3 = Path(__file__).resolve().parent.parent
    root = v3/"evidence/critic_choice_frozen_20261030"
    result, protocol = read(root/"RESULT.json"), read(root/"FROZEN_PROTOCOL.json")
    selected = v3/"evidence/matrix_frozen_20261030/seed-17-width-32/dual.joint.dynamic/MODEL.pt"
    calibrated = v3/"evidence/diagnostics_frozen_20261030/MODEL_CALIBRATED.pt"
    torch.set_num_threads(1); started = time.perf_counter()
    models, states = [], []
    for path in (selected, calibrated):
        payload = torch.load(path, map_location="cpu", weights_only=True)
        model = JointGenerator(**payload["config"]).eval(); model.load_state_dict(payload["state_dict"])
        models.append(model); states.append(payload["state_dict"])
    with (output/"TRAJECTORY_AUDIT.jsonl").open("w") as log:
        audit = Audit(v3, log)
        audit.check(protocol == result["protocol"], "consumer_protocol_identity", root)
        audit.check(protocol["original_checkpoint_sha256"] == sha(selected) and
                    protocol["calibrated_checkpoint_sha256"] == sha(calibrated), "consumer_actual_checkpoint_binding", root)
        audit.check([tensor_digest(x) for x in states] == protocol["model_hashes"], "consumer_checkpoint_parameter_identity", root)
        frozen = [{k: v for k, v in state.items() if not k.startswith(("critic.", "delivery_critic."))} for state in states]
        audit.check(tensor_digest(frozen[0]) == tensor_digest(frozen[1]) == protocol["content_actor_sha256"],
                    "consumer_same_generator_and_actor", root)
        audit.check(sha(v3/"critic_choice/run.py") == protocol["consumer_source_sha256"], "consumer_source_identity", root)
        audit.sources(protocol["profile"]["source"], v3)
        by_source, by_arm = defaultdict(list), defaultdict(list)
        for row in result["rows"]:
            by_source[row["source_id"]].append(row)
        expected_ids = {f"{protocol['source_namespace']}.{i}" for i in range(protocol["sources"])}
        audit.check(set(by_source) == expected_ids, "consumer_source_completeness", root)
        for source_id, rows in by_source.items():
            identity = int(source_id.rsplit(".", 1)[1]); source_dir = root/f"source-{identity:03d}"
            public, _ = batch([identity], protocol["source_namespace"])
            retained = restore_npz(source_dir/"PREFIX_STATE.npz")
            state = State(**retained); prefix = read(source_dir/"PREFIX.json")
            audit.check(tensor_digest(public) == prefix["input_hash"] and tensor_digest(retained) == prefix["state_hash"],
                        "consumer_source_prefix_binding", source_dir)
            audit.check(all(torch.equal(public[k], v) for k, v in restore_npz(source_dir/"PUBLIC_INPUT.npz").items()),
                        "consumer_actual_public_input", source_dir)
            predictions = {}
            for name, model in zip(("original_critic_first", "calibrated_critic_first"), models):
                values = {}
                with torch.no_grad():
                    for action in ACTIONS:
                        if action == "stop":
                            features = model.features(state, prefix["budget"]/protocol["profile"]["initial_budget"])
                            value = model.delivery_critic(features)[0, 0]
                        else:
                            child, _ = model.advance(state, action, public)
                            fee = protocol["profile"]["tariff"][action]
                            features = model.features(child, (prefix["budget"]-fee)/protocol["profile"]["initial_budget"])
                            value = model.critic(features)[0, 0] + 2 * fee
                        values[action] = float(value)
                predictions[name] = values
            seen, common = set(), defaultdict(set)
            for row in rows:
                branch = source_dir/f"draw-{row['draw']}"/row["arm"]
                item = trajectory(audit, branch/"TRAJECTORY.json", "critic_choice.analysis", protocol["model_hashes"][0])
                runtime = read(branch/"TRAJECTORY.json"); seal = read(branch/"SEAL_COST.json")
                audit.check(read(branch/"CONSUMER_OUTCOME.json") == row, "consumer_retained_outcome_identity", branch)
                audit.check(row["events"][:-1] == runtime["events"]+[seal], "consumer_runtime_ledger_identity", branch)
                close = row["caller_close"]
                audit.check(row["events"][-1] == close and close["cpu_seconds"] >= 0 and close["wall_seconds"] >= 0,
                            "consumer_caller_close_retained", branch)
                fee = protocol["profile"]["tariff"]
                audit.near(close["amount"], close["cpu_seconds"]*fee["cpu_second"]+close["wall_seconds"]*fee["wall_second"],
                           "consumer_close_meter_arithmetic", branch)
                total = item["sealed_cost"]+close["amount"]
                audit.near(row["actual_cost"], total, "consumer_entire_cost", branch)
                audit.near(math.fsum(event["amount"] for event in row["events"]), total, "consumer_all_events_sum", branch)
                audit.near(row["net_return"], item["utility"]-total, "consumer_complete_return", branch)
                audit.near(row["runtime_net_return_through_seal"], item["sealed_return"], "consumer_runtime_return", branch)
                audit.check(row["actions"] == item["actions"] and row["failure"] == item["failure"], "consumer_actions_failure", branch)
                seed = 31000000+identity*10000+row["draw"]*997
                tape = {"actor_rng": torch.Generator().manual_seed(seed).get_state(),
                        "emission_rng": torch.Generator().manual_seed(seed ^ 0x5EED1234).get_state()}
                audit.check(seed == row["seed"] and tensor_digest(tape) == row["common_future_randomness_sha256"],
                            "consumer_named_future_rng", branch)
                expected_origin = digest({"state": prefix["state_hash"], "budget": prefix["budget"], "cost": prefix["prefix_cost"],
                    "events": [runtime["events"][0]], "model": protocol["model_hashes"][0], "input": prefix["input_hash"],
                    "profile": digest(protocol["profile"]), "rng": tensor_digest((tape["actor_rng"], tape["emission_rng"]))})
                audit.check(expected_origin == row["common_prefix_snapshot_sha256"], "consumer_independent_common_snapshot", branch)
                common[row["draw"]].add(row["common_prefix_snapshot_sha256"])
                key = (row["draw"], row["arm"]); audit.check(key not in seen, "consumer_unique_arm_draw", branch); seen.add(key)
                if row["arm"] in predictions:
                    expected = predictions[row["arm"]]
                    audit.check(set(row["predicted_action_log_moments"]) == set(expected), "consumer_candidate_coverage", branch)
                    for action, value in expected.items():
                        audit.near(row["predicted_action_log_moments"][action], value, "independent_critic_action_value", branch, 3e-7)
                    chosen = min(ACTIONS, key=expected.get)
                    audit.check(chosen == row["planned_first_action"] == row["selected_first_action"], "actual_critic_first_choice_consumed", branch)
                    planners = [e for e in runtime["events"] if e["action"] == "critic_first_choice"]
                    audit.check(len(planners) == 1, "one_charged_planning_event", branch)
                    audit.near(row["planning_cost"], planners[0]["amount"], "actual_planning_cost", branch)
                elif row["arm"] == "actor":
                    with torch.no_grad():
                        law, _ = models[0].policy(state, prefix["budget"]/protocol["profile"]["initial_budget"])
                        chosen = ACTIONS[int(torch.multinomial(law.exp(), 1, generator=torch.Generator().manual_seed(seed)).item())]
                    audit.check(row["selected_first_action"] == chosen, "independent_original_actor_first_sample", branch)
                else:
                    audit.check(row["selected_first_action"] == "stop", "consumer_initial_stop_control", branch)
                by_arm[row["arm"]].append({"source": source_id, "draw": row["draw"], "sealed_return": row["net_return"], **row})
            audit.check(seen == {(draw, arm) for draw in range(protocol["draws_per_source"]) for arm in protocol["arms"]},
                        "consumer_complete_control_grid", source_dir)
            audit.check(all(len(x) == 1 for x in common.values()), "consumer_same_draw_origin_across_arms", source_dir)
        for values in by_arm.values():
            values.sort(key=lambda r: (r["source"], r["draw"]))
        for comparison, report in result["comparisons"].items():
            left, right = comparison.split("__minus__")
            paired(audit, by_arm[left], by_arm[right], report, root, seed=31, bootstrap=1000)
        for arm, values in by_arm.items():
            report = result["arms"][arm]
            audit.check(report["first_choices"] == dict(Counter(r["selected_first_action"] for r in values)), "consumer_first_choice_counts", root)
            audit.near(report["mean_cost"], np.mean([r["actual_cost"] for r in values]), "consumer_arm_mean_cost", root)
            audit.near(report["mean_utility"], np.mean([r["utility"] for r in values]), "consumer_arm_mean_utility", root)
        audit.check(audit.counts["trajectories"] == result["actual_continuations"] == 256, "consumer_all_256_retained", root)
        main = read(v3/"audit/evidence/final_20261031/AUDIT.json")
        earlier_namespaces = {ns for value in main["source_roles"].values() for ns in value["namespaces"]}
        audit.check(protocol["source_namespace"] not in earlier_namespaces, "consumer_new_source_namespace", root)
        log.flush()
        report = {"schema": "hepta.v3.independent-consumer-audit.v1", "passed": not audit.errors,
                  "trajectories": audit.counts["trajectories"], "errors": audit.errors, "checks": dict(audit.counts),
                  "max_independent_utility_absolute_error": audit.max_utility_error,
                  "main_audit_sha256": sha(v3/"audit/evidence/final_20261031/AUDIT.json"),
                  "combined_verified_trajectories": main["checks_by_kind"]["trajectories"]+audit.counts["trajectories"],
                  "source_sha256": {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  "consumer_result_sha256": sha(root/"RESULT.json"), "trajectory_audit_sha256": sha(output/"TRAJECTORY_AUDIT.jsonl"),
                  "wall_seconds": time.perf_counter()-started,
                  "scope": "actual first action, fixed original content/actor continuation, all per-branch events and decoded outputs; no gain qualification"}
        (output/"AUDIT.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"audit_passed": report["passed"], "trajectories": report["trajectories"], "errors": len(report["errors"])}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.output)
    raise SystemExit(0 if result["passed"] else 1)
