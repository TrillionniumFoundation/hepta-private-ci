# Pre-execution correction: no clipped-log objective is used.
# train_nll.py and the first unexecuted registration remain preserved.
"""A fixed bounded repair using proper log scoring on old inputs only."""

import argparse
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import resource
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...v6.neural import parameter_hash
from .data import old_feature_table
from .model import FrozenPortfolio, pair_law
from .nll_model import LogScoreAdapter
from .train import measure


def calibration(q, targets):
    confidence, predicted = q.max(-1)
    correctness = (predicted == targets).double()
    bins = []
    for lower, upper in zip((0., .5, .8, .95), (.5, .8, .95, 1.000001)):
        mask = (confidence >= lower) & (confidence < upper)
        if mask.any():
            bins.append({"lower": lower, "upper": upper, "count": int(mask.sum()),
                         "confidence": float(confidence[mask].mean()), "correctness": float(correctness[mask].mean())})
    ece = sum(row["count"] * abs(row["confidence"] - row["correctness"]) for row in bins) / len(q)
    observed = torch.nn.functional.one_hot(targets, 100).double()
    return {"selected_correctness_ECE": ece, "bins": bins,
            "full_posterior_Brier": float((q.double() - observed).square().sum(-1).mean()),
            "categorical_NLL": float(-q.gather(1, targets[:, None]).log().mean()),
            "scope": "Old development descriptive diagnostics; not independent qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "endpoints", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.protocol.read_text())
    for path, expected in spec["source_pins"].items():
        if file_sha(Path(path)) != expected:
            raise ValueError("Registered repair source changed")
    if file_sha(args.config) != spec["config_sha256"] or file_sha(args.endpoints) != spec["endpoint_sha256"]:
        raise ValueError("Repair config or endpoint identity changed")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    settings, endpoint = json.loads(args.config.read_text()), json.loads(args.endpoints.read_text())
    portfolio = FrozenPortfolio(settings["renderer_paths"])
    if portfolio.parameter_sha256 != endpoint["renderer_parameter_sha256"]:
        raise ValueError("Repair renderer differs from actual return table")
    train, _ = old_feature_table(portfolio, settings, "train", spec["train_pairs"], 240401, args.output / "fit-features")
    held, _ = old_feature_table(portfolio, settings, "development", spec["old_development_pairs"], 240503, args.output / "old-development-features")
    utility = torch.tensor(endpoint["utility_action_by_target"], dtype=torch.float64)
    strict = torch.tensor(endpoint["strict_success_action_by_target"], dtype=torch.float64)
    reference = measure(None, held, utility, strict, "entropic")
    reference["calibration"] = calibration(pair_law(held["raw_probabilities"]), held["target_codes"])
    write_json(args.output / "CANONICAL_REFERENCE.json", reference)
    results = {}
    for seed in spec["seeds"]:
        torch.manual_seed(seed)
        initial = LogScoreAdapter(2.)
        for bound in spec["residual_bounds"]:
            directory = args.output / f"seed-{seed}" / f"bound-{int(bound)}"
            directory.mkdir(parents=True, exist_ok=False)
            adapter = deepcopy(initial)
            adapter.residual_bound = float(bound)
            initial_hash = parameter_hash(adapter)
            optimizer = torch.optim.Adam(adapter.parameters(), lr=spec["learning_rate"])
            rng = torch.Generator().manual_seed(seed * 240007)
            schedule, maximum = hashlib.sha256(), 0.
            with (directory / "PROGRESS.jsonl").open("x") as log:
                for step in range(spec["steps"]):
                    indices = torch.randint(len(train["features"]), (spec["batch"],), generator=rng)
                    p = adapter(train["features"][indices], train["raw_probabilities"][indices], train["text_mask"][indices])
                    q = pair_law(p)
                    nll = -q.gather(1, train["target_codes"][indices, None]).log().mean()
                    anchor = (p - train["raw_probabilities"][indices]).square().mean()
                    loss = nll + spec["posterior_anchor_weight"] * anchor
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    maximum = max(maximum, sum(float(p.grad.abs().sum()) for p in adapter.parameters() if p.grad is not None))
                    torch.nn.utils.clip_grad_norm_(adapter.parameters(), 5.)
                    optimizer.step()
                    schedule.update(indices.numpy().tobytes())
                    log.write(json.dumps({"step": step + 1, "NLL": float(nll.detach()), "anchor": float(anchor.detach())}) + "\n")
            adapter.eval().requires_grad_(False)
            final_hash = parameter_hash(adapter)
            if initial_hash == final_hash or maximum <= 0:
                raise ValueError("Actual repair learning did not update parameters")
            checkpoint = directory / "adapter.pt"
            torch.save({"schema": "hepta.advance.semantic-adapter-nll.v1", "state_dict": adapter.state_dict(),
                        "residual_bound": float(bound), "parameter_sha256": final_hash, "seed": seed,
                        "endpoint_sha256": spec["endpoint_sha256"], "renderer_parameter_sha256": portfolio.parameter_sha256}, checkpoint)
            adapter.export_native(endpoint, directory / "NATIVE.json")
            metrics = measure(adapter, held, utility, strict, "entropic")
            with torch.no_grad():
                q = pair_law(adapter(held["features"], held["raw_probabilities"], held["text_mask"]))
            metrics["calibration"] = calibration(q, held["target_codes"])
            row = {"seed": seed, "bound": bound, "initial_sha256": initial_hash, "final_sha256": final_hash,
                   "schedule_sha256": schedule.hexdigest(), "maximum_gradient_abs_sum": maximum,
                   "checkpoint": str(checkpoint), "checkpoint_sha256": file_sha(checkpoint),
                   "native_export": str(directory / "NATIVE.json"), "native_export_sha256": file_sha(directory / "NATIVE.json"),
                   "old_development": metrics}
            write_json(directory / "RESULT.json", row)
            results[f"{seed}/{int(bound)}"] = row
            print(json.dumps({"seed": seed, "bound": bound, "CE": metrics["CE"], "strict": metrics["strict_success"],
                              "ECE": metrics["calibration"]["selected_correctness_ECE"]}), flush=True)
            del adapter, optimizer
            gc.collect()
    panels = {str(int(bound)): {key: sum(results[f"{seed}/{int(bound)}"]["old_development"][key] for seed in spec["seeds"]) / len(spec["seeds"])
                               for key in ("CE", "mean_utility", "strict_success")} for bound in spec["residual_bounds"]}
    selected = max(panels, key=lambda key: (panels[key]["CE"], panels[key]["strict_success"], -int(key)))
    qualifies = (panels[selected]["CE"] >= reference["CE"] and panels[selected]["strict_success"] >= reference["strict_success"])
    native = results[f"17/{selected}"]
    native_eligible = qualifies and native["old_development"]["CE"] >= reference["CE"] and native["old_development"]["strict_success"] >= reference["strict_success"]
    portfolio.assert_frozen()
    if any(file_sha(Path(path)) != sha for path, sha in spec["source_pins"].items()):
        raise ValueError("Frozen repair source changed during execution")
    write_json(args.output / "RESULTS.json", {"status": "completed", "protocol_sha256": file_sha(args.protocol),
        "arms": results, "panels": panels, "selected_bound": int(selected) if qualifies else None,
        "learned_candidate_old_development_eligible": qualifies, "native_seed17_old_development_eligible": native_eligible,
        "selected_native_export": native["native_export"] if native_eligible else None,
        "reference": reference, "new_confirmation_sources_opened": False, "only_adapter_updated": True,
        "actual_updates_per_arm": spec["steps"], "all_frozen_components_unchanged": True,
        "wall_ns_main": time.perf_counter_ns() - start, "cpu_ns_main": time.process_time_ns() - cpu,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024})


if __name__ == "__main__":
    main()
