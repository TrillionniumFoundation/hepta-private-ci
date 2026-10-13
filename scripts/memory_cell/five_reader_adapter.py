"""Bind a saved response LoRA to the existing research Reader owner.

No alternative model loader, dynamic adapter switching, training or adoption.
Only the existing rank-4 q/v response profile is accepted. A training receipt
binds bytes, NOT independent supervision, calibration, safety or Reader adequacy.
PEFT is imported lazily; base-only NativeSession and Group tests do not need it.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import torch
from safetensors.torch import load_file

import five_causal_experiments as c
import five_causal_native as native

SCHEMA = "hepta.five-native.bundle.v2"
PROFILE = "hepta.five-reader.response-only-lora.v1"
COMPOSITION = "hepta.reader.base-plus-response-adapter.v1"
REQUIRED_FILES = {"adapter_config.json", "adapter_model.safetensors"}
ALLOWED_FILES = REQUIRED_FILES | {"README.md"}
MAX_ADAPTER_BYTES = 64 * 1024 * 1024


def state_digest(state):
    # Exactly the existing response-training digest, not a new tensor format.
    return c.digest({k: native.tensor_digest(v) for k, v in sorted(state.items())})


def reader_identity(snapshot, spec):
    return c.digest({"profile": COMPOSITION, "base_snapshot_sha256": c.digest(snapshot),
                     "response_adapter_sha256": c.digest(spec)})


def _directory(root, relative):
    c.require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
              and ".." not in Path(relative).parts, "relative adapter directory required")
    path = Path(root) / relative
    c.require(path.is_dir() and not any(p.is_symlink() for p in (path, *path.parents)),
              "adapter directory missing or linked")
    return path


def _inventory(root, relative):
    path = _directory(root, relative)
    children = list(path.iterdir())
    c.require(REQUIRED_FILES <= {p.name for p in children} <= ALLOWED_FILES,
              "adapter must contain safetensors/config and no undeclared executables or pickle")
    c.require(all(p.is_file() and not p.is_symlink() for p in children), "ordinary adapter files only")
    c.require(sum(p.stat().st_size for p in children) <= MAX_ADAPTER_BYTES, "adapter byte limit")
    return {p.name: c.file_sha(p) for p in sorted(children)}


def validate_material(root, spec, snapshot):
    """Recheck current disk bytes even when the model is already resident."""
    c.require(isinstance(spec, dict) and set(spec) == {
        "profile", "path", "files", "base_snapshot_sha256", "base_tensor_sha256",
        "adapter_tensor_sha256", "training_receipt"
    }, "response adapter descriptor fields")
    c.require(spec["profile"] == PROFILE and spec["base_snapshot_sha256"] == c.digest(snapshot),
              "adapter/base snapshot mismatch")
    c.require(all(c.sha(spec[k]) for k in ("base_tensor_sha256", "adapter_tensor_sha256")),
              "adapter/base tensor identity missing")
    c.require(_inventory(root, spec["path"]) == spec["files"], "adapter inventory changed")
    ref = spec["training_receipt"]
    c.require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "training receipt reference")
    receipt = c.load(c.source_file(Path(root), ref["path"], ref["sha256"]))
    c.require(receipt.get("profile") == PROFILE and receipt.get("base_unchanged") is True
              and receipt.get("checkpoint_reload_equal") is True, "uncompleted response training receipt")
    c.require(receipt.get("base_tensor_sha256") == spec["base_tensor_sha256"]
              and receipt.get("adapter_tensor_sha256") == spec["adapter_tensor_sha256"],
              "receipt does not bind selected tensors")
    c.require(receipt.get("files") == {"adapter/" + k: v for k, v in spec["files"].items()},
              "receipt does not bind selected adapter files")
    return _directory(root, spec["path"]), receipt


def _config(path):
    from peft import LoraConfig
    fixed = LoraConfig(r=4, lora_alpha=8, lora_dropout=0.0,
                       target_modules=["q_proj", "v_proj"], bias="none",
                       task_type="CAUSAL_LM", inference_mode=True)
    defaults = fixed.to_dict()
    saved = c.load(path / "adapter_config.json")
    c.require(isinstance(saved, dict), "adapter config object")
    # Metadata does not select/load a base or Python class. Pass our explicit
    # fixed config below, not auto_mapping, a Hub base path, or saved code.
    metadata = {"base_model_name_or_path", "revision", "auto_mapping", "peft_version"}
    def normalized(value):
        if isinstance(value, (tuple, set)):
            return sorted(normalized(x) for x in value)
        if isinstance(value, list):
            return [normalized(x) for x in value]
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items()}
        return value
    c.require({"r", "lora_alpha", "target_modules", "peft_type", "task_type"} <= set(saved),
              "incomplete LoRA architecture")
    for name, value in saved.items():
        if name in metadata:
            continue
        expected = defaults.get(name)
        actual = value
        if name == "target_modules" and isinstance(actual, list):
            actual = sorted(actual)
        c.require(name in defaults and c.canonical(normalized(actual)) == c.canonical(normalized(expected)),
                  "unsupported saved adapter option: " + name)
    return fixed


def _check_active(model):
    from peft import get_model_status
    status = get_model_status(model)
    c.require(status.enabled is True and status.active_adapters == ["default"]
              and status.available_adapters == ["default"] and status.merged_adapters == []
              and status.trainable_params == 0 and status.num_adapter_layers > 0,
              "adapter is disabled, switched, merged, trainable or inconsistent")
    c.require(all(not p.requires_grad for p in model.parameters()), "frozen inference parameters required")


def attach(backend, root, spec, snapshot):
    """Attach only to a newly loaded disposable base before owner publication.

    PEFT mutates its input in place; callers must discard it on exceptions.
    Never attach to an already published serving object or silently reuse it.
    """
    path, receipt = validate_material(root, spec, snapshot)
    from peft import PeftModel, get_peft_model_state_dict
    c.require(not hasattr(backend.loaded, "peft_config")
              and all(not p.requires_grad for p in backend.loaded.parameters()), "fresh frozen base required")
    base_tensors = dict(backend.loaded.state_dict())
    c.require(state_digest(base_tensors) == spec["base_tensor_sha256"], "actual base differs from training base")
    config = _config(path)
    saved = load_file(str(path / "adapter_model.safetensors"), device="cpu")
    c.require(saved and all(isinstance(k, str) and (".lora_A." in k or ".lora_B." in k)
              and v.dtype == torch.float32 and v.numel() > 0 and bool(torch.isfinite(v).all())
              for k, v in saved.items()), "only finite FP32 q/v LoRA tensors accepted")
    c.require(state_digest(saved) == spec["adapter_tensor_sha256"], "serialized adapter tensor mismatch")
    model = PeftModel.from_pretrained(backend.loaded, str(path), config=config,
                                     is_trainable=False, local_files_only=True)
    model.eval().requires_grad_(False)
    actual = get_peft_model_state_dict(model)
    c.require(set(actual) == set(saved) and all(torch.equal(actual[k].cpu(), saved[k]) for k in saved),
              "incomplete or reinterpreted adapter materialization")
    c.require(sum(v.numel() for v in actual.values()) == receipt.get("trainable_parameters"),
              "adapter parameter census differs from training receipt")
    _check_active(model)
    c.require(state_digest(base_tensors) == spec["base_tensor_sha256"], "attachment mutated base")
    validate_material(root, spec, snapshot)
    backend.loaded = model
    backend.model = model.get_base_model().base_model
    backend.response_adapter_spec = deepcopy(spec)
    backend.response_adapter_base_tensors = base_tensors  # views, not another base copy
    backend.response_adapter_snapshot = deepcopy(snapshot)
    backend.response_adapter_root = Path(root)
    return {"profile": COMPOSITION, "reader_identity": reader_identity(snapshot, spec),
            "adapter_parameters": sum(v.numel() for v in actual.values()),
            "adapter_parameter_bytes": sum(v.numel()*v.element_size() for v in actual.values()),
            "base_unchanged": True, "saved_tensor_equality": True,
            "reader_adequacy_established": False, "production_accepted": False}


def verify_resident(backend):
    """No cached-object exemption for changed files, weights or active adapter."""
    from peft import get_peft_model_state_dict
    spec = backend.response_adapter_spec
    validate_material(backend.response_adapter_root, spec, backend.response_adapter_snapshot)
    _check_active(backend.loaded)
    c.require(state_digest(get_peft_model_state_dict(backend.loaded)) == spec["adapter_tensor_sha256"],
              "resident adapter tensors changed")
    c.require(state_digest(backend.response_adapter_base_tensors) == spec["base_tensor_sha256"],
              "resident base tensors changed")


def compose(root, base, adapter_path, receipt_path):
    """Build an unadopted E1/Group Reader descriptor using actual saved files.

    Base/candidate assembly is not a gate receipt. Existing independent review
    must bind the resulting new Reader identity before subsequent formal stages.
    """
    c.require(base.get("schema") == native.SCHEMA and base.get("kind") == "reader"
              and "response_adapter" not in base, "unadapted Reader descriptor required")
    c.require(base["bindings"]["reader"] == c.digest(base["snapshot"]), "wrong base Reader identity")
    root = Path(root)
    c.require(isinstance(receipt_path, str) and receipt_path and not Path(receipt_path).is_absolute()
              and ".." not in Path(receipt_path).parts, "relative receipt path required")
    path = root / receipt_path
    c.require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), "receipt linked or missing")
    receipt = c.load(path)
    spec = {"profile": PROFILE, "path": adapter_path, "files": _inventory(root, adapter_path),
            "base_snapshot_sha256": c.digest(base["snapshot"]),
            "base_tensor_sha256": receipt.get("base_tensor_sha256"),
            "adapter_tensor_sha256": receipt.get("adapter_tensor_sha256"),
            "training_receipt": {"path": receipt_path, "sha256": c.file_sha(path)}}
    validate_material(root, spec, base["snapshot"])
    result = deepcopy(base)
    result["schema"], result["response_adapter"] = SCHEMA, spec
    result["bindings"]["reader"] = reader_identity(base["snapshot"], spec)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-descriptor-sha256", required=True)
    parser.add_argument("--adapter-path", required=True)
    parser.add_argument("--training-receipt-path", required=True)
    args = parser.parse_args()
    owner = native.NativeSession(args.root)
    base = owner.descriptor(args.base_descriptor_sha256)
    result = compose(args.root, base, args.adapter_path, args.training_receipt_path)
    identity = c.digest(result)
    path = args.root / "bundles" / (identity + ".json")
    # Descriptor identity is the exact canonical bytes, with NO final newline.
    with path.open("xb") as stream:
        import os
        stream.write(c.canonical(result)); stream.flush(); os.fsync(stream.fileno())
    print(c.canonical({"descriptor_sha256": identity, "reader_identity": result["bindings"]["reader"],
                       "model_loaded": False, "production_accepted": False}).decode())


if __name__ == "__main__":
    main()
