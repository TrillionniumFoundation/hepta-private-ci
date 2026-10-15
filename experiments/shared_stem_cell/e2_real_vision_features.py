"""E2 DINOv2 feature producer: real-image, pinned-safetensors-only research ingress.

No labels, answers, paired text targets, synthetic fallback, or capability grants.
The detached pure parser is testable with fake image bytes; only run() admits
real snapshots, rigorously checks saved vs loaded tensors and counts forwards.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time

MODEL_REPO = "facebook/dinov2-small"
MODEL_REVISION = "150c8e7bb7cef2d30ec31b13a517af14840ee3f7"
WEIGHTS_SHA256 = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"
FILES = ("config.json", "preprocessor_config.json", "model.safetensors")
SCHEMA = "hepta.e2.dinov2-source-features.v1"
INPUT_SCHEMA = "hepta.e2.image-source-only.v1"
HEX = set("0123456789abcdef")
CONDITIONS = {"text_sufficient", "vision_required", "visual_evidence_removed", "visual_evidence_swapped"}


class Rejected(ValueError):
    pass


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def digest(s: str) -> str:
    if type(s) is not str or len(s) != 64 or set(s) - HEX or s == "0"*64:
        raise Rejected("invalid nonzero hex digest")
    return s


def canonical(x: object) -> bytes:
    return (json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode()


def _unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise Rejected("duplicate JSON key")
        result[k] = v
    return result


def checked_file(path: Path, expected: str, limit: int) -> bytes:
    digest(expected)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise Rejected("unsafe or oversized file")
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise Rejected("file SHA mismatch")
    return raw


def parse_source(raw: bytes, expected_sha: str, phase: str) -> list[dict]:
    if phase not in ("train", "future") or sha(raw) != digest(expected_sha):
        raise Rejected("wrong source bytes or phase")
    if len(raw) > 5_000_000 or not raw or not raw.endswith(b"\n"):
        raise Rejected("source file bounds or canonical newline violated")
    lines = raw.splitlines()
    if not 1 <= len(lines) <= 256:
        raise Rejected("source case limit exceeded")
    rows = []
    ids, groups, scopes, pictures = set(), set(), set(), set()
    for line in lines:
        if not line or len(line) > 16_384:
            raise Rejected("oversized source record")
        obj = json.loads(line, object_pairs_hook=_unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(Rejected("nonfinite JSON")))
        required = {"case_id", "group_id", "scope", "observed_at", "split", "condition",
                    "image_path", "image_sha256", "question", "source_sha256"}
        if type(obj) is not dict or set(obj) != required or obj["split"] != phase:
            raise Rejected("labels, targets or undeclared source fields forbidden")
        for name in ("case_id", "group_id", "scope", "question"):
            if type(obj[name]) is not str or not 1 <= len(obj[name].encode()) <= (2048 if name == "question" else 128):
                raise Rejected("invalid source field " + name)
        if type(obj["observed_at"]) is not int or not 0 <= obj["observed_at"] < 2**63:
            raise Rejected("invalid observation timestamp")
        if obj["condition"] not in CONDITIONS:
            raise Rejected("unsupported condition")
        if obj["condition"] == "visual_evidence_removed":
            raise Rejected("no-image intervention must not fabricate an image Encoder forward")
        if obj["case_id"] in ids:
            raise Rejected("duplicate case id")
        ids.add(obj["case_id"])
        scopes.add(obj["scope"])
        groups.add(obj["group_id"])
        filename = obj["image_path"]
        if type(filename) is not str or filename in ("", ".", "..") or len(filename) > 128 or any(c in filename for c in ("/", "\\", "\x00")):
            raise Rejected("only root-local, single-component image filenames allowed")
        if filename in pictures:
            # Identical image inputs can be reused for different interventions only with a separate
            # actual source case; this runner does not infer case-level independence.
            pass
        pictures.add(filename)
        digest(obj["image_sha256"])
        digest(obj["source_sha256"])
        # The case seal must include image identity AND question/intervention; not just a free caller-supplied token.
        expected_case = sha(canonical(["hepta.e2.image-case.v1", obj["case_id"], obj["group_id"], obj["scope"], obj["observed_at"], obj["condition"],
                                       obj["image_sha256"], obj["question"]]))
        if obj["source_sha256"] != expected_case:
            raise Rejected("source identity does not bind image+question+condition")
        rows.append(obj)
    if len(scopes) != 1:
        raise Rejected("cross-scope source set")
    if phase == "train" and len(groups) < 2:
        raise Rejected("train requires at least two source groups")
    return rows


def validate_vector(vector: object) -> list[float]:
    try:
        arr = vector.tolist()
    except AttributeError:
        arr = vector
    if type(arr) is not list or len(arr) != 384 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 8 for v in arr):
        raise Rejected("invalid physical 384D floating feature")
    return [float(v) for v in arr]


def _load_image(path: Path, expected: str):
    from PIL import Image, ImageFile
    import warnings
    Image.MAX_IMAGE_PIXELS = 2_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    raw = checked_file(path, expected, 10_000_000)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.format not in ("JPEG", "PNG", "WEBP"):
                raise Rejected("unsupported image format")
            image = opened.convert("RGB")
    if not 8 <= image.width <= 4096 or not 8 <= image.height <= 4096:
        raise Rejected("unsupported image size")
    return image


def _verify_saved_state(snapshot: Path, model):
    from safetensors import safe_open
    with safe_open(str(snapshot / "model.safetensors"), framework="pt", device="cpu") as safes:
        state = model.state_dict()
        original_keys = set(safes.keys())
        if not original_keys or set(state) != original_keys:
            raise Rejected("saved/loaded tensor-key mismatch")
        import torch
        for key in sorted(original_keys):
            original = safes.get_tensor(key)
            actual = state[key].detach().cpu()
            if original.shape != actual.shape or original.dtype != actual.dtype or not torch.equal(original, actual):
                raise Rejected("saved pretrained tensor altered: " + key)


def run(snapshot: Path, images: Path, input_path: Path, input_sha: str, phase: str,
        config_sha: str, processor_sha: str, output_dir: Path):
    import torch
    from transformers import AutoImageProcessor, AutoModel
    raw = checked_file(input_path, input_sha, 5_000_000)
    rows = parse_source(raw, input_sha, phase)
    if not snapshot.is_dir() or snapshot.is_symlink() or not images.is_dir() or images.is_symlink():
        raise Rejected("model and image roots must be physical directories")
    if set(p.name for p in snapshot.iterdir()) != set(FILES):
        raise Rejected("snapshot must have exactly three approved original files")
    file_hashes = {"model.safetensors": WEIGHTS_SHA256, "config.json": digest(config_sha),
                   "preprocessor_config.json": digest(processor_sha)}
    for fn in FILES:
        checked_file(snapshot / fn, file_hashes[fn], 125_000_000)
    config = json.loads((snapshot / "config.json").read_bytes(), object_pairs_hook=_unique)
    if config.get("model_type") != "dinov2" or config.get("hidden_size") != 384:
        raise Rejected("unapproved architecture")
    processor = AutoImageProcessor.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(str(snapshot), local_files_only=True,
                                      trust_remote_code=False, use_safetensors=True).eval().cpu()
    _verify_saved_state(snapshot, model)
    enc_id = sha(canonical([MODEL_REPO, MODEL_REVISION, file_hashes, "cls-first-token", "l2"] ))
    examples = []
    started = time.perf_counter_ns()
    model_calls = 0
    with torch.inference_mode():
        for row in rows:
            photo = _load_image(images / row["image_path"], row["image_sha256"])
            inputs = processor(images=photo, return_tensors="pt")
            hidden = model(**inputs).last_hidden_state
            model_calls += 1
            if tuple(hidden.shape[:2])[:1] != (1,) or hidden.shape[-1] != 384:
                raise Rejected("invalid pretrained hidden state")
            vector = hidden[0, 0, :].to(dtype=torch.float32)
            norm = torch.linalg.vector_norm(vector)
            if not torch.isfinite(norm) or not bool(norm > 0):
                raise Rejected("invalid vision output norm")
            values = validate_vector((vector / norm).tolist())
            examples.append({k: row[k] for k in ("case_id", "group_id", "scope", "observed_at", "split", "condition",
                                                   "image_sha256", "question", "source_sha256")})
            examples[-1]["source"] = {"modality": "image", "input_sha256": row["image_sha256"],
                                       "encoder_sha256": enc_id, "values": values}
    elapsed = time.perf_counter_ns() - started
    if model_calls != len(examples):
        raise Rejected("physical forward count mismatch")
    _verify_saved_state(snapshot, model)
    for fn in FILES:
        checked_file(snapshot / fn, file_hashes[fn], 125_000_000)
    payload = b"".join(canonical(row) for row in examples)
    record = {"schema": SCHEMA, "phase": phase, "encoder_repo": MODEL_REPO,
              "encoder_revision": MODEL_REVISION, "source_sha256": input_sha,
              "output_sha256": sha(payload), "snapshot_file_sha256s": file_hashes,
              "image_count": len(rows), "actual_model_forwards": model_calls,
              "feature_width": 384, "wall_ns": elapsed,
              "checkpoint_locally_byte_verified": True,
              "publisher_authenticated": False, "labels_seen": False,
              "production_accepted": False, "authority": "DENY_ALL"}
    output_dir.mkdir(exist_ok=False, parents=False)
    def create(path, content):
        with path.open("xb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    create(output_dir / "features.jsonl", payload)
    create(output_dir / "receipt.json", canonical(record))
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--phase", choices=["train", "future"], required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--processor-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    a = parser.parse_args()
    run(a.snapshot, a.images, a.input, a.input_sha256, a.phase,
        a.config_sha256, a.processor_sha256, a.output_dir)

if __name__ == "__main__":
    main()
