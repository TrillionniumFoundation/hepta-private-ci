"""Full finite-law autograd with component freezes and immutable checkpoints."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import torch

from .data import make_data
from .model import JointCell, save_model
from .joint_control import build_graph, refine


def expected_loss(model, data):
    mass = model.initial(data["x"].shape[0])
    losses, mean_losses, events = [], [], []
    for tick in range(data["x"].shape[1]):
        active = data["active"][:, tick]
        proposed, event, content = model.advance(mass, data["x"][:, tick])
        mass = torch.where(active[:, None], proposed, mass)
        prediction = model.state_action_values(data["x"][:, tick], content)
        squared = (prediction - data["y"][:, tick, None, :, :]).square()
        mask = (data["legal"][:, tick] & active[:, None])[:, None, :]
        expected = (mass[:, :, None, None] * squared).sum(dim=1)
        mean_prediction = (mass[:, :, None, None] * prediction).sum(dim=1)
        losses.append((expected * mask).sum())
        mean_losses.append(((mean_prediction - data["y"][:, tick]).square() * mask).sum())
        events.append((event * active[:, None]).sum())
    denominator = 2 * (data["legal"] & data["active"][:, :, None]).sum()
    return torch.stack(losses).sum() / denominator, {
        "mean_prediction_mse": torch.stack(mean_losses).sum() / denominator,
        "expected_events_per_episode": torch.stack(events).sum() / len(data["x"])}


def physical(model):
    return {key: float(value.detach()) for key, value in model.core.physical_parameters().items()}


def train_one(mode, seed, train, dev, output, *, epochs=100, grid=15, lr=0.02,
              ablation="none", hidden=12, control_epochs=30, graph=None):
    torch.manual_seed(seed)
    model = JointCell(mode, grid, hidden)
    groups = model.parameter_groups()
    if ablation != "none":
        if ablation not in groups:
            raise ValueError(ablation)
        for parameter in groups[ablation]:
            parameter.requires_grad_(False)
    initial = {key: value.detach().clone() for key, value in model.named_parameters()}
    initial_physical = physical(model)
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=lr)
    best, best_epoch, checkpoint = float("inf"), -1, None
    curves, gradient_max = [], {key: 0.0 for key in groups}
    start = time.perf_counter()
    cpu_started = time.process_time()
    for epoch in range(epochs + 1):
        if epoch:
            model.train()
            optimizer.zero_grad(set_to_none=True)
            loss, metrics = expected_loss(model, train)
            if not torch.isfinite(loss):
                raise FloatingPointError("nonfinite supervised loss")
            loss.backward()
            for key, parameters in groups.items():
                norm = sum(float(p.grad.detach().square().sum()) for p in parameters if p.grad is not None)**0.5
                gradient_max[key] = max(gradient_max[key], norm)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
        if epoch % 5 == 0 or epoch == epochs:
            model.eval()
            with torch.no_grad():
                train_loss, train_metrics = expected_loss(model, train)
                dev_loss, dev_metrics = expected_loss(model, dev)
            record = {"epoch": epoch, "train_expected_mse": float(train_loss),
                      "dev_expected_mse": float(dev_loss),
                      "train_mean_mse": float(train_metrics["mean_prediction_mse"]),
                      "dev_mean_mse": float(dev_metrics["mean_prediction_mse"]),
                      "dev_expected_events": float(dev_metrics["expected_events_per_episode"])}
            curves.append(record)
            if float(dev_loss) < best:
                best, best_epoch = float(dev_loss), epoch
                checkpoint = copy.deepcopy(model.state_dict())
    model.load_state_dict(checkpoint)
    regression_physical = physical(model)
    regression_changes = {key: float(torch.linalg.vector_norm(value.detach() - initial[key]))
                          for key, value in model.named_parameters()}
    control_start = time.perf_counter()
    control = refine(model, graph or build_graph(), epochs=control_epochs) if control_epochs else None
    control_elapsed = time.perf_counter() - control_start
    elapsed = time.perf_counter() - start
    changes = {key: float(torch.linalg.vector_norm(value.detach() - initial[key]))
               for key, value in model.named_parameters()}
    metadata = {"seed": seed, "ablation": ablation, "epochs": epochs, "learning_rate": lr,
                "best_epoch": best_epoch, "best_dev_expected_mse": best,
                "training_wall_seconds": elapsed, "gradient_max_by_group": gradient_max,
                "training_process_cpu_seconds": time.process_time() - cpu_started,
                "parameter_change_l2": changes, "initial_physical": initial_physical,
                "regression_parameter_change_l2": regression_changes,
                "regression_physical": regression_physical,
                "selected_physical": physical(model), "curves": curves,
                "control_refinement": control, "control_wall_seconds": control_elapsed,
                "total_parameters": sum(p.numel() for p in model.parameters()),
                "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
                "objective": "finite-law supervised initialization followed by exact finite joint-state soft-policy task return and semi-gradient critic/Q1 auxiliaries"}
    save_model(model, output, metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--modes", nargs="+", default=["clocked", "first_passage", "continuous", "direct"])
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(11, 16)))
    parser.add_argument("--ablations", nargs="+", default=["none"])
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--grid", type=int, default=15)
    parser.add_argument("--train-count", type=int, default=256)
    parser.add_argument("--dev-count", type=int, default=64)
    parser.add_argument("--lr", type=float, default=0.02)
    parser.add_argument("--control-epochs", type=int, default=30)
    args = parser.parse_args()
    torch.set_num_threads(1)
    started = time.perf_counter()
    cpu_start = time.process_time()
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in Path(__file__).parent.glob("*.py")}
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    train, train_manifest = make_data(100000, args.train_count)
    dev, dev_manifest = make_data(200000, args.dev_count)
    graph = build_graph() if args.control_epochs else None
    setup_seconds = time.perf_counter() - started
    for label, manifest in (("train", train_manifest), ("dev", dev_manifest)):
        (folder / (label + "_data.json")).write_text(json.dumps(manifest, sort_keys=True) + "\n")
    attempts, failures = [], []
    for mode in args.modes:
        for ablation in args.ablations:
            for seed in args.seeds:
                path = folder / f"{mode}_{ablation}_{seed}.json"
                if path.exists():
                    raise FileExistsError(path)
                fit_started = time.perf_counter()
                try:
                    result = train_one(mode, seed, train, dev, path, epochs=args.epochs,
                                       grid=args.grid, lr=args.lr, ablation=ablation,
                                       control_epochs=args.control_epochs, graph=graph)
                    attempt = {"file": str(path), "status": "complete",
                               "seconds": time.perf_counter() - fit_started,
                               "training_seconds": result["training_wall_seconds"],
                               "dev_mse": result["best_dev_expected_mse"], "epoch": result["best_epoch"]}
                except Exception:
                    attempt = {"file": str(path), "status": "failed",
                               "seconds": time.perf_counter() - fit_started, "traceback": traceback.format_exc()}
                    failures.append(attempt)
                attempts.append(attempt)
                print(json.dumps(attempt), flush=True)
    identity = hashlib.sha256(json.dumps(vars(args), sort_keys=True).encode()).hexdigest()[:12]
    receipt = {"configuration": vars(args), "attempts": attempts, "failures": failures,
               "source_hashes_at_start": source_hashes,
               "setup_seconds": setup_seconds, "wall_seconds": time.perf_counter() - started,
               "process_cpu_seconds": time.process_time() - cpu_start,
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "timing_scope": "data/oracle preparation, all model/optimizer setup, training, checkpoint serialization"}
    (folder / ("TRAINING_RUN_" + identity + ".json")).write_text(json.dumps(receipt, indent=2) + "\n")
    if failures:
        raise RuntimeError(f"{len(failures)} training fits failed; receipts retained")


if __name__ == "__main__":
    main()
