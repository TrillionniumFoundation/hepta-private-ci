"""Training worker: only original TRAIN/VAL prefixes; never fresh-test inference."""

import argparse
import hashlib
from pathlib import Path
import time

import numpy as np
import torch

from .native003_common import (PACKAGE, PROTOCOL_PATH, load_backbone, read_json,
                               sha, verify_freeze, write_new)
from .native003_heads import (FAMILIES, StopHead, append_price, hard_decisions,
                              observed_features, soft_utility)
from .training import load_weights, save_weights


def trace_split(model, data_path, split, count, output):
    start = time.process_time(), time.perf_counter()
    with np.load(data_path, allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive[f"{split}_x"][:count], copy=True))
        dt = torch.from_numpy(np.array(archive[f"{split}_dt"][:count], copy=True))
        labels = torch.from_numpy(np.array(archive[f"{split}_y"][:count, -1], copy=True))
    observed, predictions = [], []
    for first in range(0, count, 32):
        batch_x, batch_dt = x[first:first + 32], dt[first:first + 32]
        with torch.no_grad():
            logits, aux = model(batch_x, batch_dt, return_sequence=True)
            features = observed_features(logits, aux, batch_dt.cumsum(1))
        if not torch.isfinite(features).all():
            raise FloatingPointError("Nonfinite causal prefix features")
        observed.append(features)
        predictions.append(logits.argmax(-1))
    observed, predictions = torch.cat(observed), torch.cat(predictions)
    correct = (predictions == labels[:, None]).to(torch.float32)
    path = Path(output) / f"{split}.npz"
    np.savez_compressed(path, observed=observed.numpy(), correct=correct.numpy(),
                        predictions=predictions.numpy(), labels=labels.numpy())
    receipt = {"split": split, "episodes": count, "prefixes": count * x.shape[1],
               "source_dataset_sha256": sha(data_path), "trace_sha256": sha(path),
               "parent_cpu_seconds": time.process_time() - start[0],
               "wall_seconds": time.perf_counter() - start[1],
               "generation": "Causal whole-sequence forward in batches32; all prefixes precomputed and fully charged to training, not inference savings"}
    return observed, correct, receipt


def priced_bank(observed, correct, prices):
    features = torch.cat([append_price(observed, price) for price in prices])
    reward = correct.repeat(len(prices), 1)
    costs = torch.cat([torch.full((len(observed),), price) for price in prices])
    return features, reward, costs


def validation_metrics(head, bank, prices):
    with torch.no_grad():
        scores = head(bank[0])
        if not torch.isfinite(scores).all():
            raise FloatingPointError("Nonfinite validation score")
        result = hard_decisions(scores, bank[1], bank[2])
        by_price = {}
        for price in prices:
            mask = bank[2] == price
            by_price[str(price)] = {"accuracy": result["correct"][mask].mean().item(),
                                    "mean_reads": result["reads"][mask].float().mean().item(),
                                    "mean_utility": result["utility"][mask].mean().item()}
        mean_utility = sum(row["mean_utility"] for row in by_price.values()) / len(prices)
    return {"mean_utility": mean_utility, "by_price": by_price}


def train_candidate(family, learning_rate, train, validation, normalization, protocol, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    options = protocol["optimization"]
    head = StopHead(family, normalization["mean"], normalization["std"], options["seed"])
    expected = protocol["heads"][family]["trainable_parameters"]
    if head.parameter_count() != expected:
        raise ValueError("Actual head parameter count differs from frozen contract")
    initial = {name: value.detach().clone() for name, value in head.named_parameters()}
    ever_nonzero = {name: torch.zeros_like(value, dtype=torch.bool) for name, value in head.named_parameters()}
    optimizer = torch.optim.Adam(head.parameters(), lr=learning_rate)
    generator = torch.Generator().manual_seed(options["seed"] + 200003)
    batch_prefix = hashlib.sha256()
    save_weights(output / "initial.npz", head)
    checkpoints, update_cpu, validation_cpu = [], 0.0, 0.0
    with (output / "updates.jsonl").open("x") as log:
        for step in range(1, options["updates_per_learning_rate"] + 1):
            update_start = time.process_time()
            indices = torch.randint(len(train[0]), (options["batch_size"],), generator=generator)
            batch_prefix.update(indices.numpy().tobytes())
            head.train()
            optimizer.zero_grad(set_to_none=True)
            scores = head(train[0][indices])
            utility, mass = soft_utility(scores, train[1][indices], train[2][indices], options["temperature"])
            loss = -utility.mean()
            if not torch.isfinite(loss) or not torch.allclose(mass.sum(1), torch.ones_like(loss).expand(len(indices)), atol=2e-5, rtol=0):
                raise FloatingPointError("Invalid soft stopping objective or first-stop probability mass")
            loss.backward()
            gradients = {}
            for name, parameter in head.named_parameters():
                if parameter.grad is None or not torch.isfinite(parameter.grad).all():
                    raise FloatingPointError(f"Missing/nonfinite head gradient: {name}")
                ever_nonzero[name] |= parameter.grad != 0
                gradients[name] = {"l2": parameter.grad.norm().item(), "max_abs": parameter.grad.abs().max().item()}
            torch.nn.utils.clip_grad_norm_(head.parameters(), options["gradient_clip_l2"])
            optimizer.step()
            update_cpu += time.process_time() - update_start
            import json
            log.write(json.dumps({"step": step, "negative_expected_utility": loss.item(),
                                  "gradients": gradients, "batch_prefix_sha256": batch_prefix.hexdigest()}, sort_keys=True) + "\n")
            if step in options["checkpoints"]:
                validation_start = time.process_time()
                head.eval()
                metrics = validation_metrics(head, validation, protocol["execution"]["read_prices"])
                validation_cpu += time.process_time() - validation_start
                filename = f"step{step:04d}.npz"
                digest = save_weights(output / filename, head)
                checkpoints.append({"step": step, "weights": filename, "sha256": digest, "validation": metrics})
    best = min(checkpoints, key=lambda item: (-item["validation"]["mean_utility"], item["step"]))
    final_changes = {name: (value.detach() - initial[name]).norm().item() for name, value in head.named_parameters()}
    load_weights(output / best["weights"], head)
    selected_changes = {name: (value.detach() - initial[name]).norm().item() for name, value in head.named_parameters()}
    routing = None
    if family == "value_maxout":
        with torch.no_grad():
            _, branches = head(train[0], return_branches=True)
            routing = torch.bincount(branches.argmax(-1).flatten(), minlength=4).tolist()
    result = {"family": family, "learning_rate": learning_rate, "seed": options["seed"],
              "parameters": head.parameter_count(), "updates": options["updates_per_learning_rate"],
              "training_update_cpu_seconds": update_cpu, "validation_cpu_seconds": validation_cpu,
              "checkpoints": checkpoints, "best": best, "batch_prefix_sha256": batch_prefix.hexdigest(),
              "ever_nonzero_gradient_elements": {name: int(value.sum()) for name, value in ever_nonzero.items()},
              "total_ever_nonzero_gradient_elements": sum(int(value.sum()) for value in ever_nonzero.values()),
              "final_parameter_change_l2": final_changes, "selected_parameter_change_l2": selected_changes,
              "selected_train_branch_winner_counts": routing,
              "parent_cpu_seconds": time.process_time() - start[0], "wall_seconds": time.perf_counter() - start[1]}
    write_new(output / "SUMMARY.json", result)
    return result


def run_training(output):
    output = Path(output)
    verify_freeze(output)
    protocol = read_json(PROTOCOL_PATH)
    torch.set_num_threads(1)
    model, backbone = load_backbone(protocol)
    traces = output / "traces"
    traces.mkdir(parents=True, exist_ok=False)
    data = PACKAGE / "data/study001/mnist.npz"
    train_x, train_correct, train_receipt = trace_split(model, data, "train", 256, traces)
    val_x, val_correct, val_receipt = trace_split(model, data, "val", 128, traces)
    prices = protocol["execution"]["read_prices"]
    train = priced_bank(train_x, train_correct, prices)
    validation = priced_bank(val_x, val_correct, prices)
    flattened = train[0].reshape(-1, 6)
    mean = flattened.double().mean(0).float()
    std = flattened.double().std(0, correction=0).clamp_min(1e-4).float()
    normalization = {"fit_split": "original_train_first256_only", "mean": mean.tolist(), "std": std.tolist(),
                     "public_prices": prices, "feature_count": 6}
    write_new(traces / "NORMALIZATION.json", normalization)
    write_new(traces / "TRACE_RECEIPTS.json", {"train": train_receipt, "val": val_receipt, "backbone": backbone})
    summaries = {}
    for family in FAMILIES:
        family_started = time.process_time()
        folder = output / "head_search" / family
        folder.mkdir(parents=True, exist_ok=False)
        candidates = []
        for index, rate in enumerate(protocol["optimization"]["learning_rates"]):
            directory = f"lr{index}"
            result = train_candidate(family, rate, train, validation, normalization, protocol, folder / directory)
            result["directory"] = directory
            candidates.append(result)
        winner = min(candidates, key=lambda item: (-item["best"]["validation"]["mean_utility"],
                                                   item["best"]["step"], item["learning_rate"]))
        import shutil
        selected = folder / winner["directory"] / winner["best"]["weights"]
        shutil.copyfile(selected, folder / "selected.npz")
        selection = {"family": family, "seed": protocol["optimization"]["seed"],
                     "completed_candidates": len(candidates), "selected_learning_rate": winner["learning_rate"],
                     "selected_step": winner["best"]["step"], "validation": winner["best"]["validation"],
                     "selected_checkpoint_sha256": sha(folder / "selected.npz"),
                     "selection_rule": protocol["optimization"]["selection"],
                     "fresh_test_predictions_available": False}
        if selection["selected_checkpoint_sha256"] != winner["best"]["sha256"]:
            raise ValueError("Selected head checkpoint identity mismatch")
        write_new(folder / "selection.json", selection)
        summaries[family] = {"selection": selection, "candidates": candidates,
                             "family_search_parent_cpu_seconds": time.process_time() - family_started}
        write_new(folder / "SUMMARY.json", summaries[family])
    verify_freeze(output)
    result = {"status": "completed", "heads": summaries, "backbone": backbone,
              "trace_receipts": {"train": train_receipt, "val": val_receipt},
              "fresh_test_inference_performed": False, "head_selections_locked": True}
    write_new(output / "TRAINING_SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_training(args.output)
