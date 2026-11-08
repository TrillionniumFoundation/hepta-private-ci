"""Count active real degrees of freedom and retain official optimizer groups."""

import argparse
import math
from pathlib import Path

import torch

from data import save
from models import ARMS, build_model


def parameter_audit(model, probe=None):
    """Count actual parameters, with an optional label-free connectivity probe.

    A connected zero gradient is retained: silence/saturation is not padding.
    Connectivity alone cannot certify identifiability of every scalar; adapters
    use actual width dimensions, with no masked or extra padding parameters.
    """
    records, storage = [], set()
    for name, value in model.named_parameters():
        identity = (value.device, value.untyped_storage().data_ptr())
        if identity in storage:
            raise ValueError(
                "aliased parameter storage cannot be independently counted"
            )
        storage.add(identity)
        records.append(
            {
                "name": name,
                "shape": list(value.shape),
                "real_scalars": value.numel() * (2 if value.is_complex() else 1),
                "trainable": value.requires_grad,
            }
        )
    active = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    disconnected = None
    if probe is not None:
        mode = model.training
        try:
            model.train()  # Avoid inference fast paths that omit autograd edges.
            output = model(*probe)
            if not bool(torch.isfinite(output).all()):
                raise ValueError("nonfinite capacity probe output")
            gradients = torch.autograd.grad(
                output.square().sum(), [p for _, p in active], allow_unused=True
            )
            disconnected = [
                name for (name, _), grad in zip(active, gradients) if grad is None
            ]
            if any(
                grad is not None and not bool(torch.isfinite(grad).all())
                for grad in gradients
            ):
                raise ValueError("nonfinite capacity probe gradient")
        finally:
            model.train(mode)
    return {
        "parameters": records,
        "trainable_real_scalars": sum(
            r["real_scalars"] for r in records if r["trainable"]
        ),
        "frozen_real_scalars": sum(
            r["real_scalars"] for r in records if not r["trainable"]
        ),
        "disconnected_parameters": disconnected,
        "scalar_identifiability_qualified": False,
        "scope": "unique registered parameters; complex entries count as two real scalars",
    }


def match_width(arm, target, widths, *, s4_repo=None, tolerance=0.05):
    """Choose by exact counts only, before any label scoring; no padding/fallback."""
    if (
        type(target) is not int
        or target < 1
        or not math.isfinite(tolerance)
        or not 0 <= tolerance <= 0.05
    ):
        raise ValueError("positive integer target and tolerance in [0, .05] required")
    widths = list(widths)
    if not widths or len(widths) != len(set(widths)):
        raise ValueError("supply a nonempty unique width roster")
    candidates = []
    with torch.random.fork_rng(devices=[]):
        for width in widths:
            model = build_model(arm, s4_repo=s4_repo, width=width)
            count = parameter_audit(model)["trainable_real_scalars"]
            candidates.append(
                {
                    "width": width,
                    "trainable_real_scalars": count,
                    "relative_error": abs(count - target) / target,
                }
            )
    eligible = [row for row in candidates if row["relative_error"] <= tolerance]
    selected = (
        min(
            eligible,
            key=lambda row: (
                row["relative_error"],
                row["trainable_real_scalars"],
                row["width"],
            ),
        )
        if eligible
        else None
    )
    return {
        "arm": arm,
        "target_real_scalars": target,
        "tolerance": tolerance,
        "candidates": candidates,
        "selected": selected,
        "target_provenance_verified": False,
        "scope": "count matching only; target must separately bind an admitted HCSN source/configuration",
    }


def adamw(model, learning_rate, weight_decay):
    """Apply pinned S4 parameter hints; reject unknown or invalid hints."""
    if (
        not math.isfinite(learning_rate)
        or learning_rate <= 0
        or not math.isfinite(weight_decay)
        or weight_decay < 0
    ):
        raise ValueError("invalid AdamW hyperparameters")
    groups, receipts = {}, {}
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        hints = getattr(parameter, "_optim", {})
        if not isinstance(hints, dict) or set(hints) - {"lr", "weight_decay"}:
            raise ValueError(f"unsupported official optimizer hints for {name}")
        lr, decay = (
            hints.get("lr", learning_rate),
            hints.get("weight_decay", weight_decay),
        )
        if not math.isfinite(lr) or lr <= 0 or not math.isfinite(decay) or decay < 0:
            raise ValueError(f"invalid official optimizer hints for {name}")
        key = (lr, decay)
        groups.setdefault(key, []).append(parameter)
        receipts.setdefault(key, []).append(name)
    if not groups:
        raise ValueError("no trainable parameters")
    optimizer = torch.optim.AdamW(
        [
            {"params": ps, "lr": lr, "weight_decay": decay}
            for (lr, decay), ps in groups.items()
        ]
    )
    return optimizer, [
        {"lr": lr, "weight_decay": decay, "parameter_names": receipts[(lr, decay)]}
        for lr, decay in groups
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-real-scalars", type=int, required=True)
    parser.add_argument("--minimum-width", type=int, default=2)
    parser.add_argument("--maximum-width", type=int, default=128)
    parser.add_argument("--s4-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.minimum_width <= args.maximum_width <= 4096:
        parser.error("invalid bounded width roster")
    torch.set_num_threads(1)
    results = []
    for arm in ARMS:
        widths = [
            width
            for width in range(args.minimum_width, args.maximum_width + 1)
            if arm != "attention" or width % 2 == 0
        ]
        result = match_width(
            arm, args.target_real_scalars, widths, s4_repo=args.s4_repo
        )
        if result["selected"] is not None:
            model = build_model(
                arm, s4_repo=args.s4_repo, width=result["selected"]["width"]
            )
            generator = torch.Generator().manual_seed(0)
            probe = (
                torch.randn(1, 4, 25, generator=generator, dtype=torch.float64),
                torch.full((1, 4), 0.01, dtype=torch.float64),
            )
            result["selected_audit"] = parameter_audit(model, probe)
        results.append(result)
    save(
        args.output,
        {
            "schema": "hcsn-localization-capacity-roster-v1",
            "arms": results,
            "scientific_admission": "HOLD",
            "target_provenance_verified": False,
        },
    )
    return (
        0
        if all(
            row["selected"] is not None
            and not row["selected_audit"]["disconnected_parameters"]
            for row in results
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
