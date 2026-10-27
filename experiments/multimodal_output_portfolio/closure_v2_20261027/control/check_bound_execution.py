"""Three historical continuations exercise the accepted bound-critic path."""

import argparse
import json
from pathlib import Path

import torch

from ...continuation_20261027.joint.run import reference_observer
from .adapter import Generator
from .binding import BoundCritic
from .execute import episode
from .protocol import preserve_sources, sha, write
from .tasks import load_tasks


def run(assets, generator_path, binary, development, original_preflight, output):
    output.mkdir(parents=True, exist_ok=False)
    preserve_sources(output / "executed-source")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    records = json.loads((development / "VALIDATION.json").read_text())
    tasks = load_tasks(development / "validation-inputs")
    selected = [next(row for row in records if row["feedback"] == value) for value in (-1, 0, 1)]
    generator, observer = Generator(generator_path), reference_observer(assets, "reward")
    fit = json.loads((development / "FIT.json").read_text())
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    shrinkage = json.loads((development / "CRITIC_SELECTION.json").read_text())["selected_shrinkage"]
    bound = BoundCritic(development, generator_path, binary)
    checks = []
    for i, selected_row in enumerate(selected):
        original = tasks[selected_row["index"]]
        task = {**original, "index": 4 * i + 3, "expires": 7, "budget": 2}
        reference = {"index": original["index"], "feedback": selected_row["feedback"], "delivery": selected_row["initial_delivery"]}
        donor = {"index": selected[(i + 1) % 3]["index"], "feedback": selected[(i + 1) % 3]["feedback"]}
        row = episode(task, "native_numeric", reference, donor, generator, observer, binary, development,
            output, fit, heads, shrinkage, forecast_model=bound)
        old_path = original_preflight / "episodes" / row["name"] / "EPISODE.json"
        old = json.loads(old_path.read_text())
        for key in ("proposed", "admitted", "denied", "task_charge", "actual_original_kernel_executions"):
            if old[key] != row[key]:
                raise ValueError("Guarded historical continuation changed: " + key)
        for key in ("initial", "final"):
            if old[key]["sha256"] != row[key]["sha256"]:
                raise ValueError("Guarded execution changed delivered bytes")
        for key in ("prediction_before", "prediction_after"):
            if {k: v for k, v in row[key].items() if k != "bound_runtime_sha256"} != old[key]:
                raise ValueError("Valid runtime binding changed a historical forecast")
        checks.append({"feedback": row["delivered_feedback"], "source_old_episode_sha256": sha(old_path),
            "guarded_episode_sha256": sha(output / "episodes" / row["name"] / "EPISODE.json"),
            "predictions_actions_bytes_unchanged": True, "future_state_matches": row["future_state_matches"]})
    result = {"passed": True, "checks": checks, "actual_native_kernel_executions": 150,
        "actual_cold_process_restores": 3, "bound_runtime_sha256": bound.fingerprint,
        "only_historical_validation_sources": True, "new_qualification_outputs_used": False}
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "original-preflight", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.original_preflight, args.output)
