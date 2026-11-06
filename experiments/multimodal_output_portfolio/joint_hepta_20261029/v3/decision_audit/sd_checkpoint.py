"""Exact-base, development-only diffusion deltas. No model promotion authority."""

import hashlib
import json
import os
from pathlib import Path


TRAINABLE = ("conv_out.bias", "conv_out.weight")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tensor_sha(tensor):
    import torch

    value = tensor.detach().cpu().contiguous()
    h = hashlib.sha256(canonical({"shape": list(value.shape), "dtype": str(value.dtype)}))
    h.update(memoryview(value.reshape(-1).view(torch.uint8).numpy()))
    return h.hexdigest()


def inventory(module):
    return {name: {"shape": list(value.shape), "dtype": str(value.dtype),
                   "sha256": tensor_sha(value)}
            for name, value in sorted(module.state_dict().items())}


def freeze_for_training(unet):
    params = dict(unet.named_parameters())
    if not set(TRAINABLE).issubset(params):
        raise ValueError("the pinned UNet output projection is missing")
    unet.eval().requires_grad_(False)
    for name in TRAINABLE:
        params[name].requires_grad_(True)
    return [params[name] for name in TRAINABLE]


def write_json(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _sync(path):
    with Path(path).open("rb") as stream:
        os.fsync(stream.fileno())


def save_candidate(directory, unet, optimizer, rng, before, metadata):
    """Publish the manifest last; incomplete directories are never checkpoints."""
    import torch
    from safetensors.torch import save_file

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    after = inventory(unet)
    changed = sorted(name for name in before if before[name] != after.get(name))
    if set(before) != set(after) or changed != list(TRAINABLE):
        raise ValueError("every allowed tensor must change and every frozen tensor must match")
    params = dict(unet.named_parameters())
    for name in TRAINABLE:
        if (not torch.isfinite(params[name]).all()
                or not torch.isfinite(optimizer.state[params[name]]["momentum_buffer"]).all()):
            raise ValueError("nonfinite candidate or optimizer state")
    save_file({name: params[name].detach().cpu().contiguous() for name in TRAINABLE},
              str(directory / "delta.safetensors"))
    momentum = {name: optimizer.state[params[name]]["momentum_buffer"].detach().cpu().contiguous()
                for name in TRAINABLE}
    momentum["rng_state"] = rng.get_state()
    save_file(momentum, str(directory / "optimizer.safetensors"))
    files = {}
    for name in ("delta.safetensors", "optimizer.safetensors"):
        _sync(directory / name)
        files[name] = {"sha256": file_sha(directory / name),
                       "bytes": (directory / name).stat().st_size}
    manifest = {"schema": "hepta.r2.sd-development-checkpoint.v1",
                "trainable": list(TRAINABLE), "before": before, "after": after,
                "changed": changed, "files": files, "metadata": metadata,
                "confirmatory_fit": False, "production_promotion_permitted": False,
                "qualification_requires_completed_fit_result": True}
    write_json(directory / "CHECKPOINT.json", manifest)
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return file_sha(directory / "CHECKPOINT.json")


def restore_candidate(directory, unet, base_manifest_sha256, expected_sha256):
    """Require an external digest and byte-exact base before applying a delta."""
    import torch
    from safetensors.torch import load_file

    directory = Path(directory)
    manifest_path = directory / "CHECKPOINT.json"
    if directory.is_symlink() or manifest_path.is_symlink():
        raise ValueError("checkpoint symlink")
    if file_sha(manifest_path) != expected_sha256:
        raise ValueError("checkpoint identity mismatch")
    manifest = json.loads(manifest_path.read_text())
    if (manifest["schema"] != "hepta.r2.sd-development-checkpoint.v1"
            or manifest["trainable"] != list(TRAINABLE)
            or manifest["changed"] != list(TRAINABLE)
            or manifest["metadata"]["base_manifest_sha256"] != base_manifest_sha256
            or manifest["confirmatory_fit"] is not False
            or manifest["production_promotion_permitted"] is not False):
        raise ValueError("checkpoint lineage or scope mismatch")
    if inventory(unet) != manifest["before"]:
        raise ValueError("loaded base tensor identity mismatch")
    if set(manifest["after"]) != set(manifest["before"]):
        raise ValueError("candidate state roster mismatch")
    for name, before in manifest["before"].items():
        after = manifest["after"][name]
        if ((name not in TRAINABLE and after != before)
                or after["shape"] != before["shape"] or after["dtype"] != before["dtype"]):
            raise ValueError("candidate changes frozen state or parameter layout")
    if set(manifest["files"]) != {"delta.safetensors", "optimizer.safetensors"}:
        raise ValueError("checkpoint file roster mismatch")
    for name, record in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or path.stat().st_size != record["bytes"] or file_sha(path) != record["sha256"]:
            raise ValueError("checkpoint bytes mismatch")
    delta = load_file(str(directory / "delta.safetensors"))
    state = load_file(str(directory / "optimizer.safetensors"))
    if set(delta) != set(TRAINABLE) or set(state) != {*TRAINABLE, "rng_state"}:
        raise ValueError("checkpoint tensor roster mismatch")
    params = dict(unet.named_parameters())
    for name in TRAINABLE:
        for value in (delta[name], state[name]):
            if value.shape != params[name].shape or value.dtype != params[name].dtype or not torch.isfinite(value).all():
                raise ValueError("checkpoint tensor shape, dtype or finite-value mismatch")
        if tensor_sha(delta[name]) != manifest["after"][name]["sha256"]:
            raise ValueError("candidate tensor identity mismatch")
        if manifest["after"][name]["sha256"] == manifest["before"][name]["sha256"]:
            raise ValueError("allowed tensor was not updated")
    rng = torch.Generator(device="cpu")
    rng.set_state(state["rng_state"])
    with torch.no_grad():
        for name in TRAINABLE:
            params[name].copy_(delta[name])
    if inventory(unet) != manifest["after"]:
        raise ValueError("candidate restoration differs from the saved state")
    return manifest, state, rng
