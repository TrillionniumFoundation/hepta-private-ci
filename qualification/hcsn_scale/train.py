"""One immutable pretraining trajectory with train-only probes and dev selection."""

from dataclasses import asdict
import copy
import json
from pathlib import Path
import random
import resource
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.budget import Budget, BudgetExhausted, CostLedger, summarize_journal
from qualification.hcsn_adaptive.campaign import digest, save_tensor_file, write_json
from qualification.hcsn_adaptive.checkpoint import load_checkpoint, save_checkpoint
from qualification.hcsn_adaptive.datasets import file_digest, load_split
from qualification.hcsn_adaptive.features import standardize
from .model import ModelConfig, SequenceModel, tensor_map_digest, validate_split


def ridge_probe(train, targets, dev, dev_targets, penalty):
    """Minimize mean squared error + penalty * sum(non-bias weights squared)."""
    normalized, heldout, mean, scale = standardize(train, dev)
    design = torch.cat((normalized, torch.ones_like(normalized[:, :1])), 1)
    regularizer = torch.eye(design.shape[1], dtype=design.dtype, device=design.device) * (penalty * len(design) * targets.shape[1])
    regularizer[-1, -1] = 0
    weights = torch.linalg.solve(design.T @ design + regularizer, design.T @ targets)
    prediction = torch.cat((heldout, torch.ones_like(heldout[:, :1])), 1) @ weights
    mse = float((prediction - dev_targets).square().mean())
    if not np.isfinite(mse) or not torch.isfinite(weights).all():
        raise FloatingPointError("nonfinite linear probe")
    return {"weights": weights, "mean": mean, "scale": scale}, mse


def probe_prediction(probe, features):
    normalized = (features - probe["mean"]) / probe["scale"]
    return torch.cat((normalized, torch.ones_like(normalized[:, :1])), 1) @ probe["weights"]


def prepare_track(manifest, track, output):
    cfg = manifest["config"]
    identity = digest({"manifest": manifest["sha256"], "track": track})
    directory = Path(output) / "tracks" / track["id"]
    if track["kind"] == "raw":
        return identity, directory, None
    config = ModelConfig(kind=track["kind"], input_size=manifest["input_size"], width=track["width"],
                         clock_scale_seconds=manifest["clock_scale_seconds"],
                         bins=cfg["bins"], stages=cfg["stages"], dtype=cfg["dtype"])
    return identity, directory, config


def train_one(manifest, track, output, *, resume=False, stop_after=None):
    if track["kind"] == "raw":
        return train_raw(manifest, track, output)
    started = time.perf_counter()
    identity, directory, config = prepare_track(manifest, track, output)
    cfg = manifest["config"]
    existing = directory / "training.json"
    if existing.exists():
        prior = json.loads(existing.read_text())
        if prior["identity"] != identity:
            raise ValueError("existing track belongs to another frozen experiment")
        if prior["status"] not in ("paused", "interrupted"):
            return prior
    checkpoint = directory / "checkpoint.pt"
    if (directory / "cost.jsonl").exists() and not resume:
        raise FileExistsError("existing trajectory requires explicit resume")
    ledger = CostLedger(directory / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    seed = track["seed"]
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)
    model = SequenceModel(config).to(device=cfg["device"])
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg["learning_rate"])
    generator = torch.Generator(device="cpu").manual_seed(seed ^ 0x5CA1E)
    controller = {"step": 0, "status": "running", "curve": [], "history": [], "best": None,
                  "best_step": None, "best_dev": None, "recovery_discarded_operations": 0,
                  "backend_state": {"boundary": "between_independent_windows", "inflight": None},
                  "initial_parameters_sha256": tensor_map_digest(dict(model.named_parameters()))}
    if resume:
        controller = load_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                                     generator=generator, ledger=ledger)
        if controller["backend_state"] != {"boundary": "between_independent_windows", "inflight": None}:
            raise ValueError("a partial window/AD graph cannot resume at a step boundary")
    train = load_split(cfg["data_dir"], "train", manifest["data"])
    dev = load_split(cfg["data_dir"], "dev", manifest["data"])
    for data in (train, dev):
        validate_split(data, config.input_size)
    like = next(model.parameters())
    tx, ty = (torch.as_tensor(train[key], dtype=like.dtype, device=like.device) for key in ("x", "y"))
    dx, dy = (torch.as_tensor(dev[key], dtype=like.dtype, device=like.device) for key in ("x", "y"))
    if like.is_cuda:
        torch.cuda.reset_peak_memory_stats(like.device)

    def save():
        save_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                        controller=controller, generator=generator, ledger=ledger)

    def evaluate():
        samples = len(tx) + len(dx)
        with ledger.operation("frozen_encoder_linear_probe", training_examples=len(tx),
                              encoder_events=samples * tx.shape[1],
                              forward_examples=samples * tx.shape[1], development_queries=1):
            model.eval()
            train_features, train_ssl = model.representations(tx, train["dt"])
            dev_features, dev_ssl = model.representations(dx, dev["dt"])
            probe, dev_mse = ridge_probe(train_features, ty, dev_features, dy, cfg["ridge"])
            point = {"step": controller["step"], "train_ssl_mse": train_ssl, "dev_ssl_mse": dev_ssl,
                     "dev_probe_mse": dev_mse, "probe_parameters": probe["weights"].numel(),
                     "parameters_sha256": tensor_map_digest(dict(model.named_parameters()))}
            controller["curve"].append(point)
            if controller["best_dev"] is None or dev_mse < controller["best_dev"] - 1e-12:
                controller.update(best_dev=dev_mse, best_step=controller["step"], best={
                    "model": copy.deepcopy(model.state_dict()), "probe": probe,
                    "config": asdict(config), "identity": identity, "step": controller["step"]})
            if like.is_cuda:
                torch.cuda.synchronize(like.device)
            model.train()

    try:
        if not controller["curve"]:
            evaluate()
            save()
        while controller["step"] < cfg["steps"]:
            if stop_after is not None and controller["step"] >= stop_after:
                controller["status"] = "paused"
                break
            controller["status"] = "running"
            batch = min(cfg["batch_size"], len(tx))
            events = batch * (tx.shape[1] - 1)
            with ledger.operation("encoder_task_bp", training_examples=batch, encoder_events=events,
                                  forward_examples=events, backward_examples=events, proposals=1):
                indices = torch.randperm(len(tx), generator=generator)[:batch]
                optimizer.zero_grad(set_to_none=True)
                loss = model.next_sensor_loss(tx[indices.to(tx.device)], train["dt"][indices.numpy()])
                loss.backward()
                gradients = {name: parameter.grad for name, parameter in model.named_parameters()
                             if parameter.grad is not None}
                if set(gradients) != set(dict(model.named_parameters())) or any(
                        not torch.isfinite(value).all() for value in gradients.values()):
                    raise FloatingPointError("missing or nonfinite full-encoder BP gradients")
                gradient_digest = tensor_map_digest(gradients)
                nonzero = {name: bool(value.abs().max() > 0) for name, value in gradients.items()}
                norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["gradient_clip"], error_if_nonfinite=True))
                optimizer.step()
                if any(not torch.isfinite(p).all() for p in model.parameters()):
                    raise FloatingPointError("nonfinite updated parameters")
                if like.is_cuda:
                    torch.cuda.synchronize(like.device)
            controller["step"] += 1
            controller["history"].append({"step": controller["step"], "ssl_mse": float(loss.detach()),
                "batch_ids": [str(train["ids"][index]) for index in indices.tolist()],
                "gradient_sha256": gradient_digest, "gradient_norm_before_clip": norm,
                "nonzero_gradient_names": [name for name, value in nonzero.items() if value],
                "parameters_sha256": tensor_map_digest(dict(model.named_parameters()))})
            if controller["step"] in cfg["checkpoints"]:
                evaluate()
            save()
        if controller["status"] == "running":
            controller["status"] = "completed"
    except BudgetExhausted as error:
        controller.update(status="budget_exhausted", error=str(error))
    except (RuntimeError, FloatingPointError, ValueError) as error:
        controller.update(status="failed", error=type(error).__name__ + ": " + str(error))
    save()
    report = {key: value for key, value in controller.items() if key != "best"}
    report.update(identity=identity, manifest=manifest["sha256"], track=track, model=model.identity(),
                  outcome="Unavailable" if controller["best"] is None else
                  ("NoUpdate" if controller["best_step"] == 0 else "Candidate"),
                  cost=ledger.snapshot(), complete_step_checkpoint_sha256=file_digest(checkpoint),
                  peak_rss_bytes=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
                  peak_rss_scope="whole fresh track process, including Python/Torch startup",
                  cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(like.device) if like.is_cuda else None,
                  trainable_mask="all encoder, boundary controller and next-sensor decoder parameters",
                  current_parameter_sha256=tensor_map_digest(dict(model.named_parameters())))
    if controller["best"] is not None and controller["status"] in ("completed", "budget_exhausted"):
        with ledger.operation("checkpoint", mandatory=True):
            save_tensor_file(directory / "selected.pt", controller["best"])
        report.update(selected_sha256=file_digest(directory / "selected.pt"), cost=ledger.snapshot())
    report["process_work_seconds"] = time.perf_counter() - started
    write_json(existing, report)
    return report


def failure_receipt(manifest, track, output, error):
    identity, directory, _ = prepare_track(manifest, track, output)
    result = {"identity": identity, "manifest": manifest["sha256"], "track": track, "status": "failed",
              "outcome": "Unavailable", "error": type(error).__name__ + ": " + str(error),
              "cost_evidence": summarize_journal(directory / "cost.jsonl")}
    report_path = directory / "training.json"
    if report_path.exists() or isinstance(error, FileExistsError):
        write_json(directory / f"attempt-failure-{time.time_ns()}.json", result, exclusive=True)
    else:
        write_json(report_path, result)
    return result


def raw_features(data, clock_scale_seconds, *, dtype, device):
    """Fixed sensor last/mean plus known query-interval last/mean/sum summaries."""
    x = torch.as_tensor(data["x"], dtype=dtype, device=device)
    dt = torch.as_tensor(data["dt"], dtype=dtype, device=device)
    timing = torch.stack((dt[:, -1], dt.mean(1), dt.sum(1)), 1)
    return torch.cat((x[:, -1], x.mean(1), torch.log1p(timing / clock_scale_seconds)), 1)


def train_raw(manifest, track, output):
    started = time.perf_counter()
    identity, directory, _ = prepare_track(manifest, track, output)
    report_path = directory / "training.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        if report["identity"] != identity:
            raise ValueError("raw baseline belongs to another experiment")
        return report
    cfg = manifest["config"]
    ledger = CostLedger(directory / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started)
    train = load_split(cfg["data_dir"], "train", manifest["data"])
    dev = load_split(cfg["data_dir"], "dev", manifest["data"])
    for data in (train, dev):
        validate_split(data, manifest["input_size"])
    dtype, device = getattr(torch, cfg["dtype"]), cfg["device"]
    with ledger.operation("raw_sensor_ridge", training_examples=len(train["x"]),
                          forward_examples=len(train["x"]) + len(dev["x"]), development_queries=1, proposals=1):
        train_features = raw_features(train, manifest["clock_scale_seconds"], dtype=dtype, device=device)
        dev_features = raw_features(dev, manifest["clock_scale_seconds"], dtype=dtype, device=device)
        probe, dev_mse = ridge_probe(train_features, torch.as_tensor(train["y"], dtype=dtype, device=device),
            dev_features, torch.as_tensor(dev["y"], dtype=dtype, device=device), cfg["ridge"])
        if train_features.is_cuda:
            torch.cuda.synchronize(train_features.device)
    selected = {"kind": "raw", "identity": identity, "step": 0, "probe": probe,
                "clock_scale_seconds": manifest["clock_scale_seconds"]}
    with ledger.operation("checkpoint", mandatory=True):
        save_tensor_file(directory / "selected.pt", selected)
    report = {"identity": identity, "manifest": manifest["sha256"], "track": track,
              "status": "completed", "outcome": "Baseline", "step": 0,
              "best_step": 0, "best_dev": dev_mse, "history": [],
              "curve": [{"step": 0, "dev_probe_mse": dev_mse, "probe_parameters": probe["weights"].numel()}],
              "model": {"encoder_parameters": 0, "all_trainable_parameters": 0,
                        "embedding_width": train_features.shape[1], "linear_probe_parameters": probe["weights"].numel()},
              "selected_sha256": file_digest(directory / "selected.pt"), "cost": ledger.snapshot(),
              "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
              "process_work_seconds": time.perf_counter() - started,
              "learning_rule": "ClosedFormReadout", "seed_policy": "one deterministic baseline, no seed replication"}
    write_json(report_path, report)
    return report
