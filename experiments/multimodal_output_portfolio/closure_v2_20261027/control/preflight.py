"""Historical-validation-only execution check before opening new test outputs."""

import argparse
import json
from pathlib import Path

import torch

from ...continuation_20261027.joint.run import reference_observer
from .adapter import Generator
from .binding import BoundCritic
from .execute import episode
from .protocol import PROTOCOL as P, preserve_sources, sha, write
from .tasks import load_tasks


def run(assets, generator_path, binary, development, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    preserve_sources(output / "executed-source")
    records = json.loads((development / "VALIDATION.json").read_text())
    tasks = load_tasks(development / "validation-inputs")
    selected = [next(row for row in records if row["feedback"] == value) for value in (-1, 0, 1)]
    generator, observer = Generator(generator_path), reference_observer(assets, "reward")
    fit = json.loads((development / "FIT.json").read_text())
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    shrinkage = json.loads((development / "CRITIC_SELECTION.json").read_text())["selected_shrinkage"]
    forecast_model = BoundCritic(development, generator_path, binary)
    rows = []
    for symbol_index, selected_row in enumerate(selected):
        original = tasks[selected_row["index"]]
        reference = {"index": original["index"], "feedback": selected_row["feedback"], "delivery": selected_row["initial_delivery"]}
        donor = {"index": selected[(symbol_index + 1) % 3]["index"], "feedback": selected[(symbol_index + 1) % 3]["feedback"]}
        for context_index, (expires, budget) in enumerate(((6, 1), (6, 2), (7, 1), (7, 2))):
            task = {**original, "index": symbol_index * 4 + context_index, "expires": expires, "budget": budget}
            for arm in P["arms"]:
                rows.append(episode(task, arm, reference, donor, generator, observer, binary, development, output, fit, heads, shrinkage,
                                    forecast_model=forecast_model))
    result = {"passed": all(row["future_state_matches"] for row in rows), "actual_episodes": len(rows),
        "realized_symbols": sorted(set(r["delivered_feedback"] for r in rows)), "actual_kernel_executions": sum(r["actual_original_kernel_executions"] for r in rows),
        "cold_process_restores": len(rows), "actual_neural_corrections": sum(r["admitted"] for r in rows),
        "expiry_and_budget_refusals": sum(r["denied"] for r in rows), "new_test_sources_used": False,
        "audit_observer_loaded": False, "frozen_model_sha256": sha(development / "MODEL.json")}
    write(output / "RESULT.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "generator", "binary", "development", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.generator, args.binary, args.development, args.output)
