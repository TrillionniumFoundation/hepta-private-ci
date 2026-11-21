"""H1 pilot: incremental value/risk information against equal-width tanh controls.

Dynamics and every other feature are identical. All arms pay for the complete
flow AND tanh bank, so this experiment measures representation information, not
an inference speed gain. No label or residual is used to construct the controls.
"""

import argparse
import json
from pathlib import Path
import time

from .environment import execution_identity
from .run import candidate, encoder, features, finish, runtime, save, sha, sources
from .tasks import TASKS, digest, generate

METHODS = ("same_generator", "drop_value_risk", "ordinary_tanh")


def freeze(path, namespace, seeds):
    if (not namespace.startswith("hcsn-feature-confirmatory-v1/") or len(namespace) < 48
            or not 1 <= len(seeds) <= 3 or len(set(seeds)) != len(seeds) or min(seeds) < 0):
        raise ValueError("fresh root-assigned namespace and paired seeds required")
    save(path, {"schema": "hepta.hcsn-feature-confirmatory.v1", "namespace": namespace,
                "seeds": seeds, "sources": sources(), "runtime": runtime(),
                "execution": execution_identity(), "tasks": list(TASKS), "methods": list(METHODS),
                "train": 48, "dev": 24, "final": 48, "length": 12, "ridge": .001,
                "budget": {"wall_seconds": 180, "training_examples": 1000000,
                           "encoder_events": 1000000, "forward_examples": 1000000,
                           "backward_examples": 1000000, "development_queries": 100,
                           "proposals": 100},
                "claim_scope": "incremental readout information, not whole-network superiority"})


def verify(path):
    cfg = json.loads(Path(path).read_text())
    if (cfg["schema"] != "hepta.hcsn-feature-confirmatory.v1"
            or cfg["sources"] != sources() or cfg["runtime"] != runtime()
            or cfg["execution"] != execution_identity()
            or cfg["tasks"] != list(TASKS) or cfg["methods"] != list(METHODS)):
        raise ValueError("frozen feature-study source/protocol/runtime changed")
    return cfg


def banks(model, data):
    import torch
    common, names = features(model, data)
    columns = [names.index(f"{pool}.{name}") for pool in ("last", "mean") for name in ("call", "risk")]
    # Public, frozen projections with no fitting or label-driven search.
    projection = torch.tensor([[.7, -.4, .2, 0.], [.3, .6, 0., -.5]], dtype=common.dtype)
    plain = torch.tanh(torch.from_numpy(data["x"]) @ projection.T)
    replacement = torch.cat((plain[:, -1], plain.mean(1)), 1)
    dropped, ordinary = common.clone(), common.clone()
    dropped[:, columns] = 0
    ordinary[:, columns] = replacement
    return dict(zip(METHODS, (common, dropped, ordinary), strict=True)), names


def fit_case(task, seed, cfg, ledger):
    import torch
    start = time.perf_counter()
    with ledger.operation("common_complete_feature_banks",
                          encoder_events=(cfg["train"]+cfg["dev"]) * cfg["length"]):
        model = encoder(task)
        train = generate(cfg["namespace"], seed, task, "train", cfg["train"], cfg["length"])
        dev = generate(cfg["namespace"], seed, task, "dev", cfg["dev"], cfg["length"])
        training, names = banks(model, train)
        development, _ = banks(model, dev)
        ty, dy = torch.from_numpy(train["y"]), torch.from_numpy(dev["y"])
    shared_seconds = time.perf_counter() - start
    record = {"train_sha256": digest(train), "dev_sha256": digest(dev), "methods": {},
              "feature_names": names, "complete_feature_bank_seconds": shared_seconds,
              "replacement_column_mapping": {f"{pool}.{name}": f"{pool}.tanh_projection_{i}"
                                               for pool in ("last", "mean")
                                               for i, name in enumerate(("call", "risk"))},
              "eligible_mask": ["readout.weight", "readout.bias"],
              "eligible_parameters": len(names)+1, "encoder_frozen": True}
    for method in METHODS:
        arm_start = time.perf_counter()
        try:
            tx, dx = training[method], development[method]
            mean, scale = tx.mean(0), tx.std(0, unbiased=False).clamp_min(1e-8)
            tx, dx = (tx-mean)/scale, (dx-mean)/scale
            with ledger.operation("conditional_ridge", proposals=1, training_examples=len(tx)):
                fitted = candidate(task, names, tx, ty, mean, scale, "direct", cfg)
            with ledger.operation("development_selection", development_queries=2,
                                  forward_examples=2 * len(dx)), torch.no_grad():
                loss, baseline = float((fitted(dx)-dy).square().mean()), float(dy.square().mean())
                accept = loss < baseline
            record["methods"][method] = {
                "status": "selected" if accept else "no_update", "dev_mse": loss,
                "zero_dev_mse": baseline, "mean": mean.tolist(), "scale": scale.tolist(),
                "weight": fitted.weight[0].tolist() if accept else [0.] * len(names),
                "bias": float(fitted.bias[0]) if accept else 0.,
                "adaptation_wall_seconds": time.perf_counter()-arm_start,
                "standalone_wall_lower_bound": shared_seconds + time.perf_counter()-arm_start}
        except Exception as error:
            record["methods"][method] = {"status": "failed", "error": repr(error)}
    return record


def final_case(task, seed, cfg, record, ledger):
    import torch
    result = []
    with ledger.operation("encoder_construction"):
        model = encoder(task)
    for split in ("final_iid", "final_clock"):
        with ledger.operation("complete_final_feature_banks", encoder_events=cfg["final"] * cfg["length"]):
            data = generate(cfg["namespace"], seed, task, split, cfg["final"], cfg["length"])
            bank, _ = banks(model, data)
        for method in METHODS:
            arm = record["methods"][method]
            base = {"case": f"{task}/{seed}", "split": split, "method": method, "status": arm["status"]}
            if arm["status"] == "failed":
                result.append({**base, "error": arm["error"]})
                continue
            with ledger.operation("final_evaluation", forward_examples=len(data["x"])):
                x = bank[method]
                x = (x-torch.tensor(arm["mean"], dtype=x.dtype))/torch.tensor(arm["scale"], dtype=x.dtype)
                prediction = x @ torch.tensor(arm["weight"], dtype=x.dtype) + arm["bias"]
                losses = (prediction.numpy()-data["y"][:, 0])**2
                result.append({**base, "data_sha256": digest(data), "mse": float(losses.mean()),
                               "prediction": prediction.tolist(), "target": data["y"][:, 0].tolist(),
                               "sample_squared_errors": losses.tolist(), "ids": data["ids"].tolist()})
    return result


def execute(manifest, output, phase, selection_sha):
    started = time.perf_counter()
    cfg, identity = verify(manifest), sha(manifest)
    from qualification.hcsn_adaptive.budget import Budget, CostLedger
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
        save(output/"admission.json", {"manifest_sha256": identity, "config": cfg})
        selected = {}
    else:
        if (json.loads((output/"admission.json").read_text())["manifest_sha256"] != identity
                or not selection_sha or sha(output/"selection.json") != selection_sha):
            raise ValueError("final requires original manifest and externally bound selection SHA")
        with (output/"FINAL_CONSUMED").open("x") as handle:
            handle.write(selection_sha)
        selected = json.loads((output/"selection.json").read_text())["cases"]
    ledger = CostLedger(output/"cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    results = []
    for task in TASKS:
        for seed in cfg["seeds"]:
            key = f"{task}/{seed}"
            try:
                if phase == "fit":
                    selected[key] = fit_case(task, seed, cfg, ledger)
                elif "methods" in selected.get(key, {}):
                    results.extend(final_case(task, seed, cfg, selected[key], ledger))
                else:
                    results.append({"case": key, "status": "no_fitted_case", "fit_record": selected.get(key)})
            except Exception as error:
                failure = {"case": key, "status": "failed", "error": repr(error)}
                if phase == "fit":
                    selected[key] = failure
                else:
                    results.append(failure)
    result = {"manifest_sha256": identity, "phase": phase, "cost": ledger.snapshot(),
              "claim_scope": cfg["claim_scope"]}
    result["cases" if phase == "fit" else "results"] = selected if phase == "fit" else results
    finish(output/("selection.json" if phase == "fit" else "final.json"), result, ledger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "fit", "final"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--namespace")
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--selection-sha256")
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze(args.manifest, args.namespace or "", args.seeds or [])
    elif not args.output:
        parser.error("--output required")
    else:
        execute(args.manifest, args.output, args.phase, args.selection_sha256)
