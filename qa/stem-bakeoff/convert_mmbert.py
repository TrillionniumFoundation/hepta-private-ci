"""Offline, hash-pinned mmBERT pickle-to-safetensors conversion.

No arbitrary pickle loading: PyTorch >= 2.6, weights_only=True, CPU tensors,
and the exact publisher LFS hash are required. The receipt records a local
derivation; it does not claim publisher attestation of the converted file.
"""

import argparse
import json
from pathlib import Path
import shutil

from real_encoder import CANDIDATES, RealEncoderError
from teacher_snapshot import inventory

COPY_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")


def convert_mmbert(*, source, output, revision, expected_inventory_sha256,
                   operator_accepted_terms):
    spec = CANDIDATES["mmbert_small"]
    if revision != spec["revision"] or operator_accepted_terms is not True:
        raise RealEncoderError("pinned revision and operator license acceptance required")
    before = inventory(source)
    if before["inventory_sha256"] != expected_inventory_sha256:
        raise RealEncoderError("input inventory mismatch")
    files = {x["path"]: x for x in before["entries"]}
    if ("pytorch_model.bin" not in files
            or files["pytorch_model.bin"]["sha256"] != spec["upstream_bin_sha256"]
            or any(name not in files for name in COPY_FILES)):
        raise RealEncoderError("official bin hash and complete tokenizer/config files required")
    if any(files[name]["bytes"] > 64 * 1024 * 1024 for name in COPY_FILES):
        raise RealEncoderError("configuration/tokenizer byte budget exceeded")
    import torch
    import safetensors
    from safetensors.torch import save_file
    major_minor = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
    if major_minor < (2, 6):
        raise RealEncoderError("weights-only conversion requires PyTorch >= 2.6")
    destination = Path(output).absolute()
    if destination.exists() or destination.is_symlink():
        raise RealEncoderError("output must be a new directory")
    # The checksum is checked before even invoking the restricted unpickler.
    raw = torch.load(Path(source) / "pytorch_model.bin", map_location="cpu",
                     weights_only=True, mmap=True)
    if (not isinstance(raw, dict) or not raw
            or any(not isinstance(k, str) or not isinstance(v, torch.Tensor)
                   or v.device.type != "cpu" or v.layout != torch.strided
                   for k, v in raw.items())):
        raise RealEncoderError("checkpoint must contain only named dense CPU tensors")
    # Preserve all named values, including tied MLM decoder weights. Cloning
    # avoids ambiguous alias serialization; the base encoder loader then drops
    # the original MLM-only keys using Transformers' registered architecture.
    tensors = {k: v.detach().contiguous().clone() for k, v in sorted(raw.items())}
    if any(v.is_floating_point() and not bool(torch.isfinite(v).all()) for v in tensors.values()):
        raise RealEncoderError("checkpoint contains nonfinite tensors")
    destination.mkdir(mode=0o700)
    try:
        for name in COPY_FILES:
            shutil.copyfile(Path(source) / name, destination / name)
        save_file(tensors, str(destination / "model.safetensors"), metadata={"format": "pt"})
        derived = inventory(destination)
        output_hash = next(x["sha256"] for x in derived["entries"] if x["path"] == "model.safetensors")
        if inventory(source)["inventory_sha256"] != expected_inventory_sha256:
            raise RealEncoderError("input snapshot changed during conversion")
        receipt = {
            "schema": "hepta.mmbert-weights-only-conversion.v1", "revision": revision,
            "source_inventory_sha256": expected_inventory_sha256,
            "source_bin_sha256": spec["upstream_bin_sha256"],
            "output_safetensors_sha256": output_hash, "weights_only": True,
            "torch_version": torch.__version__, "safetensors_version": safetensors.__version__,
            "tensor_count": len(tensors), "named_tensor_elements": sum(v.numel() for v in tensors.values()),
            "source_metadata_sha256": {name: files[name]["sha256"] for name in COPY_FILES},
            "publisher_attestation_of_derived_file": False,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
        (destination / "conversion_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return {**receipt, "output_inventory_sha256": inventory(destination)["inventory_sha256"]}
    except Exception:
        # Only remove this function's freshly created, previously absent output.
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    args = vars(parser.parse_args())
    print(json.dumps(convert_mmbert(**args), indent=2))


if __name__ == "__main__":
    main()
