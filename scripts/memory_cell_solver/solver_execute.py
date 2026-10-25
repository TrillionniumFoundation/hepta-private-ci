"""Execute every frozen development trajectory with retained failure evidence."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from solver_common import delta, file_identity, measurement, read_pinned, save
from solver_accounting import model_observations
from solver_prepare import HERE, source_inventory
from solver_tasks import REPO

sys.path.insert(0, str(REPO / "scripts/memory_cell_network"))
from model_process import ChildFailure, run_child


def execute(output, protocol_sha256, model):
    output = Path(output).resolve()
    protocol_path = output / "protocol.json"
    protocol = read_pinned(protocol_path, protocol_sha256)
    if (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
        != protocol["source_head"]
    ):
        raise ValueError("committed source head changed")
    if source_inventory(REPO) != protocol["source_files"]:
        raise ValueError("source changed before execution")
    model_manifest = output / "model-manifest.json"
    if file_identity(model_manifest) != protocol["staged_model_manifest"]:
        raise ValueError("staged model manifest changed")
    started = measurement()
    directory = output / "trajectories"
    directory.mkdir(exist_ok=False)
    results = []
    summary = {
        "schema": "hepta.memory-cell.repair-solver-study.v1",
        "source_head": protocol["source_head"],
        "protocol_sha256": protocol_sha256,
        "rows": results,
        "development_only": True,
        "independent_future_cases": 0,
        "future_accuracy": None,
        "strong_rag_qualified": False,
        "full_budget_fission_qualified": False,
        "production_accepted": False,
    }
    try:
        for task in protocol["task_order"]:
            for arm in protocol["arms"]:
                if source_inventory(REPO) != protocol["source_files"]:
                    raise ValueError("source changed between trajectories")
                selected = protocol["tasks"][task]
                retrieval = protocol["retrieval_files"][task + ":" + arm]
                request = {
                    "output": str(directory / (task + "-" + arm)),
                    "protocol": str(protocol_path),
                    "protocol_sha256": protocol_sha256,
                    "model_manifest": str(model_manifest),
                    "model_manifest_sha256": protocol["staged_model_manifest"][
                        "sha256"
                    ],
                    "model": str(Path(model).resolve()),
                    "task": task,
                    "arm": arm,
                    "fixture": selected["fixture"],
                    "runtime_profile": selected["runtime_profile"],
                    "retrieval": retrieval["path"],
                    "retrieval_sha256": retrieval["sha256"],
                }
                path = directory / (task + "-" + arm + ".request.json")
                save(path, request)
                row = {
                    "task": task,
                    "arm": arm,
                    "accepted": False,
                    "request": file_identity(path),
                }
                results.append(row)
                try:
                    process = run_child(
                        HERE / "repair_loop.py",
                        [
                            "--request",
                            path,
                            "--request-sha256",
                            file_identity(path)["sha256"],
                        ],
                        timeout=protocol["trajectory_limits"]["wall_seconds"] + 30,
                        cwd=directory,
                        receipt_dir=output / "processes",
                        operation="code-solver-trajectory",
                    )
                except ChildFailure as error:
                    process = error.receipt
                    row["process_error"] = str(error)
                row["process"] = {
                    k: v for k, v in process.items() if k not in ("stdout", "stderr")
                }
                result_path = Path(request["output"]) / "result.json"
                if result_path.exists():
                    result = json.loads(result_path.read_text())
                    row.update(
                        result=result,
                        result_file=file_identity(result_path),
                        accepted=result["accepted"]
                        and process["returncode"] == 0
                        and not process["timed_out"],
                    )
                else:
                    row.update(
                        status="execution_failed_without_complete_result",
                        recovered_model_observations=model_observations(
                            request["output"]
                        ),
                    )
                row["execution_valid"] = bool(
                    row.get("result", {}).get("execution_valid")
                    and process["returncode"] == 0
                    and not process["timed_out"]
                )
                save(directory / (task + "-" + arm + ".summary.json"), row)
                if not row["execution_valid"]:
                    raise ValueError(
                        "registered trajectory execution failed; no automatic retry"
                    )
        after = source_inventory(REPO)
        save(output / "source-after.json", after)
        if after != protocol["source_files"]:
            raise ValueError("source changed during actual study")
        summary["source_unchanged"] = True
    except Exception as error:
        summary.update(
            execution_error=f"{type(error).__name__}: {error}", source_unchanged=False
        )
    finally:
        summary["measurements"] = delta(started, measurement())
        summary["task_success"] = {
            arm: {
                "correct": sum(r["accepted"] for r in results if r["arm"] == arm),
                "registered_total": len(protocol["task_order"]),
                "attempted_total": sum(r["arm"] == arm for r in results),
            }
            for arm in protocol["arms"]
        }
        observed = [
            r.get("result", r.get("recovered_model_observations", {})) for r in results
        ]
        summary["recorded_model_calls_started"] = sum(
            r.get("model_queries_started", 0) for r in observed
        )
        summary["recorded_prompt_tokens"] = sum(
            r.get("prompt_tokens", 0) for r in observed
        )
        summary["recorded_generated_tokens"] = sum(
            r.get("generated_tokens", 0) for r in observed
        )
        summary["incomplete_trajectory_results"] = sum(
            "result" not in r for r in results
        )
        summary["costs_are_lower_bounds_if_incomplete"] = summary[
            "incomplete_trajectory_results"
        ] > 0 or any(r.get("token_totals_are_lower_bounds", False) for r in observed)
        summary["unexecuted_trajectories"] = [
            {"task": task, "arm": arm, "reason": "not reached after execution failure"}
            for task in protocol["task_order"]
            for arm in protocol["arms"]
            if not any(r["task"] == task and r["arm"] == arm for r in results)
        ]
        summary["model_storage_bytes"] = json.loads(model_manifest.read_text())["file"][
            "bytes"
        ]
        summary["retained_bytes_before_summary"] = sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        )
        summary["whole_system_cost_complete"] = False
        summary["shared_asset_note"] = (
            "One retained GGUF and source corpus; each trajectory loads its own fresh model process. Standalone deployment would also require model/runtime/source storage. Fixed serial order can warm OS caches."
        )
        save(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "protocol-sha256", "model"):
        parser.add_argument("--" + name, required=True)
    result = execute(**vars(parser.parse_args()))
    print(json.dumps(result["task_success"]))
    raise SystemExit(1 if result.get("execution_error") else 0)
