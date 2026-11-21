"""Stage C: accurate named architectures on the same fresh mechanism tasks."""
import argparse
import copy
import importlib.metadata
import json
from pathlib import Path
import time

from .architectures import ArchitectureModel, KINDS, UnavailableBaseline, WIDTHS
from .environment import execution_identity
from .joint import restore, score, state, state_digest
from .run import candidate, finish, runtime, save, sha, sources
from .tasks import TASKS, digest, generate


def optional_ncps():
    try:
        distribution = importlib.metadata.distribution("ncps")
    except importlib.metadata.PackageNotFoundError:
        return {"status": "UNAVAILABLE", "reason": "official ncps distribution absent"}
    files = {str(p): sha(distribution.locate_file(p)) for p in (distribution.files or [])
             if str(p).startswith("ncps/") and str(p).endswith(".py")}
    if not files:
        raise ValueError("installed ncps has no verifiable Python source inventory")
    return {"status": "available", "version": distribution.version, "sources": files}


def freeze(path, namespace, seeds):
    if (not namespace.startswith("hcsn-architecture-confirmatory-v1/") or len(namespace) < 54
            or not 1 <= len(seeds) <= 3 or len(set(seeds)) != len(seeds) or min(seeds) < 0):
        raise ValueError("fresh architecture namespace and one to three paired seeds required")
    save(path, {"schema": "hepta.hcsn-architecture-confirmatory.v1", "namespace": namespace,
                "seeds": seeds, "sources": sources(), "runtime": runtime(),
                "execution": execution_identity(), "official_ncps": optional_ncps(),
                "tasks": list(TASKS), "architectures": list(KINDS), "widths": WIDTHS,
                "parameter_target": 280, "parameter_band": [238, 322], "train": 24,
                "dev": 12, "final": 24, "length": 8, "steps": 12,
                "learning_rate": .005, "ridge": .001,
                "budget": {"wall_seconds": 180, "training_examples": 1000000,
                           "encoder_events": 1000000, "forward_examples": 1000000,
                           "backward_examples": 1000000, "development_queries": 160,
                           "proposals": 160}})


def verify(path):
    cfg = json.loads(Path(path).read_text())
    if (cfg["schema"] != "hepta.hcsn-architecture-confirmatory.v1"
            or cfg["sources"] != sources() or cfg["runtime"] != runtime()
            or cfg["execution"] != execution_identity() or cfg["official_ncps"] != optional_ncps()
            or cfg["tasks"] != list(TASKS) or cfg["architectures"] != list(KINDS)
            or cfg["widths"] != WIDTHS):
        raise ValueError("architecture source/runtime/official dependency identity differs")
    return cfg


def fit_case(kind, task, seed, cfg, ledger):
    import torch
    with ledger.operation("construction_and_fresh_train_dev", proposals=1):
        torch.manual_seed(seed)
        model = ArchitectureModel(kind)
        train = generate(cfg["namespace"], seed, task, "train", cfg["train"], cfg["length"])
        dev = generate(cfg["namespace"], seed, task, "dev", cfg["dev"], cfg["length"])
    with ledger.operation("common_conditional_readout_fit", training_examples=len(train["x"]),
                          encoder_events=len(train["x"]) * cfg["length"]), torch.no_grad():
        tx = model.representations(train)
        model.mean.copy_(tx.mean(0))
        model.scale.copy_(tx.std(0, unbiased=False).clamp_min(1e-8))
        initial = candidate(task, [], (tx - model.mean) / model.scale, torch.from_numpy(train["y"]),
                            model.mean, model.scale, "direct", cfg)
        model.readout.load_state_dict(initial.state_dict())
    with ledger.operation("incumbent_development", development_queries=1,
                          encoder_events=len(dev["x"]) * cfg["length"], forward_examples=len(dev["x"])):
        baseline, _, _ = score(model, dev)
    base = state(model)
    with ledger.operation("bp_candidate", proposals=1):
        trial = copy.deepcopy(model)
        optimizer = torch.optim.Adam(trial.parameters(), lr=cfg["learning_rate"])
    for _ in range(cfg["steps"]):
        with ledger.operation("full_mask_bp_step", training_examples=len(train["x"]),
                              encoder_events=len(train["x"]) * cfg["length"],
                              forward_examples=len(train["x"]), backward_examples=len(train["x"])):
            optimizer.zero_grad(set_to_none=True)
            loss = (trial(train) - torch.from_numpy(train["y"])).square().mean()
            loss += cfg["ridge"] / len(train["x"]) * trial.readout.weight.square().sum()
            loss.backward()
            if not all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in trial.parameters()):
                raise FloatingPointError("missing/nonfinite full-model gradient")
            torch.nn.utils.clip_grad_norm_(trial.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
    with ledger.operation("candidate_development", development_queries=1,
                          encoder_events=len(dev["x"]) * cfg["length"], forward_examples=len(dev["x"])):
        value, _, _ = score(trial, dev)
    chosen = state(trial) if value < baseline else base
    if not all(bool(torch.isfinite(p).all()) for p in trial.parameters()):
        raise FloatingPointError("nonfinite trained candidate")
    return {"status": "selected" if value < baseline else "no_update",
            "architecture": model.identity(), "train_sha256": digest(train), "dev_sha256": digest(dev),
            "base_dev_mse": baseline, "candidate_dev_mse": value,
            "base_sha256": state_digest(base), "candidate_sha256": state_digest(state(trial)),
            "selected_state": chosen, "selected_sha256": state_digest(chosen),
            "optimizer_steps": cfg["steps"], "fixed_normalization": "initial train-only features"}


def execute(manifest, output, phase, selection_sha):
    started = time.perf_counter()
    cfg, identity = verify(manifest), sha(manifest)
    from qualification.hcsn_adaptive.budget import Budget, CostLedger
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
        save(output / "admission.json", {"manifest_sha256": identity, "config": cfg})
        selected = {}
    else:
        if (not selection_sha or sha(output / "selection.json") != selection_sha
                or json.loads((output / "admission.json").read_text())["manifest_sha256"] != identity):
            raise ValueError("final requires exact external selection digest and original admission")
        with (output / "FINAL_CONSUMED").open("x") as handle:
            handle.write(selection_sha)
        selected = json.loads((output / "selection.json").read_text())["cases"]
    ledger = CostLedger(output / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    results = []
    for task in TASKS:
        for seed in cfg["seeds"]:
            for kind in KINDS:
                key = f"{task}/{seed}/{kind}"
                try:
                    if phase == "fit":
                        before = time.perf_counter()
                        record = fit_case(kind, task, seed, cfg, ledger)
                        record["whole_fit_case_wall_seconds"] = time.perf_counter() - before
                        save(output / f"fit-{task}-{seed}-{kind}.json", record)
                        selected[key] = record
                    else:
                        record = selected.get(key, {})
                        if record.get("status") not in ("selected", "no_update"):
                            results.append({"case": key, "status": record.get("status", "no_fitted_case"),
                                            "fit_record": record})
                            continue
                        with ledger.operation("restore_selected_model"):
                            model = ArchitectureModel(kind)
                            restore(model, record["selected_state"])
                            if state_digest(state(model)) != record["selected_sha256"]:
                                raise ValueError("selected model bytes changed")
                        for split in ("final_iid", "final_clock"):
                            with ledger.operation("new_final_data"):
                                data = generate(cfg["namespace"], seed, task, split, cfg["final"], cfg["length"])
                            with ledger.operation("final_evaluation", encoder_events=len(data["x"]) * cfg["length"],
                                                  forward_examples=len(data["x"])):
                                mse, predictions, errors = score(model, data)
                                results.append({"case": key, "split": split, "status": record["status"],
                                                "architecture": model.identity(), "data_sha256": digest(data),
                                                "mse": mse, "prediction": predictions,
                                                "sample_squared_errors": errors, "target": data["y"][:, 0].tolist(),
                                                "ids": data["ids"].tolist()})
                except Exception as error:
                    failure = {"case": key, "status": "UNAVAILABLE" if isinstance(error, UnavailableBaseline) else "failed",
                               "error": repr(error)}
                    if phase == "fit":
                        selected[key] = failure
                        save(output / f"fit-{task}-{seed}-{kind}.json", failure)
                    else:
                        results.append(failure)
    result = {"manifest_sha256": identity, "phase": phase, "cost": ledger.snapshot(),
              "claims": "small synthetic parameter-band pilot; no foundation-model or energy advantage",
              "cases" if phase == "fit" else "results": selected if phase == "fit" else results}
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

