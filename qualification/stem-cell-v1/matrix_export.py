"""Join separately supplied labels to an externally pinned prediction seal.

No owner attestation is issued here. The output feeds paired_execution.audit_pair
without fabricating missing FLOPs/energy/peak memory or independent superiority.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from matrix_materials import file_sha256, strict_json, validate_config
from next_round_matrix import _digest
from paired_execution import PHASES, _integer, _sha


def read_sealed(directory, expected_seal_id):
    root = Path(directory)
    _sha(expected_seal_id, "independently retained prediction seal")
    if (root / "FAILED.json").exists():
        raise ValueError("failed or publication-uncertain run cannot be consumed")
    for name in ("COMMITTED.json", "execution.json", "predictions.json", "bank.safetensors"):
        if (root / name).is_symlink() or not (root / name).is_file():
            raise ValueError("missing, partial or linked prediction artifact")
    seal = strict_json(root / "COMMITTED.json")
    if (not isinstance(seal, dict) or set(seal) != {"schema", "files", "seal_id", "sealed_at_ns"}
            or seal["schema"] != "hepta.stem.prediction-seal.v1"
            or not isinstance(seal["files"], dict)
            or set(seal["files"]) != {"execution.json", "predictions.json", "bank.safetensors"}):
        raise ValueError("invalid prediction seal inventory")
    if seal["seal_id"] != expected_seal_id or _digest({k: v for k, v in seal.items() if k != "seal_id"}) != expected_seal_id:
        raise ValueError("prediction seal changed from retained reference")
    for name, digest in seal["files"].items():
        _sha(digest, "artifact digest")
        if file_sha256(root / name) != digest:
            raise ValueError("sealed prediction or weight artifact changed")
    return strict_json(root / "execution.json"), strict_json(root / "predictions.json"), seal


def _validate_population(execution, profile, contract):
    growth = execution.get("growth_receipt")
    growing = execution["config"].get("growth_policy")
    if (growing is not None) != (execution["schema"] == "hepta.stem.bound-execution.v2"):
        raise ValueError("growth execution must preserve its explicit schema")
    if growing is not None:
        from matrix_growth import GROWTH_ARMS
        if (not isinstance(growth, dict) or growth.get("policy_id") != _digest(growing)
                or growth.get("split_performed") is not (profile["arm_id"] in GROWTH_ARMS)
                or execution.get("peak_trainable_params") != growth.get("peak_live_trainable_params")
                or execution["training"].get("growth") != growth
                or growth.get("decision_step") != growing["decision_step"]
                or growth.get("optimizer_reset_count") != 1):
            raise ValueError("incomplete or inconsistent actual growth evidence")
        _integer(growth["decision_step"], "growth decision step", 1)
        _integer(growth["optimizer_reset_count"], "optimizer reset count", 1)
        _integer(growth.get("source_group_count"), "growth source group count", 1)
        residual = growth.get("training_residual")
        if type(residual) not in (int, float) or not math.isfinite(residual) or residual < 0:
            raise ValueError("invalid recorded training residual")
        if growth["split_performed"] and (residual <= growing["loss_threshold"]
                or growth["source_group_count"] < growing["minimum_source_groups"]):
            raise ValueError("claimed split did not satisfy its frozen criterion")
        if execution["training"].get("steps") != execution["config"]["train_steps"]:
            raise ValueError("training step count differs from frozen schedule")
        _integer(execution["peak_trainable_params"], "live transition parameters", 1)
        if execution["peak_trainable_params"] > contract["max_peak_trainable_params"]:
            raise ValueError("growth exceeded the common lifecycle budget")
    elif growth is not None:
        raise ValueError("legacy execution cannot claim a growth transition")
    inventory = execution["inventory"]
    if inventory["cells"] != profile["logical_cells"] or inventory["active_cells_cap"] != profile["active_cells_per_round_cap"]:
        raise ValueError("actual population geometry differs from plan")
    for name in ("head_params", "gate_params", "parameters", "trainable_parameters"):
        _integer(inventory[name], name, 1)
    if inventory["head_params"] + inventory["gate_params"] != inventory["parameters"] or inventory["parameters"] != inventory["trainable_parameters"]:
        raise ValueError("incomplete actual bank parameter accounting")
    if inventory["parameters"] > profile["total_head_budget_params"]:
        raise ValueError("total trainable parameters exceed the bound")
    if growing is not None:
        if execution["peak_trainable_params"] < inventory["parameters"]:
            raise ValueError("transition peak below current parameters")
        if growth["split_performed"]:
            if (growth.get("final_parameters") != inventory["parameters"]
                    or growth.get("parent_for_child") != [i % 16 for i in range(32)]
                    or growth.get("parent_parameters", 0) * 2 != inventory["parameters"]
                    or growth["peak_live_trainable_params"] != growth["parent_parameters"] + inventory["parameters"]):
                raise ValueError("growth lineage or live tensor inventory changed")
    if growing is not None:
        from family_routing import POLICY_SCHEMA as FAMILY_SCHEMA, validate_family_record
        if growing["schema"] == FAMILY_SCHEMA:
            validate_family_record(growth, inventory, growing)
        elif "routing_profile" in inventory or "transition_probe" in growth:
            raise ValueError("legacy flat routing cannot be relabeled as family preservation")
    retained = execution["config"].get("retention_policy")
    if retained is not None:
        from retention_training import validate_retention_record
        if execution["training"].get("retention") != execution.get("retention_receipt"):
            raise ValueError("inconsistent retention observation")
        validate_retention_record(execution.get("retention_receipt"), retained,
                                  execution["trained_bank_sha256"], execution["classification_classes"])
        role_counts = execution["retention_receipt"]["role_examples"]
        if (growth["probe_examples"] != role_counts["old_train_groups"] + role_counts["new_train_groups"]
                or growth.get("residual_probe_examples") != role_counts["new_train_groups"]
                or growth["source_group_count"] != len(retained["new_train_groups"])):
            raise ValueError("validation folds entered the growth probe")
        phase2 = execution["config"]["train_steps"] - growing["decision_step"]
        batch = execution["config"]["batch_size"]
        expected = {"replay_examples_seen": phase2 * min(batch, role_counts["old_train_groups"]),
                    "new_examples_seen": phase2 * min(batch, role_counts["new_train_groups"]),
                    "reference_bank_rows": phase2 * min(batch, role_counts["old_train_groups"])}
        first_seen = growing["decision_step"] * min(batch, role_counts["old_train_groups"])
        if (execution["training"].get("retained_specialization") != expected
                or growth["pre_growth_training"]["examples_seen"] != first_seen
                or execution["training"]["examples_seen"] != first_seen + expected["replay_examples_seen"] + expected["new_examples_seen"]):
            raise ValueError("replay/reference training work denominator mismatch")
    elif "retention_receipt" in execution or "retention" in execution["training"]:
        raise ValueError("legacy run cannot claim a retention protocol")
    return growth, growing, retained


def export_observed(plan, contract, directory, *, expected_seal_id, observer_path, expected_observer_sha256):
    _sha(expected_observer_sha256, "independent observer receipt digest")
    if file_sha256(observer_path) != expected_observer_sha256:
        raise ValueError("observer bytes differ from retained reference")
    observer = strict_json(observer_path)
    execution, predictions, seal = read_sealed(directory, expected_seal_id)
    if execution.get("schema") not in ("hepta.stem.bound-execution.v1", "hepta.stem.bound-execution.v2", "hepta.stem.bound-execution.v3"):
        raise ValueError("single-Head/legacy receipts cannot be relabeled as V2 Cell populations")
    profile = validate_config(plan, contract, execution["config"])
    for key in ("contract_id", "source_sha", "device_id", "workload_sha256"):
        if execution[key] != contract[key]:
            raise ValueError("sealed execution does not match frozen " + key)
    if execution["plan_id"] != plan["plan_id"] or execution["arm_id"] != profile["arm_id"]:
        raise ValueError("wrong plan or arm identity")
    if execution["outcomes_loaded"] is not False or execution["production_authorized"] is not False:
        raise ValueError("model execution cannot load outcomes or grant authority")
    compressed = execution["config"].get("consolidation_policy")
    if compressed is not None:
        from consolidation_record import precursor_projection
        precursor = precursor_projection(execution, execution["config"], contract)
        growth, growing, retained = _validate_population(precursor, profile, contract)
    else:
        if execution["schema"] == "hepta.stem.bound-execution.v3" or "consolidation_receipt" in execution:
            raise ValueError("unbound compression cannot be relabeled")
        growth, growing, retained = _validate_population(execution, profile, contract)
    inventory = execution["inventory"]
    if set(execution["phase_flops"]) != set(PHASES):
        raise ValueError("all physical work phases required")
    for phase, value in execution["phase_flops"].items():
        if value is not None:
            _integer(value, phase)
    expected_fields = {"schema", "seal_id", "contract_id", "observer_id", "created_at_ns", "rows"}
    if (not isinstance(observer, dict) or set(observer) != expected_fields
            or observer["schema"] != "hepta.stem.independent-labels.v1"
            or observer["seal_id"] != expected_seal_id
            or observer["contract_id"] != contract["contract_id"]
            or observer["observer_id"] != contract["observer_id"]):
        raise ValueError("observer receipt is not bound to this sealed execution")
    sealed = _integer(seal["sealed_at_ns"], "seal time", 1)
    if _integer(execution["predictions_complete_at_ns"], "prediction completion time", 1) > sealed:
        raise ValueError("seal cannot precede prediction completion")
    created = _integer(observer["created_at_ns"], "observer receipt time", 1)
    if not contract["eval_start_ns"] <= sealed <= created < contract["eval_end_ns"]:
        raise ValueError("observer join must follow sealing within the frozen future window")
    labels = observer["rows"]
    if (not isinstance(predictions, list) or not isinstance(labels, list)
            or len(predictions) != len(contract["task_ids"]) or len(labels) != len(predictions)):
        raise ValueError("complete prediction and observation denominators required")
    requests, briers, correctness, confidences = [], [], [], []
    classes = _integer(execution["classification_classes"], "class count", 2)
    if classes > 16:
        raise ValueError("invalid legal-action width")
    for task_id, prediction, label in zip(contract["task_ids"], predictions, labels, strict=True):
        if (not isinstance(label, dict) or set(label) != {"task_id", "input_digest", "label", "observed_at_ns"}
                or prediction["task_id"] != task_id or label["task_id"] != task_id
                or label["input_digest"] != prediction["input_digest"]):
            raise ValueError("unpaired, reordered or substituted observation")
        _sha(label["input_digest"], "prediction input digest")
        target = _integer(label["label"], "independent label")
        if target >= classes:
            raise ValueError("independent label outside legal set")
        timestamp = _integer(label["observed_at_ns"], "observation time", 1)
        predicted = _integer(prediction["predicted_at_ns"], "prediction time", 1)
        if not contract["eval_start_ns"] <= predicted <= sealed <= timestamp <= created:
            raise ValueError("observation cannot precede prediction sealing")
        status, logits = prediction["status"], prediction["logits"]
        outcome = 0  # Preregistered availability-weighted classification accuracy.
        if status == "completed":
            if (not isinstance(logits, list) or len(logits) != classes
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in logits)):
                raise ValueError("invalid complete prediction")
            pivot = max(logits)
            exps = [math.exp(v - pivot) for v in logits]
            probabilities = [v / sum(exps) for v in exps]
            predicted_class = max(range(classes), key=logits.__getitem__)
            outcome = int(predicted_class == target)
            confidences.append(max(probabilities))
            correctness.append(outcome)
            briers.append(sum((p - int(i == target)) ** 2 for i, p in enumerate(probabilities)))
        elif status not in ("failed", "timed_out", "unknown") or logits is not None:
            raise ValueError("failed/unknown requests cannot contain successful logits")
        latency = _integer(prediction["latency_ns"], "end-to-end latency", 1)
        requests.append(dict(task_id=task_id, status=status, latency_ns=latency,
                             energy_joules=prediction["energy_joules"], peak_memory_bytes=prediction["peak_memory_bytes"],
                             outcome=outcome, observed_at_ns=timestamp, observer_id=observer["observer_id"]))
    # Recheck publication and observer input after parsing/joining. This is not
    # a defense against malicious change-and-restore or independent attestation.
    read_sealed(directory, expected_seal_id)
    if file_sha256(observer_path) != expected_observer_sha256:
        raise ValueError("observer changed during join")
    export = dict(schema="hepta.stem.paired-run-export.v1", contract_id=contract["contract_id"],
                  arm_id=execution["arm_id"], source_sha=contract["source_sha"], device_id=contract["device_id"],
                  workload_sha256=contract["workload_sha256"], head_params=inventory["head_params"],
                  trainable_params=inventory["trainable_parameters"], peak_trainable_params=execution.get("peak_trainable_params", inventory["parameters"]),
                  unique_weight_bytes=execution["unique_weight_bytes"], phase_flops=execution["phase_flops"],
                  flop_profile=execution["flop_profile"], flop_components=execution["flop_components"],
                  execution_kind=execution["execution_kind"], weight_receipt_sha256=_digest(execution["encoder_receipt"]),
                  observer_receipt_sha256=expected_observer_sha256, requests=requests)
    # Reliability is reported with its own denominator; failures are not
    # silently omitted from the end-to-end task accuracy.
    ece = 0.
    for bucket in range(10):
        ids = [i for i, c in enumerate(confidences) if min(9, int(c * 10)) == bucket]
        if ids:
            ece += abs(sum(confidences[i] - correctness[i] for i in ids)) / len(confidences)
    summary = dict(total=len(requests), completed=len(briers), failed_or_unknown=len(requests) - len(briers),
                   availability_weighted_accuracy=sum(r["outcome"] for r in requests) / len(requests),
                   completed_only_brier=sum(briers) / len(briers) if briers else None,
                   completed_only_ece_10_bins=ece if briers else None,
                   failure_penalized_brier=(sum(briers) + 2 * (len(requests) - len(briers))) / len(requests),
                   retention_established=False, statistical_superiority_established=False,
                   independent_observer_authenticity_verified=False, production_authorized=False)
    if retained is not None:
        summary["retention_receipt"] = execution["retention_receipt"]
    if "work_observation" in execution:
        observation = execution["work_observation"]
        if observation.get("stopped") is not None:
            raise ValueError("budget-stopped execution cannot be scored as completed")
        if observation.get("policy") != execution["config"].get("measurement_policy"):
            raise ValueError("measurement policy differs from frozen configuration")
        if execution["flop_profile"] != observation.get("profile"):
            raise ValueError("measurement profile changed")
        checked_phases = ("train", "inference", "migration") if compressed is not None or (growing and growth["split_performed"]) else ("train", "inference")
        for phase in checked_phases:
            if execution["phase_flops"][phase] != observation["phase_flops"][phase]:
                raise ValueError("execution count differs from its measurement record")
        # Do not substitute a whole-process high-water mark or package energy
        # into the stricter per-request metrics consumed by paired_execution.
        summary["execution_work_observation"] = observation
    if growing is not None:
        # Preserve matching data/training/optimizer-reset references through the
        # normalized export. An arm label alone is not a controlled comparison.
        cfg = execution["config"]
        protocol = {k: cfg.get(k) for k in ("growth_policy", "train_steps", "batch_size", "width_units",
                    "context_tokens", "snapshot_sha256", "encoder_profile", "measurement_policy")}
        if retained is not None:
            protocol["retention_policy"] = retained
        if compressed is not None:
            protocol["consolidation_policy"] = compressed
        protocol.update(seed=plan["seed"], workload_sha256=contract["workload_sha256"])
        export.update(schema="hepta.stem.paired-run-export.v2", training_protocol_sha256=_digest(protocol))
        summary["growth_receipt"] = growth
    if compressed is not None:
        report = execution["consolidation_receipt"]
        export.update(schema="hepta.stem.paired-run-export.v3", output_profile=execution["output_profile"],
                      precursor_trainable_params=report["teacher_parameters"])
        summary["consolidation_receipt"] = report
    return export, summary


def main():
    from matrix_runtime import write_json_exclusive
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "contract", "run-dir", "seal-id", "observer", "observer-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    export, summary = export_observed(strict_json(args.plan), strict_json(args.contract), args.run_dir,
                                      expected_seal_id=args.seal_id, observer_path=args.observer,
                                      expected_observer_sha256=args.observer_sha256)
    # Exclusive output directory: never overwrite an earlier observer join.
    root = Path(args.output)
    root.mkdir(exist_ok=False)
    write_json_exclusive(root / "paired-run.json", export)
    write_json_exclusive(root / "calibration.json", summary)
    write_json_exclusive(root / "COMMITTED.json", {"seal_id": args.seal_id,
                         "files": {n: file_sha256(root / n) for n in ("paired-run.json", "calibration.json")}})


if __name__ == "__main__":
    main()
