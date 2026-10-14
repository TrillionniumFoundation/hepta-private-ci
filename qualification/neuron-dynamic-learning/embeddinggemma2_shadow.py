"""EmbeddingGemma 2 offline, untrusted-input-denying shadow qualifier.

Does not download models, publish cell state, train a production model, mint
an inference receipt or authorize FinalUse. Actual model execution is optional
and requires an independently reviewed local SHA256-complete snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import time

import numpy as np

from offline_stem import canonical_bytes, quantize_q24, rust_feature_digest_q24

MODEL = "google/embeddinggemma-2"
PROFILES = {
    "text": ({"text", "code"}, {"vision_config": None, "audio_config": None}, 270),
    "vision": ({"text", "code", "image", "video"}, {"audio_config": None}, 440),
    "audio": ({"text", "code", "audio"}, {"vision_config": None}, 570),
    "all": ({"text", "code", "image", "audio", "video"}, {}, 740),
}
EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "audio": {".wav", ".flac", ".ogg"},
    "video": {".mp4", ".webm", ".mov", ".mkv"},
}
DIMENSIONS = {128, 256, 512, 768}
ROLES = {"search_query", "document", "classification", "code_retrieval"}
MAX_MEDIA_BYTES = 256 * 1024 * 1024
MAX_BATCH = 32


class QualificationError(ValueError):
    """Wrong identity, corrupted data, unsupported execution or missing evidence."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_sha(value: object, size: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % size, value) is not None


def _bounded_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value) is not None


def _verify_file_tree(root: Path, names: dict) -> None:
    if not isinstance(names, dict) or not names:
        raise QualificationError("complete local file inventory required")
    actual = set()
    weights = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise QualificationError("symlink forbidden in model snapshot")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if set(names) != actual:
        raise QualificationError("snapshot file inventory incomplete")
    for name, expected in names.items():
        relative = Path(name)
        if (not isinstance(name, str) or relative.is_absolute() or not name
                or ".." in relative.parts or "\\" in name or not is_sha(expected, 64)):
            raise QualificationError("unsafe model file entry")
        path = root / relative
        # Deserialization of arbitrary PyTorch pickle or executable payloads is forbidden.
        # Only safetensors and inert reviewed config/tokenizer/preprocessor assets
        # may be present in a pinned snapshot (exact inventory is still required).
        if not path.is_file() or path.suffix.lower() in {
            ".py", ".pyc", ".pyo", ".pkl", ".pickle", ".pt", ".pth", ".bin",
            ".so", ".dylib", ".dll", ".exe", ".sh", ".bat", ".ps1",
        }:
            raise QualificationError("unsafe executable/serialized artifact or missing model file")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        if hasher.hexdigest() != expected:
            raise QualificationError("model artifact bytes changed")
        weights += name.endswith(".safetensors")
    if weights == 0:
        raise QualificationError("safetensors weight required")


def load_manifest(path: Path) -> tuple[dict, Path, str]:
    if path.is_symlink():
        raise QualificationError("manifest symlink forbidden")
    path = path.resolve(strict=True)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {"model_id", "revision", "snapshot", "files", "runtime", "profile",
                "dimension", "precision", "license"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise QualificationError("unknown or missing pinned manifest field")
    if (manifest["model_id"] != MODEL or not is_sha(manifest["revision"], 40)
            or not isinstance(manifest["profile"], str)
            or manifest["profile"] not in PROFILES
            or type(manifest["dimension"]) is not int or manifest["dimension"] not in DIMENSIONS
            or not isinstance(manifest["precision"], str)
            or manifest["precision"] not in ("float32", "bfloat16")
            or manifest["license"] != "Apache-2.0"):
        raise QualificationError("unsupported model, size, dtype, license or revision")
    runtime = manifest["runtime"]
    packages = {"torch", "transformers", "tokenizers", "safetensors", "sentence-transformers"}
    if manifest["profile"] != "text":
        packages |= {"pillow", "soundfile", "torchcodec"}
    if not isinstance(runtime, dict) or set(runtime) != packages or any(
        not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9.+_-]{1,64}", v)
        for v in runtime.values()
    ):
        raise QualificationError("incomplete pinned runtime")
    name = manifest["snapshot"]
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise QualificationError("unsafe snapshot path")
    root = path.parent / name
    if root.is_symlink():
        raise QualificationError("snapshot symlink forbidden")
    root = root.resolve(strict=True)
    if not root.is_dir() or not root.is_relative_to(path.parent):
        raise QualificationError("snapshot outside approved root")
    _verify_file_tree(root, manifest["files"])
    profile_digest = sha256(b"hepta.embeddinggemma2.shadow.v1" + canonical_bytes(manifest))
    return manifest, root, profile_digest


def validate_sample(row: dict, profile: str, media_root: Path | None) -> tuple[tuple, object]:
    required = {"scope_id", "principal_id", "purpose_id", "cell_id",
                "generation", "authority_epoch", "input"}
    if not isinstance(row, dict) or set(row) != required:
        raise QualificationError("exact scoped Cell request required")
    if any(not _bounded_id(row[k]) for k in ("scope_id", "principal_id", "purpose_id", "cell_id")):
        raise QualificationError("bad Cell principal/scope identity")
    if any(type(row[k]) is not int or row[k] < 1 for k in ("generation", "authority_epoch")):
        raise QualificationError("invalid generation or authority epoch")
    inp = row["input"]
    if not isinstance(inp, dict) or set(inp) != {"modality", "role", "value", "sha256"}:
        raise QualificationError("exact modality span required")
    modality, role, value, expected = (inp[k] for k in ("modality", "role", "value", "sha256"))
    if modality not in PROFILES[profile][0] or role not in ROLES or not is_sha(expected, 64):
        raise QualificationError("modality / role / digest mismatch")
    if not isinstance(value, str) or not value or len(value) > 32768:
        raise QualificationError("unbounded input")
    if modality in ("text", "code"):
        if sha256(value.encode("utf-8")) != expected:
            raise QualificationError("text source digest mismatch")
        payload = value
    else:
        if media_root is None:
            raise QualificationError("media requires approved local source root")
        relative = Path(value)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in value
                or "://" in value or value.startswith("//")):
            raise QualificationError("network and path traversal denied")
        media_root = media_root.resolve(strict=True)
        target = media_root / relative
        if any(p.is_symlink() for p in (target, *target.parents) if p == media_root or media_root in p.parents):
            raise QualificationError("media symlinks forbidden")
        try:
            target = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise QualificationError("media missing or unsafe path") from exc
        if (not target.is_relative_to(media_root) or not target.is_file()
                or target.suffix.lower() not in EXTENSIONS[modality]
                or not 0 < target.stat().st_size <= MAX_MEDIA_BYTES):
            raise QualificationError("unsafe media or oversized asset")
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise QualificationError("media bytes changed")
        payload = {modality: str(target)}
    key = (row["scope_id"], row["principal_id"], row["purpose_id"],
           row["generation"], row["authority_epoch"], modality, role, expected)
    return key, payload


def normalize_truncation(vector: object, dimension: int) -> list[float]:
    """Independent Matryoshka oracle; reject zero/nonfinite, re-normalize after slicing."""
    values = np.asarray(vector, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != 768 or dimension not in DIMENSIONS:
        raise QualificationError("expected exact 768d native representation")
    if not np.isfinite(values).all():
        raise QualificationError("nonfinite source embedding")
    cropped = values[:dimension]
    norm = float(np.linalg.norm(cropped))
    if not math.isfinite(norm) or norm < 1e-12:
        raise QualificationError("zero or invalid MRL prefix")
    return (cropped / norm).tolist()


def _prompt(role: str, modality: str) -> str | None:
    if modality not in ("text", "code"):
        return None
    return {"search_query": "SearchQuery", "document": "Document",
            "classification": "Classification", "code_retrieval": "CodeRetrieval"}[role]


class FrozenGemmaShadow:
    def __init__(self, manifest_path: Path, *, device: str = "cpu"):
        self.manifest, self.snapshot, self.profile_digest = load_manifest(manifest_path)
        if device not in ("cpu", "cuda"):
            raise QualificationError("unapproved execution device")
        # Disable any hub use before optional imports or model initialization.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        for package, expected in self.manifest["runtime"].items():
            try:
                installed = metadata.version(package)
            except metadata.PackageNotFoundError as exc:
                raise QualificationError("missing pinned local inference runtime") from exc
            if installed != expected:
                raise QualificationError("local runtime version mismatch")
        import torch
        from sentence_transformers import SentenceTransformer
        precision = self.manifest["precision"]
        if device == "cuda" and not torch.cuda.is_available():
            raise QualificationError("CUDA requested but unavailable")
        if precision == "bfloat16" and (device != "cuda" or not torch.cuda.is_bf16_supported()):
            raise QualificationError("BF16 requires supported CUDA hardware")
        dtype = torch.bfloat16 if precision == "bfloat16" else torch.float32
        self.model = SentenceTransformer(
            str(self.snapshot), device=device, model_kwargs={"torch_dtype": dtype},
            config_kwargs=PROFILES[self.manifest["profile"]][1],
            local_files_only=True, trust_remote_code=False,
        )
        self.model.eval()
        self._inference_context = torch.inference_mode
        self.model_encode_calls = 0
        # Set only after complete on-disk digest and pinned-runtime validation,
        # and after real SentenceTransformer loading succeeds. This is NOT an
        # independent attestation of Hugging Face origin or worker ownership.
        self._verified_local_weights = True

    def encode_cells(self, requests: list[dict], *, media_root: Path | None = None) -> dict:
        if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_BATCH:
            raise QualificationError("unbounded Cell batch")
        started = time.perf_counter_ns()
        prior_encode_calls = self.model_encode_calls
        first = requests[0]
        domain = tuple(first.get(k) for k in
                       ("scope_id", "principal_id", "purpose_id", "generation", "authority_epoch"))
        keys, unique = [], {}
        cells = set()
        for row in requests:
            key, payload = validate_sample(row, self.manifest["profile"], media_root)
            if key[:5] != domain or row["cell_id"] in cells:
                raise QualificationError("cross-scope cache or duplicate Cell")
            cells.add(row["cell_id"])
            keys.append(key)
            unique.setdefault(key, payload)
        output = {}
        groups = {}
        for key, payload in unique.items():
            groups.setdefault((key[-3], _prompt(key[-2], key[-3])), []).append((key, payload))
        for (_, prompt), chunk in groups.items():
            arguments = [payload for _, payload in chunk]
            # API calls are NOT equivalent to physical transformer forward count.
            with self._inference_context():
                encoded = self.model.encode(
                    arguments, prompt_name=prompt, batch_size=8,
                    truncate_dim=self.manifest["dimension"], normalize_embeddings=True,
                    convert_to_numpy=True, show_progress_bar=False,
                )
            self.model_encode_calls += 1
            array = np.asarray(encoded, dtype=np.float64)
            if array.shape != (len(chunk), self.manifest["dimension"]):
                raise QualificationError("model ignored MRL dimension / wrong output count")
            for (key, _), vector in zip(chunk, array):
                norm = float(np.linalg.norm(vector))
                if not np.isfinite(vector).all() or abs(norm - 1.0) > 0.005:
                    raise QualificationError("nonfinite or non-normalized real model output")
                output[key] = vector
        result = []
        for row, key in zip(requests, keys):
            vector = output[key]
            compatible = self.manifest["dimension"] <= 256
            q24 = quantize_q24(vector.tolist()) if compatible else None
            result.append({
                "cell_id": row["cell_id"], "input_digest": key[-1],
                "scope_id": row["scope_id"], "principal_id": row["principal_id"],
                "purpose_id": row["purpose_id"], "generation": row["generation"],
                "authority_epoch": row["authority_epoch"],
                "modality": key[-3], "role": key[-2],
                "embedding_f32_digest": sha256(np.asarray(vector, dtype="<f4").tobytes()),
                "features_q24": q24,
                "feature_digest": rust_feature_digest_q24(q24) if q24 is not None else None,
                "requires_new_neuron_profile": not compatible,
                "pipeline_digest": self.profile_digest,
                "authority": "DENY_ALL",
            })
        return {
            "evidence_type": (
                "local_weight_execution_unverified_origin"
                if getattr(self, "_verified_local_weights", False)
                else "deterministic_stub_contract_only"
            ),
            "physical_local_model_execution": bool(getattr(self, "_verified_local_weights", False)),
            "model_origin_independently_authenticated": False,
            "model_id": MODEL, "model_revision": self.manifest["revision"],
            "profile": self.manifest["profile"], "feature_dimension": self.manifest["dimension"],
            "distinct_input_rows": len(unique), "cell_requests": len(requests),
            "sentence_transformer_encode_calls": self.model_encode_calls - prior_encode_calls,
            "physical_transformer_forward_calls": None,
            "measured_wall_micros": (time.perf_counter_ns() - started) // 1000,
            "independently_authenticated_receipt": False,
            "production_promotion": "DENY_ALL", "rows": result,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline EmbeddingGemma 2 Stem shadow")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    runner = FrozenGemmaShadow(args.manifest, device=args.device)
    result = runner.encode_cells(
        json.loads(args.requests.read_text(encoding="utf-8")), media_root=args.media_root,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
