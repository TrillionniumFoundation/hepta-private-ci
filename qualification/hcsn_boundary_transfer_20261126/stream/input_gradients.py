"""Measure input derivatives on nine frozen occupancy checkpoints without fitting."""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import torch

ARMS = ("qvi_raw", "qvi_centered", "fixed_centered")
SEEDS = (601, 1601, 2601)
ARCHIVE_SHA256 = "8cf1d68f5c8924ff415d9efcb134921b302b268a24c2f03c365c1cf7c706e182"


def quantiles(values):
    probabilities = torch.tensor([0.0, 0.5, 1.0], dtype=torch.double)
    return torch.quantile(torch.cat(values).double(), probabilities).tolist()


def evaluate(model, sequence, delivered_boundary):
    ranks = Counter()
    norms = []
    logit_first_frame = []
    logit_last_frame = []
    for batch in sequence.split(16, dim=1):
        frame = batch[:1].detach().requires_grad_()
        _, _, state = model(frame, return_features=True)
        delivered = delivered_boundary(state.message, model.boundary_reference, model.boundary_mode, state.step)
        sender = delivered[:, 0, :16]
        rows = []
        for unit in range(sender.shape[-1]):
            if sender.requires_grad:
                grad = torch.autograd.grad(
                    sender[:, unit].sum(), frame, allow_unused=True, retain_graph=True
                )[0]
            else:
                grad = None
            rows.append(torch.zeros_like(frame[0, :, :5]) if grad is None else grad[0, :, :5])
        jacobian = torch.stack(rows, dim=1).double()
        if not torch.isfinite(jacobian).all():
            raise ValueError("Non-finite sender derivative")
        ranks.update(torch.linalg.matrix_rank(jacobian).tolist())
        norms.append(torch.linalg.matrix_norm(jacobian, ord="fro"))

        inputs = batch.detach().requires_grad_()
        final_logits = model(inputs)[-1]
        margin = final_logits[:, 1] - final_logits[:, 0]
        grad = torch.autograd.grad(margin.sum(), inputs)[0]
        if not torch.isfinite(grad).all():
            raise ValueError("Non-finite classification derivative")
        logit_first_frame.append(torch.linalg.vector_norm(grad[0, :, :5], dim=-1))
        logit_last_frame.append(torch.linalg.vector_norm(grad[-1, :, :5], dim=-1))
    return {
        "first_sender_matrix_rank": dict(sorted(ranks.items())),
        "sender_frobenius_min_median_max": quantiles(norms),
        "final_logit_margin_first_frame_gradient_norm_min_median_max": quantiles(logit_first_frame),
        "final_logit_margin_last_frame_gradient_norm_min_median_max": quantiles(logit_last_frame),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--study", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    sys.path.insert(0, str(args.study.resolve()))
    from run import load_data, model_for
    from qualification.hcsn_closure_20261124.boundary_fix import delivered_boundary

    torch.set_num_threads(1)
    archive_hash = hashlib.sha256(args.weights.read_bytes()).hexdigest()
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError("Expected the original fixed-128 checkpoint archive")
    inputs = load_data(args.data, {"train", "test"})["test"][0]
    if tuple(inputs.shape) != (8, 224, 6):
        raise ValueError("Expected the original 224 eight-frame windows")
    results = {}
    with zipfile.ZipFile(args.weights) as archive:
        for arm in ARMS:
            for seed in SEEDS:
                name = f"{arm}-{seed}"
                payload = archive.read(f"campaign/{name}/selected.pt")
                model = model_for(arm)
                weights = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
                model.load_state_dict(weights, strict=True)
                model.eval().requires_grad_(False)
                results[name] = evaluate(model, inputs, delivered_boundary)
                results[name]["weight_sha256"] = hashlib.sha256(payload).hexdigest()
    print(json.dumps({
        "design": "Post-hoc. Mixed precision model, CPU PyTorch reverse mode through original forward. Derivatives are with respect to standardized post-clipping inputs. Batch members evolve independently.",
        "rank_definition": "PyTorch matrix_rank of double-cast 16x5 native gradients, using its default numerical threshold.",
        "torch_version": str(torch.__version__),
        "num_windows": inputs.shape[1],
        "sequence_length": inputs.shape[0],
        "archive_sha256": archive_hash,
        "results": results,
    }, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
