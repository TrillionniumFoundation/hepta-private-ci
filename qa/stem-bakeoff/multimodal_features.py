"""Shared, frozen COCO modality bank and explicitly defined late-fusion views.

The image channel uses one fixed neutral text prompt required by the processor.
Captions and images are each encoded once, independently of pair labels. A
joint Cell reads both cached channels; this is late fusion, not a joint-token
cross-attention experiment. No labels or source IDs enter the model inputs.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import resource
import time
import zipfile

import numpy as np
import torch

from feature_bundle import FeatureBundleV1, FeatureIdentityV1
from real_encoder import CANDIDATES, FrozenRealEncoder, canonical_sha256
from real_model_bakeoff import model_tensor_digest, rss_observation

IMAGE_PROMPT = "Image."
FUSION = "concat-text-image-product-absolute-difference-cosine-v1"
ARMS = ("text_only", "image_only", "text_image")
INTERVENTIONS = ("paired", "missing_text", "missing_image", "shuffled_image")
MAX_BANK_BYTES = 32 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def bank_code_identity():
    names = ("multimodal_features.py", "multimodal_cohorts.py", "real_encoder.py",
             "real_encoder_candidates.json", "feature_bundle.py", "teacher_snapshot.py",
             "teacher_forward.py", "teacher_media_seal.py", "real_model_bakeoff.py")
    return {name: _sha(Path(__file__).with_name(name).read_bytes()) for name in names}


def bank_tensor_digest(features):
    """Bind tensor values independently of their NPZ container representation."""
    if set(features) != {"text", "image"}:
        raise ValueError("exactly two modality arrays required")
    digest = hashlib.sha256()
    for name in ("text", "image"):
        value = features[name]
        if isinstance(value, torch.Tensor):
            if value.device.type != "cpu" or value.requires_grad:
                raise ValueError("frozen CPU bank required")
            value = value.detach().numpy()
        value = np.asarray(value)
        if (value.ndim != 2 or value.dtype != np.dtype("float32")
                or value.nbytes > MAX_BANK_BYTES // 2 or not np.isfinite(value).all()):
            raise ValueError("invalid bounded bank tensor")
        digest.update(_json([name, str(value.dtype), list(value.shape)]))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _validate_manifest(manifest):
    shape = manifest["shape"]
    if (type(shape) is not list or len(shape) != 2
            or any(type(v) is not int for v in shape)
            or not 2 <= shape[0] <= 2048 or not 1 <= shape[1] <= 1024
            or manifest["plan"]["code_file_sha256"] != bank_code_identity()
            or len(manifest["image_ids"]) != shape[0]
            or any(type(v) is not int or v < 0 for v in manifest["image_ids"])
            or len(set(manifest["image_ids"])) != shape[0]
            or set(manifest["provenance"]) != {"text", "image"}
            or any(len(v) != shape[0] or any(type(h) is not str or not HEX.fullmatch(h) for h in v)
                   for v in manifest["provenance"].values())
            or not HEX.fullmatch(manifest["feature_tensor_sha256"])):
        raise ValueError("invalid bank shape, source provenance or code identity")


def _verify_features(manifest, features):
    _validate_manifest(manifest)
    if (any(list(v.shape) != manifest["shape"] for v in features.values())
            or bank_tensor_digest(features) != manifest["feature_tensor_sha256"]):
        raise ValueError("bank tensor shape or immutable values changed")


def _unique_images(rows):
    selected = {}
    for split in rows.values():
        for row in split:
            if row["label"] == 1:
                image_id = row["image_id"]
                if image_id in selected:
                    raise ValueError("a source image has multiple selected positive captions")
                selected[image_id] = row
    return [selected[key] for key in sorted(selected)]


def build_bank(*, cohorts, snapshot, inventory_sha256, output,
               operator_accepted_terms, threads=4, batch_size=2):
    from multimodal_cohorts import load_cohorts
    if (operator_accepted_terms is not True or type(threads) is not int
            or not 1 <= threads <= 8 or type(batch_size) is not int
            or not 1 <= batch_size <= 4):
        raise ValueError("invalid bounded encoder budget")
    root, target = Path(cohorts).resolve(), Path(output).absolute()
    if target.exists() or not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("new output directory with a real existing parent required")
    data_hash = _sha((root / "manifest.json").read_bytes())
    dataset, rows = load_cohorts(root, expected_manifest_sha256=data_hash)
    images = _unique_images(rows)
    if not 2 <= len(images) <= 2048:
        raise ValueError("source image bank outside budget")
    target.mkdir(mode=0o700)
    code = bank_code_identity()
    plan = {"schema": "hepta.multimodal-feature-bank-plan.v1",
            "dataset_manifest_sha256": data_hash, "image_count": len(images),
            "candidate": "embeddinggemma2_740m", "profile": "text_image",
            "checkpoint_revision": CANDIDATES["embeddinggemma2_740m"]["revision"],
            "checkpoint_inventory_sha256": inventory_sha256,
            "task": "classification", "image_neutral_prompt": IMAGE_PROMPT,
            "max_tokens": 1024, "batch_size": batch_size, "threads": threads,
            "code_file_sha256": code, "labels_enter_model_inputs": False}
    (target / "plan.json").write_bytes(_json(plan) + b"\n")
    torch.set_num_threads(threads)
    began = time.perf_counter()
    owner = FrozenRealEncoder(candidate="embeddinggemma2_740m", snapshot=snapshot,
        revision=plan["checkpoint_revision"], expected_inventory_sha256=inventory_sha256,
        operator_accepted_terms=True, profile="text_image", max_tokens=1024,
        task="classification", scope_id="coco-pair-research")
    before = model_tensor_digest(owner._model)
    arrays, provenance, receipt_files = {}, {}, {}
    observed = {"model": 0, "vision": 0}
    def root_hook(_module, _inputs, _output):
        observed["model"] += 1
    def vision_hook(_module, _inputs, _output):
        observed["vision"] += 1
    handles = [owner._model.register_forward_hook(root_hook),
               owner._model.vision_tower.register_forward_hook(vision_hook)]
    try:
        for channel in ("text", "image"):
            features, evidence, receipts = [], [], []
            for offset in range(0, len(images), batch_size):
                batch = images[offset:offset + batch_size]
                records = [{"text": row["text"]} if channel == "text" else
                           {"text": IMAGE_PROMPT, "image": row["image_path"]} for row in batch]
                metadata = [{"image_id": row["image_id"], "caption_id": row["caption_id"],
                    "source_image_sha256": row["image_sha256"],
                    "source_caption_sha256": row["text_sha256"], "channel": channel}
                    for row in batch]
                bundle = owner.encode_records(records, media_root=root, source_records=metadata)
                features.append(bundle.read_global())
                evidence.extend(bundle.source_record_digests)
                receipts.append({"offset": offset, "source_ids": [r["image_id"] for r in batch],
                    "bundle_manifest": bundle.manifest(), **owner.last_receipt})
                print(json.dumps({"channel": channel, "encoded": offset + len(batch),
                                  "total": len(images), "rss": rss_observation()["bytes"]}), flush=True)
            arrays[channel] = torch.cat(features).numpy()
            provenance[channel] = evidence
            payload = _json(receipts) + b"\n"
            name = f"{channel}-receipts.json"
            (target / name).write_bytes(payload)
            receipt_files[channel] = {"file": name, "sha256": _sha(payload),
                "model_calls": len(receipts), "encoded_rows": len(images),
                "encode_ms": sum(r["encode_ms"] for r in receipts),
                "forward_ms_samples": [r["forward_ms"] for r in receipts],
                "batch_sizes": [r["batch_size"] for r in receipts]}
    finally:
        for handle in handles:
            handle.remove()
    after = model_tensor_digest(owner._model)
    if before != after or any(p.grad is not None or p.requires_grad for p in owner._model.parameters()):
        raise ValueError("frozen shared encoder changed")
    if code != bank_code_identity() or _sha((root / "manifest.json").read_bytes()) != data_hash:
        raise ValueError("bank source changed during execution")
    # Reload verifies original media bytes and deterministic pairing after all forwards.
    load_cohorts(root, expected_manifest_sha256=data_hash)
    stream = io.BytesIO()
    np.savez(stream, **arrays)
    payload = stream.getvalue()
    if len(payload) > MAX_BANK_BYTES:
        raise ValueError("feature bank exceeds byte budget")
    (target / "features.npz").write_bytes(payload)
    manifest = {"schema": "hepta.multimodal-feature-bank.v1", "plan": plan,
        "plan_sha256": canonical_sha256(plan), "base_identity": asdict(owner.identity),
        "image_ids": [r["image_id"] for r in images], "provenance": provenance,
        "features_file": "features.npz", "features_sha256": _sha(payload),
        "feature_tensor_sha256": bank_tensor_digest(arrays),
        "shape": list(arrays["text"].shape), "feature_storage_bytes": sum(a.nbytes for a in arrays.values()),
        "encoder": {**owner.accounting, "tensor_sha256_before": before,
                    "tensor_sha256_after": after, "load_ms": owner.load_ms},
        "receipts": receipt_files, "observed_module_calls": observed,
        "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "runtime": {"platform": platform.platform(), "torch": torch.__version__,
                    "wall_ms": (time.perf_counter() - began) * 1000},
        "image_only_contains_fixed_neutral_text": True,
        "foundation_pretraining_contamination_excluded": False,
        "authority": "DENY_ALL", "production_activation_allowed": False}
    if observed != {"model": sum(v["model_calls"] for v in receipt_files.values()),
                    "vision": receipt_files["image"]["model_calls"]}:
        raise ValueError("observed model/vision calls differ from retained receipts")
    (target / "manifest.json").write_bytes(_json(manifest) + b"\n")
    return manifest


def load_bank(directory, *, expected_manifest_sha256, expected_data_sha256):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("real bank directory required")
    path = root / "manifest.json"
    if path.is_symlink() or path.stat().st_size > MAX_BANK_BYTES:
        raise ValueError("invalid bank manifest")
    raw = path.read_bytes()
    if _sha(raw) != expected_manifest_sha256:
        raise ValueError("bank manifest differs from external pin")
    manifest = json.loads(raw)
    if (manifest["schema"] != "hepta.multimodal-feature-bank.v1"
            or manifest["plan"]["dataset_manifest_sha256"] != expected_data_sha256
            or canonical_sha256(manifest["plan"]) != manifest["plan_sha256"]
            or manifest["features_file"] != "features.npz"
            or manifest["authority"] != "DENY_ALL"
            or manifest["production_activation_allowed"] is not False):
        raise ValueError("bank dataset, plan or authority mismatch")
    _validate_manifest(manifest)
    path = root / "features.npz"
    if path.is_symlink() or path.stat().st_size > MAX_BANK_BYTES:
        raise ValueError("invalid feature payload")
    raw = path.read_bytes()
    if _sha(raw) != manifest["features_sha256"]:
        raise ValueError("feature payload hash mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != 2 or {e.filename for e in entries} != {"text.npy", "image.npy"}
                or sum(e.file_size for e in entries) > MAX_BANK_BYTES):
            raise ValueError("invalid feature array inventory")
        for entry in entries:
            with archive.open(entry) as stream:
                version = np.lib.format.read_magic(stream)
                if version not in ((1, 0), (2, 0)):
                    raise ValueError("unsupported bank array header")
                reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                          else np.lib.format.read_array_header_2_0)
                shape, fortran, dtype = reader(stream, max_header_size=4096)
                if (list(shape) != manifest["shape"] or fortran
                        or dtype != np.dtype("float32")
                        or entry.file_size - stream.tell() != shape[0] * shape[1] * 4):
                    raise ValueError("bank header violates declared shape/dtype/budget")
    with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
        features = {key: torch.from_numpy(arrays[key].copy()) for key in ("text", "image")}
    _verify_features(manifest, features)
    if set(manifest["receipts"]) != {"text", "image"}:
        raise ValueError("both modality receipts required")
    for channel, receipt in manifest["receipts"].items():
        path = root / receipt["file"]
        if (receipt["file"] != f"{channel}-receipts.json" or path.parent != root
                or path.is_symlink() or not path.is_file()
                or path.stat().st_size > MAX_BANK_BYTES
                or _sha(path.read_bytes()) != receipt["sha256"]):
            raise ValueError("bank forward receipt mismatch")
    return manifest, features


def pair_features(rows, bank_manifest, bank_features, *, arm, intervention="paired"):
    """Use the same width and fixed transform for all arms; no learned projection."""
    if arm not in ARMS or intervention not in INTERVENTIONS or not 1 <= len(rows) <= 512:
        raise ValueError("invalid bounded paired feature request")
    _verify_features(bank_manifest, bank_features)
    index = {value: i for i, value in enumerate(bank_manifest["image_ids"])}
    partner = {}
    if intervention == "shuffled_image":
        blocks = {}
        for row in rows:
            blocks.setdefault(row["pair_block_id"], set()).add(row["image_id"])
        if any(len(ids) != 2 for ids in blocks.values()):
            raise ValueError("swapping requires exactly two images per independent block")
        for ids in blocks.values():
            a, b = sorted(ids)
            partner.update({a: b, b: a})
    image_ids = [partner.get(r["image_id"], r["image_id"]) for r in rows]
    text_ids = [r["source_caption_image_id"] for r in rows]
    text = bank_features["text"][[index[i] for i in text_ids]].clone()
    vision = bank_features["image"][[index[i] for i in image_ids]].clone()
    text_missing = arm == "image_only" or intervention == "missing_text"
    image_missing = arm == "text_only" or intervention == "missing_image"
    if text_missing and image_missing:
        raise ValueError("both modalities missing")
    if text_missing:
        text.zero_()
    if image_missing:
        vision.zero_()
    # Interaction features disappear when either evidence channel is missing.
    joint = not text_missing and not image_missing
    product = text * vision if joint else torch.zeros_like(text)
    difference = (text - vision).abs() if joint else torch.zeros_like(text)
    cosine = torch.nn.functional.cosine_similarity(text, vision).unsqueeze(1) if joint else torch.zeros((len(rows), 1))
    fused = torch.cat((text, vision, product, difference, cosine), dim=1)
    base = FeatureIdentityV1(**bank_manifest["base_identity"])
    identity = replace(base, preprocess_sha256=canonical_sha256({
        "base": base.preprocess_sha256, "fusion": FUSION,
        "image_prompt": IMAGE_PROMPT, "missing_interactions": "zero",
        "feature_code_sha256": _sha(Path(__file__).read_bytes())}))
    sources = tuple(canonical_sha256({"row": r, "arm": arm, "intervention": intervention,
        "text_feature_source": bank_manifest["provenance"]["text"][index[t]],
        "image_feature_source": bank_manifest["provenance"]["image"][index[i]],
        "bank_feature_sha256": bank_manifest["features_sha256"]})
        for r, t, i in zip(rows, text_ids, image_ids))
    return FeatureBundleV1.from_tensors(global_features=fused,
        source_record_digests=sources, identity=identity,
        missing_mask=torch.tensor([[text_missing, image_missing, True, True, True]] * len(rows)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cohorts", "snapshot", "inventory-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=2)
    build_bank(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
