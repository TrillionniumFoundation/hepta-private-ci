"""V6 label release after complete frozen-source and actual repaired-state replay."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from cell_field_action_io import write_json
from cell_field_audit_v6 import audit_run, read_arrays, read_json
from cell_field_evaluate_v6 import TASKS, HEADS, SEEDS, POLICIES, evaluate_probabilities, evaluation_protocol
from cell_field_features import file_hash
from cell_field_score_v5 import decrypt_roles, independent_path


def score(run, data, protocol, output, label_key):
    root, data, protocol, output = map(Path, (run, data, protocol, output))
    if output.resolve().is_relative_to(root.resolve()) or output.exists():
        raise ValueError("new evaluation directory outside sealed predictions required")
    plan = read_json(protocol)
    if plan["evaluation"] != evaluation_protocol():
        raise ValueError("frozen V6 evaluation family changed")
    output.mkdir(parents=True)
    try:
        audit = audit_run(root, data, protocol)
    except Exception as error:
        audit = {"all_replays_valid": False, "heldout_labels_opened": False,
                 "error": {"type": type(error).__name__, "message": str(error)}}
    write_json(output/"pre_label_audit.json", audit)
    if not audit["all_replays_valid"]:
        rejected = {"schema": "hepta.cell-field-fresh-evaluation.v6", "disposition": "REJECT_PRE_LABEL_AUDIT",
            "all_registered_gates_met": False, "heldout_labels_opened": False,
            "reason": "sealed pre-label replay or complete finite prediction census failed",
            "authority": "DENY_ALL", "production_authority": False}
        write_json(output/"evaluation.json", rejected)
        write_json(output/"scientific_review.json", rejected)
        return rejected
    write_json(output/"label_access.json", {"protocol_sha256": audit["protocol_sha256"],
        "pre_evaluation_seal_sha256": audit["pre_evaluation_seal_sha256"],
        "pre_label_audit_sha256": file_hash(output/"pre_label_audit.json"),
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "scope": "decrypt authenticated labels only in memory; no retuning or selection; key not recorded by evaluator"})
    roles, probabilities, labels, components, costs, path_rows, pressure_rows = {}, {}, {}, {}, {}, [], []
    audited = {(r["task"], r["head"], r["seed"], r["policy"]): r for r in audit["rows"]}
    mapping = {"current": "current_validation", "future": "future_test", "old": "old_test"}
    for task in TASKS:
        inputs = read_json(root/task/"inputs.json")
        roles[task] = decrypt_roles(data/task, inputs, plan, task, audit["protocol_sha256"], label_key)
        labels[task] = {name: roles[task][role]["labels"] for name, role in mapping.items()}
        components[task] = {name: roles[task][role]["components"] for name, role in mapping.items()}
        probabilities[task], costs[task] = {}, {}
        for head in HEADS:
            probabilities[task][head], costs[task][head] = {}, {}
            for seed in SEEDS:
                directory = root/task/f"seed{seed}-{head}"
                old = roles[task]["old_test"]
                warmup = read_arrays(directory/"warmup/warmup.npz")["probabilities"]
                old_warmup = warmup[old["indices"]]
                entry, timing = {"warmup_old": old_warmup}, {}
                for policy in POLICIES:
                    path = directory/"mpc"/policy
                    recorded = read_json(path/"result.json")
                    arrays = read_arrays(path/"trajectory.npz")
                    entry[policy] = {name: arrays["terminal_probabilities"][roles[task][role]["indices"]] for name, role in mapping.items()}
                    timing[policy] = {k: audited[task, head, seed, policy][k]
                                     for k in ("status", "completed_steps", "registered_steps", "cpu_ns", "wall_ns", "valid_record")}
                    path_rows.append({"task": task, "head": head, "seed": seed, "policy": policy,
                        "execution_status": recorded["status"], **independent_path(arrays["probabilities"][:, old["indices"]], old["labels"], old_warmup)})
                probabilities[task][head][seed], costs[task][head][seed] = entry, timing
                pressure = directory/"pressure"
                search = read_json(pressure/"search.json")
                pressure_rows.append({"task": task, "head": head, "seed": seed, "kind": "search", "status": search["status"], "tau": search["tau"]})
                for checkpoint in search["checkpoint_offsets"]:
                    frozen = read_json(pressure/checkpoint/"frozen_plans.json")
                    for i, candidate in enumerate(frozen["plans"]):
                        verified = read_json(pressure/checkpoint/f"verified/{i}.json")
                        arrays = read_arrays(pressure/checkpoint/f"verified/{i}.npz")
                        repaired = independent_path(arrays["retention_probabilities"], old["labels"], old_warmup)
                        row = {"task": task, "head": head, "seed": seed, "kind": "slot", "checkpoint": checkpoint,
                            "candidate_id": candidate["id"], "verification_status": verified["verification"]["status"],
                            "probe_certified": verified["verification"]["certified"], "trajectory_kind": "prospective_return_not_owner_publication",
                            **repaired}
                        guard_path = pressure/checkpoint/f"guarded/{i}.json"
                        if guard_path.exists():
                            guard_record = read_json(guard_path)
                            guarded = independent_path(read_arrays(guard_path.with_suffix(".npz"))["retention_probabilities"], old["labels"], old_warmup)
                            row["original_guard"] = {"verification_status": guard_record["verification"]["status"],
                                "probe_certified": guard_record["verification"]["certified"], **guarded}
                            row["guard_repair_comparison"] = {
                                "same_positive_returned_steps": repaired["committed_steps"] == guarded["committed_steps"] and repaired["committed_steps"] > 0,
                                "repair_minus_guard_terminal_mean_nll": repaired["terminal_mean_nll_excess"]-guarded["terminal_mean_nll_excess"],
                                "scope": "descriptive returned endpoints; a rejected zero-step guard is not a continuing-retention comparator"}
                        pressure_rows.append(row)
    result = evaluate_probabilities(probabilities, labels, components, plan, costs)
    result.update(protocol_sha256=audit["protocol_sha256"], pre_evaluation_seal_sha256=audit["pre_evaluation_seal_sha256"],
                  pre_label_audit_sha256=file_hash(output/"pre_label_audit.json"), evaluated_at=datetime.now(timezone.utc).isoformat())
    write_json(output/"evaluation.json", result)
    write_json(output/"independent-retention.json", {"policies": path_rows, "pressure": pressure_rows,
        "scope": "independent old-test dataset-mean loss paths; no retuning; only actually returned/committed trajectories scored"})
    write_json(output/"scientific_review.json", {"candidate": plan["evaluation"]["candidate"],
        "protocol_sha256": result["protocol_sha256"], "evaluation_sha256": file_hash(output/"evaluation.json"),
        "pre_evaluation_seal_sha256": result["pre_evaluation_seal_sha256"],
        "pre_label_audit_sha256": result["pre_label_audit_sha256"],
        "disposition": "eligible_for_trusted_native_review" if result["all_registered_gates_met"] else "REJECT",
        "failed_primary": [r for r in result["primary_contrasts"] if not r["criterion_met"]],
        "failed_compute": [r for r in result["cost_contrasts"] if not r["criterion_met"]],
        "failed_completion": [r for r in result["completion_gates"] if not r["criterion_met"]],
        "authority": "DENY_ALL", "production_authority": False,
        "scope": "local scientific review receipt, not a host trust root or activation capability"})
    return result


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "data", "protocol", "output"):
        parser.add_argument("--"+name, required=True)
    args = vars(parser.parse_args())
    key = bytes.fromhex(sys.stdin.readline().strip())
    result = score(**args, label_key=key)
    print(json.dumps({k: result.get(k) for k in ("census_complete", "candidate_completed_fits", "primary_criteria_met", "all_registered_gates_met", "disposition")}))
