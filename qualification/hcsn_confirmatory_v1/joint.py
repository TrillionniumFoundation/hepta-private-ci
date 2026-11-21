"""Stage B: shared dynamics/communication/readout mask and real semantic edits."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from .run import candidate, encoder, features, finish, runtime, save, sha, sources
from .environment import execution_identity
from .tasks import TASKS, digest, generate
from .joint_program import apply_program

METHODS = ("conditional_direct", "joint_bp", "semantic_program", "program_then_bp")
OUTER = ("encoder.drive.weight", "encoder.drive.bias", "encoder.writer.weight",
         "encoder.writer.bias", "boundary.weight", "boundary.bias")


def freeze(path, namespace, seeds):
    if (not namespace.startswith("hcsn-joint-confirmatory-v1/") or len(namespace) < 46
            or not 1 <= len(seeds) <= 5 or len(set(seeds)) != len(seeds) or min(seeds) < 0):
        raise ValueError("root-assigned fresh namespace and distinct paired seeds required")
    save(path, {"schema": "hepta.hcsn-joint-confirmatory.v1", "stage": "joint_mask",
                "namespace": namespace, "seeds": seeds, "sources": sources(), "runtime": runtime(),
                "execution": execution_identity(),
                "tasks": list(TASKS), "methods": list(METHODS), "train": 24, "dev": 12,
                "final": 24, "length": 8, "steps": 12, "learning_rate": .005, "ridge": .001,
                "budget": {"wall_seconds": 180, "training_examples": 1000000,
                           "encoder_events": 1000000, "forward_examples": 1000000,
                           "backward_examples": 1000000, "development_queries": 100,
                           "proposals": 100},
                "discovery_cost": {"assistant_tokens": None, "api_cost": None,
                                   "design_wall_seconds": None, "meaning": "unknown, not zero"}})


def verify(path):
    cfg = json.loads(Path(path).read_text())
    if (cfg["schema"] != "hepta.hcsn-joint-confirmatory.v1" or cfg["stage"] != "joint_mask"
            or cfg["sources"] != sources() or cfg["runtime"] != runtime()
            or cfg["execution"] != execution_identity()
            or cfg["tasks"] != list(TASKS) or cfg["methods"] != list(METHODS)):
        raise ValueError("joint source/protocol/runtime identity mismatch")
    return cfg


def build(task):
    import torch
    from torch import nn

    class JointModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.flow = encoder(task)
            width = 2 * len(self.flow.encoder.feature_names) + 2
            self.readout = nn.Linear(width, 1, dtype=torch.float64)
            self.register_buffer("mean", torch.zeros(width, dtype=torch.float64))
            self.register_buffer("scale", torch.ones(width, dtype=torch.float64))
            self.mask = tuple("flow." + name for name in OUTER) + ("readout.weight", "readout.bias")
            for name, parameter in self.named_parameters():
                parameter.requires_grad_(name in self.mask)

        def forward(self, data):
            x, _ = features(self.flow, data, grad=torch.is_grad_enabled())
            return self.readout((x - self.mean) / self.scale)

    return JointModel()


def state(model):
    return {name: value.detach().tolist() for name, value in model.state_dict().items()}


def restore(model, saved):
    import torch
    model.load_state_dict({name: torch.tensor(saved[name], dtype=value.dtype)
                           for name, value in model.state_dict().items()}, strict=True)


def state_digest(saved):
    return hashlib.sha256(json.dumps(saved, sort_keys=True, allow_nan=False).encode()).hexdigest()


def changes(before, model):
    after = state(model)
    changed = [name for name in before if before[name] != after[name]]
    if set(changed) - set(model.mask):
        raise ValueError("candidate edited outside common eligible parameter mask")
    return changed


def score(model, data):
    import torch
    with torch.no_grad():
        prediction = model(data).squeeze(-1)
    losses = (prediction.numpy() - data["y"][:, 0])**2
    return float(losses.mean()), prediction.tolist(), losses.tolist()


def fit_case(task, seed, cfg, ledger):
    import torch
    with ledger.operation("new_train_dev"):
        train = generate(cfg["namespace"], seed, task, "train", cfg["train"], cfg["length"])
        dev = generate(cfg["namespace"], seed, task, "dev", cfg["dev"], cfg["length"])
        model = build(task)
    with ledger.operation("shared_conditional_readout_initialization", proposals=1,
                          encoder_events=len(train["x"]) * cfg["length"], training_examples=len(train["x"])):
        tx, names = features(model.flow, train)
        model.mean.copy_(tx.mean(0))
        model.scale.copy_(tx.std(0, unbiased=False).clamp_min(1e-8))
        fitted = candidate(task, names, (tx - model.mean) / model.scale,
                           torch.from_numpy(train["y"]), model.mean, model.scale, "direct", cfg)
        model.readout.load_state_dict(fitted.state_dict())
    with ledger.operation("incumbent_dev", development_queries=1,
                          encoder_events=len(dev["x"]) * cfg["length"], forward_examples=len(dev["x"])):
        base_score, _, _ = score(model, dev)
    initial = state(model)
    record = {"train_sha256": digest(train), "dev_sha256": digest(dev), "base_state": initial,
              "base_sha256": state_digest(initial), "base_dev_mse": base_score,
              "eligible_mask": model.mask, "eligible_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
              "fixed_normalization": "train-only initial encoder features; unchanged after outer edits", "methods": {}}
    for method in METHODS:
        before = time.perf_counter()
        try:
            with ledger.operation("candidate_admission", proposals=1):
                trial = copy.deepcopy(model)
            if method in ("semantic_program", "program_then_bp"):
                with ledger.operation("assistant_semantic_program"):
                    apply_program(trial, task)
                    changes(initial, trial)
            if method in ("joint_bp", "program_then_bp"):
                parameters = [p for p in trial.parameters() if p.requires_grad]
                optimizer = torch.optim.Adam(parameters, lr=cfg["learning_rate"])
                for _ in range(cfg["steps"]):
                    with ledger.operation("joint_bp_step", training_examples=len(train["x"]),
                                          encoder_events=len(train["x"]) * cfg["length"],
                                          forward_examples=len(train["x"]), backward_examples=len(train["x"])):
                        optimizer.zero_grad(set_to_none=True)
                        loss = (trial(train) - torch.from_numpy(train["y"])).square().mean()
                        loss += cfg["ridge"] / len(train["x"]) * trial.readout.weight.square().sum()
                        loss.backward()
                        if not all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in parameters):
                            raise FloatingPointError("missing/nonfinite common-mask gradient")
                        torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True)
                        optimizer.step()
            changed = changes(initial, trial)
            if not all(bool(torch.isfinite(p).all()) for p in trial.parameters()):
                raise FloatingPointError("nonfinite candidate")
            if method == "conditional_direct":
                value = base_score
            else:
                with ledger.operation("candidate_dev", development_queries=1,
                                      encoder_events=len(dev["x"]) * cfg["length"], forward_examples=len(dev["x"])):
                    value, _, _ = score(trial, dev)
            accepted = value < base_score
            selected = state(trial) if accepted else initial
            status = "reference" if method == "conditional_direct" else ("selected" if accepted else "no_update")
            record["methods"][method] = {"status": status,
                                         "candidate_dev_mse": value, "edited_names": changed,
                                         "candidate_sha256": state_digest(state(trial)),
                                         "selected_sha256": state_digest(selected), "selected_state": selected,
                                         "adaptation_wall_seconds": time.perf_counter() - before,
                                         "direct_scope": "conditional readout only; no nonlinear optimum" if method == "conditional_direct" else None}
        except Exception as error:
            record["methods"][method] = {"status": "failed", "error": repr(error),
                                         "adaptation_wall_seconds": time.perf_counter() - before}
    return record


def execute(manifest, output, phase, selection_sha):
    started = time.perf_counter()
    cfg, identity = verify(manifest), sha(manifest)
    import torch
    from qualification.hcsn_adaptive.budget import Budget, CostLedger
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
        save(output / "admission.json", {"manifest_sha256": identity, "config": cfg})
        (output / "joint_program.py").write_bytes(Path(__file__).with_name("joint_program.py").read_bytes())
        selected = {}
    else:
        if (not selection_sha or sha(output / "selection.json") != selection_sha
                or json.loads((output / "admission.json").read_text())["manifest_sha256"] != identity):
            raise ValueError("final requires the externally sealed selection and original manifest")
        with (output / "FINAL_CONSUMED").open("x") as handle:
            handle.write(selection_sha)
        selected = json.loads((output / "selection.json").read_text())["cases"]
    ledger = CostLedger(output / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    results = []
    for task in TASKS:
        for seed in cfg["seeds"]:
            key = f"{task}/{seed}"
            try:
                if phase == "fit":
                    record = fit_case(task, seed, cfg, ledger)
                    save(output / f"fit-{task}-{seed}.json", record)
                    selected[key] = record
                else:
                    record = selected.get(key, {})
                    if "methods" not in record:
                        results.append({"case": key, "status": "no_fitted_case", "fit_record": record})
                        continue
                    model = build(task)
                    for split in ("final_iid", "final_clock"):
                        with ledger.operation("new_final_data"):
                            data = generate(cfg["namespace"], seed, task, split, cfg["final"], cfg["length"])
                        for method, arm in record["methods"].items():
                            if arm["status"] == "failed":
                                results.append({"case": key, "split": split, "method": method, **arm})
                                continue
                            with ledger.operation("final_model_evaluation",
                                                  encoder_events=len(data["x"]) * cfg["length"], forward_examples=len(data["x"])):
                                restore(model, arm["selected_state"])
                                if state_digest(state(model)) != arm["selected_sha256"]:
                                    raise ValueError("selected state identity mismatch")
                                mse, prediction, errors = score(model, data)
                                results.append({"case": key, "split": split, "method": method,
                                                "status": arm["status"], "data_sha256": digest(data),
                                                "mse": mse, "prediction": prediction, "sample_squared_errors": errors,
                                                "target": data["y"][:, 0].tolist(), "ids": data["ids"].tolist()})
            except Exception as error:
                failure = {"case": key, "status": "failed", "error": repr(error)}
                if phase == "fit":
                    selected[key] = failure
                else:
                    results.append(failure)
    result = {"manifest_sha256": identity, "phase": phase, "cost": ledger.snapshot(),
              "discovery_cost": cfg["discovery_cost"], "claims": "joint-mask mechanism pilot only",
              "cases" if phase == "fit" else "results": selected if phase == "fit" else results}
    path = output / ("selection.json" if phase == "fit" else "final.json")
    finish(path, result, ledger)


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

