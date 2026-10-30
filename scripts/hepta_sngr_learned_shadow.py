#!/usr/bin/env python3
"""Opt-in, CPU-only synthetic continuation and Z neural regression experiment.

No Laya, no actual observed task outcomes, no stochastic BSDE training. Labels
come from the *known analytic* scalar affine decoupling field of an FBSDE.
PyTorch is optional and intentionally NOT imported by the default Hepta CI.
"""

from __future__ import annotations

import argparse
import json
import math
import time


def analytic_field(
    x, t, *, slope: float, intercept: float, diffusion: float, horizon: float
):
    """Vectorized torch-only manufactured affine field and Z sensitivity."""
    denominator = 1.0 - slope * (horizon - t)
    return (slope * x + intercept) / denominator, diffusion * slope / denominator


def experiment(
    seed: int = 17,
    train_steps: int = 400,
    train_count: int = 1024,
    test_count: int = 512,
) -> dict[str, object]:
    """Compare held-out neural approximation to a closed-form linear baseline.

    The splits are independently seeded continuous draws, not future-observed
    runtime features. Model capacity/training cost is NOT matched to linear fit.
    """
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("invalid seed")
    if not isinstance(train_steps, int) or not 1 <= train_steps <= 2000:
        raise ValueError("training steps outside explicit budget")
    if not isinstance(train_count, int) or not 128 <= train_count <= 8192:
        raise ValueError("training sample count outside bounds")
    if not isinstance(test_count, int) or not 128 <= test_count <= 8192:
        raise ValueError("test sample count outside bounds")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "opt-in PyTorch is unavailable; no synthetic training occurred"
        ) from exc

    torch.set_num_threads(1)
    torch.manual_seed(seed)
    # Operating domain: slope * horizon < 1 (positive global denominator).
    slope, intercept, diffusion, horizon = 0.45, 0.2, 0.3, 1.0

    def make_data(count: int, data_seed: int):
        generator = torch.Generator(device="cpu").manual_seed(data_seed)
        state = 4 * torch.rand((count, 1), generator=generator) - 2
        t = torch.rand((count, 1), generator=generator)
        value, z = analytic_field(
            state,
            t,
            slope=slope,
            intercept=intercept,
            diffusion=diffusion,
            horizon=horizon,
        )
        features = torch.cat((state, t), dim=1)
        targets = torch.cat((value, z), dim=1)
        return features, targets

    train_x, train_y = make_data(train_count, seed + 101)
    test_x, test_y = make_data(test_count, seed + 707)
    # Exact feature and target samples never cross train/test boundaries.
    overlap = set(map(tuple, train_x.tolist())).intersection(
        map(tuple, test_x.tolist())
    )
    if overlap:
        raise RuntimeError("disjoint random draws unexpectedly overlapped")
    torch.manual_seed(seed + 202)
    model = torch.nn.Sequential(
        torch.nn.Linear(2, 32),
        torch.nn.Tanh(),
        torch.nn.Linear(32, 32),
        torch.nn.Tanh(),
        torch.nn.Linear(32, 2),
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.009, weight_decay=0.0001)
    weight = torch.tensor([1.0, 4.0])
    start = time.perf_counter()
    for _ in range(train_steps):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        pred = model(train_x)
        loss = ((pred - train_y).square() * weight).mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
    elapsed = time.perf_counter() - start
    model.eval()
    with torch.no_grad():
        predictions = model(test_x)
        absolute_error = (predictions - test_y).abs().mean(dim=0)
        worst_error = (predictions - test_y).abs().max(dim=0).values
        # Simple linear baseline uses same TRAIN data, not validation/test fitting.
        intercept_column = torch.ones((train_count, 1))
        design_train = torch.cat((intercept_column, train_x), dim=1)
        linear_coefficients = torch.linalg.lstsq(design_train, train_y).solution
        design_test = torch.cat((torch.ones((test_count, 1)), test_x), dim=1)
        linear_errors = (design_test @ linear_coefficients - test_y).abs().mean(dim=0)
        constant_errors = (train_y.mean(dim=0) - test_y).abs().mean(dim=0)
        # Deliberately out of certified state support: do not silently present
        # any neural prediction as an admitted generalization in this region.
        ood_generator = torch.Generator(device="cpu").manual_seed(seed + 909)
        ood_state = 2.5 + torch.rand((test_count, 1), generator=ood_generator)
        ood_time = torch.rand((test_count, 1), generator=ood_generator)
        ood_value, ood_z = analytic_field(
            ood_state,
            ood_time,
            slope=slope,
            intercept=intercept,
            diffusion=diffusion,
            horizon=horizon,
        )
        ood_features = torch.cat((ood_state, ood_time), dim=1)
        ood_targets = torch.cat((ood_value, ood_z), dim=1)
        ood_mae = (model(ood_features) - ood_targets).abs().mean(dim=0)
    if not all(math.isfinite(float(z)) for z in absolute_error):
        raise RuntimeError("non-finite neural outcome")
    return {
        "evidence_class": "manufactured_analytic_field_supervised_only",
        "scope": "synthetic_fbsde_affine_value_and_z_no_real_model",
        "train_samples": train_count,
        "heldout_samples": test_count,
        "train_steps": train_steps,
        "seed": seed,
        "model_parameters": sum(p.numel() for p in model.parameters()),
        "train_wall_seconds": elapsed,
        "test_value_mae": float(absolute_error[0]),
        "test_z_mae": float(absolute_error[1]),
        "test_value_max_abs_error": float(worst_error[0]),
        "test_z_max_abs_error": float(worst_error[1]),
        "linear_value_mae": float(linear_errors[0]),
        "linear_z_mae": float(linear_errors[1]),
        "constant_value_mae": float(constant_errors[0]),
        "constant_z_mae": float(constant_errors[1]),
        "ood_state_range": [2.5, 3.5],
        "ood_value_mae": float(ood_mae[0]),
        "ood_z_mae": float(ood_mae[1]),
        "ood_supported": False,
        "real_task_accuracy": None,
        "global_stochastic_fbsde_solved": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--train-steps", type=int, default=400)
    args = parser.parse_args()
    if not args.demo:
        parser.error("opt-in only: use --demo")
    print(
        json.dumps(
            experiment(seed=args.seed, train_steps=args.train_steps),
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )
