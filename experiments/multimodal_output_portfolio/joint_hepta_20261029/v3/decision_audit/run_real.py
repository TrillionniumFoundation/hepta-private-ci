"""Two registered fixed schedules using actual pinned pretrained generators.

This is a development execution canary, not a learned controller experiment,
new four-arm training result, independent semantic score or production gate.
"""

import argparse
import json
from pathlib import Path
import platform
import re
import time

from .dual_runtime import FixedSchedule, Request, digest_file, run, write_json
from .local_models import LocalModels


SCHEDULES = {
    "direct": ("perceive", "text", "draft", "verify", "stop"),
    "revision": ("perceive", "text", "draft", "verify", "revise", "text",
                 "refine", "verify", "stop"),
}


def execute(models, output, source_sha, threads=2):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("An immutable Git source identity is required")
    root, output = Path(models), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    input_manifest = json.loads((root / "task" / "INPUT_MANIFEST.json").read_text())
    original = root / "task" / "input.jpg"
    if digest_file(original) != input_manifest["sha256"]:
        raise ValueError("Original public image differs from acquisition receipt")
    from PIL import Image
    with Image.open(original) as raw:
        resized = raw.convert("RGB")
        resized.thumbnail((512, 512), Image.Resampling.LANCZOS)
        resized.save(output / "input.png")
    derived_sha = digest_file(output / "input.png")
    request = Request("hf-documentation:bee:" + input_manifest["revision"],
                      str(output / "input.png"), derived_sha,
                      "Explain the main visible subject and its relation to the plant. "
                      "Produce a simple diagram showing their relative positions.")
    plan = {"source_sha": source_sha, "schedules": SCHEDULES, "seed": 17,
            "threads": threads, "deadline_seconds": 600, "input": input_manifest,
            "input_preprocessing": {"operation": "RGB_thumbnail_512_LANCZOS_PNG",
                                    "derived_sha256": derived_sha},
            "role": "public_development_execution_only", "fresh_holdout_opened": False,
            "training_performed": False, "learned_controller": False,
            "independent_semantic_evaluation": "pending",
            "runtime_sources": {p.name: digest_file(p)
                                for p in sorted(Path(__file__).parent.glob("*.py"))}}
    write_json(output / "PLAN.json", plan)
    episodes = []
    try:
        for name, actions in SCHEDULES.items():
            backend = LocalModels(root / "vlm", root / "sd", threads)
            before = time.process_time(), time.perf_counter()
            result = run(request, backend, FixedSchedule(actions), output / name,
                         seed=17, horizon=len(actions), deadline_seconds=600)
            outer = {"cpu_seconds": time.process_time() - before[0],
                     "wall_seconds": time.perf_counter() - before[1]}
            outer.update({"scope": "inclusive_run_call_through_return_including_report_writes",
                          "do_not_add_to_nested_action_totals": True,
                          "exclusive_unattributed_cpu": max(0, outer["cpu_seconds"] - result["cpu_seconds"]),
                          "exclusive_unattributed_wall": max(0, outer["wall_seconds"] - result["wall_seconds"])})
            write_json(output / name / "OUTER_COST.json", outer)
            episodes.append({"name": name, "status": result["status"], "outer": outer,
                             "selected": result["selected"], "error": result["error"]})
            # Model objects are independent; the OS file cache may stay warm.
            del backend
            import gc
            gc.collect()
    finally:
        summary = {"source_sha": source_sha, "episodes": episodes,
                   "completed_registered_schedules": len(episodes) == len(SCHEDULES),
                   "process_cpu_seconds": time.process_time() - start[0],
                   "process_wall_seconds": time.perf_counter() - start[1],
                   "scope": "inclusive_setup_and_both_runs_before_summary_write",
                   "platform": platform.platform(), "python": platform.python_version(),
                   "semantic_acceptance": "pending_independent_evaluation",
                   "new_four_arm_training": False, "all_blockers_closed": False,
                   "unknown_costs": ["package_install", "energy", "future_training",
                                     "independent_semantic_evaluation", "summary_write"],
                   "acquisition_cost_receipt": "separate_ACQUISITION.json"}
        write_json(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    summary = execute(args.models, args.output, args.source_sha, args.threads)
    print(json.dumps(summary, indent=2, allow_nan=False))
    if not summary["completed_registered_schedules"] or any(e["status"] != "delivered" for e in summary["episodes"]):
        raise SystemExit(1)
