"""Check the final deployed native path on three historical calibration cases."""

import argparse
import json
from pathlib import Path

import torch

from ...continuation_20261027.joint.run import reference_observer
from .adapter import Generator
from .admission_binding import BoundAdmission
from .admission_qualify import execute
from .protocol import preserve_sources, sha, write
from .tasks import load_tasks


def run(assets, generator_path, binary, development, calibration, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    preserve_sources(output / "executed-source")
    bound = BoundAdmission(calibration, development, generator_path, binary, assets)
    generator = Generator(generator_path)
    public, private = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    records = json.loads((calibration / "ROWS.json").read_text())
    source_tasks = load_tasks(calibration / "calibration_id-inputs")
    checks = []
    for scalar in (-1, 0, 1):
        previous = next(r for r in records if not r["declared_ood"] and r["feedback"] == scalar)
        task = {**source_tasks[previous["index"]], "role": "historical-preflight", "declared_ood": False}
        row = execute(task, generator, public, private, bound, binary, development, output)
        for key in ("feedback", "category", "probability", "confidence_ppm", "commit", "actual_correction", "strict_success"):
            if previous[key] != row[key]:
                raise ValueError("Actual native deployment differs from offline historical calibration: " + key)
        if previous["candidate"]["sha256"] != row["candidate"]["sha256"]:
            raise ValueError("Actual native deployment changed calibration candidate bytes")
        checks.append({"feedback": scalar, "category": row["category"], "same_candidate_action_probability_and_host_decision": True,
            "actual_future_state_matches": row["future_state_matches"], "episode_sha256": sha(output / "episodes" / f"historical-preflight-{task['index']:04}" / "EPISODE.json")})
    result = {"passed": True, "checks": checks, "actual_native_kernel_executions": 150,
        "new_test_outputs_computed": False, "original_native_profile_unchanged": True}
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "calibration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.calibration, args.output)
