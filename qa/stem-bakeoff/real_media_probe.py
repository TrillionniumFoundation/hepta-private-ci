#!/usr/bin/env python3
"""Execute pinned EG2 text+image weights and retain byte-bound structure evidence.

The generated geometry is a procedural execution fixture, not a task dataset.
No retrieval, alignment, localization or multimodal quality claim is measured.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from feature_bundle import FeatureBundleError, FeatureBundleV1, MODALITIES
from real_encoder import (CANDIDATES, FrozenRealEncoder, RealEncoderError,
                          canonical_sha256, source_digests)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT = "A red square and a blue circle on a white background."
SOURCE_RECORD = {"fixture_id": "procedural-red-square-blue-circle-v1",
                 "source_kind": "procedural-execution-fixture", "quality_labels": None}


class MediaProbeError(ValueError):
    pass


def _peak_rss_bytes():
    try:
        import resource
    except ImportError:
        return None
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw) if sys.platform == "darwin" else int(raw) * 1024


def create_fixture(directory):
    """A deterministic program image; its semantic correctness is not scored."""
    from PIL import Image, ImageDraw
    path = Path(directory) / "procedural_input.png"
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 64, 112, 152), fill=(220, 30, 40))
    draw.ellipse((144, 64, 232, 152), fill=(30, 60, 220))
    image.save(path, format="PNG", optimize=False)
    image_bytes = path.read_bytes()
    text_sha = hashlib.sha256(TEXT.encode()).hexdigest()
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    media_sources = [("text", text_sha), ("image", image_sha)]
    expected_source = canonical_sha256({
        "text_source": source_digests([TEXT], [SOURCE_RECORD])[0],
        "media_sources": media_sources})
    return {"text": TEXT, "image": path.name}, {
        "record": dict(SOURCE_RECORD), "text_utf8_sha256": text_sha,
        "image_file_sha256": image_sha, "image_file_bytes": len(image_bytes),
        "image_shape": [256, 256, 3], "decoded_rgb_payload_bytes": 256 * 256 * 3,
        "expected_source_record_sha256": expected_source}


def inspect_bundle(bundle, *, expected_identity, expected_source, model_calls, vision_calls):
    """Validate observed structure and source identity without inferring quality."""
    if type(bundle) is not FeatureBundleV1 or model_calls != 1 or vision_calls != 1:
        raise MediaProbeError("one observed model and vision-tower call required")
    bundle.require_identity(expected_identity)
    if bundle.source_record_digests != (expected_source,):
        raise MediaProbeError("forward output does not bind the actual text/image record")
    views = bundle.snapshot()
    required = {"global_features", "token_features", "token_valid", "modality_ids", "missing_mask"}
    if not required.issubset(views):
        raise MediaProbeError("real text/image token views are required")
    if {"region_boxes", "region_valid", "time_spans", "time_valid"}.intersection(views):
        raise MediaProbeError("this processor does not attest region or time alignment")
    global_features, tokens = views["global_features"], views["token_features"]
    if (global_features.dtype != torch.float32 or tokens.dtype != torch.float32
            or global_features.shape != (1, 768) or tokens.shape[0] != 1 or tokens.shape[2] != 768
            or not torch.allclose(global_features.norm(dim=-1), torch.ones(1), atol=1e-4)):
        raise MediaProbeError("unexpected native EG2 width, float32 snapshot or normalized output")
    expected_missing = torch.tensor([[False, False, True, True, True]])
    if not torch.equal(views["missing_mask"], expected_missing):
        raise MediaProbeError("text/image presence does not match the submitted record")
    valid = views["token_valid"]
    kinds = views["modality_ids"]
    counts = {name: int(((kinds == i) & valid).sum()) for i, name in enumerate(MODALITIES)}
    if counts["text"] < 1 or counts["image"] < 1 or sum(counts[k] for k in MODALITIES[2:]):
        raise MediaProbeError("native token markers do not prove both text and image were consumed")
    return {"bundle_sha256": bundle.bundle_digest, "cache_key": bundle.cache_key,
            "source_record_digests": list(bundle.source_record_digests),
            "identity": asdict(bundle.identity), "global_shape": list(global_features.shape),
            "token_shape": list(tokens.shape), "valid_token_counts_by_modality": counts,
            "padding_token_count": int((~valid).sum()),
            "missing_mask": views["missing_mask"].tolist(),
            "feature_payload_bytes": sum(v.numel() * v.element_size() for v in views.values()),
            "retained_view_manifest": bundle.manifest(),
            "token_semantics": "contextualized states tagged by original modality marker",
            "region_alignment_attested": False, "time_alignment_attested": False}, views


def input_tensor_manifest(inputs):
    """Measure the actual model-bound tensors, deduplicating aliased storage."""
    entries, storage = {}, {}
    for name, value in inputs.items():
        if not isinstance(value, torch.Tensor):
            raise MediaProbeError("model inputs must be tensors")
        payload = value.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()
        entries[name] = {"shape": list(value.shape), "dtype": str(value.dtype),
                         "payload_bytes": len(payload),
                         "bytes_sha256": hashlib.sha256(payload).hexdigest()}
        allocation = value.untyped_storage()
        storage[(str(value.device), allocation.data_ptr())] = allocation.nbytes()
    return {"tensors": entries,
            "tensor_payload_bytes": sum(v["payload_bytes"] for v in entries.values()),
            "unique_input_storage_bytes": sum(storage.values()),
            "semantics": "observed input tensors; excludes allocator and activation memory"}


def save_views(directory, views):
    """Persist inspectable numeric arrays without pickle or replacement."""
    outputs = {}
    for name, value in views.items():
        path = Path(directory) / f"{name}.npy"
        with path.open("xb") as stream:
            np.save(stream, value.cpu().numpy(), allow_pickle=False)
        payload = path.read_bytes()
        outputs[name] = {"file": path.name, "bytes": len(payload),
                         "file_sha256": hashlib.sha256(payload).hexdigest()}
    return outputs


def run_probe(*, snapshot, expected_inventory_sha256, output, operator_accepted_terms,
              device="cpu", max_tokens=1024):
    destination = Path(output).absolute()
    resolved = destination.resolve()
    if (destination.is_symlink() or resolved == REPO_ROOT or resolved.is_relative_to(REPO_ROOT)
            or not destination.parent.is_dir() or destination.parent.is_symlink()):
        raise MediaProbeError("use a new external evidence directory with an existing real parent")
    destination.mkdir(mode=0o700)
    start = time.perf_counter()
    before_rss = _peak_rss_bytes()
    try:
        record, source = create_fixture(destination)
        owner = FrozenRealEncoder(
            candidate="embeddinggemma2_740m", snapshot=snapshot,
            revision=CANDIDATES["embeddinggemma2_740m"]["revision"],
            expected_inventory_sha256=expected_inventory_sha256,
            operator_accepted_terms=operator_accepted_terms, device=device,
            profile="text_image", max_tokens=max_tokens, task="classification")
        loaded_rss = _peak_rss_bytes()
        vision = getattr(owner._model, "vision_tower", None)
        if vision is None or getattr(owner._model, "audio_tower", None) is not None:
            raise MediaProbeError("text_image must load vision and omit the audio tower")
        calls = {"model": 0, "vision": 0}
        observed_inputs = []
        def input_hook(_module, args, kwargs):
            if args or not {"input_ids", "pixel_values"}.issubset(kwargs):
                raise MediaProbeError("expected keyword text and image tensors at model boundary")
            observed_inputs.append(input_tensor_manifest(kwargs))
        def root_hook(_module, _args, _output):
            calls["model"] += 1
        def vision_hook(_module, _args, _output):
            calls["vision"] += 1
        handles = [owner._model.register_forward_pre_hook(input_hook, with_kwargs=True),
                   owner._model.register_forward_hook(root_hook),
                   vision.register_forward_hook(vision_hook)]
        try:
            bundle = owner.encode_records([record], media_root=destination,
                                          source_records=[SOURCE_RECORD])
        finally:
            for handle in handles:
                handle.remove()
        source_path = destination / record["image"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["image_file_sha256"]:
            raise MediaProbeError("source image changed during the forward")
        summary, views = inspect_bundle(
            bundle, expected_identity=owner.identity,
            expected_source=source["expected_source_record_sha256"],
            model_calls=calls["model"], vision_calls=calls["vision"])
        if (len(observed_inputs) != 1 or owner.last_receipt["model_forward_calls"] != 1
                or owner.last_receipt["trainable_parameter_count"] != 0
                or owner.last_receipt.get("feature_bundle_sha256") != bundle.bundle_digest):
            raise MediaProbeError("backend receipt disagrees with frozen forward observations")
        retained = save_views(destination, views)
        result = {"schema": "hepta.real-text-image-execution-probe.v1",
                  "status": "EXECUTED", "input": {"submitted_record": record, **source},
                  "feature_evidence": summary, "saved_feature_views": retained,
                  "forward_receipt": dict(owner.last_receipt),
                  "observed_module_calls": calls, "observed_model_inputs": observed_inputs[0],
                  "process_lifetime_peak_rss_bytes": {"before_load": before_rss,
                      "after_load": loaded_rss, "after_forward_and_retention": _peak_rss_bytes()},
                  "rss_semantics": "process lifetime peak; not incremental per-input allocation",
                  "probe_overhead": "input hashing and feature snapshot copies are included in timings/RSS",
                  "elapsed_ms": (time.perf_counter() - start) * 1000,
                  "input_kind": "procedural-execution-fixture-without-quality-labels",
                  "multimodal_quality_qualified": False, "energy_measured": False,
                  "independent_hardware_attestation": False,
                  "authority": "DENY_ALL", "production_activation_allowed": False}
        result["receipt_sha256"] = canonical_sha256(result)
        with (destination / "receipt.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        return result
    except Exception as error:
        failure = {"schema": "hepta.real-text-image-execution-probe.v1", "status": "FAILED",
                   "error_type": type(error).__name__, "reason": str(error),
                   "multimodal_quality_qualified": False, "authority": "DENY_ALL"}
        with (destination / "failure.json").open("x", encoding="utf-8") as stream:
            json.dump(failure, stream, sort_keys=True, indent=2, allow_nan=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--accept-model-terms", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.threads <= 8:
        parser.error("threads must be in 1..8")
    torch.set_num_threads(args.threads)
    try:
        result = run_probe(snapshot=args.snapshot,
                           expected_inventory_sha256=args.expected_inventory_sha256,
                           output=args.output, operator_accepted_terms=args.accept_model_terms,
                           device=args.device, max_tokens=args.max_tokens)
    except (FeatureBundleError, RealEncoderError, MediaProbeError, OSError, RuntimeError,
            ImportError) as error:
        print(json.dumps({"status": "FAILED", "reason": str(error)}))
        return 2
    print(json.dumps({"status": result["status"], "output": str(Path(args.output).absolute()),
                      "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
