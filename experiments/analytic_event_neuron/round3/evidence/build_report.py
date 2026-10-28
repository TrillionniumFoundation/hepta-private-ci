"""Render completed frozen results; this module does not fit or evaluate models."""

import argparse
import hashlib
import json
import os
from pathlib import Path
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
        values = {}
        with tarfile.open(root / item["archive"], "r|gz") as archive:
            for member in archive:
                if member.name in ("EXECUTION.json", "AUDIT.json"):
                    values[member.name] = json.load(archive.extractfile(member))
                if len(values) == 2:
                    break
        execution, audit = values["EXECUTION.json"], values["AUDIT.json"]
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
    return {"schema": "hepta.analytic-event.round3.main-costs.v1", "sums": sums, "scopes": rows,
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
        ("worst_window_old_nll_increase", "Worst-window old NLL increase", .02),
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
    root, destination = Path(root), Path(destination)
    for relative in ("main/RUN_INDEX.json", "FEEDBACK_INDEX.json", "CALIBRATION_INDEX.json", "RUNTIME_INDEX.json"):
        if not read(root / relative)["complete"]:
            raise ValueError("Registered confirmation is incomplete: " + relative)
    main, feedback, calibration, runtime = [read(root / path) for path in (
        "MAIN_RESULTS.json", "FEEDBACK_RESULTS.json", "calibration_confirmation/RESULTS.json", "RUNTIME_RESULTS.json")]
    for name, value in (("MAIN_RESULTS", main), ("FEEDBACK_RESULTS", feedback),
                        ("CALIBRATION_RESULTS", calibration), ("RUNTIME_RESULTS", runtime)):
        write(destination / "results" / (name + ".json"), value)
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
        "result_sha256": {str(p.relative_to(destination)): sha(p) for p in sorted((destination / "results").glob("*RESULTS.json"))},
    }
    acceptance["scientific_acceptance_complete"] = bool(
        all(acceptance["main_registered_superiority"].values())
        and all(acceptance["feedback_registered_superiority"].values())
        and any(x["passes_joint_empirical_gate"] for x in acceptance["calibration_and_retention"].values())
        and acceptance["runtime_qualification_passed"])
    write(destination / "ACCEPTANCE.json", acceptance)
    figures(main, feedback, calibration, destination / "figures")
    return {"decision": acceptance["decision"], "scientific_acceptance_complete": acceptance["scientific_acceptance_complete"],
            "main_scope_count": len(costs["scopes"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.run_dir, args.destination)))
