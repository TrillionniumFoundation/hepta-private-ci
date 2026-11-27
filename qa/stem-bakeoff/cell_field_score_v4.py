"""Open withheld labels only after verifying the complete frozen run inventory."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from cell_field_action_io import write_json
from cell_field_evaluate import metrics
from cell_field_evaluate_v4 import evaluate_probabilities, verify_pre_label_seal
from cell_field_features import file_hash


def _labels(data, inputs, plan, task):
    roles = {}
    for filename in ("validation_labels.json", "final_labels.json"):
        path = data / filename
        expected = inputs["data_receipt"]["files"][filename]
        if (path.is_symlink() or path.stat().st_size != expected["bytes"]
                or file_hash(path) != expected["sha256"]):
            raise ValueError("withheld labels differ from their pre-run identity")
        payload = json.loads(path.read_bytes())
        for role, values in payload["roles"].items():
            sources = inputs["sources"]
            expected_indices = [row["index"] for row in sources if row["role"] == role]
            y = np.asarray(values["labels"], dtype=np.int64)
            if (role in roles or values["indices"] != expected_indices
                    or len(y) != plan["source_counts"][task][role]
                    or values["source_ids"] != [sources[i]["source_id"] for i in expected_indices]
                    or np.any(y < 0) or np.any(y >= 4)):
                raise ValueError("withheld label/source role mismatch")
            roles[role] = {"indices": np.asarray(expected_indices), "labels": y,
                          "components": np.asarray([sources[i]["component_id"] for i in expected_indices])}
    if set(roles) != {"old_validation", "current_validation", "old_test", "future_test"}:
        raise ValueError("exact withheld role census required")
    return roles


def pressure_retention(run, inputs, labels):
    rows = []
    for fit in run["fits"]:
        directory = inputs[fit["task"]]["root"] / f"seed{fit['seed']}-{fit['head']}"
        if not (directory / "warmup/warmup.npz").is_file():
            rows.append({"fit_id": fit["fit_id"], "status": "unavailable"})
            continue
        role = labels[fit["task"]]["old_test"]
        with np.load(directory / "warmup/warmup.npz", allow_pickle=False) as archive:
            anchor = metrics(archive["probabilities"][role["indices"]], role["labels"])[0]["nll"]
        for name in ("prevention", "recovery"):
            path = directory / "pressure" / name
            if not path.is_dir():
                continue
            results = json.loads((path / "results.json").read_bytes())
            for i, result in enumerate(results):
                row = {"fit_id": fit["fit_id"], "checkpoint": name,
                       "candidate_id": result["candidate_id"], "status": result["execution_status"]}
                if result["execution_status"] == "completed":
                    with np.load(path / f"actual/{i}.npz", allow_pickle=False) as archive:
                        trajectory = [metrics(p, role["labels"])[0]["nll"]
                                      for p in archive["retention_probabilities"]]
                    excess = np.asarray(trajectory) - anchor
                    row.update(warmup_old_test_nll=anchor, path_old_test_nll=trajectory,
                        inherited_excess=float(excess[0]), maximum_future_excess=float(excess[1:].max()),
                        terminal_excess=float(excess[-1]),
                        future_retention_within_tolerance=bool(excess[1:].max() <= 1e-9))
                rows.append(row)
    return {"rows": rows, "scope": "independent old-test mean NLL at every actual H8 step; no retuning or candidate selection"}


def score(run, data, protocol, output):
    root, data, protocol, output = map(Path, (run, data, protocol, output))
    seal = verify_pre_label_seal(root, protocol)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "label_access.json", {"verified_pre_evaluation_seal_sha256":
        file_hash(root / "pre_evaluation_seal.json"), "protocol_sha256": seal["protocol_sha256"],
        "access_authorized_at": datetime.now(timezone.utc).isoformat(),
        "intent": "score all fixed policies and independent retention paths; no model or protocol changes"})
    plan = json.loads(protocol.read_bytes())
    run_record = json.loads((root / "run.json").read_bytes())
    roles, sources, labels, components, probabilities, costs = {}, {}, {}, {}, {}, {}
    for task in plan["tasks"]:
        sources[task] = {**json.loads((root / task / "inputs.json").read_bytes()), "root": root / task}
        roles[task] = _labels(data / task, sources[task], plan, task)
        mapping = {"current": "current_validation", "old": "old_test", "future": "future_test"}
        labels[task] = {key: roles[task][role]["labels"] for key, role in mapping.items()}
        components[task] = {key: roles[task][role]["components"] for key, role in mapping.items()}
        probabilities[task], costs[task] = {}, {}
        for head in plan["head_modes"]:
            probabilities[task][head], costs[task][head] = {}, {}
            for seed in plan["seeds"]:
                directory = root / task / f"seed{seed}-{head}"
                entry, cost_entry = {}, {}
                warm = directory / "warmup/warmup.npz"
                if warm.is_file():
                    with np.load(warm, allow_pickle=False) as archive:
                        entry["warmup_old"] = archive["probabilities"][roles[task]["old_test"]["indices"]]
                for policy in plan["mpc"]["policies"]:
                    path = directory / "mpc" / policy
                    if not (path / "result.json").is_file():
                        continue
                    result = json.loads((path / "result.json").read_bytes())
                    cost_entry[policy] = {key: result[key] for key in ("status", "cpu_ns", "wall_ns")}
                    if result["status"] != "completed" or result["completed_steps"] != plan["mpc"]["steps"]:
                        cost_entry[policy]["status"] = "unavailable"
                        continue
                    with np.load(path / "trajectory.npz", allow_pickle=False) as archive:
                        values = archive["terminal_probabilities"]
                    entry[policy] = {key: values[roles[task][role]["indices"]] for key, role in mapping.items()}
                probabilities[task][head][seed], costs[task][head][seed] = entry, cost_entry
    result = evaluate_probabilities(probabilities, labels, components, plan, costs)
    result.update(protocol_sha256=seal["protocol_sha256"],
        pre_evaluation_seal_sha256=file_hash(root / "pre_evaluation_seal.json"),
        evaluated_at=datetime.now(timezone.utc).isoformat())
    write_json(output / "evaluation.json", result)
    write_json(output / "pressure-retention.json", pressure_retention(run_record, sources, roles))
    write_json(output / "scientific_review.json", {"candidate": plan["mpc"]["candidate"],
        "protocol_sha256": result["protocol_sha256"], "evaluation_sha256": file_hash(output / "evaluation.json"),
        "pre_evaluation_seal_sha256": result["pre_evaluation_seal_sha256"],
        "disposition": "eligible_for_trusted_native_review" if result["all_registered_gates_met"] else "REJECT",
        "failed_primary": [row for row in result["primary_contrasts"] if not row["criterion_met"]],
        "failed_compute": [row for row in result["cost_contrasts"] if not row["criterion_met"]],
        "authority": "DENY_ALL", "production_authority": False,
        "scope": "local scientific evaluation receipt; not a signature, host trust root or activation"})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "data", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    result = score(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("census_complete", "primary_criteria_met",
        "all_scientific_criteria_met", "all_cost_criteria_met", "all_registered_gates_met")}))
