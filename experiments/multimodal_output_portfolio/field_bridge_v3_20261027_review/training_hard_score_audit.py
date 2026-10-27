"""Independent observer/utility truth for retained V3 training endpoints.

This verifier regenerates only public/target input panels and observer scores.
It never constructs or runs a generator, changes a policy, or selects an outcome.
Ordered batch boundaries exactly match the frozen hard_panel implementation.
"""

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import torch

from .native_session_audit import SEEDS, array_digest, bound, digest, inventory, member, read, require


OBSERVERS = ("reward", "audit")
CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")
MODES = ("field", "generic", "richer", "h7")
OBSERVATION_FIELDS = ("pixels", "mask", "text_tokens")
TARGET_FIELDS = ("pixels", "text_tokens", "labels")


def parameter_identity(model):
    value = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        tensor = tensor.detach().cpu().contiguous()
        value.update(name.encode())
        value.update(str(tensor.dtype).encode())
        value.update(str(tuple(tensor.shape)).encode())
        value.update(tensor.numpy().tobytes())
    return value.hexdigest()


def tensor_identity(values, fields):
    return hashlib.sha256(b"".join(values[name].contiguous().numpy().tobytes() for name in fields)).hexdigest()


def rebuild_batch(source, offset, count, seed, condition):
    """Reconstruct the source-pair instruction, side swap, mask and target."""
    require(offset >= 0 and count > 0 and 2 * (offset + count) <= len(source), "Invalid endpoint source range")
    rng = torch.Generator().manual_seed(int(seed))
    left, right = torch.arange(2 * offset, 2 * (offset + count), 2), torch.arange(2 * offset + 1, 2 * (offset + count), 2)
    pixels = torch.cat((source.images[left], source.images[right]), dim=3).float() / 255
    original_labels = torch.stack((source.labels[left], source.labels[right]), dim=1)
    swapped = torch.randint(2, (count,), generator=rng).bool()
    target_pixels, target_labels = pixels.clone(), original_labels.clone()
    target_pixels[swapped] = torch.cat((pixels[swapped, :, :, 28:], pixels[swapped, :, :, :28]), dim=3)
    target_labels[swapped] = target_labels[swapped].flip(1)
    caption_tokens = torch.tensor([1, 3, 0, 4, 0, 5, 0, 2]).repeat(count, 1)
    caption_tokens[:, 2], caption_tokens[:, 4] = target_labels[:, 0] + 14, target_labels[:, 1] + 14
    caption_tokens[:, 6] = torch.sign(target_labels[:, 0] - target_labels[:, 1]) + 7
    tokens = torch.tensor([1, 9, 12, 11, 13, 11, 2, 0]).repeat(count, 1)
    tokens[:, 1] = 9 + swapped.long()
    mask = torch.ones_like(pixels)
    scale = {"clean": 0., "occlusion": .08, "missing": .08, "heavy_noise": .4}[condition]
    if condition != "clean":
        side = torch.randint(2, (count,), generator=rng)
        missing = torch.ones(count, dtype=torch.bool) if condition == "missing" else torch.rand(count, generator=rng) < 0.
        for index in range(count):
            if missing[index]:
                selected = int(side[index])
                mask[index, :, :, 28 * selected:28 * (selected + 1)] = 0
                tokens[index, 3 + 2 * selected] = original_labels[index, selected] + 14
            else:
                width = 11 if condition == "occlusion" else 6
                row = int(torch.randint(0, 29 - width, (), generator=rng))
                column = int(torch.randint(0, 57 - width, (), generator=rng))
                mask[index, :, row:row + width, column:column + width] = 0
    public_pixels = (pixels + scale * torch.randn(pixels.shape, generator=rng)).clamp(0, 1) * mask
    return {"public": {"pixels": public_pixels, "mask": mask, "text_tokens": tokens},
            "target": {"pixels": target_pixels, "text_tokens": caption_tokens, "labels": target_labels},
            "source_ids": [[source.ids[int(i)], source.ids[int(j)]] for i, j in zip(left, right, strict=True)]}


def rebuild_panel(source, role, seed, conditions, p, expected):
    result, metadata = [], []
    count = len(source) // 2
    role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
    for condition_index, condition in enumerate(conditions):
        for offset in range(0, count, p["panel_batch_size"]):
            rows = min(p["panel_batch_size"], count - offset)
            common = seed * 1009 + role_seed + condition_index * 1000003 + offset
            batch = rebuild_batch(source, offset, rows, p["panel_seed_offset"] + common, condition)
            record = {"condition": condition, "noise_seed": p["hard_forward_seed_offset"] + common,
                "batch_size": rows, "source_ids": batch["source_ids"],
                "public_sha256": tensor_identity(batch["public"], OBSERVATION_FIELDS),
                "target_sha256": tensor_identity(batch["target"], TARGET_FIELDS)}
            metadata.append(record)
            result.append({**batch, "condition": condition, "rows": rows})
    require(expected == {"batches": metadata, "sha256": bound(metadata), "independent_of_schedule_id": True},
            "Rebuilt panel source ordering, RNG, public bytes, target bytes or batching differs")
    return result


class GroupedObserver:
    """Score complete ordered batches; cache only observer digits for exact bytes."""

    def __init__(self, observers, expected_identities, cache_size=512):
        require(tuple(observers) == OBSERVERS and all(not o.training and not any(p.requires_grad for p in o.parameters())
                for o in observers.values()), "Two frozen observers in reward,audit order are required")
        self.observers, self.identities = observers, expected_identities
        require({name: parameter_identity(model) for name, model in observers.items()} == expected_identities,
                "Observer parameter identity differs before verification")
        self.cache, self.cache_size = OrderedDict(), cache_size
        self.logical_calls = {name: 0 for name in observers}
        self.logical_examples = {name: 0 for name in observers}
        self.actual_calls = {name: 0 for name in observers}
        self.actual_examples = {name: 0 for name in observers}
        self.hits = {name: 0 for name in observers}

    @torch.inference_mode()
    def score(self, pixels_u8, captions, target, observer, charge):
        pixels_u8 = np.asarray(pixels_u8)
        n = len(pixels_u8)
        require(pixels_u8.dtype == np.uint8 and pixels_u8.shape == (n, 1, 28, 56) and len(captions) == n
                and tuple(target["pixels"].shape) == (n, 1, 28, 56) and tuple(target["labels"].shape) == (n, 2),
                "Invalid retained image/caption/target dimensions")
        image = torch.from_numpy(np.array(pixels_u8, copy=True)).float() / 255
        key = (observer, self.identities[observer], n, hashlib.sha256(pixels_u8.tobytes()).hexdigest())
        self.logical_calls[observer] += 2
        self.logical_examples[observer] += 2 * n
        if key in self.cache:
            digits = self.cache.pop(key)
            self.hits[observer] += 1
        else:
            left = self.observers[observer](image[:, :, :, :28]).argmax(1)
            right = self.observers[observer](image[:, :, :, 28:]).argmax(1)
            digits = torch.stack((left, right), dim=1).numpy().copy()
            self.actual_calls[observer] += 2
            self.actual_examples[observer] += 2 * n
        self.cache[key] = digits
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        mse = (image - target["pixels"]).square().flatten(1).mean(1).double().numpy()
        labels = target["labels"].numpy()
        parsed, relation, valid = np.full((n, 2), -1, dtype=np.int64), np.full(n, -2), np.zeros(n, dtype=bool)
        for index, caption in enumerate(captions):
            match = CAPTION.fullmatch(str(caption).strip())
            if match:
                parsed[index] = int(match[1]), int(match[2])
                relation[index] = {"less": -1, "equal": 0, "greater": 1}[match[3]]
                valid[index] = True
        fields = {"text_fact": np.where(valid, (parsed != labels).mean(1), 1.),
            "relation": np.where(valid, relation != np.sign(labels[:, 0] - labels[:, 1]), 1.).astype(np.float64),
            "image_fact": (digits != labels).mean(1),
            "crossmodal_disagreement": np.where(valid, (parsed != digits).mean(1), 1.), "pixel_mse": mse}
        weights = {"text_fact": .30, "relation": .15, "image_fact": .35, "crossmodal_disagreement": .10, "pixel_mse": .10}
        # Python3.12 sum uses compensated float summation. Preserve the frozen
        # observer's Python scalar arithmetic rather than a NumPy reduction.
        loss = np.fromiter((sum(weights[name] * float(value[index]) for name, value in fields.items())
                            for index in range(n)), dtype=np.float64, count=n)
        values = 1 - 2 * loss - charge
        require(np.isfinite(values).all(), "Independent hard output utility is nonfinite")
        return values, {"image_digits": digits, **fields}

    def costs(self):
        require({name: parameter_identity(model) for name, model in self.observers.items()} == self.identities,
                "Observer parameters changed during verification")
        return {"logical_observer_batch_calls": self.logical_calls, "logical_observer_digit_examples": self.logical_examples,
                "actual_observer_batch_calls": self.actual_calls, "actual_observer_digit_examples": self.actual_examples,
                "observer_batch_cache_hits": self.hits}


def verify_hard(path, panels, expected_values, arithmetic, charge):
    with np.load(path, allow_pickle=False) as packed:
        require(set(packed.files) == {"pixels_u8", "captions_utf8", "output_sha256", "source_ids", "conditions",
                "values_reward", "values_audit"}, "Hard endpoint array inventory differs")
        arrays = {key: packed[key].copy() for key in packed.files}
    expected_ids = [pair for part in panels for pair in part["source_ids"]]
    conditions = [part["condition"] for part in panels for _ in range(part["rows"])]
    n, pixels, captions = len(expected_ids), arrays["pixels_u8"], arrays["captions_utf8"]
    require(arrays["source_ids"].tolist() == expected_ids and arrays["conditions"].tolist() == conditions
            and pixels.dtype == np.uint8 and pixels.shape == (n, 1, 28, 56) and captions.shape == (n,),
            "Hard endpoint source, condition or media shape differs")
    hashes = [hashlib.sha256(image.tobytes() + str(caption).encode("utf-8", errors="strict")).hexdigest()
              for image, caption in zip(pixels, captions, strict=True)]
    require(hashes == arrays["output_sha256"].tolist(), "Retained hard output byte hash differs")
    reconstructed = {name: [] for name in OBSERVERS}
    evidence = {name: hashlib.sha256() for name in OBSERVERS}
    offset = 0
    for part in panels:
        end = offset + part["rows"]
        for name in OBSERVERS:
            value, primitive = arithmetic.score(pixels[offset:end], captions[offset:end], part["target"], name, charge)
            reconstructed[name].append(value)
            for key, entries in primitive.items():
                evidence[name].update(key.encode() + np.asarray(entries).tobytes())
        offset = end
    require(offset == n, "Hard-score batch coverage differs")
    means, values_sha = {}, {}
    for index, name in enumerate(OBSERVERS):
        value, saved = np.concatenate(reconstructed[name]), arrays["values_" + name]
        require(saved.dtype == np.float64 and saved.shape == (n,) and np.isfinite(saved).all()
                and np.array_equal(saved, expected_values[index]), "Saved hard values differ from the complete endpoint aggregate")
        require(np.array_equal(value, saved), "Independent observer and hard-output utility differs from the recorded values")
        means[name], values_sha[name] = float(value.mean()), array_digest(value)
    return {"file_sha256": digest(path), "rows": n, "observer_values_verified": 2 * n, "means": means,
            "values_sha256": values_sha, "recomputed_primitives_sha256": {name: value.hexdigest() for name, value in evidence.items()},
            "maximum_value_error": 0., "batch_sizes": [part["rows"] for part in panels], "exact": True}


def load_observers(assets, expected_asset_records):
    from ..field_bridge_v3_20261027.assets import ORIGINAL_ARCHIVE, PINNED
    from ..v6.observer import Recognizer
    assets = Path(assets)
    restored = read(assets / "RESTORATION.json")
    registry = {record["path"]: record["sha256"] for record in restored["selected_files"]}
    require(restored["archive_sha256"] == ORIGINAL_ARCHIVE, "Original observer archive provenance differs")
    observers, identities = {}, {}
    for name in OBSERVERS:
        relative = f"ndu-runs/full-002/{name}-observer.pt"
        identity = digest(assets / relative)
        require(identity == registry[relative] == PINNED[relative] and all(record["pinned_files"][relative] == identity
                and record["loaded_observers"] == list(OBSERVERS) and record["original_archive_sha256"] == ORIGINAL_ARCHIVE
                for record in expected_asset_records), "Endpoint observer file provenance differs")
        record = torch.load(assets / relative, map_location="cpu", weights_only=True)
        model = Recognizer().eval().requires_grad_(False)
        model.load_state_dict(record["state_dict"] if "state_dict" in record else record, strict=True)
        require(all(torch.isfinite(tensor).all() for tensor in model.state_dict().values()), "Invalid observer parameter")
        observers[name] = model
        identities[name] = {"file_sha256": identity, "parameter_sha256": parameter_identity(model)}
    return observers, identities


def audit(run, phase, source, freeze_path, assets):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    run, source, freeze_path = Path(run).resolve(), Path(source).resolve(), Path(freeze_path).resolve()
    require(phase in ("development", "audit"), "Hard score truth is restricted to completed training endpoints")
    directories = {seed: run / phase / str(seed) for seed in SEEDS}
    require(all((directory / "COMPLETE.json").is_file() and not (directory / "FAILED.json").exists() for directory in directories.values()),
            "All three phase completions are required before any endpoint outcome or source role is opened")
    freeze_id, freeze, protocol = digest(freeze_path), read(freeze_path), read(source / "PROTOCOL.json")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and phase in freeze["allowed_phases"]
            and freeze["protocol_sha256"] == digest(source / "PROTOCOL.json") and protocol["seeds"] == list(SEEDS),
            "Invalid training phase source freeze")
    for name, identity in freeze["source_files"].items():
        require(digest(member(source.parent, name)) == identity, f"Frozen source differs: {name}")
    for name, identity in freeze.get("artifacts", {}).items():
        require(digest(member(run, name)) == identity, f"Frozen prior phase artifact differs: {name}")
    p = protocol["training"]
    require(p["panel_batch_size"] == 128 and p["refinement_charge"] == .002, "Registered hard-score batching or charge differs")
    completions, complete_identities, asset_records = {}, {}, []
    for seed, directory in directories.items():
        complete, start = inventory(directory), read(directory / "START.json")
        require(complete["seed"] == start["seed"] == seed and complete["stage"] == complete["group"] == start["phase"] == phase
                and start["freeze_sha256"] == freeze_id and start["protocol_sha256"] == freeze["protocol_sha256"]
                and start["registered_commit"] == freeze["registered_commit"]
                and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()), "Endpoint execution provenance differs")
        completions[seed] = complete
        complete_identities[seed] = digest(directory / "COMPLETE.json")
        asset_records.append(read(directory / "ASSET_IDENTITIES.json"))
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    observers, observer_ids = load_observers(assets, asset_records)
    arithmetic = GroupedObserver(observers, {k: v["parameter_sha256"] for k, v in observer_ids.items()})
    from ..field_bridge_v3_20261027.source_roles import load_corpus_roles
    roles = [phase + "_task", phase + "_clean"]
    corpus = load_corpus_roles(Path(assets) / "ndu-data", roles, source / "SOURCE_ALLOCATION.json")
    require(list(corpus.splits) == roles and corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"]
            and digest(source / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"], "Endpoint-only role source identity differs")
    methods = ([f"ordinary_{i}" for i in range(4)] if phase == "development" else ["ordinary"]) + list(MODES)
    schedules, results = p[phase + "_schedule_ids"], {}
    require(len(schedules) == len(set(schedules)) == 4, "Training endpoint schedule count differs")
    for seed, directory in directories.items():
        complete = completions[seed]
        require(complete["methods"] == methods and complete["schedule_ids"] == schedules
                and complete["endpoints_shared_across_paths_and_methods"] is True, "Endpoint method/schedule grid differs")
        panel_records = read(directory / "ENDPOINT_IDENTITIES.json")
        panels = {name: rebuild_panel(corpus.splits[phase + "_" + name], phase + "_" + name, seed,
            p["conditions"] if name == "task" else ["clean"], p, panel_records[name]) for name in ("task", "clean")}
        with np.load(directory / "ENDPOINTS.npz", allow_pickle=False) as packed:
            aggregate = {name: packed[name].copy() for name in packed.files}
        require(aggregate["methods"].tolist() == methods and aggregate["schedule_ids"].tolist() == schedules
                and aggregate["observer_names"].tolist() == list(OBSERVERS)
                and digest(directory / "ENDPOINTS.npz") == complete["endpoint_values_sha256"], "Endpoint aggregate identity differs")
        files, charge = {}, p["refinement_charge"] * (1 + (p["fixed_actions"][str(seed)] != 0))
        for name in ("task", "clean"):
            ids = [pair for part in panels[name] for pair in part["source_ids"]]
            conditions = [part["condition"] for part in panels[name] for _ in range(part["rows"])]
            require(aggregate[name + "_source_ids"].tolist() == ids and aggregate[name + "_conditions"].tolist() == conditions
                    and aggregate[name + "_panel_identity"].item() == panel_records[name]["sha256"]
                    and aggregate["original_" + name].shape == (2, len(ids))
                    and aggregate[name + "_values"].shape == (len(methods), 4, 2, len(ids)), "Endpoint aggregate source/grid dimensions differ")
            relative = f"original-{name}.npz"
            files[relative] = verify_hard(directory / relative, panels[name], aggregate["original_" + name], arithmetic, charge)
        require(set(complete["paths"]) == {f"{method}/{schedule}" for method in methods for schedule in schedules}, "Missing method endpoint path")
        for method_index, method in enumerate(methods):
            for schedule_index, schedule in enumerate(schedules):
                path = directory / method / f"schedule-{schedule}"
                record = read(path / "COMPLETE.json")
                require(digest(path / "COMPLETE.json") == complete["paths"][f"{method}/{schedule}"]["complete_sha256"]
                        and (record["seed"], record["method"], record["schedule_id"], record["stage"], record["group"]) ==
                            (seed, method, schedule, phase, phase), "Method checkpoint endpoint provenance differs")
                for name in ("task", "clean"):
                    relative = str((path / (name + ".npz")).relative_to(directory))
                    result = verify_hard(path / (name + ".npz"), panels[name],
                        aggregate[name + "_values"][method_index, schedule_index], arithmetic, charge)
                    require(result["file_sha256"] == record["endpoint_files"][name]["file_sha256"]
                            and result["means"] == record["endpoint_files"][name]["means"], "Recorded endpoint means or output file identity differs")
                    files[relative] = result
                print(f"hard-score verification phase={phase} seed={seed} method={method} schedule={schedule} exact", flush=True)
        require(all(complete["files"][name] == result["file_sha256"] == digest(directory / name) for name, result in files.items()),
                "Endpoint evidence changed during verification")
        require(digest(directory / "COMPLETE.json") == complete_identities[seed]
                and digest(directory / "ENDPOINTS.npz") == complete["endpoint_values_sha256"]
                and digest(directory / "ENDPOINT_IDENTITIES.json") == complete["files"]["ENDPOINT_IDENTITIES.json"],
                "Endpoint provenance or aggregate changed during verification")
        results[str(seed)] = {"complete_sha256": digest(directory / "COMPLETE.json"),
            "endpoints_sha256": digest(directory / "ENDPOINTS.npz"), "panel_identities_sha256": digest(directory / "ENDPOINT_IDENTITIES.json"),
            "asset_identities_sha256": digest(directory / "ASSET_IDENTITIES.json"), "files": files,
            "fixed_deployment_action": p["fixed_actions"][str(seed)], "charge": charge,
            "source_panel_batches_rebuilt": sum(len(panel) for panel in panels.values()),
            "hard_output_rows_verified": sum(result["rows"] for result in files.values()),
            "observer_values_verified": sum(result["observer_values_verified"] for result in files.values())}
    require(digest(freeze_path) == freeze_id and all(digest(member(source.parent, name)) == identity
            for name, identity in freeze["source_files"].items()), "Frozen source changed during score verification")
    return {"schema": "hepta.field-bridge.v3.independent-training-hard-score-audit.1", "passed": True,
        "phase": phase, "seeds": results, "protocol_sha256": freeze["protocol_sha256"], "freeze_sha256": freeze_id,
        "registered_commit": freeze["registered_commit"], "source_files": freeze["source_files"],
        "observer_identities": observer_ids, "source_roles_loaded": roles, "source_manifest_sha256": protocol["source_manifest_sha256"],
        "auditor_source_sha256": digest(__file__), "helper_source_sha256": digest(Path(__file__).with_name("native_session_audit.py")),
        "script_sha256": digest(__file__),
        "hard_output_rows_verified": sum(result["hard_output_rows_verified"] for result in results.values()),
        "observer_values_verified": sum(result["observer_values_verified"] for result in results.values()),
        "source_panel_batches_rebuilt": sum(result["source_panel_batches_rebuilt"] for result in results.values()),
        **arithmetic.costs(), "generator_forward_calls": 0, "generator_models_loaded": 0,
        "score_value_comparison": "exact float64 equality; original float32 pixel/observer arithmetic and ordered batch boundaries",
        "maximum_value_error": 0., "batch_cache_scope": "exact ordered full-batch pixels and observer parameter hash; no cached target or score",
        "torch_threads": 2, "torch_interop_threads": 1, "torch_version": torch.__version__, "numpy_version": np.__version__,
        "new_policy_choices_or_independent_observations": 0, "additional_verification_only": True,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--phase", choices=("development", "audit"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists() and not args.output.resolve().is_relative_to((args.run / args.phase).resolve()),
            "Verification receipt must be new and outside immutable endpoint phase inventory")
    result = audit(args.run, args.phase, args.source, args.freeze, args.assets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "phase": args.phase, "hard_rows": result["hard_output_rows_verified"],
                      "receipt_sha256": digest(args.output)}))
