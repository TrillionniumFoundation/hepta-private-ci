"""Independent derivative, deployment-equivalence and delivered-artifact checks."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from ...v6.data import make_batch
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer, observe_tensors, read_bundle
from ...v6.plan_training import ControlledSnapshot
from .evaluate import checksum, write_json
from .protocol import PROTOCOL as P
from .train import deploy, portfolio_loss


def derivative_check():
    logits = torch.tensor([[.4, -.7, .1]], dtype=torch.float64, requires_grad=True)
    utility = torch.tensor([[[.2, .5], [-.3, .7], [.1, -.8]]], dtype=torch.float64, requires_grad=True)
    error = 0.
    for gamma in (0., 2.):
        loss = portfolio_loss(logits, utility, gamma)
        gradients = torch.autograd.grad(loss, (logits, utility))
        for which, parameter in enumerate((logits, utility)):
            for index in np.ndindex(tuple(parameter.shape)):
                upper, lower = parameter.detach().clone(), parameter.detach().clone()
                upper[index] += 1e-6
                lower[index] -= 1e-6
                other = (logits, utility)[1 - which].detach()
                arguments = ((upper, other), (lower, other)) if which == 0 else ((other, upper), (other, lower))
                numeric = (float(portfolio_loss(*arguments[0], gamma))
                           - float(portfolio_loss(*arguments[1], gamma))) / 2e-6
                error = max(error, abs(numeric - float(gradients[which][index])))
    if error > 1e-8:
        raise AssertionError("Portfolio probability/pathwise gradient is inconsistent")
    return error


def verify(assets, output):
    from ...v6.data import load_corpus
    assets, output = Path(assets), Path(output)
    torch.set_num_threads(2)
    result = json.loads((output / "RESULT.json").read_text())
    runtime = json.loads((output / "RUNTIME.json").read_text())
    executed = output / "executed-source"
    source = executed if executed.is_dir() else Path(__file__).parent
    for file, digest in runtime["source_sha256"].items():
        if checksum(source / file) != digest:
            raise ValueError("Executed source changed")
    if checksum(output / "ROWS.jsonl") != result["rows_sha256"]:
        raise ValueError("Raw outcomes changed")
    rows = [json.loads(line) for line in (output / "ROWS.jsonl").read_text().splitlines()]
    original = assets / "ndu-runs/full-002"
    corpus = load_corpus(assets / "ndu-data", evaluator_sources=10000)
    snapshot = ControlledSnapshot.load(original / "seed-17-terminal_entropic_ndu.pt")
    batch = make_batch(corpus, "train", 12, 442)
    with torch.inference_mode():
        state = snapshot.encode(batch.observation, noise_seed=881)
        expected = snapshot.decode(state)
        noise = torch.randn(12, snapshot.config["hidden"], generator=torch.Generator().manual_seed(881))
        actual, choices = deploy(snapshot._base._model, snapshot._gate, batch.observation, noise)
    if (not torch.equal(expected.token_ids, actual.token_ids)
            or not torch.equal(expected.image_logits, actual.image_logits)
            or tuple(choices.tolist()) != state.plan_indices):
        raise AssertionError("Amortized deployment differs from original ControlledSnapshot")
    observer = Recognizer().eval().requires_grad_(False)
    observer.load_state_dict(torch.load(original / "audit-observer.pt", weights_only=True))
    teacher_parameters = parameter_hash(observer)
    maximum_error, checked = 0., 0
    groups = {}
    for row in rows:
        key = (row["split"], row["corruption"], row["pair"] // 16)
        groups.setdefault(key, []).append(row)
    for (split, corruption, block), records in groups.items():
        start = block * 16
        conditions = P["test_corruptions"] if split == "test" else ["clean"]
        offset = P["test_offset"] if split == "test" else P["retention_offset"]
        source_batch = make_batch(corpus, split, 16, P["evaluation_seed"] + start + conditions.index(corruption) * 10000,
                                  corruption=corruption, offset=offset + start)
        for chunk_start in range(0, len(records), 32):
            chunk = records[chunk_start:chunk_start + 32]
            pixels, captions, indices = [], [], []
            for row in chunk:
                decoded, caption, hashes = read_bundle({k: output / v for k, v in row["artifacts"]["paths"].items()})
                if hashes != row["artifacts"]["sha256"]:
                    raise ValueError("Delivered media changed")
                index = row["pair"] - start
                if list(source_batch.source_ids[index]) != row["source_ids"] or source_batch.target.labels[index].tolist() != row["private_labels"]:
                    raise ValueError("Private scoring identity differs from original source")
                pixels.append(decoded); captions.append(caption); indices.append(index)
            audited = observe_tensors(observer, torch.cat(pixels), captions,
                                      source_batch.target.pixels[indices], source_batch.target.labels[indices])
            for row, observed in zip(chunk, audited):
                maximum_error = max(maximum_error, abs(observed["utility"] - row["audit"]["utility"]))
                if observed["image_digits"] != row["audit"]["image_digits"]:
                    raise AssertionError("Audit decoder predictions changed")
                checked += 1
    if maximum_error > 1e-7 or teacher_parameters != parameter_hash(observer):
        raise AssertionError("Independent raw-output rescoring failed")
    training = json.loads((output / "TRAINING.json").read_text())
    for entry in training:
        if not all(entry["parameter_changes"].values()) or not entry["gate_changed"]:
            raise AssertionError("Generator/encoder/transition/gate did not all update")
        path = output / f"seed-{entry['seed']}-{entry['arm']}.pt"
        if checksum(path) != entry["checkpoint_sha256"]:
            raise ValueError("Trained checkpoint changed")
        ControlledSnapshot.load(path).verify_integrity()
    receipt = {"source_pins_unchanged": True, "portfolio_gradient_max_error": derivative_check(),
               "original_snapshot_deployment_bitwise_equal": True, "actual_deliveries_reaudited": checked,
               "maximum_audit_utility_error": maximum_error, "all_generator_components_and_gate_changed": True,
               "checkpoint_reload_integrity": True, "checks_passed": True,
               "scientific_acceptance_is_separate": result["registered_acceptance_passed"]}
    write_json(output / "INDEPENDENT_AUDIT.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.assets, args.output)
