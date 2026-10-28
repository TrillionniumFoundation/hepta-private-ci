"""Prepare once under unset dispatch; every inference case loads identical bytes."""

import hashlib
from pathlib import Path

import numpy as np

from fixed_inputs_common import array_identity, canonical, identity, read, require, write


ARRAY_SPEC = {
    "observation_pixels": ("<f4", (1, 28, 56)),
    "observation_mask": ("<f4", (1, 28, 56)),
    "observation_text_tokens": ("<i8", (8,)),
    "target_pixels": ("<f4", (1, 28, 56)),
    "target_text_tokens": ("<i8", (8,)),
    "target_labels": ("<i8", (2,)),
    "latent_noise": ("<f4", (96,)),
}
PUBLIC = ("observation_pixels", "observation_mask", "observation_text_tokens")
TRUTH = ("target_pixels", "target_text_tokens", "target_labels")


def numeric_bytes(rows):
    return rows * sum(np.dtype(dtype).itemsize * int(np.prod(tail)) for dtype, tail in ARRAY_SPEC.values())


def validate_arrays(arrays, count):
    require(set(arrays) == set(ARRAY_SPEC), "Snapshot array inventory differs")
    result = {}
    for name, (dtype, tail) in ARRAY_SPEC.items():
        value = arrays[name]
        require(value.dtype.str == dtype and value.shape == (count, *tail), "Snapshot type/shape differs: " + name)
        result[name] = array_identity(value)
    return result


def public_target_identity(arrays):
    return {name: hashlib.sha256(b"".join(arrays[key].tobytes(order="C") for key in names)).hexdigest()
            for name, names in (("public_sha256", PUBLIC), ("target_sha256", TRUTH))}


def verify_snapshot(directory, expected_identity, current_panels, protocol, sources):
    """Only NumPy/bytes: verify every field, batch, file and latent-noise tensor."""
    directory = Path(directory)
    require(not directory.is_symlink(), "Snapshot directory is a symlink")
    manifest_path = directory / "MANIFEST.json"
    require(identity(manifest_path) == expected_identity, "Snapshot manifest identity changed")
    manifest = read(manifest_path)
    require(manifest["schema"] == protocol["snapshot_schema"] and manifest["source_registration"] == sources,
            "Snapshot provenance differs")
    require(manifest["source_roles"] == protocol["source_roles"] and manifest["seed"] == 17
            and manifest["preparation_capability"] == "AVX512" and manifest["model_calls"] == 0,
            "Snapshot scope differs")
    require(manifest["panel_identities"] == current_panels, "Snapshot input panel identity differs")
    require(manifest["all_input_sha256"] == hashlib.sha256(canonical(manifest["batches"])).hexdigest(),
            "Snapshot aggregate input identity differs")
    expected_order = [(panel, index) for panel in ("task", "clean")
                      for index in range(len(current_panels[panel]["batches"]))]
    require([(row["panel"], row["batch_index"]) for row in manifest["batches"]] == expected_order,
            "Snapshot batch ordering/inventory differs")
    expected_files, result, total = {"MANIFEST.json"}, {"task": [], "clean": []}, 0
    for row in manifest["batches"]:
        panel, index, count = row["panel"], row["batch_index"], row["batch_size"]
        expected = current_panels[panel]["batches"][index]
        require({k: row[k] for k in expected} == expected, "Snapshot batch metadata differs")
        filename = panel + "-" + str(index).zfill(3) + ".npz"
        require(row["file"]["path"] == filename, "Unexpected snapshot filename")
        path = directory / filename
        require(identity(path) == {k: row["file"][k] for k in ("bytes", "sha256")}, "Snapshot NPZ changed")
        with np.load(path, allow_pickle=False) as saved:
            require(len(saved.files) == len(set(saved.files)), "Duplicate snapshot array")
            arrays = {name: saved[name].copy(order="C") for name in saved.files}
        require(validate_arrays(arrays, count) == row["arrays"], "Snapshot tensor bytes changed")
        require(public_target_identity(arrays) == {k: expected[k] for k in ("public_sha256", "target_sha256")},
                "Saved tensor bytes differ from frozen public/target inputs")
        total += sum(value.nbytes for value in arrays.values())
        result[panel].append((row, arrays))
        expected_files.add(filename)
    require({p.name for p in directory.iterdir()} == expected_files, "Snapshot has unknown or missing files")
    expected_total = numeric_bytes(sum(protocol["panel_rows"].values()))
    require(total == manifest["numeric_tensor_bytes"] == expected_total, "Snapshot tensor byte total differs")
    require(sum(p.stat().st_size for p in directory.iterdir()) <= protocol["storage_bounds"]["snapshot_bytes"],
            "Snapshot exceeded registered storage bound")
    return manifest, result


def prepare(directory, inputs, protocol, sources):
    """No neural models: materialize original public/target inputs and private RNG noise."""
    import torch
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.source_roles import load_corpus_roles
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning import panels
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_stages import panel_identity

    v3, current = read(inputs["v3_protocol"]), read(inputs["current_panel_identities"])
    require(v3["training"]["fixed_actions"]["17"] == 0, "Frozen deployment action differs")
    require(protocol["latent_hidden"] == 96, "Latent dimension changed")
    corpus = load_corpus_roles(inputs["asset_train-images-idx3-ubyte.gz"].parent, protocol["source_roles"])
    endpoint = {"task": panels(corpus, "development_task", 17, v3["training"]["conditions"], v3),
                "clean": panels(corpus, "development_clean", 17, ["clean"], v3)}
    actual = {name: panel_identity(panel) for name, panel in endpoint.items()}
    write(Path(directory).parent / "prepare" / "RECONSTRUCTED_PANELS.json", actual)
    require(canonical(actual) == canonical(current), "Unset preparation inputs differ from current V5")
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    rows = []
    for panel in ("task", "clean"):
        for index, part in enumerate(endpoint[panel]):
            observation, target = part.batch.observation, part.batch.target
            generator = torch.Generator().manual_seed(part.noise_seed)
            noise = torch.randn(len(part.batch.source_ids), protocol["latent_hidden"], generator=generator)
            tensors = (observation.pixels, observation.mask, observation.text_tokens,
                       target.pixels, target.text_tokens, target.labels, noise)
            arrays = {name: tensor.detach().cpu().contiguous().numpy().copy(order="C")
                      for name, tensor in zip(ARRAY_SPEC, tensors, strict=True)}
            metadata = validate_arrays(arrays, len(part.batch.source_ids))
            filename = panel + "-" + str(index).zfill(3) + ".npz"
            with (directory / filename).open("xb") as stream:
                np.savez(stream, **arrays)
            rows.append({"panel": panel, "batch_index": index, **current[panel]["batches"][index],
                         "file": {"path": filename, **identity(directory / filename)}, "arrays": metadata})
    require(canonical({name: panel_identity(panel) for name, panel in endpoint.items()}) == canonical(current),
            "Preparation mutated panel inputs")
    manifest = {"schema": protocol["snapshot_schema"], "source_registration": sources,
                "source_roles": protocol["source_roles"], "seed": 17, "preparation_capability": "AVX512",
                "model_calls": 0, "panel_identities": current, "batches": rows,
                "numeric_tensor_bytes": numeric_bytes(sum(protocol["panel_rows"].values())),
                "all_input_sha256": hashlib.sha256(canonical(rows)).hexdigest()}
    write(directory / "MANIFEST.json", manifest)
    manifest_identity = identity(directory / "MANIFEST.json")
    verify_snapshot(directory, manifest_identity, current, protocol, sources)
    return {"manifest": manifest_identity, "all_input_sha256": manifest["all_input_sha256"],
            "numeric_tensor_bytes": manifest["numeric_tensor_bytes"],
            "total_snapshot_bytes": sum(p.stat().st_size for p in directory.iterdir())}


def torch_panels(loaded):
    """Tensor views of verified saved bytes: no random generation or data reconstruction."""
    import torch
    from experiments.multimodal_output_portfolio.v6.data import Batch, Observation, Target
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning import PanelBatch

    result = {}
    for panel, records in loaded.items():
        parts = []
        for row, arrays in records:
            tensors = {name: torch.from_numpy(value) for name, value in arrays.items()}
            observation = Observation(*(tensors[name] for name in PUBLIC))
            target = Target(*(tensors[name] for name in TRUTH))
            source_ids = tuple(tuple(pair) for pair in row["source_ids"])
            batch = Batch(observation, target, source_ids)
            parts.append((PanelBatch(row["condition"], batch, row["noise_seed"]), tensors["latent_noise"]))
        result[panel] = parts
    return result


def verify_loaded_unchanged(loaded):
    for records in loaded.values():
        for row, arrays in records:
            require(validate_arrays(arrays, row["batch_size"]) == row["arrays"], "Loaded input tensor mutated")
