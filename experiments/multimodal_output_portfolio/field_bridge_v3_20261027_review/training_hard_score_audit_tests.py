"""Synthetic target reconstruction, grouped observer and tampering contracts."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_v3_20261027.learning import panels
from ..field_bridge_v3_20261027.training_stages import panel_identity
from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import observe_tensors
from . import training_hard_score_audit as audit


class BatchSensitiveObserver(torch.nn.Module):
    def __init__(self, offset):
        super().__init__()
        self.register_buffer("offset", torch.tensor(offset))
        self.batch_sizes = []

    def forward(self, image):
        self.batch_sizes.append(len(image))
        values = image.flatten(1).mean(1)
        result = torch.stack([values * (index - 4) for index in range(10)], dim=1)
        result[:, (len(image) + int(self.offset)) % 10] += 20
        return result


def fixture():
    splits = {}
    rng = torch.Generator().manual_seed(271045)
    for role, count in (("development_task", 10), ("development_clean", 8)):
        images = torch.randint(256, (count, 1, 28, 28), generator=rng, dtype=torch.uint8)
        labels = torch.randint(10, (count,), generator=rng)
        hashes = tuple(hashlib.sha256(row.numpy().tobytes()).hexdigest() for row in images)
        identities = tuple(f"synthetic-score:{role}:{i}:{value}" for i, value in enumerate(hashes))
        splits[role] = SourceSplit(images, labels, identities, hashes)
    return SourceCorpus(splits, {"synthetic_only": True})


def observers():
    return {name: BatchSensitiveObserver(offset).eval().requires_grad_(False)
            for name, offset in zip(audit.OBSERVERS, (0, 3), strict=True)}


def arithmetic(models):
    return audit.GroupedObserver(models, {name: audit.parameter_identity(model) for name, model in models.items()})


def reject(call):
    try:
        call()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("Expected independent hard-score audit rejection")


def hard_arrays(panel, models, charge):
    rng = np.random.default_rng(271046)
    pixels, captions, values = [], [], {name: [] for name in models}
    for part in panel:
        image = rng.integers(0, 256, (part["rows"], 1, 28, 56), dtype=np.uint8)
        labels = part["target"]["labels"].tolist()
        text = [f"left {left} right {right} relation {'less' if left < right else 'greater' if left > right else 'equal'}"
                for left, right in labels]
        text[-1] = "malformed synthetic caption"
        for name, model in models.items():
            expected = observe_tensors(model, torch.from_numpy(image.copy()).float() / 255, text,
                                      part["target"]["pixels"], part["target"]["labels"])
            values[name].extend(row["utility"] - charge for row in expected)
        pixels.append(image)
        captions.extend(text)
    image = np.concatenate(pixels)
    return {"pixels_u8": image, "captions_utf8": np.asarray(captions),
        "source_ids": np.asarray([pair for part in panel for pair in part["source_ids"]]),
        "conditions": np.asarray([part["condition"] for part in panel for _ in range(part["rows"])]),
        "output_sha256": np.asarray([hashlib.sha256(row.tobytes() + caption.encode()).hexdigest()
            for row, caption in zip(image, captions, strict=True)]),
        **{"values_" + name: np.asarray(value, dtype=np.float64) for name, value in values.items()}}


def run(out):
    started = time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads(Path(audit.__file__).parent.parent.joinpath("field_bridge_v3_20261027/PROTOCOL.json").read_text())
    protocol["training"]["panel_batch_size"] = 3
    corpus = fixture()
    checked_batches, guards, verified_files = 0, 0, []
    for role in corpus.splits:
        conditions = protocol["training"]["conditions"] if role.endswith("task") else ["clean"]
        original = panels(corpus, role, 17, conditions, protocol)
        # The audited artifact is JSON; production's in-memory tuples become
        # lists when ENDPOINT_IDENTITIES.json is written and reopened.
        identity = json.loads(json.dumps(panel_identity(original)))
        rebuilt = audit.rebuild_panel(corpus.splits[role], role, 17, conditions, protocol["training"], identity)
        checked_batches += len(rebuilt)
        for expected, actual in zip(original, rebuilt, strict=True):
            for group, names in (("observation", audit.OBSERVATION_FIELDS), ("target", audit.TARGET_FIELDS)):
                found = actual["public" if group == "observation" else "target"]
                assert all(torch.equal(getattr(getattr(expected.batch, group), name), found[name]) for name in names)
        corrupted = copy.deepcopy(identity)
        corrupted["batches"][0]["target_sha256"] = "0" * 64
        reject(lambda: audit.rebuild_panel(corpus.splits[role], role, 17, conditions, protocol["training"], corrupted))
        guards += 1
        models, charge = observers(), .004
        arrays = hard_arrays(rebuilt, models, charge)
        file = out / f"{role}.npz"
        np.savez_compressed(file, **arrays)
        verifier = arithmetic(models)
        expected_values = np.stack([arrays["values_" + name] for name in audit.OBSERVERS])
        receipt = audit.verify_hard(file, rebuilt, expected_values, verifier, charge)
        assert receipt["exact"] and receipt["maximum_value_error"] == 0
        counts_before = copy.deepcopy(verifier.costs())
        audit.verify_hard(file, rebuilt, expected_values, verifier, charge)
        counts_after = verifier.costs()
        assert counts_before["actual_observer_batch_calls"] == counts_after["actual_observer_batch_calls"]
        assert all(counts_after["logical_observer_batch_calls"][name] == 4 * len(rebuilt) for name in models)
        assert all(counts_after["observer_batch_cache_hits"][name] == len(rebuilt) for name in models)
        sample = rebuilt[0]
        n = sample["rows"]
        baseline, primitive = verifier.score(arrays["pixels_u8"][:n], arrays["captions_utf8"][:n], sample["target"], "reward", charge)
        alternate = {**sample["target"], "pixels": 1 - sample["target"]["pixels"]}
        changed, _ = verifier.score(arrays["pixels_u8"][:n], arrays["captions_utf8"][:n], alternate, "reward", charge)
        assert not np.array_equal(changed, baseline)
        assert np.all(primitive["image_digits"] == n % 10)
        for name, mutate in (
            ("value", lambda d: d["values_reward"].__setitem__(0, d["values_reward"][0] + .01)),
            ("hash", lambda d: d["output_sha256"].__setitem__(0, "0" * 64)),
            ("source", lambda d: d["source_ids"].__setitem__((0, 0), "foreign-source")),
            ("condition", lambda d: d["conditions"].__setitem__(0, "wrong")),
        ):
            bad = copy.deepcopy(arrays)
            mutate(bad)
            corrupted_file = out / f"{role}-corrupt-{name}.npz"
            np.savez_compressed(corrupted_file, **bad)
            reject(lambda: audit.verify_hard(corrupted_file, rebuilt, expected_values, verifier, charge))
            guards += 1
        bad = copy.deepcopy(arrays)
        bad["pixels_u8"][0].fill(0)
        bad["output_sha256"][0] = hashlib.sha256(bad["pixels_u8"][0].tobytes() + str(bad["captions_utf8"][0]).encode()).hexdigest()
        corrupted_file = out / f"{role}-rehashed-pixel-tamper.npz"
        np.savez_compressed(corrupted_file, **bad)
        reject(lambda: audit.verify_hard(corrupted_file, rebuilt, expected_values, verifier, charge))
        guards += 1
        reject(lambda: audit.verify_hard(file, rebuilt, expected_values, verifier, .002))
        guards += 1
        verified_files.append({"role": role, "rows": receipt["rows"], "batch_sizes": receipt["batch_sizes"], "exact": True})
    models = observers()
    reject(lambda: audit.GroupedObserver(models, {name: "0" * 64 for name in models}))
    guards += 1
    reject(lambda: audit.audit(out / "uncompleted", "development", out / "no-source", out / "no-freeze", out / "no-assets"))
    guards += 1
    result = {"schema": "hepta.field-bridge.v3.training-hard-score-audit-contract.1", "passed": True,
        "synthetic_only": True, "real_outcomes_or_registered_source_roles_opened": False,
        "source_panel_batches_rebuilt": checked_batches, "panels": verified_files, "corruption_or_boundary_rejections": guards,
        "all_target_and_public_tensors_exact": True, "grouped_observer_and_utility_values_exact": True,
        "incomplete_remainder_batches_verified": True, "cache_recomputes_target_dependent_scores": True,
        "actual_grouping_exercised_by_batch_sensitive_observer": True,
        "generator_forward_calls": 0, "auditor_source_sha256": audit.digest(audit.__file__),
        "test_source_sha256": audit.digest(__file__), "wall_ns": time.perf_counter_ns() - started}
    path = out / "TRAINING_HARD_SCORE_AUDIT_CONTRACT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"passed": True, "guards": guards, "receipt_sha256": audit.digest(path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.out)
