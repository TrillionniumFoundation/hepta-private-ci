"""Tensor-product learning of the augmented regenerative payoff operator.

The branch is the supplied payoff coefficients. A neural trunk approximates
transition moments, preserving terminal mass and elementary positivity bounds.
Approximate learned moments are not asserted to satisfy a semigroup identity.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from .operators import RegenerativeSpec, operator_features
from .markov import ACTIVE_BINS, BIN_COUNT, transition_bins, state_bin

HERE = Path(__file__).resolve().parent
ACTIVE_DECAYS = np.array([0.0, 0.5, 1.0, 2.0, 4.0])
REFRACTORY_DECAYS = np.array([0.0, 1.0, 3.0])
CONTEXT_FIELDS = ["mu", "sigma", "reset", "refractory", "discount", "distance", "horizon", "pending"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contexts(count, seed):
    rng = np.random.default_rng(seed)
    unit = rng.random((count, 8))
    lower = np.array([-0.85, 0.22, 0.55, 0.04, 0.02, 0.015, 0.04, 0.0])
    upper = np.array([0.15, 0.48, 1.25, 0.16, 0.4, 4.0, 0.75, 1.0])
    rows = lower + unit * (upper - lower)
    # Sample close-to-boundary states as well as the wide physical range.
    near = rng.random(count) < 0.5
    rows[near, 5] = np.exp(rng.uniform(np.log(0.015), np.log(1.3), near.sum()))
    rows[rng.random(count) < 0.4, 4] = 0.0
    rows[:, 7] *= rows[:, 3]
    rows[rng.random(count) < 0.65, 7] = 0.0
    rows[rows[:, 7] > 0, 5] = rows[rows[:, 7] > 0, 2]
    return rows


def reference_rows(rows, order=96):
    output = []
    defects = []
    for mu, sigma, reset, refractory, discount, distance, horizon, pending in rows:
        spec = RegenerativeSpec(mu, sigma, reset, refractory, discount)
        item = operator_features(spec, distance, horizon, pending_refractory=pending,
                                 active_decays=ACTIVE_DECAYS,
                                 refractory_decays=REFRACTORY_DECAYS / refractory,
                                 quadrature_order=order)
        output.append(np.r_[item["discounted_features"], item["discounted_events"],
                            item["discounted_active_time"],
                            transition_bins(spec, distance, horizon, pending)])
        defects.append(item["mass_quadrature_defect"])
    return np.asarray(output), np.asarray(defects)


class RegenerativeValueLayer(nn.Module):
    """Linear in payoff; nonlinear in physical state, dynamics and elapsed time."""

    def __init__(self, width=64):
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(8, width), nn.SiLU(),
                                   nn.Linear(width, width), nn.SiLU(),
                                   nn.Linear(width, width), nn.SiLU(), nn.Linear(width, 8 + BIN_COUNT))
        self.double()

    def outputs(self, rows):
        if rows.ndim != 2 or rows.shape[1] != 8 or rows.dtype != torch.float64:
            raise ValueError("float64 context rows with eight fields required")
        if (not bool(torch.isfinite(rows).all()) or bool((rows[:, 1:4] <= 0).any()) or
                bool((rows[:, 4:] < 0).any()) or bool((rows[:, 7] > rows[:, 3]).any()) or
                bool(((rows[:, 7] > 0) & (torch.abs(rows[:, 5] - rows[:, 2]) > 1e-12)).any())):
            raise ValueError("invalid physical context or refractory reset state")
        boundary = (rows[:, 5] == 0) & (rows[:, 7] == 0)
        if bool(boundary.any()):
            reset_rows = rows.clone()
            reset_rows[boundary, 5] = rows[boundary, 2]
            reset_rows[boundary, 7] = rows[boundary, 3]
            moments, probabilities = self.outputs(reset_rows)
            increment = torch.zeros_like(moments)
            increment[boundary, 8] = 1.0
            return moments + increment, probabilities
        center = rows.new_tensor([-0.35, 0.35, 0.90, 0.10, 0.20, 1.3, 0.395, 0.5])
        scale = rows.new_tensor([0.5, 0.13, 0.35, 0.06, 0.20, 1.3, 0.355, 0.5])
        normalized = torch.cat([rows[:, :7], (rows[:, 7] / rows[:, 3])[:, None]], dim=1)
        raw = self.trunk((normalized - center) / scale)
        q, t, eta, a = rows[:, 4:5], rows[:, 6:7], rows[:, 7:8], rows[:, 3:4]
        active_t = torch.clamp(t - eta, min=0)
        discount_t = torch.exp(-q * t)
        probabilities = torch.softmax(raw[:, 8:], dim=1)
        mass = probabilities[:, :ACTIVE_BINS].sum(dim=1, keepdim=True)
        active = mass * torch.cat([torch.ones_like(mass), torch.exp(
            -rows.new_tensor(ACTIVE_DECAYS[1:]) * nn.functional.softplus(raw[:, 0:4]))], dim=1)
        refractory = (1 - mass) * torch.cat([torch.ones_like(mass), torch.exp(
            -rows.new_tensor(REFRACTORY_DECAYS[1:]) * torch.sigmoid(raw[:, 4:6]))], dim=1)
        features = discount_t * torch.cat([active, refractory], dim=1)
        maximum_count = torch.ceil(active_t / a)
        events = maximum_count * torch.sigmoid(raw[:, 6:7] - 3)
        occupied_limit = torch.exp(-q * eta) * torch.where(q > 0, -torch.expm1(-q * active_t)
                                                        / torch.clamp(q, min=1e-10), active_t)
        occupation = occupied_limit * torch.sigmoid(raw[:, 7:8])
        result = torch.cat([features, events, occupation], dim=1)
        # Deterministic holding/release is an exact branch, not a learned hazard.
        held = eta > t
        held_features = discount_t * torch.cat([torch.zeros_like(active), torch.exp(
            -rows.new_tensor(REFRACTORY_DECAYS) * (eta - t) / a)], dim=1)
        held_result = torch.cat([held_features, torch.zeros_like(events), torch.zeros_like(occupation)], dim=1)
        result = torch.where(held, held_result, result)
        released = eta == t
        release_x = torch.where(eta > 0, rows[:, 2:3], rows[:, 5:6])
        release_features = discount_t * torch.cat([torch.exp(-rows.new_tensor(ACTIVE_DECAYS) * release_x),
                                                    torch.zeros_like(refractory)], dim=1)
        release_result = torch.cat([release_features, torch.zeros_like(events), torch.zeros_like(occupation)], dim=1)
        result = torch.where(released, release_result, result)
        deterministic = (held | released).squeeze(1)
        if bool(deterministic.any()):
            indices = torch.nonzero(deterministic).squeeze(1)
            one_hot = torch.zeros((len(indices), BIN_COUNT), dtype=rows.dtype, device=rows.device)
            for index, row_index in enumerate(indices.tolist()):
                row = rows[row_index].detach().numpy()
                terminal_x = row[2] if row[7] > 0 else row[5]
                one_hot[index, state_bin(terminal_x, max(0.0, row[7]-row[6]), row[3])] = 1.0
            probabilities = probabilities.index_copy(0, indices, one_hot)
        return result, probabilities

    def moments(self, rows):
        return self.outputs(rows)[0]

    def transition_probabilities(self, rows):
        return self.outputs(rows)[1]

    def forward(self, rows, payoff):
        """Last two payoff coefficients are event reward and active running rate."""
        return (self.moments(rows) * payoff).sum(dim=-1)


def save_model(model, path):
    np.savez_compressed(path, **{k: v.detach().numpy() for k, v in model.state_dict().items()})


def load_model(path):
    model = RegenerativeValueLayer()
    with np.load(path) as weights:
        model.load_state_dict({k: torch.from_numpy(weights[k].copy()) for k in weights.files})
    return model.eval()


def shard_data(path, rows, targets, defects):
    path.mkdir(parents=True, exist_ok=True)
    hashes = []
    for index, start in enumerate(range(0, len(rows), 512)):
        name = path / f"part-{index:03d}.npz"
        np.savez_compressed(name, contexts=rows[start:start+512], targets=targets[start:start+512],
                            mass_defects=defects[start:start+512])
        hashes.append({"path": str(name.relative_to(HERE)), "sha256": sha256(name), "bytes": name.stat().st_size})
    return hashes


def load_data(path):
    arrays = [np.load(p) for p in sorted(path.glob("part-*.npz"))]
    try:
        return tuple(np.concatenate([p[key] for p in arrays]) for key in ("contexts", "targets", "mass_defects"))
    finally:
        for item in arrays:
            item.close()


def prepare(protocol, output):
    receipt = {"schema": "hepta.value-learning.data.v1", "protocol_sha256": sha256(HERE / "VALUE_PROTOCOL.json"), "splits": {}}
    for split in ("train", "development"):
        count = protocol[f"{split}_rows"]
        rows = contexts(count, protocol["split_seeds"][split])
        started = time.perf_counter()
        targets, defects = reference_rows(rows, protocol["quadrature_order"])
        receipt["splits"][split] = {"files": shard_data(output / split, rows, targets, defects),
                                    "rows": count, "wall_seconds": time.perf_counter() - started,
                                    "max_mass_quadrature_defect": float(np.max(np.abs(defects)))}
        print(json.dumps({"prepared": split, **receipt["splits"][split]}, allow_nan=False), flush=True)
    (output / "DATA.json").write_text(json.dumps(receipt, indent=2) + "\n")


def train(protocol, output):
    x, y, _ = load_data(output / "train")
    dx, dy, _ = load_data(output / "development")
    train_x, train_y = torch.from_numpy(x), torch.from_numpy(y)
    dev_x, dev_y = torch.from_numpy(dx), torch.from_numpy(dy)
    reports = []
    for seed in protocol["model_seeds"]:
        torch.manual_seed(seed)
        model = RegenerativeValueLayer(protocol["width"])
        initial = deepcopy(model.state_dict())
        optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
        generator = torch.Generator().manual_seed(seed + 1)
        best, best_state, best_step = float("inf"), None, None
        history = []
        started = time.perf_counter()
        for step in range(protocol["steps"] + 1):
            if step % 100 == 0:
                with torch.no_grad():
                    dp, dt = model.outputs(dev_x)
                    loss_dev = float((dp - dev_y[:, :10]).square().mean() +
                                     0.03 * -(dev_y[:, 10:] * torch.log(torch.clamp(dt, min=1e-15))).sum(dim=1).mean())
                history.append({"step": step, "development_mse": loss_dev})
                if loss_dev < best:
                    best, best_state, best_step = loss_dev, deepcopy(model.state_dict()), step
            if step == protocol["steps"]:
                break
            indices = torch.randint(len(x), (protocol["batch_size"],), generator=generator)
            prediction, probabilities = model.outputs(train_x[indices])
            loss = (prediction - train_y[indices, :10]).square().mean() + 0.03 * -(
                train_y[indices, 10:] * torch.log(torch.clamp(probabilities, min=1e-15))).sum(dim=1).mean()
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            optimizer.step()
        model.load_state_dict(best_state)
        model_path = output / f"model-{seed}.npz"
        save_model(model, model_path)
        changes = {name: float(torch.linalg.vector_norm(value - initial[name])) for name, value in model.state_dict().items()}
        with torch.no_grad():
            train_mse = float((model.moments(train_x) - train_y[:, :10]).square().mean())
        report = {"seed": seed, "best_step": best_step, "development_mse": best, "train_mse": train_mse,
                  "parameter_count": sum(p.numel() for p in model.parameters()), "changes": changes,
                  "all_parameter_tensors_changed": all(v > 0 for v in changes.values()), "history": history,
                  "model_path": str(model_path.relative_to(HERE)), "model_sha256": sha256(model_path),
                  "wall_seconds": time.perf_counter() - started}
        reports.append(report)
        (output / f"train-{seed}.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k:v for k,v in report.items() if k not in {"changes", "history"}}), flush=True)
    (output / "TRAINING.json").write_text(json.dumps({"schema": "hepta.value-learning.training.v1", "fits": reports}, indent=2) + "\n")


def verify_freeze(path):
    freeze = json.loads(Path(path).read_text())
    for item in freeze["files"]:
        source = HERE / item["path"]
        if sha256(source) != item["sha256"]:
            raise ValueError("frozen source/model differs: " + item["path"])
    for item in freeze.get("external_files", []):
        source = HERE.parent / item["path"]
        if not source.resolve().is_relative_to((HERE.parent / "first_passage_cell").resolve()):
            raise ValueError("external dependency leaves the frozen first-passage package")
        if sha256(source) != item["sha256"]:
            raise ValueError("frozen external dependency differs: " + item["path"])
    return sha256(path)


def confirm(protocol, output, freeze):
    identity = verify_freeze(freeze)
    if (output / "CONFIRMATION.json").exists():
        raise FileExistsError("confirmation already exists; preserve its frozen outcome")
    rows = contexts(protocol["confirmation_rows"], protocol["split_seeds"]["confirmation"])
    targets, defects = reference_rows(rows, protocol["confirmation_reference_order"])
    files = shard_data(output / "confirmation", rows, targets, defects)
    rng = np.random.default_rng(2026102905)
    payoff = rng.normal(size=(len(targets), 10))
    payoff /= np.linalg.norm(payoff, axis=1, keepdims=True)
    results = []
    for seed in protocol["model_seeds"]:
        model = load_model(output / f"model-{seed}.npz")
        with torch.no_grad():
            predictions, transitions = model.outputs(torch.from_numpy(rows))
            predictions, transitions = predictions.numpy(), transitions.numpy()
        difference = predictions - targets[:, :10]
        values_error = np.sum(difference * payoff, axis=1)
        mass_defect = predictions[:, 0] + predictions[:, 5] - np.exp(-rows[:, 4] * rows[:, 6])
        result = {"seed": seed, "moment_rmse": float(np.sqrt(np.mean(difference ** 2))),
                  "maximum_absolute_moment_error": float(np.max(np.abs(difference))),
                  "value_rmse_unit_l2_payoff": float(np.sqrt(np.mean(values_error ** 2))),
                  "maximum_absolute_value_error": float(np.max(np.abs(values_error))),
                  "max_discounted_mass_defect": float(np.max(np.abs(mass_defect))),
                  "mean_transition_total_variation": float(np.mean(np.abs(transitions-targets[:,10:]).sum(axis=1)/2)),
                  "maximum_transition_total_variation": float(np.max(np.abs(transitions-targets[:,10:]).sum(axis=1)/2)),
                  "finite_outputs": bool(np.isfinite(predictions).all() and np.isfinite(transitions).all())}
        gate = protocol["heldout_gate"]
        result["gate_passed"] = bool(result["moment_rmse"] <= gate["moment_rmse"] and
                                     result["value_rmse_unit_l2_payoff"] <= gate["value_rmse_unit_l2_payoff"] and
                                     result["max_discounted_mass_defect"] <= gate["mass_defect"] and result["finite_outputs"] and
                                     result["mean_transition_total_variation"] <= gate["mean_transition_total_variation"])
        for index, start in enumerate(range(0, len(rows), 512)):
            np.savez_compressed(output / "confirmation" / f"prediction-{seed}-{index:03d}.npz",
                                predictions=predictions[start:start+512], transitions=transitions[start:start+512], payoff=payoff[start:start+512])
        results.append(result)
    report = {"schema": "hepta.value-learning.confirmation.v1", "freeze_sha256": identity,
              "rows": len(rows), "reference_files": files,
              "max_reference_mass_quadrature_defect": float(np.max(np.abs(defects))),
              "results": results, "all_passed": all(r["gate_passed"] for r in results),
              "scope": "Heldout finite context domain; positivity/mass constraints do not prove learned semigroup or Bellman convergence."}
    (output / "CONFIRMATION.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "train", "confirm"])
    parser.add_argument("--output", type=Path, default=HERE / "value_evidence")
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    protocol = json.loads((HERE / "VALUE_PROTOCOL.json").read_text())
    args.output.mkdir(exist_ok=True)
    if args.command == "prepare":
        prepare(protocol, args.output)
    elif args.command == "train":
        train(protocol, args.output)
    else:
        if args.freeze is None:
            raise ValueError("confirmation requires the source/model freeze")
        confirm(protocol, args.output, args.freeze)


if __name__ == "__main__":
    main()
