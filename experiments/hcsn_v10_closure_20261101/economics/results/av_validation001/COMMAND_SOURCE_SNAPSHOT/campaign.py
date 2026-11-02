"""Historical AV continuation models with jointly fitted latent renewal memory."""

import argparse
import copy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch
from torch import nn

from . import interfaces as base
from .history import AcceptedHistory, HistoryForecast, HistoryModel
from .models import Model

HERE = Path(__file__).parent
FAMILIES = ("direct", "gru", "ssm", "history", "renewal", "mean", "single")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def sources():
    return {p.name: sha(p) for p in sorted(HERE.glob("*.py"))}


def configure_assets(output):
    from experiments.hcsn_v8_execution_20261101.frontend import legacy_v3, replay
    legacy_v3.RECOVERED = output / "assets"
    replay.DATA = output / "assets/data"


def prepare(output, bundle):
    output.mkdir(parents=True, exist_ok=False)
    assets = output / "assets"
    (assets / "data").mkdir(parents=True)
    from experiments.hcsn_v8_execution_20261101.frontend.replay import DATA
    from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import restored_checkpoint
    for name in ("train.npz", "validation.npz", "test.npz"):
        shutil.copyfile(DATA / name, assets / "data" / name)
    for task in ("async_av", "av_binding"):
        dest = output / task
        dest.mkdir()
        source = bundle / "experiments/hcsn_v9_followup_20261101/persistent_av/results002" / task
        for name in ("training.npz", "validation.npz", "INPUTS.json"):
            shutil.copyfile(source / name, dest / name)
        checkpoint = assets / "experiments/hcsn_causal_execution_v3/results/av_probe" / task / "selected_encoder.npz"
        checkpoint.parent.mkdir(parents=True)
        shutil.copyfile(restored_checkpoint(task), checkpoint)
    files = [p for p in output.rglob("*") if p.is_file()]
    write(output / "PLAN.json", {
        "schema": "hcsn-v10-historical-AV-latent-renewal.v1", "source_sha256": sources(),
        "input_sha256": {str(p.relative_to(output)): sha(p) for p in files},
        "fit_seeds": [101001, 101003, 101009, 101021, 101033], "families": FAMILIES,
        "tasks": ["async_av", "av_binding"], "max_epochs": 200, "minimum_epochs": 50,
        "patience": 35, "learning_rate": .003, "weight_decay": .001,
        "selection": "Minimum historical-validation masked BCE; ordinary family selected before evaluation",
        "ordinary_pool": ["direct", "gru", "ssm", "history"],
        "primary": "Descriptive D-B utility on previously exposed historical recordings, common head/control",
        "controls": ["common_full fixed acquisition", "common task-value control"],
        "latent_law": "Input-local Brownian first-passage/reset count mixture rotating signed content pairs, coefficients from previous state; accepted packet then assimilated",
        "joint_training": "Physics encoder, content drive/gain, phase angles and continuation-correctness readout trained together",
        "target": "Actual correctness of the same frozen historical content head at each legal future cache endpoint, not a teacher posterior or latent-media truth",
        "test_role": "All historical splits/actors were exposed before; no fresh confirmation",
        "count_ablations": "Mean-preserving two-point and one-transition, each independently retrained; also full-weight execution ablation",
        "raw_history_capacity": "Six accepted 41-scalar records plus six masks; 32-byte identity digest is not neural state",
        "limitations": ["weak old v3 head", "not v6", "not an identified physical AV law", "no new recordings", "fixed content encoder/head", "logical source/service clock", "no strongest-family qualification", "no production adoption"],
        "scientific_confirmation": False, "all_blockers_closed": False, "torch": torch.__version__})
    print(json.dumps({"prepared": str(output), "inputs": len(files)}), flush=True)


def plan_at(output):
    plan = json.loads((output / "PLAN.json").read_text())
    if plan["source_sha256"] != sources():
        raise RuntimeError("Candidate source changed after freeze")
    for name, digest in plan["input_sha256"].items():
        if sha(output / name) != digest:
            raise RuntimeError("Input changed: " + name)
    return plan


def arrays(path):
    with np.load(path, allow_pickle=False) as data:
        return tuple(torch.tensor(data[k], dtype=torch.float64) for k in ("x", "y", "mask"))


def construct(family, tx):
    if family == "history":
        model = HistoryModel()
        model.family = "history"
        return model
    return Model(family, tx.mean((0, 1)), tx.std((0, 1)).clamp(min=.1))


def loss(model, data):
    x, y, mask = data
    errors = nn.functional.binary_cross_entropy_with_logits(model(x), y, reduction="none")
    return (errors * mask).sum() / mask.sum()


def train(output):
    plan = plan_at(output)
    reports = {}
    for task in plan["tasks"]:
        dest = output / task / "fits"
        dest.mkdir()
        training = arrays(output / task / "training.npz")
        validation = arrays(output / task / "validation.npz")
        reports[task] = {}
        for seed in plan["fit_seeds"]:
            reports[task][str(seed)] = {}
            for family in plan["families"]:
                torch.manual_seed(seed)
                model = construct(family, training[0])
                initial = copy.deepcopy(model.state_dict())
                optimizer = torch.optim.AdamW(model.parameters(), lr=plan["learning_rate"],
                                               weight_decay=plan["weight_decay"])
                best, selected, weights, history = float("inf"), 0, None, []
                start_cpu, start_wall = time.process_time(), time.monotonic()
                for epoch in range(plan["max_epochs"] + 1):
                    if epoch:
                        optimizer.zero_grad(set_to_none=True)
                        objective = loss(model, training)
                        objective.backward()
                        nn.utils.clip_grad_norm_(model.parameters(), 5)
                        optimizer.step()
                    with torch.no_grad():
                        score = float(loss(model, validation))
                    if not np.isfinite(score):
                        raise ArithmeticError("Nonfinite validation loss")
                    history.append(score)
                    if score < best - 1e-8:
                        best, selected, weights = score, epoch, copy.deepcopy(model.state_dict())
                    if epoch >= plan["minimum_epochs"] and epoch - selected >= plan["patience"]:
                        break
                torch.save(model.state_dict(), dest / f"{family}-{seed}-final.pt")
                model.load_state_dict(weights)
                checkpoint = dest / f"{family}-{seed}-selected.pt"
                torch.save(weights, checkpoint)
                changes = {k: float((v - initial[k]).abs().max()) for k, v in weights.items()}
                report = {"validation_bce": best, "selected_epoch": selected,
                    "last_epoch": epoch, "max_budget_reached": epoch == plan["max_epochs"],
                    "history": history, "parameters": sum(p.numel() for p in model.parameters()),
                    "checkpoint_sha256": sha(checkpoint), "maximum_parameter_change": changes,
                    "fit_cpu_seconds_nested": time.process_time() - start_cpu,
                    "fit_wall_seconds_nested": time.monotonic() - start_wall}
                write(dest / f"{family}-{seed}-fit.json", report)
                reports[task][str(seed)][family] = report
                print(json.dumps({"task": task, "seed": seed, "family": family,
                    "bce": best, "selected_epoch": selected}), flush=True)
    write(output / "FIT.json", reports)
    selected = {t: {str(s): min(plan["ordinary_pool"], key=lambda f: (
        reports[t][str(s)][f]["validation_bce"], f)) for s in plan["fit_seeds"]} for t in plan["tasks"]}
    write(output / "FROZEN_MODELS.json", {"plan_sha256": sha(output / "PLAN.json"),
        "fit_sha256": sha(output / "FIT.json"), "selection": selected,
        "before_historical_evaluation": True, "fresh_confirmation": False})


def evaluate(output):
    plan = plan_at(output)
    configure_assets(output)
    fits = json.loads((output / "FIT.json").read_text())
    frozen = json.loads((output / "FROZEN_MODELS.json").read_text())
    if frozen["fit_sha256"] != sha(output / "FIT.json"):
        raise RuntimeError("Fit reports changed after freeze")
    runs = []
    with gzip.open(output / "TRACES.jsonl.gz", "xt") as raw:
        for task in plan["tasks"]:
            head, _, _ = base.fit_development_adapters(task, base.legacy_data(task, "val"), output / task)
            data = base.legacy_data(task, "test")
            labels = base.labels_of(data)
            training_x = arrays(output / task / "training.npz")[0]
            write(output / task / "HISTORICAL_INPUTS.json", base.data_identity(data))
            for seed in plan["fit_seeds"]:
                for family in (*plan["families"], "same_weight_mean", "same_weight_single"):
                    fitted_family = "renewal" if family.startswith("same_weight_") else family
                    model = construct(fitted_family, training_x)
                    path = output / task / "fits" / f"{fitted_family}-{seed}-selected.pt"
                    if sha(path) != fits[task][str(seed)][fitted_family]["checkpoint_sha256"]:
                        raise RuntimeError("Checkpoint identity changed")
                    model.load_state_dict(torch.load(path, weights_only=True))
                    model.eval()
                    if family.startswith("same_weight_"):
                        model.mode = family.removeprefix("same_weight_")
                    for i, label in enumerate(labels):
                        for policy in ("fixed", "value"):
                            object_id = f"v10-{task}-{seed}-{family}-{i}-{policy}"
                            model_id = hashlib.sha256((sha(path) + family).encode()).hexdigest()[:32]
                            if family == "history":
                                core = AcceptedHistory(head, model_id)
                                forecast = HistoryForecast(model, head, core, model_id)
                            else:
                                core = None if family == "direct" else base.PersistentCore(model, head, model_id)
                                forecast = base.Forecast(model, head, model_id)
                            result = base.run_episode(object_id, base.CacheBudget(65536), head, forecast,
                                base.FixedServiceModel(), base.PreparedPrefixService(*base.episode_arrays(data, i), object_id),
                                lambda _: None, clock=base.LogicalClock(), core=core,
                                horizon=6 if policy == "fixed" else 2,
                                fixed_plans=base.fixed_plans("common_full") if policy == "fixed" else None)
                            correct = int(result["output"]["predicted_class"] == int(label))
                            row = {"task": task, "seed": seed, "family": family, "policy": policy,
                                "index": i, "source_id": str(data["ids"][i]), "actor": str(data["group_ids"][i]),
                                "label": int(label), "correct": correct, "requests": result["requested_observations"],
                                "utility": correct - result["observation_fee"] - result["latency_fee"] - result["deadline_penalty"]}
                            if any(e.get("status") in ("failed", "rejected", "timed_out") for e in result["events"]):
                                raise RuntimeError("Historical acceptance failed")
                            runs.append(row)
                            raw.write(json.dumps({**row, "execution": result,
                                "updates": [] if core is None else (core.events if family == "history" else core.updates)}) + "\n")
    write(output / "SCORES.json", {"rows": runs, "frozen_selection": frozen["selection"],
        "raw_sha256": sha(output / "TRACES.jsonl.gz")})
    report = {"scope": "Previously exposed historical v3 AV continuation prediction; newly defined latent input-local renewal inductive bias", "runs": len(runs), "tasks": {}, "fresh_confirmation": False,
        "content_head_jointly_trained": False, "identified_AV_physical_law": False,
        "strongest_ordinary_qualified": False, "production_acceptance": False}
    for task in plan["tasks"]:
        stats = {}
        for seed in plan["fit_seeds"]:
            ordinary = frozen["selection"][task][str(seed)]
            means = {arm: float(np.mean([r["utility"] for r in runs if r["task"] == task and r["seed"] == seed and r["family"] == family and r["policy"] == policy]))
                for arm, family, policy in (("A", ordinary, "fixed"), ("B", ordinary, "value"),
                    ("C", "renewal", "fixed"), ("D", "renewal", "value"), ("H", "history", "value"))}
            stats[str(seed)] = {"ordinary": ordinary, "means": means,
                "D-B": means["D"] - means["B"], "B-A": means["B"] - means["A"],
                "D-C": means["D"] - means["C"], "C-A": means["C"] - means["A"],
                "interaction": means["D"] - means["C"] - means["B"] + means["A"], "D-H": means["D"] - means["H"]}
        report["tasks"][task] = {"fits": stats, "D_minus_B_descriptive_mean": float(np.mean([r["D-B"] for r in stats.values()])),
            "recording_ids": sorted({r["source_id"] for r in runs if r["task"] == task}),
            "actor_groups": sorted({r["actor"] for r in runs if r["task"] == task})}
    write(output / "SUMMARY.json", report)
    print(json.dumps({"runs": len(runs), "D_minus_B": {t: v["D_minus_B_descriptive_mean"] for t, v in report["tasks"].items()}}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.command == "prepare":
        prepare(args.output, args.bundle)
    elif args.command == "train":
        train(args.output)
    else:
        evaluate(args.output)


if __name__ == "__main__":
    main()
