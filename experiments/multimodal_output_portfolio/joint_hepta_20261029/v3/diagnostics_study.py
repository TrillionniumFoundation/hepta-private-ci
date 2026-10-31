"""Execute the prespecified v3 paired diagnostic and critic-calibration cohorts."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..mechanism_data import batch
from ..media import utility
from ..model import tensor_digest
from .diagnostics import evaluate_prefix, paired_ce_difference, fit_validate_critics, _write_json
from .model import JointGenerator
from .profile import make_profile


def run(checkpoint, output):
    checkpoint, output = Path(checkpoint), Path(output)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = JointGenerator(**payload["config"]).eval()
    model.load_state_dict(payload["state_dict"], strict=True)
    if model.width != 32 or model.config["mode"] != "dual":
        raise ValueError("This prespecified diagnostic cohort requires the width-32 dual model")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    output.mkdir(parents=True, exist_ok=False)
    profile, started = make_profile(), time.perf_counter()
    roles = ("fit", "analysis")
    prefixes, continuations = ((), ("shared",)), ("stop", "dynamic")
    protocol = {"schema": "hepta.joint-generation.diagnostic-cohort.v3",
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "checkpoint_metadata": payload.get("metadata"), "model_sha256": tensor_digest(model.state_dict()),
        "profile": profile.to_dict(), "namespaces": {r: f"joint-v3-calibration.{r}.20261030" for r in roles},
        "sources_per_role": 8, "prefixes": prefixes, "continuations": continuations, "draws": 4,
        "bootstrap": 400, "fit_updates": 100, "fit_lr": .001, "gradient_clip": 5.,
        "future_seed": "17000000+role_index*1000000+source*10000+prefix_index*1000+continuation_index*100+7919*draw",
        "old_confirmation_sources_consumed": 0, "research_effect_qualified": False,
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("diagnostics.py", "critic_calibration.py", "diagnostics_study.py",
                                       "model.py", "runtime.py", "profile.py")}}
    _write_json(output / "STUDY_PROTOCOL.json", protocol)
    cohorts, completed = defaultdict(list), []
    for role_index, role in enumerate(roles):
        namespace = protocol["namespaces"][role]
        for source in range(8):
            public, target = batch([source], namespace)
            for prefix_index, prefix in enumerate(prefixes):
                for continuation_index, continuation in enumerate(continuations):
                    directory = output / role / f"source-{source:03d}" / f"prefix-{prefix_index}" / continuation
                    seed = 17000000 + role_index * 1000000 + source * 10000 + prefix_index * 1000 + continuation_index * 100
                    result = evaluate_prefix(model, public, lambda readback: utility(readback, target).item(),
                        directory, source_id=f"{namespace}.{source}", prefix=prefix, draws=4,
                        seed=seed, profile=profile, continuation=continuation, bootstrap=400)
                    cohorts[role].append(result)
                    completed.append(str(directory / "DIAGNOSTICS.json"))
                    _write_json(output / "STUDY_PROGRESS.json", {"completed": completed,
                        "elapsed_wall_seconds": time.perf_counter() - started})
                    print(json.dumps({"diagnostic_group": len(completed), "expected_groups": 64,
                                      "role": role, "source": source, "prefix": prefix,
                                      "continuation": continuation}), flush=True)
    comparisons = {}
    for role in roles:
        for prefix_index, prefix in enumerate(prefixes):
            for continuation in continuations:
                groups = [r for r in cohorts[role] if r["prefix"] == list(prefix) and r["continuation"] == continuation]
                rows = [row for group in groups for row in group["rows"]]
                stop = {(r["source_id"], r["draw"]): r for r in rows if r["arm"] == "stop"}
                for arm in sorted({r["arm"] for r in rows}):
                    chosen = [r for r in rows if r["arm"] == arm]
                    values = [r["complete_return"] for r in chosen]
                    baseline = [stop[(r["source_id"], r["draw"])]["complete_return"] for r in chosen]
                    key = f"{role}/prefix-{prefix_index}/{continuation}/{arm}"
                    comparisons[key] = {**paired_ce_difference(values, baseline,
                        source_ids=[r["source_id"] for r in chosen], bootstrap=400, seed=17),
                        "mean_utility": float(np.mean([r["utility"] for r in chosen])),
                        "mean_complete_cost": float(np.mean([r["complete_cost"] for r in chosen])),
                        "failures": sum(r["failure"] is not None for r in chosen)}
    fitting = fit_validate_critics(model, cohorts["fit"], cohorts["analysis"], output / "critic_fit",
                                  updates=100, learning_rate=.001, gradient_clip=5.)
    calibrated = output / "MODEL_CALIBRATED.pt"
    torch.save({"config": model.config, "state_dict": model.state_dict(),
                "metadata": {"source_checkpoint_sha256": protocol["checkpoint_sha256"],
                             "critic_fit_protocol": fitting["protocol"], "research_effect_qualified": False}}, calibrated)
    summary = {"protocol": protocol, "completed_groups": len(completed),
               "actual_continuations": sum(len(r["rows"]) for values in cohorts.values() for r in values),
               "comparisons": comparisons, "critic_fitting": fitting,
               "calibrated_checkpoint_sha256": hashlib.sha256(calibrated.read_bytes()).hexdigest(),
               "total_wall_seconds": time.perf_counter() - started, "research_effect_qualified": False,
               "semantic_qualification": False, "confirmation_sources_consumed": 0}
    _write_json(output / "STUDY_SUMMARY.json", summary)
    print(json.dumps({"completed_groups": len(completed), "actual_continuations": summary["actual_continuations"],
                      "output": str(output), "wall_seconds": summary["total_wall_seconds"]}), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.checkpoint, arguments.output)
