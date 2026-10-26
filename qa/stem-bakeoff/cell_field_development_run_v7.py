"""Run the frozen twelve-configuration grid on disclosed historical sources only."""

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path
import time

import numpy as np

from cell_field_action_io import environment, source_hashes, write_json
from cell_field_development_artifacts_v7 import materialize_checkpoints, save_failure, save_result
from cell_field_development_audit_v7 import full_field_parity, per_source_nll
from cell_field_development_data_v7 import PINS, load_development
from cell_field_development_selection_v7 import (HEADS, POLICIES, SEEDS, SELECTION_RULE, TASKS,
    VERSIONS, configurations, select_configuration, summarize_configuration)
from cell_field_features import file_hash
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import canonical, normalize_features


HISTORICAL_SEALS = {"v5": "6232c84ff700bd914bec340f645454b8f9a6c40daa984aeb220261bbdb010ff9",
    "v6": "437b68f35b7cb6721ec6beda29e87dbaaf26cf70387e0bc98f8b7e7feecc27bc"}


def policy_order(index, fit_ordinal):
    shift = (index+fit_ordinal) % len(POLICIES)
    return POLICIES[shift:]+POLICIES[:shift]


def validate_plan(plan, workspace):
    if (plan["schema"] != "hepta.cell-field-development-protocol.v7"
            or plan["configurations"] != configurations() or plan["selection_rule"] != SELECTION_RULE
            or plan["versions"] != list(VERSIONS) or plan["tasks"] != list(TASKS)
            or plan["head_modes"] != list(HEADS) or plan["seeds"] != list(SEEDS)
            or plan["primary_policies"] != list(POLICIES) or plan["reference_policy"] != "full_h8"
            or plan["data_plan"]["historical_pins"] != json.loads(json.dumps(PINS))
            or plan["historical_run_seal_sha256"] != HISTORICAL_SEALS
            or plan["execution_order"]["policy_rotation"] != "rotate primary_policies left by (configuration_index+fit_ordinal)%3"
            or plan["execution_order"]["repeat_cost_measurements"] is not False
            or plan["audit"]["full_field_parity_absolute_tolerance"] != 1e-9):
        raise ValueError("exact frozen development source, grid, selection and cost-order plan required")
    for version, digest in HISTORICAL_SEALS.items():
        if file_hash(workspace/f"pft-run-{version}/pre_evaluation_seal.json") != digest:
            raise ValueError("historical run seal differs")
    if file_hash(workspace/"pft-development-v7/source-power-design.json") != plan["data_plan"]["source_power_design_sha256"]:
        raise ValueError("pre-grid source and power planning receipt differs")


def load_warmup(workspace, plan, version, task, head, seed, inputs):
    fit = f"{version}-{task}-seed{seed}-{head}"
    entry = plan["historical_warmups"][fit]
    expected_path = f"{task}/seed{seed}-{head}/warmup/checkpoint"
    if entry["relative_directory"] != expected_path or set(entry["files"]) != {"manifest.json", "state.npz"}:
        raise ValueError("historical warmup path differs from registered fit")
    directory = workspace/f"pft-run-{version}"/expected_path
    for name, pin in entry["files"].items():
        path = directory/name
        if path.is_symlink() or path.stat().st_size != pin["bytes"] or file_hash(path) != pin["sha256"]:
            raise ValueError("original full warmup checkpoint differs")
    metadata = json.loads((directory/"manifest.json").read_bytes())
    contexts = {name: dataset_digest(*inputs["split"][name]) for name in ("old_train", "current_train")}
    state = CellTrainingState.load(directory, metadata["bindings"], inputs["plan"]["optimizer"],
        contexts, entry["state_sha256"])
    if (state.bindings["protocol_sha256"] != PINS[version]["protocol"]
            or state.step_count != inputs["plan"]["warmup_steps"] or state.active_context != "current_train"):
        raise ValueError("original optimizer/protocol clock or selected context differs")
    return state


def execute(workspace, protocol, output):
    from cell_field_policy_v7 import execute_policy
    workspace, protocol, output = map(Path, (workspace, protocol, output))
    plan = json.loads(protocol.read_bytes())
    validate_plan(plan, workspace)
    output.mkdir(parents=True, exist_ok=False)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    hashes, protocol_sha = source_hashes(), file_hash(protocol)
    source_sha = hashlib.sha256(canonical(hashes)).hexdigest()
    identity = {"controller_protocol_sha256": protocol_sha, "controller_source_sha256": source_sha}
    write_json(output/"executed_source.json", hashes)
    (output/"protocol.json").write_bytes(protocol.read_bytes())
    inputs_by_task, preparation_errors, fits = {}, {}, []
    for version, task in product(VERSIONS, TASKS):
        try:
            inputs = load_development(version, task, workspace/f"pft-data-{version}/cohorts",
                workspace/f"pft-features-{version}", workspace/"pft-data-v5/inputs")
            inputs_by_task[version, task] = inputs
            write_json(output/"inputs"/f"{version}-{task}.json", json.loads(json.dumps(inputs["provenance"])))
        except Exception as error:
            preparation_errors[version, task] = error
    for ordinal, (version, task, head, seed) in enumerate(product(VERSIONS, TASKS, HEADS, SEEDS)):
        fit = {"version": version, "task": task, "head": head, "seed": seed,
            "fit_id": f"{version}-{task}-seed{seed}-{head}", "ordinal": ordinal}
        try:
            if (version, task) in preparation_errors:
                raise preparation_errors[version, task]
            inputs = inputs_by_task[version, task]
            warmup = load_warmup(workspace, plan, version, task, head, seed, inputs)
            anchors = np.asarray([warmup.head.loss_gradients(normalize_features(x), y, 0.)[0]
                for x, y in inputs["old_panels"]])
            selection_sources = {name: inputs["role_metadata"][role] for name, role in
                (("old", "old_test"), ("future", "future_test"))}
            fit.update(inputs=inputs, warmup=warmup, anchors=anchors,
                selection_sources_sha256=hashlib.sha256(canonical(selection_sources)).hexdigest(),
                warm_old_losses=per_source_nll(warmup, inputs["selection"]["old"]))
        except Exception as error:
            fit["preparation_error"] = error
        fits.append(fit)
    preparation_cost = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began}
    summaries, orders, call_cpu, output_count = [], [], 0, 0

    def run_case(fit, configuration, policy, directory):
        descriptor = {key: fit[key] for key in ("version", "task", "head", "seed", "fit_id")}
        descriptor["selection_sources_sha256"] = fit.get("selection_sources_sha256")
        start, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            if "preparation_error" in fit:
                raise fit["preparation_error"]
            values = fit["inputs"]
            result = execute_policy(fit["warmup"], values["split"]["current_train"], values["current_panels"],
                values["old_panels"], fit["anchors"], policy, configuration, **identity)
            elapsed = {"cpu_ns": time.process_time_ns()-start_cpu, "wall_ns": time.perf_counter_ns()-start}
            row = save_result(directory, descriptor, fit["warmup"], values, fit["anchors"], policy,
                configuration, result, elapsed, fit["warm_old_losses"], controller_identity=identity)
            return row, result
        except Exception as error:
            elapsed = {"cpu_ns": time.process_time_ns()-start_cpu, "wall_ns": time.perf_counter_ns()-start}
            return save_failure(directory, descriptor, policy, error, elapsed), None

    for item in plan["configurations"]:
        index, configuration, rows = item["index"], item["configuration"], []
        for fit in fits:
            order = policy_order(index, fit["ordinal"])
            orders.append({"index": index, "fit_id": fit["fit_id"], "policies": list(order)})
            for policy in order:
                directory = output/f"config{index:02d}"/fit["fit_id"]/policy
                row, _ = run_case(fit, configuration, policy, directory)
                rows.append(row)
                call_cpu += row["cpu_ns"]
                output_count += 1
            print(json.dumps({"configuration": index, "fit": fit["fit_id"], "completed_primary_slots": output_count,
                "policy_statuses": [{k: row[k] for k in ("policy", "status", "completed_steps")} for row in rows[-3:]]}), flush=True)
        summary = summarize_configuration(index, rows)
        summaries.append(summary)
        write_json(output/f"config{index:02d}"/"summary.json", summary)
        write_json(output/"configuration-summaries.json", summaries)
        if source_hashes() != hashes or file_hash(protocol) != protocol_sha:
            raise RuntimeError("development source/protocol changed during the registered grid")
    selection = select_configuration(summaries)
    write_json(output/"selection.json", selection)
    parity, selected = [], selection["selected_index"]
    if selected is not None:
        configuration = plan["configurations"][selected]["configuration"]
        for fit in fits:
            try:
                references = {}
                for policy in POLICIES:
                    directory = output/f"config{selected:02d}"/fit["fit_id"]/policy
                    references[policy] = materialize_checkpoints(directory, fit["warmup"], fit["inputs"],
                        fit["anchors"], policy, configuration, controller_identity=identity)
                directory = output/f"config{selected:02d}"/fit["fit_id"] / "full_h8"
                row, result = run_case(fit, configuration, "full_h8", directory)
                call_cpu += row["cpu_ns"]
                if result is None:
                    raise RuntimeError("selected Full reference did not produce a trace: "+str(row["error"]))
                materialize_checkpoints(directory, fit["warmup"], fit["inputs"], fit["anchors"],
                    "full_h8", configuration, controller_identity=identity)
                check = full_field_parity(*references["future_field_h8"], result)
                check["passed"] = check["passed"] and row["audit_passed"]
                parity.append({"fit_id": fit["fit_id"], **check, "full_policy_cpu_ns": row["cpu_ns"],
                    "full_policy_status": row["status"], "full_policy_error": row["error"]})
            except Exception as error:
                parity.append({"fit_id": fit["fit_id"], "passed": False,
                    "error": {"type": type(error).__name__, "message": str(error)}})
    if source_hashes() != hashes or file_hash(protocol) != protocol_sha:
        raise RuntimeError("source/protocol changed before the development seal")
    parity_passed = len(parity) == 24 and all(row["passed"] for row in parity)
    result = {"schema": "hepta.cell-field-development-run.v7", "protocol_sha256": protocol_sha,
        "executed_source_sha256": source_sha, "primary_outputs": output_count, "registered_primary_outputs": 864,
        "selection": selection, "full_reference_parity": parity, "full_reference_parity_passed": parity_passed,
        "development_conditions_met": selection["confirmation_plausibility_passed"] and parity_passed,
        "new_confirmation_selected": False, "scientific_acceptance": False,
        "shared_preparation": preparation_cost, "all_policy_call_cpu_ns": call_cpu,
        "cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-began,
        "completed_at": datetime.now(timezone.utc).isoformat(), "environment": environment()}
    write_json(output/"execution-order.json", orders)
    write_json(output/"run.json", result)
    files = {p.relative_to(output).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
        for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output/"development_seal.json", {"schema": "hepta.cell-field-development-seal.v7",
        "files": files, "protocol_sha256": protocol_sha, "executed_source_sha256": source_sha,
        "historical_development_labels_used": True, "new_confirmation_labels_accessed": False,
        "scientific_acceptance": False})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "protocol", "output"):
        parser.add_argument("--"+name, required=True)
    execute(**vars(parser.parse_args()))
