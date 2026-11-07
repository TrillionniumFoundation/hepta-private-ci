"""Single-source parameter-update wiring for both real pretrained generators.

Each generator is trained separately. A fixed dual schedule then checks adapter
reattachment across model-family switches. There is no holdout or efficacy claim.
"""

import argparse
import gc
import json
from pathlib import Path
import re
import shutil
import time

from .adapted_models import AdaptedLocalModels
from .dual_runtime import FixedSchedule, Request, digest_file, run, write_json
from .train_adapter import train as train_text
from .train_image_adapter import train as train_image


ACTIONS = ("perceive", "text", "draft", "verify", "stop")
INSTRUCTION = ("Explain the main visible subject and its relation to the plant. "
               "Produce a simple diagram showing their relative positions.")


def execute(models, output, source_sha, threads=2):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Immutable source identity is required")
    started = time.process_time(), time.perf_counter()
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent / "evidence" / "real_20261105"
    rows, checkpoints, cancelled = [], {}, False
    inference = {"status": "not_run_unqualified_training"}
    try:
        review = json.loads((source / "REVIEW.json").read_text())
        original = next(x for x in review["original_file_manifest"] if x["path"] == "real/input.png")
        if digest_file(source / "input.png") != original["sha256"]:
            raise ValueError("The prior derived input differs from its original evidence")
        shutil.copyfile(source / "input.png", output / "input.png")
        shared = {"source_id": "public-bee-single-source-wiring",
                  "image_path": "input.png", "image_sha256": original["sha256"]}
        text_data = {"schema": "hepta.real-adapter-training-data.v1", "role": "training_only",
                     "examples": [{**shared,
                         "instruction": "Describe the main visible subject and its relation to the plant in one sentence.",
                         "target": "A bee is on the center of a pink flower."}]}
        image_data = {"schema": "hepta.real-image-adapter-training-data.v1", "role": "training_only",
                      "examples": [{**shared, "prompt": "A bee on a pink flower.",
                                    "target_provenance": "public input photo; reconstruction wiring only"}]}
        write_json(output / "text_manifest.json", text_data)
        write_json(output / "image_manifest.json", image_data)
        plan = {"source_sha": source_sha, "declared_source_count": 1, "seed": 17,
                "steps_per_generator": 2, "rank": 4, "learning_rate": .001, "threads": threads,
                "role": "engineering_parameter_update_reload_and_dual_execution_only",
                "prior_run_source_sha": review["source_sha"], "inference_actions": ACTIONS,
                "manifests": {n: digest_file(output / (n + "_manifest.json")) for n in ("text", "image")},
                "runtime_sources": {p.name: digest_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "holdout_count": 0, "learned_controller": False, "joint_reward_training": False,
                "independent_semantic_evaluation": False, "image_target_is_diagram": False}
        write_json(output / "PLAN.json", plan)
        for name, trainer in (("text", train_text), ("image", train_image)):
            stage_start = time.process_time(), time.perf_counter()
            row = {"generator": name, "status": "not_started"}
            try:
                if cancelled:
                    row["status"] = "not_run_after_cancellation"
                    continue
                row["status"] = "started"; write_json(output / (name + "_stage.json"), row)
                trained = trainer(models, output / (name + "_manifest.json"), output / (name + "_training"),
                                  source_sha, plan["manifests"][name], seed=17, rank=4, steps=2,
                                  learning_rate=.001, threads=threads, cpu_budget=600, wall_budget=600)
                row.update(status=trained["status"], completed_updates=trained["completed_updates"],
                           error=trained.get("error"))
                cancelled = cancelled or trained["status"] == "cancelled"
                if trained["status"] == "completed":
                    checkpoint = trained.get("checkpoint")
                    if not checkpoint or (name == "image" and trained.get("checkpoint_qualified") is not True):
                        raise RuntimeError("Completed trainer omitted its admitted checkpoint")
                    row["checkpoint"] = checkpoint
                    checkpoints["vlm" if name == "text" else "sd"] = {
                        "path": str(output / (name + "_training") / checkpoint["path"]),
                        "sha256": checkpoint["sha256"]}
            except (Exception, KeyboardInterrupt) as exc:
                cancelled = cancelled or isinstance(exc, KeyboardInterrupt)
                row.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                           error={"type": type(exc).__name__, "message": str(exc)})
            finally:
                gc.collect()
                row["cpu_seconds"] = time.process_time() - stage_start[0]
                row["wall_seconds"] = time.perf_counter() - stage_start[1]
                row["cost_scope"] = "inclusive_trainer_call_and_cleanup_before_stage_write"
                row["do_not_add_to_nested_training_cost"] = True
                rows.append(row); write_json(output / (name + "_stage.json"), row)
        if len(checkpoints) == 2 and not cancelled:
            outer = time.process_time(), time.perf_counter()
            backend = AdaptedLocalModels(Path(models) / "vlm", Path(models) / "sd", checkpoints, threads=threads)
            request = Request(shared["source_id"], str(output / "input.png"), original["sha256"], INSTRUCTION)
            result = run(request, backend, FixedSchedule(ACTIONS), output / "adapted_dual",
                         seed=17, horizon=len(ACTIONS), deadline_seconds=600)
            inference = {"status": result["status"], "error": result["error"], "selected": result["selected"]}
            del backend; gc.collect()
            inference["outer_cpu_seconds"] = time.process_time() - outer[0]
            inference["outer_wall_seconds"] = time.perf_counter() - outer[1]
            inference["cost_scope"] = "inclusive_adapted_backend_construction_run_and_cleanup"
            inference["do_not_add_to_nested_action_cost"] = True
            write_json(output / "inference_outer.json", inference)
    except (Exception, KeyboardInterrupt) as exc:
        rows.append({"generator": "setup_or_inference", "status": "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                     "error": {"type": type(exc).__name__, "message": str(exc)}})
    summary = {"source_sha": source_sha, "stages": rows, "inference": inference,
               "completed_generators": sum(r["status"] == "completed" for r in rows),
               "cpu_seconds": time.process_time() - started[0],
               "wall_seconds": time.perf_counter() - started[1],
               "cost_scope": "inclusive_setup_training_dual_inference_cleanup_and_stage_writes_before_summary",
               "declared_source_count": 1, "holdout_count": 0,
               "training_design": "separate_single_generator_updates",
               "joint_training_efficacy": False, "four_arm_efficacy": False,
               "semantic_acceptance": "not_inferred", "production_qualified": False,
               "separate_cost_receipts": ["acquisition/ACQUISITION.json"],
               "workflow_cost_source": "separate command meters and GitHub job timestamps",
               "unknown_outer_costs": ["process_startup", "energy", "summary_write"]}
    write_json(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("models", "output", "source-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--threads", type=int, default=2)
    result = execute(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["completed_generators"] != 2 or result["inference"]["status"] != "delivered":
        raise SystemExit(1)
