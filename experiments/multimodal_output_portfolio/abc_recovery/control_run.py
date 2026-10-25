"""Freeze all policies before opening the complete new task evaluation census."""

import argparse
import gzip
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

from .training_run import AREA, ROOT, file_sha, write_json


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.control_run"


def pins():
    dependencies = {
        "abc_recovery": ("control_run", "training_run", "base_recovery", "control", "critic", "risk", "route",
                         "planning", "runtime", "emission", "media", "episodes", "interventions", "evaluation", "trees", "trees_tests"),
        "v7": ("sources", "data", "model", "snapshot", "evaluation"),
        "v6": ("data", "neural", "observer"),
    }
    return {f"{folder}/{name}.py": file_sha(AREA / folder / f"{name}.py")
            for folder, names in dependencies.items() for name in names}


def freeze(args):
    protocol = json.loads(args.protocol.read_text())
    training = json.loads((args.training / "result.json").read_text())
    qualification = json.loads((args.qualification / "result.json").read_text())
    expected = {(seed, arm) for seed in protocol["training_seeds"] for arm in protocol["training"]["arms"]}
    models = {(row["seed"], row["arm"]): row for row in training["models"]}
    if training["status"] != "completed" or len(training["models"]) != 15 or set(models) != expected:
        raise ValueError("The entire registered training census must finish before control evaluation")
    if (not qualification["both_qualified"] or qualification["protocol_sha256"] != file_sha(args.protocol)
            or file_sha(args.manifest) != protocol["source_manifest_file_sha256"]):
        raise ValueError("Source or observer qualification differs from the frozen study")
    primary = args.primary
    secondary = args.qualification / "secondary-observer.pt"
    if (file_sha(primary) != qualification["primary_file_sha256"]
            or file_sha(secondary) != qualification["secondary_file_sha256"]):
        raise ValueError("Qualified observer files changed")
    for row in models.values():
        if file_sha(row["model_path"]) != row["model_file_sha256"]:
            raise ValueError("Trained generator file changed")
    args.output.mkdir(parents=True, exist_ok=False)
    registration = {"schema": "hepta.abc.control-census-registration.v1", "registered_unix_ns": time.time_ns(),
        "source_sha256": pins(), "protocol_sha256": file_sha(args.protocol),
        "amendment_sha256": file_sha(args.protocol.with_name("protocol-amendment-001.json")),
        "manifest_sha256": file_sha(args.manifest), "training_result_sha256": file_sha(args.training / "result.json"),
        "qualification_result_sha256": file_sha(args.qualification / "result.json"),
        "paths": {name: str(getattr(args, name).resolve()) for name in
                  ("cache", "manifest", "protocol", "training", "qualification", "primary", "output")},
        "secondary": str(secondary.resolve()), "observer_file_sha256": {
            "primary": qualification["primary_file_sha256"], "secondary": qualification["secondary_file_sha256"]},
        "generators": list(models.values()), "source_roles_read": ["development", "forecast_fit", "forecast_calibration"],
        "fit_before_evaluate_barrier": True, "formal_audit_retention_test_outcomes_opened": False,
        "dynamic_risk_global_optimality_claim": False}
    write_json(args.output / "registration.json", registration)
    return args.output / "registration.json"


def load_bundle(directory):
    from .control import load_feedback
    from .route import load_route
    directory = Path(directory)
    frozen = json.loads((directory / "policy-freeze.json").read_text())
    for name, sha in frozen["files_sha256"].items():
        if file_sha(directory / name) != sha:
            raise ValueError("Frozen policy artifact changed: " + name)
    policies = {name: load_feedback(directory / f"{name}.pt") for name in frozen["feedback_names"]}
    return {"feedback": policies.pop("feedback"), "profiles": policies,
            "static": json.loads((directory / "static.json").read_text()),
            "route": load_route(directory / "route.pt") if frozen["route"] else None}


def fit_model(snapshot, corpus, primary, directory, protocol, seed, arm):
    from .control import PROFILES, calibration_report, fit_feedback, save_feedback, select_static
    from .route import fit_route, save_route
    from .trees import collect_tree, stable_seed
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    directory.mkdir(parents=True, exist_ok=False)
    def collect(name, scenarios):
        role = protocol["roles"][name]
        return collect_tree(snapshot, corpus, {"primary": primary}, directory / name,
            role=role["role"], pair_start=role["pair_start"], pair_count=role["pair_count"],
            scenarios=scenarios, training_seed=seed)
    fit = collect("critic_fit", protocol["fit_generation_scenarios"])
    policy_dir = directory / "policies"
    policy_dir.mkdir()
    names = list(PROFILES) if arm == "output_ndu" else ["feedback"]
    policies, reports = {}, {}
    for name in names:
        initialization = stable_seed("critic", seed, name) % (2**63 - 2000)
        policy = fit_feedback(fit, name, initialization, protocol["critic"])
        save_feedback(policy, policy_dir / f"{name}.pt")
        policies[name] = policy
        reports[name] = {"Q1": policy.critic.one_step_model.fit_report, "Q2": policy.critic.two_step_model.fit_report}
    if arm == "output_ndu":
        route = fit_route(fit, stable_seed("route", seed) % (2**63 - 2), protocol["critic"])
        save_route(route, policy_dir / "route.pt")
        reports["one_shot_route"] = route.fit_report
    del fit
    tuning = collect("static_tuning", protocol["tuning_generation_scenarios"])
    write_json(policy_dir / "static.json", select_static(tuning))
    del tuning
    calibration = collect("critic_calibration", protocol["fit_generation_scenarios"])
    write_json(policy_dir / "calibration.json", {name: calibration_report(policy, calibration) for name, policy in policies.items()})
    write_json(policy_dir / "fits.json", reports)
    files = [f"{name}.pt" for name in names] + ["static.json", "calibration.json", "fits.json"]
    if arm == "output_ndu":
        files.append("route.pt")
    freeze_record = {"schema": "hepta.abc.policy-freeze.v1", "frozen_unix_ns": time.time_ns(),
        "seed": seed, "arm": arm, "feedback_names": names, "route": arm == "output_ndu",
        "files_sha256": {name: file_sha(policy_dir / name) for name in files},
        "task_evaluation_opened": False, "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu, "calibration_used_to_select_or_refit": False}
    write_json(policy_dir / "policy-freeze.json", freeze_record)
    return {"seed": seed, "arm": arm, "directory": str(directory),
            "policy_freeze_sha256": file_sha(policy_dir / "policy-freeze.json")}


def evaluate_model(snapshot, corpus, observers, directory, bundle, protocol, seed, arm, rows):
    from .evaluation import (intervention_rows, offline_primary_oracles, projected_rows,
                             save_selection, select_public_paths)
    from .interventions import evaluate_intervention
    from .trees import collect_tree
    role = protocol["roles"]["evaluation"]
    tree_dir = directory / "evaluation"
    data = collect_tree(snapshot, corpus, observers, tree_dir, role=role["role"],
        pair_start=role["pair_start"], pair_count=role["pair_count"],
        scenarios=protocol["evaluation_generation_scenarios"], training_seed=seed)
    selected, work = select_public_paths(snapshot._model, data, bundle,
                                         extended=arm == "output_ndu", training_seed=seed)
    save_selection(directory / "public-selections.json", selected, work)
    # Freeze all online choices before allowing privileged evaluation outcomes.
    oracles = offline_primary_oracles(data)
    write_json(directory / "offline-oracle-selections.json", {name: value.tolist() for name, value in oracles.items()})
    count = 0
    for row in projected_rows(data, {**selected, **oracles}, seed=seed, arm=arm, tree_directory=tree_dir):
        rows.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        count += 1
    if arm == "output_ndu":
        for profile in ("shared_state_clamp_semantic_couple", "encoder_initial_only_fixed"):
            destination = directory / profile
            result = evaluate_intervention(snapshot, corpus, observers, destination, data, profile)
            for row in intervention_rows(result, seed=seed, arm=arm, directory=destination):
                rows.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                count += 1
    rows.flush()
    return {"seed": seed, "arm": arm, "policy_replay_rows": count,
            "source_pairs": role["pair_count"], "public_selection_sha256": file_sha(directory / "public-selections.json"),
            "data_file_sha256": file_sha(tree_dir / "data.pt"), "MPC_planning_work": work}


def execute(registration_path):
    registration = json.loads(Path(registration_path).read_text())
    paths = {key: Path(value) for key, value in registration["paths"].items()}
    output = paths["output"]
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    fitted, evaluated = [], []
    try:
        if (pins() != registration["source_sha256"] or file_sha(paths["protocol"]) != registration["protocol_sha256"]
                or file_sha(paths["manifest"]) != registration["manifest_sha256"]):
            raise ValueError("Frozen control execution inputs changed")
        import torch
        from ..v7.evaluation import load_reward
        from ..v7.snapshot import Snapshot
        from ..v7.sources import load_roles
        protocol = json.loads(paths["protocol"].read_text())
        torch.set_num_threads(protocol["threads"])
        corpus = load_roles(paths["cache"], paths["manifest"], roles=tuple(registration["source_roles_read"]))
        observers = {name: load_reward(path, registration["observer_file_sha256"][name])[0]
                     for name, path in (("primary", paths["primary"]), ("secondary", registration["secondary"]))}
        for model in registration["generators"]:
            seed, arm = model["seed"], model["arm"]
            print(json.dumps({"phase": "fit_start", "seed": seed, "arm": arm}), flush=True)
            snapshot = Snapshot.load(model["model_path"], expected_file_sha256=model["model_file_sha256"])
            destination = output / f"seed-{seed}" / arm
            fitted.append(fit_model(snapshot, corpus, observers["primary"], destination, protocol, seed, arm))
            print(json.dumps({"phase": "fit_complete", "seed": seed, "arm": arm}), flush=True)
        write_json(output / "all-policies-frozen.json", {"frozen_unix_ns": time.time_ns(), "policies": fitted,
                   "evaluation_sources_not_yet_scored": True, "source_sha256": pins()})
        with gzip.open(output / "evaluation-rows.jsonl.gz", "xt", encoding="utf-8") as rows:
            for model, fitted_row in zip(registration["generators"], fitted):
                seed, arm = model["seed"], model["arm"]
                print(json.dumps({"phase": "evaluation_start", "seed": seed, "arm": arm}), flush=True)
                snapshot = Snapshot.load(model["model_path"], expected_file_sha256=model["model_file_sha256"])
                destination = Path(fitted_row["directory"])
                bundle = load_bundle(destination / "policies")
                evaluated.append(evaluate_model(snapshot, corpus, observers, destination, bundle, protocol, seed, arm, rows))
                print(json.dumps({"phase": "evaluation_complete", "seed": seed, "arm": arm}), flush=True)
        if pins() != registration["source_sha256"]:
            raise RuntimeError("Source code changed during prospective control execution")
        write_json(output / "result.json", {"status": "completed", "fitted": fitted, "evaluated": evaluated,
                   "evaluation_rows_file_sha256": file_sha(output / "evaluation-rows.jsonl.gz"),
                   "all_policies_frozen_sha256": file_sha(output / "all-policies-frozen.json"),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                   "scientific_benefit_gates_evaluated": False, "all_blockers_closed": False})
    except BaseException as error:
        write_json(output / "failure.json", {"status": "failed", "error": repr(error), "traceback": traceback.format_exc(),
                   "fitted_models": len(fitted), "evaluated_models": len(evaluated),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    for name in ("cache", "manifest", "protocol", "training", "qualification", "primary", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.child)
        return
    if any(getattr(args, key) is None for key in ("cache", "manifest", "protocol", "training", "qualification", "primary", "output")):
        parser.error("All frozen execution inputs and a new output directory are required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    registration = freeze(args)
    with (args.output / "process.log").open("x") as stream:
        child = subprocess.Popen([sys.executable, "-B", "-m", MODULE, "--child", str(registration)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in child.stdout:
            stream.write(line)
            stream.flush()
            print(line, end="", flush=True)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(args.output / "whole-process-cost.json", {"exit_code": code,
               "wall_ns": time.perf_counter_ns() - wall, "parent_cpu_ns": time.process_time_ns() - cpu,
               "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "child_peak_rss_bytes": after.ru_maxrss * 1024,
               "includes": "all tree materialization, physical media, critic and static training, calibration, independent MPC simulations, full evaluation, scoring, metadata and child exit",
               "cost_is_deployed_online_latency": False})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
