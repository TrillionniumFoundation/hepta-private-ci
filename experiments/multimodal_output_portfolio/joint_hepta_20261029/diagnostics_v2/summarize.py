"""Read-only, fixed-plan analysis of the four registered v2 development runs.

No training or threshold options are provided. The statistical engine and both
plans must match the original registration's source receipts. Original media
are not reopened: their independently executed archive audit is reported as such.
"""

import argparse
import ast
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import tarfile

from .archive import SCHEMA as ARCHIVE_SCHEMA, file_identity, read_json, safe_file
from ..contract import JointGenerationProfile
from ..research_gate_v2 import analyse_panel, read_seal


HERE = Path(__file__).resolve().parents[1]
REGISTRATION = "9a0b16a620b4203093268a2a917f76bb99eb61ef"
PACKAGE = "experiments/multimodal_output_portfolio/joint_hepta_20261029/"
PLAN_FILES = ("development_plan_v2.json", "development_plan_distillation_v2.json")
PLAN_HASHES = ("622661ff7b8b2b38d866a96e25b42553d12479579309b6f5fec0e837f2c37653",
               "d69b201890c11e0c44e3f7ab4ef345be86a1559ec3abacc7feda2258f110abdd")
SCHEMA = "hepta.joint-generation.development-summary.v2"


def registered_tariff():
    """Read the literal from source whose hash is bound by the run receipt."""
    tree = ast.parse((HERE / "runtime.py").read_bytes())
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "TARIFF" for target in node.targets)]
    if len(values) != 1 or values[0]["cpu_second"] != 0.02 or values[0]["wall_second"] != 0.001:
        raise ValueError("Registered time/service tariff literal is unavailable")
    return values[0]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def close(actual, expected, label):
    if (type(actual) not in (int, float) or not math.isfinite(actual)
            or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)):
        raise ValueError("Measured summary disagrees: " + label)


def original_bytes(root, manifest, name):
    matches = [item for item in manifest["preserved_originals"] if item["source_path"] == name]
    if len(matches) != 1:
        raise ValueError("Exactly one preserved original is required: " + name)
    item = matches[0]
    payload = safe_file(root, item["stored_path"]).read_bytes()
    if item["encoding"] == "gzip_original_bytes":
        payload = gzip.decompress(payload)
    elif item["encoding"] != "original_bytes":
        raise ValueError("Unexpected original storage encoding")
    if len(payload) != item["source_bytes"] or sha(payload) != item["source_sha256"]:
        raise ValueError("Preserved original bytes differ: " + name)
    return payload


def original_json(root, manifest, name):
    return json.loads(original_bytes(root, manifest, name))


def validate_compact(root):
    root = Path(root).resolve()
    manifest = read_json(safe_file(root, "MANIFEST.json"))
    if manifest.get("schema") != ARCHIVE_SCHEMA:
        raise ValueError("Not a registered v2 compact archive")
    for name, identity in manifest["stored_files"].items():
        if file_identity(safe_file(root, name)) != identity:
            raise ValueError("Compact stored bytes differ: " + name)
    audit = read_json(safe_file(root, "AUDIT.json"))
    if audit != manifest["audit"] or audit.get("integrity_passed") is not True:
        raise ValueError("Original independent archive audit did not pass")
    if audit.get("process_completed_successfully") is not True:
        raise ValueError("The original metered run is incomplete")
    return root, manifest


def source_binding(root, manifest):
    receipt = original_json(root, manifest, "SOURCE_RECEIPT.json")
    if (receipt["before"] != receipt["after"] or receipt["source_bytes_unchanged"] is not True
            or receipt["before"]["commit"] != REGISTRATION):
        raise ValueError("Study does not bind the fixed v2 registration")
    files = receipt["before"]["files"]
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    if sha(payload) != receipt["before"]["sha256"]:
        raise ValueError("Source snapshot digest differs")
    for name in (*PLAN_FILES, "research_gate_v2.py", "controller_v2_protocol.json"):
        if files.get(PACKAGE + name) != sha((HERE / name).read_bytes()):
            raise ValueError("Analysis plan/engine differs from the registered source: " + name)
    return receipt


def episode_cost_components(record, tariff):
    """Separate explicitly charged service fees from overlapping time meters.

    Each action has original CPU/wall readings. The terminal delivery event has
    only its charged total in the original file, so its time tariff is recovered
    after subtracting the known delivery fee. No separate CPU/wall split is
    invented for that event.
    """
    actions, events = record["actions"], record["events"]
    if len(events) != len(actions) + 1 or events[-1]["selected_action"] != "delivery":
        raise ValueError("Episode does not expose the registered action/delivery ledger")
    fixed, action_cpu, action_wall, action_time = 0.0, 0.0, 0.0, 0.0
    for index, (action, event) in enumerate(zip(actions, events[:-1], strict=True)):
        name = event["selected_action"]
        if name != action["action"] or name not in tariff:
            raise ValueError("Action trace and charged service identity differ")
        cpu, wall = action["cpu_seconds"], action["wall_seconds"]
        if any(not math.isfinite(value) or value < 0 for value in (cpu, wall)):
            raise ValueError("Invalid recorded action CPU/wall time")
        service = tariff[name] + (tariff["encode"] if index == 0 else 0.0)
        timing = tariff["cpu_second"] * cpu + tariff["wall_second"] * wall
        close(sum(cost["amount"] for cost in event["costs"]), service + timing, "action fee and original CPU/wall")
        fixed += service
        action_cpu += cpu
        action_wall += wall
        action_time += timing
    fixed += tariff["delivery"]
    delivery_time = sum(cost["amount"] for cost in events[-1]["costs"]) - tariff["delivery"]
    if not math.isfinite(delivery_time) or delivery_time < -1e-12:
        raise ValueError("Invalid recovered terminal delivery time fee")
    close(record["actual_cost"], fixed + action_time + delivery_time, "complete episode time/service decomposition")
    return {"fixed_action_and_encode_service_fees": fixed, "logged_action_cpu_seconds": action_cpu,
            "logged_action_wall_seconds": action_wall, "logged_action_time_tariff_cost": action_time,
            "terminal_delivery_time_tariff_cost": delivery_time,
            "episode_time_tariff_cost": action_time + delivery_time,
            "actual_episode_cost": record["actual_cost"]}


def trajectory_rows(root, manifest):
    """Stream original JSON members without extraction or media access."""
    originals = {item["source_path"]: item for item in manifest["preserved_originals"]
                 if item["encoding"] == "tar_member_original_bytes"}
    if not originals:
        raise ValueError("Original controller trajectories are absent")
    seen = set()
    records = {}
    counts, failures, costs = Counter(), Counter(), Counter()
    phase_components = {}
    tariff = registered_tariff()
    with tarfile.open(safe_file(root, "TRAJECTORIES.tar.gz"), "r:gz") as archive:
        for member in archive:
            path = Path(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or member.name in seen or member.name not in originals):
                raise ValueError("Unexpected or unsafe preserved trajectory member")
            item = originals[member.name]
            if item.get("archive_member") != member.name or item["stored_path"] != "TRAJECTORIES.tar.gz":
                raise ValueError("Trajectory member mapping changed")
            payload = archive.extractfile(member).read()
            if len(payload) != item["source_bytes"] or sha(payload) != item["source_sha256"]:
                raise ValueError("Raw trajectory no longer matches original bytes")
            data = json.loads(payload)
            parts = path.parts
            kind = ("distillation_training" if "distillation" in parts else "training") if "training" in parts else (
                "evaluation" if "development" in parts or "evaluation" in parts else
                "distillation_evaluation" if "distillation" in parts and ("teacher" in parts or "student" in parts) else "diagnostic")
            counts[kind] += 1
            failures[kind] += data["failure"] is not None
            costs[kind] += data["actual_cost"]
            measured = episode_cost_components(data, tariff)
            component_totals = phase_components.setdefault(kind, Counter())
            component_totals.update(measured)
            seen.add(member.name)
            if kind in {"evaluation", "distillation_evaluation"}:
                records[member.name] = data
    if seen != set(originals) or len(seen) != manifest["audit"]["trajectory_chains_verified"]:
        raise ValueError("Original preserved trajectory panel is incomplete")
    if dict(counts) != manifest["audit"]["counts_by_phase"]:
        raise ValueError("Recomputed trajectory counts differ from the independent audit")
    if sum(failures.values()) != manifest["audit"]["failures"]:
        raise ValueError("Recomputed failure counts differ from the independent audit")
    return records, {"counts_by_phase": dict(counts), "failures_by_phase": dict(failures),
                     "sum_actual_episode_cost_by_phase": dict(costs),
                     "cost_components_by_phase": {key: dict(value) for key, value in phase_components.items()},
                     "terminal_delivery_cpu_wall_split": "Not recorded separately; only their metered tariff sum is recoverable",
                     "episode_costs_overlap_process_time_cost_and_must_not_be_added_wholesale": True}


def validate_row(row, trajectory, result, arm):
    for key in ("seed", "width"):
        if row[key] != result[key]:
            raise ValueError("Evaluation row configuration differs from the training result")
    if (row["arm"] != arm or row["source_namespace"] != "controller-v2-development"
            or row["profile_sha256"] != result["profile_sha256"]
            or trajectory["profile_sha256"] != row["profile_sha256"]
            or trajectory["source_id"] != "synthetic.controller-v2-development." + str(row["source"])
            or trajectory["seed"] != result["seed"] + 200000 + row["source"] * 7919 + row["draw"] * 997
            or row["failure"] != trajectory["failure"]
            or dict(row["artifacts"]) != dict(trajectory["outcome"]["artifact_sha256"])
            or row["actions"] != [item["action"] for item in trajectory["actions"]]):
        raise ValueError("Evaluation row differs from its actual trajectory")
    close(row["utility"], trajectory["outcome"]["delivered_utility"], "utility")
    close(row["cost"], trajectory["actual_cost"], "actual cost")
    close(row["return"], trajectory["net_return"], "actual return")
    close(row["return"], row["utility"] - row["cost"], "return decomposition")
    if any(not math.isfinite(value) or value < 0 for value in row["cost_by_kind"].values()):
        raise ValueError("Negative or nonfinite service cost component")
    close(row["cost"], sum(row["cost_by_kind"].values()), "cost-kind decomposition")
    if not math.isfinite(row["audit_close_cost"]) or row["audit_close_cost"] < 0:
        raise ValueError("Audit close cost must be measured and nonnegative")
    close(row["net_with_audit_close"], row["return"] - row["audit_close_cost"], "audit-inclusive return")


def phase_cost_report(result, process):
    fields = ("cpu_seconds", "wall_seconds", "physical_cost")
    totals = {key: 0.0 for key in fields}
    for label, values in result["phase_costs"].items():
        if any(not math.isfinite(values[key]) or values[key] < 0 for key in fields):
            raise ValueError("Invalid physical phase measurement: " + label)
        close(values["physical_cost"], 0.02 * values["cpu_seconds"] + 0.001 * values["wall_seconds"], label)
        for key in fields:
            totals[key] += values[key]
    runner = result["measured_runner_total"]
    residual = {key: runner[key] - totals[key] for key in fields}
    if any(value < -1e-8 for value in residual.values()):
        raise ValueError("Named phase totals exceed the original whole runner meter")
    if process["tariff"] != {"cpu_second": 0.02, "wall_second": 0.001}:
        raise ValueError("Original process time tariff differs from registration")
    close(process["measured_process_tariff_cost"],
          (process["child_cpu_seconds"] + process["supervisor_cpu_seconds"]) * 0.02 + process["wall_seconds"] * 0.001,
          "whole-process tariff")
    process_residual = {"cpu_seconds": process["child_cpu_seconds"] + process["supervisor_cpu_seconds"] - runner["cpu_seconds"],
                        "wall_seconds": process["wall_seconds"] - runner["wall_seconds"],
                        "physical_cost": process["measured_process_tariff_cost"] - runner["physical_cost"]}
    if any(value < -1e-6 for value in process_residual.values()):
        raise ValueError("Whole-process measurement is below the contained runner measurement")
    return {"named_phase_time_tariff_totals": totals, "runner_unassigned_residual": residual,
            "outside_runner_including_startup_import_exit_and_supervisor": process_residual,
            "whole_process_measured_time_tariff_cost": process["measured_process_tariff_cost"],
            "distillation_training_time_tariff_cost": result["phase_costs"]["distillation.training"]["physical_cost"],
            "complete_lifecycle_savings_qualified": False,
            "accounting_limit": "Phase and process meters overlap; fixed serving action tariffs are separate. Cold deployment loading, fixed-volume lifecycle allocation and cross-host uncertainty are not inferred."}


def registered_run_costs(root, manifest, result, process, audit):
    """Charge fixed service fees once on top of the encompassing time meter."""
    inside = ("training", "evaluation", "distillation_training", "distillation_evaluation")
    components = audit["cost_components_by_phase"]
    fixed = sum(components[key]["fixed_action_and_encode_service_fees"] for key in inside)
    episode_time = sum(components[key]["episode_time_tariff_cost"] for key in inside)
    process_time = process["measured_process_tariff_cost"]
    if episode_time > process_time + 1e-8:
        raise ValueError("Contained episode time fees exceed the encompassing process meter")
    feedback = original_json(root, manifest, "feedback/RESULTS.json")
    if (feedback["development_results_sha256"] != sha(original_bytes(root, manifest, "run/RESULTS.json"))
            or feedback["diagnostic_source_sha256"] != file_identity(HERE / "diagnostics_v2/controller_feedback.py")["sha256"]
            or feedback["study_seed"] != result["seed"] or feedback["width"] != result["width"]
            or feedback["parameters_updated"] is not False or feedback["used_for_candidate_selection"] is not False
            or feedback["confirmation_sources_consumed"] != 0):
        raise ValueError("Post-run feedback diagnostic is not bound to this development result")
    cpu, wall = feedback["cost"]["cpu_seconds"], feedback["cost"]["wall_seconds"]
    if any(not math.isfinite(value) or value < 0 for value in (cpu, wall)):
        raise ValueError("Feedback diagnostic timing is invalid")
    feedback_time = 0.02 * cpu + 0.001 * wall
    feedback_fixed = components["diagnostic"]["fixed_action_and_encode_service_fees"]
    if components["diagnostic"]["episode_time_tariff_cost"] > feedback_time + 1e-8:
        raise ValueError("Diagnostic episode time exceeds its encompassing diagnostic meter")
    return {"inside_meter_fixed_service_fees": fixed,
            "inside_meter_episode_time_tariff_cost_already_in_process": episode_time,
            "inside_meter_other_time_cost_including_setup_optimization_and_audit": process_time - episode_time,
            "whole_process_time_tariff_cost": process_time,
            "whole_process_plus_fixed_service_fees": process_time + fixed,
            "post_meter_feedback": {"cpu_seconds": cpu, "wall_seconds": wall,
                "time_tariff_cost": feedback_time, "fixed_service_fees": feedback_fixed,
                "time_plus_fixed_service_cost": feedback_time + feedback_fixed,
                "excluded": "Feedback interpreter startup/imports and final summary serialization are outside its run-entry meter"},
            "combined_observed_time_and_fixed_service_cost": process_time + fixed + feedback_time + feedback_fixed,
            "same_cpu_wall_cost_added_twice": False,
            "deployment_lifecycle_savings_established": False,
            "unmeasured_external_scope": ["environment provisioning and package installation", "repository and artifact downloads",
                                          "public source/evidence publication", "standalone archive/analysis and upload processes",
                                          "supervisor startup before its timer and feedback startup/final summary tail"],
            "interpretation": "Complete addition of the recorded registered-scope time and fixed fees; an observed lower bound for wider research infrastructure, not a per-candidate deployment allocation"}


def certainty_equivalent(values):
    transformed = [-2.0 * value for value in values]
    maximum = max(transformed)
    return -(maximum + math.log(sum(math.exp(value - maximum) for value in transformed) / len(transformed))) / 2


def describe(rows):
    return {"episodes": len(rows), "failures": sum(row["failure"] is not None for row in rows),
            "utility_ce": certainty_equivalent([row["utility"] for row in rows]),
            "serving_net_ce": certainty_equivalent([row["return"] for row in rows]),
            "audit_inclusive_net_ce": certainty_equivalent([row["net_with_audit_close"] for row in rows]),
            "mean_utility": sum(row["utility"] for row in rows) / len(rows),
            "mean_serving_cost": sum(row["cost"] for row in rows) / len(rows),
            "mean_audit_close_cost": sum(row["audit_close_cost"] for row in rows) / len(rows),
            "mean_audit_inclusive_cost": sum(row["cost"] + row["audit_close_cost"] for row in rows) / len(rows)}


def load_configuration(root, manifest, protocol):
    source = source_binding(root, manifest)
    result = original_json(root, manifest, "run/RESULTS.json")
    executed = original_json(root, manifest, "run/EXECUTED_PROTOCOL.json")
    process = original_json(root, manifest, "PROCESS_RECEIPT.json")
    if (result.get("schema") != "hepta.joint-generation.controller-v2.development.v1"
            or result.get("stage") != "development" or result.get("smoke") is not False
            or result.get("confirmation_sources_consumed") != 0 or result.get("old_test_sources_used") is not False
            or result["protocol_sha256"] != sha((HERE / "controller_v2_protocol.json").read_bytes())
            or executed != protocol or set(result["arms"]) != set(protocol["arms"])):
        raise ValueError("Configuration is not a complete registered v2 development run")
    if process["exit_code"] != 0 or process["timed_out"] or not process["child_reaped"]:
        raise ValueError("Original process did not complete normally")
    profile = JointGenerationProfile.from_dict(original_json(root, manifest, "run/PROFILE.json"))
    if profile.digest != result["profile_sha256"]:
        raise ValueError("Frozen profile identity differs")
    for name, expected in result["source_sha256"].items():
        if (Path(name).name != name or sha((HERE / name).read_bytes()) != expected
                or source["before"]["files"].get(PACKAGE + name) != expected):
            raise ValueError("Original training source identity differs")
    for mode in ("dual", "ordinary"):
        training = result["pretraining"][mode]
        if training["updates"] != protocol["pretraining_updates"] or len(training["loss_history"]) != training["updates"]:
            raise ValueError("Incomplete registered pretraining")
    records, audit = trajectory_rows(root, manifest)
    mechanisms, students, descriptions = [], [], {}
    for arm, values in result["arms"].items():
        training, evaluation = values["training"], values["evaluation"]
        if (training["actual_episodes"] != protocol["joint_updates"] * protocol["joint_batch"]
                or len(training["updates"]) != protocol["joint_updates"]
                or training["final_parameters_sha256"] != values["checkpoint"]["model_sha256"]):
            raise ValueError("Incomplete registered joint training")
        for row in evaluation["rows"]:
            path = f"run/{arm}/development/source-{row['source']:03d}-draw-{row['draw']}/TRAJECTORY.json"
            validate_row(row, records[path], result, arm)
            if records[path]["parameter_snapshot_sha256"] != values["checkpoint"]["model_sha256"]:
                raise ValueError("Evaluated model differs from its selected checkpoint")
        mechanisms.extend(evaluation["rows"])
        descriptions[arm] = describe(evaluation["rows"])
    distilled = result["distillation"]
    if (distilled["actual_training_episodes"] != protocol["distillation_rounds"] * protocol["distillation_sources_per_round"]
            or len(distilled["rounds"]) != protocol["distillation_rounds"]
            or distilled["generator_and_critics_unchanged"] is not True):
        raise ValueError("Incomplete registered distillation")
    for name in ("teacher", "student"):
        model_sha = (result["arms"]["hepta_dynamic_risk"]["checkpoint"] if name == "teacher"
                     else distilled["checkpoint"])["model_sha256"]
        for row in distilled[name]["rows"]:
            path = f"run/distillation/{name}/source-{row['source']:03d}-draw-{row['draw']}/TRAJECTORY.json"
            validate_row(row, records[path], result, "hepta_" + name)
            if records[path]["parameter_snapshot_sha256"] != model_sha:
                raise ValueError("Teacher/student evaluation differs from its selected checkpoint")
        students.extend(distilled[name]["rows"])
        descriptions["hepta_" + name] = describe(distilled[name]["rows"])
    return mechanisms, students, {"seed": result["seed"], "width": result["width"],
        "compact_manifest_sha256": file_identity(root / "MANIFEST.json")["sha256"],
        "result_original_sha256": sha(original_bytes(root, manifest, "run/RESULTS.json")),
        "profile_sha256": profile.digest, "descriptive_arms": descriptions, "trajectory_audit": audit,
        "physical_cost_reconciliation": phase_cost_report(result, process),
        "registered_run_cost_accounting": registered_run_costs(root, manifest, result, process, audit)}


def run(inputs, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("A new analysis directory is required")
    seals = [read_seal(HERE / name) for name in PLAN_FILES]
    if tuple(seal["plan_sha256"] for seal in seals) != PLAN_HASHES:
        raise ValueError("Frozen v2 development acceptance plan changed")
    protocol = read_json(HERE / "controller_v2_protocol.json")
    expected = {(seed, width) for seed in seals[0]["plan"]["seeds"] for width in seals[0]["plan"]["widths"]}
    mechanisms, students, configurations, errors = [], [], {}, []
    for path in sorted(Path(inputs).rglob("MANIFEST.json")):
        try:
            value = read_json(path)
            if value.get("schema") != ARCHIVE_SCHEMA:
                continue
            names = {item["source_path"] for item in value["preserved_originals"]}
            if "run/RESULTS.json" not in names or "run/EXECUTED_PROTOCOL.json" not in names:
                continue  # Observer and engineering probes are separate evidence.
            root, manifest = validate_compact(path.parent)
            left, right, report = load_configuration(root, manifest, protocol)
            key = (report["seed"], report["width"])
            if key not in expected or key in configurations:
                raise ValueError("Unexpected or duplicate training configuration")
            configurations[key] = report
            mechanisms.extend(left)
            students.extend(right)
        except (ValueError, KeyError, TypeError, OSError, OverflowError, tarfile.TarError) as exc:
            errors.append({"compact_manifest": str(path), "error": type(exc).__name__ + ": " + str(exc)})
    missing = sorted(expected - set(configurations))
    complete = not missing and not errors
    result = {"schema": SCHEMA, "registration_sha": REGISTRATION,
              "analysis_source_sha256": file_identity(Path(__file__))["sha256"],
              "statistical_engine_sha256": file_identity(HERE / "research_gate_v2.py")["sha256"],
              "plan_sha256": dict(zip(PLAN_FILES, PLAN_HASHES, strict=True)),
              "configurations": [configurations[key] for key in sorted(configurations)],
              "missing_configurations": missing, "errors": errors, "complete_validated_panel": complete,
              "mechanism_gate": None, "distillation_gate": None,
              "fresh_confirmation_consumed_by_analysis": False,
              "original_media_reopened": False, "independent_original_file_audit_receipts_verified": complete,
              "research_qualified": False, "natural_semantic_qualified": False,
              "lifecycle_savings_qualified": False}
    if complete:
        result["mechanism_gate"] = analyse_panel(seals[0]["plan"], mechanisms)
        result["distillation_gate"] = analyse_panel(seals[1]["plan"], students)
        accounting = [entry["registered_run_cost_accounting"] for entry in configurations.values()]
        result["all_configurations_observed_cost"] = {
            key: sum(entry[key] for entry in accounting)
            for key in ("inside_meter_fixed_service_fees", "whole_process_time_tariff_cost",
                        "whole_process_plus_fixed_service_fees", "combined_observed_time_and_fixed_service_cost")}
        result["all_configurations_observed_cost"]["post_meter_feedback_cost"] = sum(
            entry["post_meter_feedback"]["time_plus_fixed_service_cost"] for entry in accounting)
        result["all_configurations_observed_cost"]["external_scope_unmeasured_not_zero"] = True
    output.mkdir(parents=True, exist_ok=False)
    (output / "SUMMARY.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    for name, rows in (("MECHANISM_ROWS.json.gz", mechanisms), ("DISTILLATION_ROWS.json.gz", students)):
        payload = (json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        (output / name).write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.inputs, args.output)
    print(json.dumps({"complete_validated_panel": result["complete_validated_panel"],
                      "configurations": len(result["configurations"]),
                      "errors": result["errors"], "missing_configurations": result["missing_configurations"],
                      "mechanism_admission": (result["mechanism_gate"] or {}).get("development_admission_pass"),
                      "distillation_admission": (result["distillation_gate"] or {}).get("development_admission_pass")}, sort_keys=True))
    return int(not result["complete_validated_panel"])


if __name__ == "__main__":
    raise SystemExit(main())
