"""Render completed frozen results; this module does not fit or evaluate models."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main_costs(root):
    index = read(root / "main/RUN_INDEX.json")
    if not index["complete"] or len(index["scopes"]) != 15:
        raise ValueError("All registered scopes are required")
    rows = []
    for item in index["scopes"]:
        if sha(root / item["archive"]) != item["archive_receipt"]["sha256"]:
            raise ValueError("Completed main archive changed")
        if sha(root / item["analysis"]) != item["analysis_sha256"]:
            raise ValueError("Completed main analysis changed")
        values = {}
        with tarfile.open(root / item["archive"], "r|gz") as archive:
            for member in archive:
                if member.name in ("EXECUTION.json", "AUDIT.json"):
                    values[member.name] = json.load(archive.extractfile(member))
                if len(values) == 2:
                    break
        execution, audit = values["EXECUTION.json"], values["AUDIT.json"]
        if not item["audit_passed"] or not audit["passed"]:
            raise ValueError("An unaudited scope cannot enter the report")
        rows.append({"scope": item["scope"], "seed": item["seed"], "law": item["law"],
            "execution": execution, "audit": audit,
            "scope_wall_ns_including_replay_and_archive": item["scope_wall_ns_including_replay_and_archive"],
            "archive_bytes": item["archive_receipt"]["compressed_bytes"],
            "archived_members": item["archive_receipt"]["file_count"]})
    sums = {
        "scope_wall_ns_including_replay_and_archive": sum(r["scope_wall_ns_including_replay_and_archive"] for r in rows),
        "evaluation_wall_ns": sum(r["execution"]["wall_ns"] for r in rows),
        "evaluation_parent_cpu_ns": sum(r["execution"]["parent_cpu_ns"] for r in rows),
        "evaluation_native_requests": sum(r["execution"]["native_requests"] for r in rows),
        "evaluation_native_ticks": sum(r["execution"]["original_sparse_ticks"] for r in rows),
        "evaluation_native_ipc_wall_ns": sum(r["execution"]["native_ipc_wall_ns"] for r in rows),
        "audit_wall_ns": sum(r["audit"]["wall_ns"] for r in rows),
        "audit_native_requests": sum(r["audit"]["native_replay_accounting"]["requests"] for r in rows),
        "audit_native_ticks": sum(r["audit"]["native_replay_accounting"]["ticks"] for r in rows),
        "audit_native_ipc_wall_ns": sum(r["audit"]["native_replay_accounting"]["ipc_wall_ns"] for r in rows),
        "delivered_numeric_pngs": sum(r["execution"]["transport"]["deliveries"] for r in rows),
        "transport_files": sum(r["execution"]["transport"]["files"] for r in rows),
        "reopened_observations": sum(r["execution"]["transport"]["observations"] for r in rows),
        "archive_bytes": sum(r["archive_bytes"] for r in rows),
        "archived_members": sum(r["archived_members"] for r in rows),
    }
    recovery = read(root / "MAIN_OPERATIONAL_RECOVERY.json")
    identity = read(root / "MAIN_RESUME1_IDENTITY.json")
    resume = read(root / "MAIN_RESUME1_EXECUTION.json")
    if (not identity["all_original_data_and_model_identities_exact"]
            or identity["operational_recovery_sha256"] != sha(root / "MAIN_OPERATIONAL_RECOVERY.json")
            or resume["returncode"] != 0
            or resume["source_commit"] != index["source_commit"]):
        raise ValueError("Operational recovery or completed retry identity is invalid")
    operational = {
        "failed_attempt_scope": recovery["scope"],
        "failed_attempts": 1,
        "failed_original_files_retained": recovery["original_file_count"],
        "failed_attempt_archive_sha256": recovery["archive"]["sha256"],
        "failure_interpretation": recovery["failure_interpretation"],
        "exception_class": recovery["exception_class"],
        "exception_errno": recovery["exception_errno"],
        "failed_attempt_costs": recovery["failed_attempt_costs"],
        "failed_attempt_completed_control_count": None,
        "failed_attempt_included_in_utility_estimation": False,
        "retry_created_new_independent_sample": False,
        "retry_data_and_model_bytes_identical": True,
        "retry_deterministically_regenerated_original_data": True,
        "recorded_resume": resume,
        "resume_overlaps_successful_scope_timings_and_must_not_be_added": True,
        "completed_registered_control_executions": 86400,
        "all_attempt_control_executions": None,
        "receipt_sha256": {name: sha(root / name) for name in (
            "MAIN_OPERATIONAL_RECOVERY.json", "MAIN_RESUME1_IDENTITY.json", "MAIN_RESUME1_EXECUTION.json")},
    }
    return {"schema": "hepta.analytic-event.round3.main-costs.v1", "sums": sums, "scopes": rows,
        "sums_cover_completed_registered_scopes_only": True,
        "operational_attempts": operational,
        "failed_attempt_costs_unknown_not_zero": True,
        "scope_wall_excludes_dataset_and_model_prewrites": True,
        "wall_metrics_are_nested_and_must_not_be_added": True,
        "parent_cpu_excludes_native_child_cpu": True,
        "native_child_cpu_ns": None, "energy_joules": None, "money": None,
        "shared_host_timings_are_not_isolated_hardware_benchmarks": True}


def figures(main, feedback, calibration, destination):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/aen-r3-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    destination.mkdir(parents=True, exist_ok=True)
    blocks = [
        ("Main diffusion task", main["primary_contrasts"],
         ["analytic_vs_history", "analytic_vs_native", "event_vs_continuous"]),
        ("Paid-feedback task", feedback["contrasts"],
         ["event_vs_gaussian", "analytic_vs_numeric", "analytic_vs_gaussian"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.1), layout="constrained")
    for ax, (title, values, names) in zip(axes, blocks):
        for i, name in enumerate(names):
            value = values[name]
            mean, (low, high) = value["mean_difference"], value["interval"]
            ax.errorbar(mean, i, xerr=[[mean - low], [high - mean]], fmt="o",
                        color="#285A8A", capsize=5, linewidth=2)
        ax.axvline(0, color="#697386", linewidth=1)
        ax.axvline(.01, color="#B94636", linestyle="--", linewidth=1,
                   label="Superiority margin +0.01")
        ax.axvline(-.01, color="#89939E", linestyle=":", linewidth=1,
                   label="Event noninferiority margin -0.01")
        ax.set_yticks(range(3), [n.replace("_vs_", " − ").replace("_", " ") for n in names])
        ax.invert_yaxis()
        ax.set_title(title, fontweight="bold")
        ax.set_xlabel("Paired net utility difference (higher is better)")
        ax.grid(axis="x", alpha=.15)
    axes[1].legend(loc="lower right", fontsize=8)
    fig.suptitle("Frozen confirmation: 5 training seeds, 4,000 paired bootstrap draws\n"
                 "Intervals use alpha = 0.05/3 within each primary family", fontsize=12)
    for extension in ("png", "svg"):
        fig.savefig(destination / ("primary_effects." + extension), dpi=180)
    plt.close(fig)
    names = ["frozen", "protected", "protected_q24", "calibrated", "calibrated_q24",
             "calibrated_unconstrained", "replay", "online"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.5), layout="constrained", sharey=True)
    labels = [n.replace("calibrated_unconstrained", "unconstrained").replace("_", " ") for n in names]
    specifications = [
        ("worst_window_old_nll_increase", "Worst-window old NLL increase\n(cross-seed mean)", .02),
        ("shifted_ece", "Shifted classwise ECE", .04),
        ("shifted_coverage95", "Shifted 95% interval coverage", None),
    ]
    for ax, (key, title, threshold) in zip(axes, specifications):
        values = [calibration["arms"][n]["shifted_calibration"]["classwise_ece"] if key == "shifted_ece"
                  else calibration["arms"][n][key] for n in names]
        ax.scatter(values, range(len(names)), s=45, color="#285A8A", zorder=3)
        if threshold is not None:
            ax.axvline(threshold, color="#B94636", linestyle="--", linewidth=1)
        else:
            ax.axvspan(.92, .98, color="#55A978", alpha=.13)
            ax.axvline(.95, color="#697386", linestyle=":", linewidth=1)
        ax.set_yticks(range(len(names)), labels)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.grid(axis="x", alpha=.15)
    axes[0].invert_yaxis()
    axes[2].set_xlim(.88, 1.0)
    fig.suptitle("Calibration and retention are separate gates\n"
                 "12 fixed windows per seed; empirical results do not imply uniform protection", fontsize=12)
    for extension in ("png", "svg"):
        fig.savefig(destination / ("calibration_retention." + extension), dpi=180)
    plt.close(fig)


def build(root, destination):
    from .. import freeze
    root, destination = Path(root), Path(destination)
    frozen = freeze.verify(root)
    for relative in ("main/RUN_INDEX.json", "FEEDBACK_INDEX.json", "CALIBRATION_INDEX.json", "RUNTIME_INDEX.json"):
        index = read(root / relative)
        if not index["complete"]:
            raise ValueError("Registered confirmation is incomplete: " + relative)
        if index["source_commit"] != frozen["source_commit"]:
            raise ValueError("Phase index has a different frozen source identity")
        for entry in index["scopes"]:
            for path, expected in entry.get("files_sha256", {}).items():
                candidate = (root / path).resolve()
                if not candidate.is_relative_to(root.resolve()) or sha(candidate) != expected:
                    raise ValueError("Completed phase artifact changed: " + path)
            if "result" in entry and sha(root / entry["result"]) != entry["sha256"]:
                raise ValueError("Calibration result differs from the frozen phase receipt")
    main, feedback, calibration, runtime = [read(root / path) for path in (
        "MAIN_RESULTS.json", "FEEDBACK_RESULTS.json", "calibration_confirmation/RESULTS.json", "RUNTIME_RESULTS.json")]
    if (calibration["global_freeze_sha256"] != sha(root / "FREEZE.json")
            or calibration["prepared_sha256"] != frozen["artifacts_sha256"]["calibration_prepared/PREPARED.json"]
            or calibration["registration"] != read(freeze.PROJECT / "PROTOCOL.json")["calibration"]):
        raise ValueError("Calibration result has a different freeze, prepared study, or registration")
    if any(value["source_commit"] != frozen["source_commit"] for value in (main, feedback, runtime)):
        raise ValueError("Result belongs to a different frozen scientific source")
    if sha(root / "FEEDBACK_RESULTS.json") != read(root / "FEEDBACK_STATISTICS_EXECUTION.json")["results_sha256"]:
        raise ValueError("Feedback result differs from its frozen statistics receipt")
    (destination / "results").mkdir(parents=True, exist_ok=True)
    for source, name in (("MAIN_RESULTS.json", "MAIN_RESULTS"), ("FEEDBACK_RESULTS.json", "FEEDBACK_RESULTS"),
                         ("calibration_confirmation/RESULTS.json", "CALIBRATION_RESULTS"), ("RUNTIME_RESULTS.json", "RUNTIME_RESULTS")):
        shutil.copyfile(root / source, destination / "results" / (name + ".json"))
    costs = main_costs(root)
    write(root / "MAIN_EXECUTION_COSTS.json", costs)
    write(destination / "results/MAIN_EXECUTION_COSTS.json", costs)
    acceptance = {
        "schema": "hepta.analytic-event.round3.acceptance.v1", "decision": "KEEP_RESEARCH",
        "source_commit": main["source_commit"], "production_promotion": False,
        "implementation_and_registered_confirmation_complete": True,
        "main_registered_superiority": {k: v["passes_registered_superiority"] for k, v in main["primary_contrasts"].items()},
        "main_event_noninferiority": main["event_noninferiority"],
        "feedback_registered_superiority": {k: feedback["contrasts"][k]["empirical_superiority_001"]
            for k in ("event_vs_gaussian", "analytic_vs_numeric", "analytic_vs_gaussian")},
        "feedback_event_noninferiority": feedback["contrasts"]["event_vs_gaussian"]["empirical_noninferiority_001"],
        "calibration_and_retention": {k: {g: v[g] for g in (
            "passes_original_bounded_retention_gate", "passes_new_nll_efficacy_gate",
            "passes_descriptive_calibration_gate", "passes_joint_empirical_gate")}
            for k, v in calibration["arms"].items()},
        "runtime_qualification_passed": runtime["passed"],
        "new_function_class_established": False, "general_dqn_convergence_established": False,
        "unlimited_retention_established": False, "hardware_energy_advantage_established": False,
        "fresh_native_build_this_round": False,
        "just_fmt": {"status": "NOT_RUN", "reason": "No Rust changes; partial checkout has no codex-rs tree and just is unavailable."},
        "gate_rule": "All scientific gates are the preconfirmation frozen gates; negative or equivalent outcomes are retained.",
        "aggregate_boolean_scope": "Descriptive conjunction of the three main superiority gates, three feedback superiority gates, at least one calibration joint gate, and runtime qualification. Separate noninferiority and mismatch diagnostics remain individually reported; this is not a new registered decision rule.",
        "frozen_source_and_prepared_binding": {"sources": len(frozen["sources_sha256"]), "prepared_artifacts": len(frozen["artifacts_sha256"]), "verified_before_and_after_reporting": True},
        "result_sha256": {str(p.relative_to(destination)): sha(p) for p in sorted((destination / "results").glob("*RESULTS.json"))},
    }
    acceptance["scientific_acceptance_complete"] = bool(
        all(acceptance["main_registered_superiority"].values())
        and all(acceptance["feedback_registered_superiority"].values())
        and any(x["passes_joint_empirical_gate"] for x in acceptance["calibration_and_retention"].values())
        and acceptance["runtime_qualification_passed"])
    write(destination / "ACCEPTANCE.json", acceptance)
    figures(main, feedback, calibration, destination / "figures")
    freeze.verify(root)
    return {"decision": acceptance["decision"], "scientific_acceptance_complete": acceptance["scientific_acceptance_complete"],
            "main_scope_count": len(costs["scopes"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.run_dir, args.destination)))
