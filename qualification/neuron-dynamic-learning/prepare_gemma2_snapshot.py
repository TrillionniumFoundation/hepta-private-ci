"""Opt-in SHA-pinned public EmbeddingGemma 2 snapshot preparation.

Only an explicit CLI invocation contacts Hugging Face. It verifies the exact
remote commit, declared Apache-2.0 license, safe file inventory and LFS SHA256
when present, then publishes a complete local snapshot/manifest. This does not
authenticate the origin cryptographically or authorize model promotion.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from embeddinggemma2_shadow import MODEL, PROFILES, DIMENSIONS, QualificationError, load_manifest

MAX_FILES = 256
MAX_TOTAL_BYTES = 4 * 1024**3
ALLOWED_SUFFIXES = {".json", ".txt", ".model", ".safetensors", ".vocab",
                    ".tiktoken", ".sentencepiece", ".jinja", ".merges"}
REQUIRED_PACKAGES = {"torch", "transformers", "tokenizers", "safetensors",
                     "sentence-transformers"}
MULTIMODAL_PACKAGES = {"pillow", "soundfile", "torchcodec"}


def remote_plan(info: object, revision: str) -> list[tuple[str, str | None, int | None]]:
    """Reject unsupported remote files and floating refs before any download."""
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise QualificationError("40-character model revision required")
    if getattr(info, "sha", None) != revision:
        raise QualificationError("remote model API did not resolve exact commit")
    card = getattr(info, "card_data", None)
    license_name = (card.get("license") if isinstance(card, dict)
                    else getattr(card, "license", None))
    if license_name != "apache-2.0":
        raise QualificationError("upstream Apache-2.0 license not verified by API")
    siblings = getattr(info, "siblings", None)
    if not isinstance(siblings, list) or not siblings or len(siblings) > MAX_FILES:
        raise QualificationError("incomplete or oversized remote file list")
    entries, expected_total = [], 0
    for sibling in siblings:
        name = getattr(sibling, "rfilename", None)
        if not isinstance(name, str) or not name or len(name) > 240:
            raise QualificationError("invalid remote file path")
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or any(part.startswith(".") for part in relative.parts)):
            if name == ".gitattributes":
                continue
            raise QualificationError("unsafe remote file path")
        if name in ("README.md", "LICENSE", "LICENSE.txt"):
            continue
        if relative.suffix.lower() not in ALLOWED_SUFFIXES:
            raise QualificationError("unapproved remote artifact extension")
        size = getattr(sibling, "size", None)
        lfs = getattr(sibling, "lfs", None)
        digest = (lfs.get("sha256") if isinstance(lfs, dict)
                  else getattr(lfs, "sha256", None))
        if digest is not None and not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise QualificationError("invalid remote LFS SHA256")
        if size is not None:
            if type(size) is not int or size <= 0 or size > MAX_TOTAL_BYTES:
                raise QualificationError("invalid source file size")
            expected_total += size
            if expected_total > MAX_TOTAL_BYTES:
                raise QualificationError("remote snapshot exceeds offline resource budget")
        entries.append((name, digest, size))
    if not any(name.endswith(".safetensors") for name, _, _ in entries):
        raise QualificationError("remote snapshot contains no safetensors")
    if not any(name.endswith("config.json") for name, _, _ in entries):
        raise QualificationError("required model configuration missing")
    return sorted(entries)


def prepare_snapshot(revision: str, destination: Path, *, profile: str = "text",
                     dimension: int = 256, precision: str = "float32",
                     api=None, downloader=None, runtime_versions: dict | None = None) -> dict:
    """Create a local manifest without code loading, unsafe refs or partial output."""
    if (profile not in PROFILES or dimension not in DIMENSIONS
            or precision not in ("float32", "bfloat16")):
        raise QualificationError("unregistered device/model configuration")
    destination = Path(destination)
    if destination.exists() or not destination.parent.is_dir() or destination.is_symlink():
        raise QualificationError("destination must not exist and parent must exist")
    if api is None or downloader is None:
        try:
            from huggingface_hub import HfApi, hf_hub_download
        except ImportError as exc:
            raise QualificationError("explicit Hugging Face preparation dependency missing") from exc
        api = HfApi() if api is None else api
        downloader = hf_hub_download if downloader is None else downloader
    info = api.model_info(repo_id=MODEL, revision=revision, files_metadata=True)
    files = remote_plan(info, revision)
    packages = REQUIRED_PACKAGES | (MULTIMODAL_PACKAGES if profile != "text" else set())
    versions = runtime_versions if runtime_versions is not None else {
        name: metadata.version(name) for name in sorted(packages)
    }
    if not isinstance(versions, dict) or set(versions) != packages or any(
        not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9.+_-]{1,64}", v)
        for v in versions.values()
    ):
        raise QualificationError("snapshot runtime inventory not pinned")
    temp = Path(tempfile.mkdtemp(prefix="gemma2-verified-", dir=destination.parent))
    try:
        snapshot = temp / "snapshot"
        snapshot.mkdir(mode=0o700)
        hashes, total_bytes = {}, 0
        for name, lfs_sha, length in files:
            remote_path = Path(downloader(repo_id=MODEL, filename=name, revision=revision))
            if not remote_path.is_file():
                raise QualificationError("download did not return a regular artifact")
            output = snapshot / name
            output.parent.mkdir(parents=True, exist_ok=True)
            digester = hashlib.sha256()
            amount = 0
            with remote_path.open("rb") as src, output.open("xb") as dst:
                while block := src.read(1024 * 1024):
                    amount += len(block)
                    total_bytes += len(block)
                    if total_bytes > MAX_TOTAL_BYTES:
                        raise QualificationError("download exceeded source byte budget")
                    digester.update(block)
                    dst.write(block)
            actual = digester.hexdigest()
            if not amount or (length is not None and amount != length):
                raise QualificationError("source file byte length differs from registry")
            if lfs_sha is not None and actual != lfs_sha:
                raise QualificationError("source file LFS SHA256 differs from registry")
            hashes[name] = actual
        manifest = {
            "model_id": MODEL, "revision": revision, "snapshot": "snapshot",
            "files": hashes, "runtime": versions, "profile": profile,
            "dimension": dimension, "precision": precision, "license": "Apache-2.0",
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        _, _, profile_digest = load_manifest(temp / "manifest.json")
        os.rename(temp, destination)
        return {"source": MODEL, "revision": revision,
                "model_files": len(files), "bytes_verified": total_bytes,
                "pipeline_digest": profile_digest,
                "local_manifest": str(destination / "manifest.json"),
                "remote_metadata_is_not_independent_signature": True,
                "actual_encoder_forward_executed": False,
                "production_promotion": "DENY_ALL"}
    finally:
        if temp.exists():
            shutil.rmtree(temp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Opt-in SHA-pinned Gemma2 weight preparation")
    parser.add_argument("--revision", required=True, help="exact remote git commit")
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="text")
    parser.add_argument("--dimension", type=int, choices=tuple(sorted(DIMENSIONS)), default=256)
    parser.add_argument("--precision", choices=("float32", "bfloat16"), default="float32")
    args = parser.parse_args()
    print(json.dumps(prepare_snapshot(args.revision, args.destination, profile=args.profile,
                                      dimension=args.dimension, precision=args.precision),
                     sort_keys=True))
