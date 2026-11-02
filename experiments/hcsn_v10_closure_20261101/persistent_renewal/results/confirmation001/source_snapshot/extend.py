"""Validation-only extension of three named exhausted SSM candidates.

No base test metrics or raw test outputs are opened by this module.
"""

import argparse
import copy
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .campaign import nll, read_plan, sha, source_hashes, write
from .models import Model


CANDIDATES = [(100107, "ssm", 16), (100113, "ssm", 16), (100113, "ssm", 32)]
HERE = Path(__file__).parent


def prepare(base, output):
    plan, _ = read_plan(base)
    fit = json.loads((base / "FIT.json").read_text())
    exhausted = sorted((int(seed), family, c["width"]) for seed, report in fit.items()
        for family, item in report["families"].items() for c in item["candidates"] if c["budget_exhausted"])
    if exhausted != CANDIDATES:
        raise ValueError("Only the three predeclared validation-exhausted candidates may extend")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base / "source_snapshot", output / "source_snapshot")
    shutil.copy2(HERE / "extend.py", output / "source_snapshot/extend.py")
    write(output / "EXTENSION_PLAN.json", {"schema": "hcsn-v10-validation-only-extension.v1",
        "base_directory": str(base.resolve()), "base_plan_sha256": sha(base / "PLAN.json"),
        "base_fit_sha256": sha(base / "FIT.json"), "base_frozen_models_sha256": sha(base / "FROZEN_MODELS.json"),
        "extension_source_sha256": sha(HERE / "extend.py"), "original_sources": source_hashes(),
        "candidates": CANDIDATES, "initial_max_epochs": 320, "extended_max_epochs": 960,
        "selection_trigger": "Only validation-budget exhaustion, frozen candidate names; never base test results",
        "base_test_status_at_instruction": "Economics agent already launched base evaluate; core owner has not opened its test summary or raw metrics",
        "test_access_by_other_agents": "Not assumed absent; this procedure never reads base evaluation files and its rule is fixed by exhausted validation candidates",
        "restart_rule": "Same initialization, data bytes, minibatch seeds and Adam; verify all first321 validation values and best weights at epoch320 exactly, then continue",
        "patience": plan["training"]["patience"], "min_delta": plan["training"]["min_delta"],
        "new_world_namespace": [20261101, 101993],
        "confirmation_rule": "After validation-only selection freezes, evaluate full 2x2 and both no-core references on fresh independent holdout namespace; retain all base results",
        "cost_rule": "Inherited base fit costs charged in their original stage; all repeated prefix work and extension cost charged anew in this stage",
        "real_AV_confirmation": False, "strong_ordinary_qualification": False})
    plan["world_namespace"] = [20261101, 101993]
    plan["training"]["max_epochs"] = 960
    plan["extension_only_candidates"] = CANDIDATES
    plan["extension_plan_sha256"] = sha(output / "EXTENSION_PLAN.json")
    plan["source_sha256"] = source_hashes()
    plan["created_unix"] = time.time()
    write(output / "PLAN.json", plan)
    print(json.dumps({"plan_sha256": sha(output / "PLAN.json"), "candidates": CANDIDATES}), flush=True)


def train(output):
    plan, _ = read_plan(output)
    extension = json.loads((output / "EXTENSION_PLAN.json").read_text())
    if sha(HERE / "extend.py") != extension["extension_source_sha256"]:
        raise ValueError("Extension source changed")
    base = Path(extension["base_directory"])
    if sha(base / "FIT.json") != extension["base_fit_sha256"] or sha(base / "FROZEN_MODELS.json") != extension["base_frozen_models_sha256"]:
        raise ValueError("Base fit changed")
    report = json.loads((base / "FIT.json").read_text())
    shutil.copytree(base / "fits", output / "fits")
    receipts = []
    for seed, family, width in CANDIDATES:
        began_cpu, began_wall = time.process_time(), time.perf_counter()
        family_report = report[str(seed)]["families"][family]
        parent = next(c for c in family_report["candidates"] if c["width"] == width)
        data = np.load(base / "fits" / f"data_{seed}.npz")
        x, y, vx, vy = (data[name] for name in ("train_x", "train_y", "validation_x", "validation_y"))
        model = Model(family, seed, width)
        first, second = ({k: np.zeros_like(v) for k, v in model.p.items()} for _ in range(2))
        history, best, significant_best, significant_epoch, best_epoch, step = [], float("inf"), float("inf"), 0, 0, 0
        weights, stopped, verified = copy.deepcopy(model.p), False, False
        for epoch in range(extension["extended_max_epochs"] + 1):
            if epoch:
                order = np.random.default_rng(np.random.SeedSequence([seed, epoch - 1, 711])).permutation(len(x))
                for indices in np.array_split(order, len(x) // plan["training"]["batch_size"]):
                    _, gradient = model.loss_grad(x[indices], y[indices])
                    norm = np.sqrt(sum(np.sum(g * g) for g in gradient.values()))
                    step += 1
                    for key, value in gradient.items():
                        g = value * min(1, 5 / max(norm, 1e-12))
                        first[key] = .9 * first[key] + .1 * g
                        second[key] = .999 * second[key] + .001 * g * g
                        model.p[key] -= plan["training"]["learning_rate"] * (first[key] / (1 - .9 ** step)) / (np.sqrt(second[key] / (1 - .999 ** step)) + 1e-8)
            score = nll(model.sequence(vx), vy); history.append(score)
            if score < best:
                best, best_epoch, weights = score, epoch, copy.deepcopy(model.p)
            if score < significant_best - plan["training"]["min_delta"]:
                significant_best, significant_epoch = score, epoch
            if epoch <= extension["initial_max_epochs"] and score != parent["validation_nll_history"][epoch]:
                raise AssertionError(f"Prefix trajectory changed at epoch {epoch}")
            if epoch == extension["initial_max_epochs"]:
                original = np.load(base / "fits" / f"{family}_{seed}_w{width}.npz")
                if any(not np.array_equal(weights[key], original[key]) for key in weights):
                    raise AssertionError("Epoch320 best weights changed")
                verified = True
            if epoch >= plan["training"]["min_epochs"] and epoch - significant_epoch >= plan["training"]["patience"]:
                stopped = True; break
        if not verified:
            raise AssertionError("Extended candidate did not verify its prefix")
        model.p = weights
        path = output / "fits" / f"{family}_{seed}_w{width}.npz"
        np.savez_compressed(path, **weights)
        item = {**parent, "validation_nll": best, "selected_epoch": best_epoch,
            "epochs_completed": len(history) - 1, "validation_plateau_stop": stopped,
            "budget_exhausted": not stopped, "validation_nll_history": history,
            "checkpoint_sha256": sha(path), "fit_cpu_seconds": time.process_time() - began_cpu,
            "fit_wall_seconds": time.perf_counter() - began_wall,
            "parent_fit_cpu_seconds_charged_before": parent["fit_cpu_seconds"],
            "repeated_epoch0_to320_validation_exact": True, "repeated_epoch320_best_weights_exact": True,
            "fit_scope": "Fresh restart including full repeated prefix and extension, cost charged once anew"}
        family_report["candidates"] = [item if c["width"] == width else c for c in family_report["candidates"]]
        receipts.append({"seed": seed, **item})
        print(json.dumps({"seed": seed, **{k: item[k] for k in ("family", "width", "validation_nll", "epochs_completed", "validation_plateau_stop", "fit_cpu_seconds")}}), flush=True)
    for seed, seed_report in report.items():
        for family, family_report in seed_report["families"].items():
            selected = min(family_report["candidates"], key=lambda c: (c["validation_nll"], c["width"]))
            family_report["selected_width"], family_report["validation_nll"] = selected["width"], selected["validation_nll"]
        seed_report["selected_ordinary_family"] = min(plan["ordinary_core_families"], key=lambda f: (seed_report["families"][f]["validation_nll"], f))
        # Copied original per-seed report is kept under its original identity.
        write(output / "fits" / f"EXTENDED_FIT_{seed}.json", seed_report)
    write(output / "FIT.json", report)
    write(output / "EXTENSION_RESULTS.json", {"candidates": receipts, "base_test_files_opened": False,
        "all_candidates_validation_plateau": all(c["validation_plateau_stop"] for s in report.values() for f in s["families"].values() for c in f["candidates"])})
    write(output / "FROZEN_MODELS.json", {"plan_sha256": sha(output / "PLAN.json"), "fit_sha256": sha(output / "FIT.json"),
        "before_test_world_generation": True, "checkpoints": {str(p.relative_to(output)): sha(p) for p in (output / "fits").glob("*_w*.npz")},
        "selection": {str(s): {"ordinary_family": report[str(s)]["selected_ordinary_family"],
            "widths": {f: report[str(s)]["families"][f]["selected_width"] for f in plan["families"]}} for s in plan["fit_seeds"]}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path)
    args = parser.parse_args()
    cpu, wall = time.process_time(), time.perf_counter()
    prepare(args.base, args.output) if args.command == "prepare" else train(args.output)
    write(args.output / f"EXTENSION_{args.command.upper()}_RUNTIME.json", {"inclusive_cpu_seconds": time.process_time() - cpu,
        "inclusive_wall_seconds": time.perf_counter() - wall, "nested_diagnostics_not_added": True, "energy_joules": None})


if __name__ == "__main__":
    main()
