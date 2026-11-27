"""Run existing HX tasks in fresh processes and compare declared cost budgets.

This additional small-task campaign does not replace the original 170-run
experiment, localization, or Cell E07. Each fit keeps the existing split,
minibatch, validation-selection, immutable-attempt and held-out-test protocol.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from .attempts import source_snapshot
from .benchmark import aggregate, atomic_json, validate_config


def cost_comparison(record, wall_budgets, quality_ratios):
    """Use validation only for cost curves; retain every failure/censored row."""
    curve = [point for point in record.get("validation_curve", []) if point.get("eligible", True)]
    baseline = record.get("validation_constant_mse")
    same_wall = []
    for budget in wall_budgets:
        eligible = [point for point in curve if point["wall_seconds"] <= budget]
        point = min(eligible, key=lambda point: point["best_mse"]) if eligible else None
        same_wall.append(dict(budget_seconds=budget, observation=point))
    same_quality = []
    for ratio in quality_ratios:
        target = baseline * ratio if baseline is not None else None
        reached = next((point for point in curve if point["best_mse"] <= target), None) if target is not None else None
        same_quality.append(dict(ratio_to_training_mean_predictor=ratio,
                                 validation_mse_target=target, first_observed=reached))
    return dict(same_wall_validation=same_wall, same_quality_validation=same_quality,
                scope="recorded validation checkpoints; test used once after selection")


def run(config, output):
    validate_config(config)
    output.mkdir(parents=True, exist_ok=False)
    source = source_snapshot(Path(__file__).parent)
    atomic_json(output / "PLAN.json", config, replace=False)
    atomic_json(output / "SOURCE.json", source, replace=False)
    started, rows = time.perf_counter(), []
    matrix = [(task, model, seed) for task in config["tasks"]
              for seed in config["seeds"] for model in config["models"]]
    if config.get("matrix_order") == "interleaved":
        matrix = []
        for index, seed in enumerate(config["seeds"]):
            models = config["models"][index:] + config["models"][:index]
            for offset, model in enumerate(models):
                tasks = config["tasks"] if (index+offset) % 2 == 0 else config["tasks"][::-1]
                matrix.extend((task, model, seed) for task in tasks)
    atomic_json(output / "EXECUTION_ORDER.json", matrix, replace=False)
    for index, (task, model, seed) in enumerate(matrix):
        remaining = config["campaign_wall_seconds"] - (time.perf_counter() - started)
        row = dict(task=task, model=model, seed=seed, status="not_started", process=None)
        rows.append(row)
        if remaining <= 0:
            row["reason"] = "campaign wall budget exhausted before process launch"
            continue
        if source_snapshot(Path(__file__).parent) != source:
            raise RuntimeError("campaign source changed; prior results retained")
        destination = output / f"{index:03d}-{task}-{model}-{seed}"
        destination.mkdir()
        single = dict(config, tasks=[task], models=[model], seeds=[seed])
        atomic_json(destination / "CONFIG.json", single, replace=False)
        command = [sys.executable, "-m", "qualification.hcsn.benchmark", "--config",
                   str(destination / "CONFIG.json"), "--output", str(destination / "RESULT.json")]
        before = time.perf_counter()
        with (destination / "stdout.log").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
            child = None
            try:
                child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                atomic_json(destination / "PROCESS_STARTED.json", dict(pid=child.pid, command=command), replace=False)
                try:
                    code = child.wait(timeout=min(config["fit_wall_seconds"], remaining))
                    timed_out = False
                except subprocess.TimeoutExpired:
                    child.kill()
                    code = child.wait()
                    timed_out = True
                row["process"] = dict(pid=child.pid, returncode=code, timed_out=timed_out,
                                      direct_child_reaped=True)
            except OSError as error:
                row["process"] = dict(returncode=None, timed_out=False, launch_error=str(error))
            finally:
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait()
        row["process"].update(wall_seconds=time.perf_counter()-before, command=command)
        result_path = destination / "RESULT.json"
        if result_path.exists():
            report = json.loads(result_path.read_text())
            if len(report["runs"]) != 1 or report["source_files_sha256"] != source:
                raise RuntimeError("child report does not match the frozen single-fit source")
            record = report["runs"][0]
            row.update(status=record["status"], result=record,
                       report_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                       report=str(result_path.relative_to(output)),
                       comparison=cost_comparison(record, config["wall_budgets"], config["quality_ratios"]))
        else:
            row.update(status="interrupted", reason="no terminal report; immutable attempt files retained")
        atomic_json(destination / "PROCESS.json", row["process"], replace=False)
        atomic_json(output / "PROGRESS.json", rows)
        print(f"{index+1}/{len(matrix)} {task} {model} {seed}: {row['status']}", flush=True)
    terminal = [row["result"] for row in rows if "result" in row]
    pairs = []
    for task in config["tasks"]:
        for seed in config["seeds"]:
            group = {row["model"]: row for row in terminal if row["task"] == task and row["seed"] == seed}
            for other in ("matched_gate", "hx_dual_prepared"):
                if other not in config["models"]:
                    continue
                complete = all(group.get(name, {}).get("status") == "completed" for name in ("hx_dual", other))
                pairs.append(dict(task=task, seed=seed, pair=["hx_dual", other], complete=complete,
                                  parameters_match=all(group["hx_dual"][key] == group[other][key]
                                                       for key in ("parameters", "trainable_parameters"))
                                  if complete else None))
    report = dict(schema="hepta.hx-ablation.v1", config=config, rows=rows,
                  source_files_sha256=source, wall_seconds=time.perf_counter()-started,
                  summary=aggregate(terminal),
                  completed=sum(row["status"] == "completed" for row in rows),
                  requested=len(matrix),
                  paired_parameter_checks=pairs,
                  status="completed" if all(row["status"] == "completed" for row in rows) else "partial",
                  protocol=dict(tasks="existing delayed_recall/adding definitions",
                                comparison=("filled training/validation wall budget; only in-budget checkpoints eligible"
                                            if config.get("training_wall_seconds") else
                                            "same updates/data; validation wall prefixes only"),
                                parameters="HX dual and matched_gate match exactly; GRU width matched only",
                                cpu_rss="one fresh process per fit; OS high-water includes interpreter",
                                integration="additional small-task study, not original full campaign or E07"))
    atomic_json(output / "RESULT.json", report, replace=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(json.loads(args.config.read_text()), args.output.resolve())
    print(json.dumps({key: report[key] for key in ("status", "requested", "completed", "wall_seconds")}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
