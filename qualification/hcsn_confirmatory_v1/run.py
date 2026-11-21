"""Stage A: frozen features, common readout mask, fresh data, sealed final use."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import time

from .tasks import TASKS, digest, generate
from .semantic_program import shared_encoder_prior, write_readout
from .environment import execution_identity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METHODS = ("direct", "local_bp", "semantic_program", "program_then_bp")
DEPENDENCIES = ("hcsn_prepared/model.py", "hcsn_scale/model.py",
                "hcsn_adaptive/batched_flow.py", "hcsn_adaptive/finite_control.py",
                "hcsn_adaptive/impulse_execution.py", "hcsn_adaptive/budget.py",
                "hcsn_training/population_generator.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)


def sources():
    files = list(HERE.glob("*.py")) + list(HERE.glob("*.md"))
    files += [ROOT / "qualification" / p for p in DEPENDENCIES]
    for path in list(files):
        for parent in path.parents:
            if parent == ROOT:
                break
            init = parent / "__init__.py"
            if init.is_file():
                files.append(init)
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(files))}


def runtime():
    return {"python": platform.python_version(),
            **{name: importlib.metadata.version(name) for name in ("numpy", "torch")}}


def finish(path, result, ledger):
    result["cost_snapshot_scope"] = "before primary receipt serialization; see cost sidecar"
    save(path, result)
    with ledger.operation("checkpoint", mandatory=True):
        pass
    cost = ledger.snapshot()
    cost["scope"] = "through primary receipt and checkpoint; sidecar/stdout/exit require outer process meter"
    save(path.with_suffix(".cost.json"), cost)
    print(json.dumps({"artifact_sha256": sha(path), "cost": cost}, sort_keys=True))


def freeze(path, namespace, seeds):
    if not namespace.startswith("hcsn-confirmatory-v1/") or len(namespace) < 40:
        raise ValueError("root must allocate a fresh, long confirmatory namespace")
    if not 1 <= len(seeds) <= 5 or len(set(seeds)) != len(seeds) or min(seeds) < 0:
        raise ValueError("one to five distinct nonnegative paired seeds required")
    save(path, {"schema": "hepta.hcsn-confirmatory.v1", "stage": "readout_only",
                "source_base": "602e2db1ed9cbf6d10b120973b021c2733995b10",
                "namespace": namespace, "seeds": seeds, "sources": sources(), "runtime": runtime(),
                "execution": execution_identity(),
                "tasks": list(TASKS), "methods": list(METHODS), "train": 48, "dev": 24,
                "final": 48, "length": 12, "steps": 64, "learning_rate": .02, "ridge": .001,
                "budget": {"wall_seconds": 180, "training_examples": 1000000,
                           "encoder_events": 1000000, "forward_examples": 1000000,
                           "backward_examples": 1000000, "development_queries": 160,
                           "proposals": 160},
                "discovery_cost": {"assistant_tokens": None, "api_cost": None,
                                   "design_wall_seconds": None, "meaning": "unknown, not zero"}})


def verify(path):
    cfg = json.loads(Path(path).read_text())
    if (cfg["schema"] != "hepta.hcsn-confirmatory.v1" or cfg["stage"] != "readout_only"
            or cfg["sources"] != sources() or cfg["runtime"] != runtime()
            or cfg["execution"] != execution_identity()
            or cfg["tasks"] != list(TASKS) or cfg["methods"] != list(METHODS)):
        raise ValueError("source, protocol, runtime or stage differs from frozen identity")
    return cfg


def encoder(task):
    from qualification.hcsn_prepared.model import PreparedSequenceModel
    from qualification.hcsn_scale.model import ModelConfig
    model = PreparedSequenceModel(ModelConfig("hcsn", 4, 4, .1))
    shared_encoder_prior(model, task)
    return model.eval().requires_grad_(False)


def features(model, data, *, grad=False):
    import torch
    x, dt = torch.from_numpy(data["x"]), torch.from_numpy(data["dt"])
    with torch.set_grad_enabled(grad):
        values = model.encode_batch(x, dt)
        means = values.mean(1)
        extra = torch.stack(((values[:, :, 0] / dt).mean(1), x[:, -1, 3] * means[:, 2]), 1)
        result = torch.cat((values[:, -1], means, extra), 1)
    names = [f"{pool}.{name}" for pool in ("last", "mean") for name in model.encoder.feature_names]
    return result, names + ["mean.event_rate", "query.mean.content_1"]


def candidate(task, names, x, y, mean, scale, method, cfg):
    import torch
    from torch import nn
    model = nn.Linear(x.shape[1], 1, dtype=torch.float64)
    with torch.no_grad():
        model.weight.zero_()
        model.bias.zero_()
        if method in ("semantic_program", "program_then_bp"):
            weights, bias = write_readout(task, names)
            w = torch.tensor(weights, dtype=x.dtype)
            model.weight.copy_((w * scale)[None])
            model.bias.fill_(bias + float(w @ mean))
        if method == "direct":
            design = torch.cat((x, torch.ones_like(x[:, :1])), 1)
            penalty = torch.eye(design.shape[1], dtype=x.dtype) * cfg["ridge"]
            penalty[-1, -1] = 0
            solution = torch.linalg.solve(design.T @ design + penalty, design.T @ y)
            model.weight.copy_(solution[:-1].T)
            model.bias.copy_(solution[-1])
    if method in ("local_bp", "program_then_bp"):
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg["learning_rate"])
        for _ in range(cfg["steps"]):
            optimizer.zero_grad(set_to_none=True)
            loss = (model(x) - y).square().mean() + cfg["ridge"] / len(x) * model.weight.square().sum()
            loss.backward()
            if not all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
                raise FloatingPointError("missing/nonfinite readout gradient")
            optimizer.step()
    if not all(bool(torch.isfinite(p).all()) for p in model.parameters()):
        raise FloatingPointError("nonfinite candidate")
    return model


def execute(manifest, output, phase, selection_sha):
    started = time.perf_counter()
    cfg, identity = verify(manifest), sha(manifest)
    import numpy as np
    import torch
    from qualification.hcsn_adaptive.budget import Budget, CostLedger
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
        save(output / "admission.json", {"manifest_sha256": identity, "config": cfg})
        (output / "semantic_program.py").write_bytes((HERE / "semantic_program.py").read_bytes())
        selected = {}
    else:
        if (json.loads((output / "admission.json").read_text())["manifest_sha256"] != identity
                or not selection_sha or sha(output / "selection.json") != selection_sha):
            raise ValueError("final requires exact external selection digest and original manifest")
        with (output / "FINAL_CONSUMED").open("x") as handle:
            handle.write(selection_sha)
        selected = json.loads((output / "selection.json").read_text())["cases"]
    ledger = CostLedger(output / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    results = []
    for task in TASKS:
        for seed in cfg["seeds"]:
            key = f"{task}/{seed}"
            try:
                with ledger.operation("encoder_construction"):
                    model = encoder(task)
                if phase == "fit":
                    with ledger.operation("fresh_train_dev_and_features",
                                          encoder_events=(cfg["train"] + cfg["dev"]) * cfg["length"]):
                        train = generate(cfg["namespace"], seed, task, "train", cfg["train"], cfg["length"])
                        dev = generate(cfg["namespace"], seed, task, "dev", cfg["dev"], cfg["length"])
                        before = time.perf_counter()
                        tx, names = features(model, train)
                        dx, _ = features(model, dev)
                        feature_seconds = time.perf_counter() - before
                        mean, scale = tx.mean(0), tx.std(0, unbiased=False).clamp_min(1e-8)
                        tx, dx = (tx - mean) / scale, (dx - mean) / scale
                        ty, dy = torch.from_numpy(train["y"]), torch.from_numpy(dev["y"])
                    record = {"train_sha256": digest(train), "dev_sha256": digest(dev),
                              "feature_seconds": feature_seconds, "feature_names": names,
                              "mean": mean.tolist(), "scale": scale.tolist(), "methods": {},
                              "frozen_parameters": sum(p.numel() for p in model.parameters()),
                              "eligible_mask": ["readout.weight", "readout.bias"],
                              "eligible_parameters": tx.shape[1] + 1}
                    for method in METHODS:
                        arm_start = time.perf_counter()
                        try:
                            steps = cfg["steps"] if method in ("local_bp", "program_then_bp") else 0
                            reads = cfg["train"] * (steps if steps else int(method == "direct"))
                            with ledger.operation(method, proposals=1, training_examples=reads,
                                                  forward_examples=steps * len(tx), backward_examples=steps * len(tx)):
                                fitted = candidate(task, names, tx, ty, mean, scale, method, cfg)
                            with ledger.operation("development_selection", development_queries=2,
                                                  forward_examples=2 * len(dx)), torch.no_grad():
                                score, baseline = float((fitted(dx) - dy).square().mean()), float(dy.square().mean())
                                accept = score < baseline
                                record["methods"][method] = {
                                    "status": "selected" if accept else "no_update", "dev_mse": score,
                                    "zero_dev_mse": baseline,
                                    "weight": fitted.weight[0].tolist() if accept else [0.] * tx.shape[1],
                                    "bias": float(fitted.bias[0]) if accept else 0.,
                                    "adaptation_wall_seconds": time.perf_counter() - arm_start,
                                    "standalone_wall_lower_bound": feature_seconds + time.perf_counter() - arm_start}
                        except Exception as error:
                            record["methods"][method] = {"status": "failed", "error": repr(error)}
                    selected[key] = record
                else:
                    record = selected.get(key, {})
                    if "methods" not in record:
                        results.append({"case": key, "status": "no_fitted_case", "fit_record": record})
                        continue
                    for split in ("final_iid", "final_clock"):
                        with ledger.operation("fresh_final_features", encoder_events=cfg["final"] * cfg["length"]):
                            data = generate(cfg["namespace"], seed, task, split, cfg["final"], cfg["length"])
                            x, _ = features(model, data)
                            x = (x - torch.tensor(record["mean"], dtype=x.dtype)) / torch.tensor(record["scale"], dtype=x.dtype)
                        for method, arm in record["methods"].items():
                            if arm["status"] == "failed":
                                results.append({"case": key, "split": split, "method": method, **arm})
                                continue
                            with ledger.operation("final_evaluation", forward_examples=len(x)):
                                prediction = x @ torch.tensor(arm["weight"], dtype=x.dtype) + arm["bias"]
                                losses = (prediction.numpy() - data["y"][:, 0])**2
                                results.append({"case": key, "split": split, "method": method,
                                                "status": arm["status"], "data_sha256": digest(data),
                                                "mse": float(losses.mean()), "sample_squared_errors": losses.tolist(),
                                                "prediction": prediction.tolist(), "target": data["y"][:, 0].tolist(),
                                                "ids": data["ids"].tolist()})
            except Exception as error:
                failure = {"case": key, "status": "failed", "error": repr(error)}
                if phase == "fit":
                    selected[key] = failure
                else:
                    results.append(failure)
    result = {"manifest_sha256": identity, "phase": phase, "cost": ledger.snapshot(),
              "discovery_cost": cfg["discovery_cost"], "claims": "readout-only mechanism pilot; no superiority test"}
    result["cases" if phase == "fit" else "results"] = selected if phase == "fit" else results
    finish(output / ("selection.json" if phase == "fit" else "final.json"), result, ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "fit", "final"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--namespace")
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--selection-sha256")
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze(args.manifest, args.namespace or "", args.seeds or [])
    elif not args.output:
        parser.error("--output required")
    else:
        execute(args.manifest, args.output, args.phase, args.selection_sha256)


if __name__ == "__main__":
    main()

