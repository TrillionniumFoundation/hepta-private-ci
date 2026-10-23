"""Private tokenizer compatibility view for original Laya shadow checkpoints.

Pinned upstream laya.agent.Agent may write tokenizer/tokenizer_config.json
during construction. Never expose the verified publisher snapshot to this
normalization. This module grants no production or effect authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable

MAX_TOKENIZER_FILES = 64
MAX_TOKENIZER_ENTRIES = 512
MAX_TOKENIZER_BYTES = 256 * 1024 * 1024
COMPAT_CONFIG = "tokenizer_config.json"


def _hash_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("original checkpoint component is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("original tokenizer directory is missing or linked")
    hashes: dict[str, str] = {}
    total = 0
    entries = 0
    for path in root.rglob("*"):
        entries += 1
        if entries > MAX_TOKENIZER_ENTRIES or len(path.relative_to(root).parts) > 8:
            raise ValueError("tokenizer compatibility tree exceeds fixed limits")
        if path.is_symlink():
            raise ValueError("tokenizer tree must not contain linked members")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("tokenizer tree contains a non-regular member")
        total += path.stat().st_size
        if len(hashes) >= MAX_TOKENIZER_FILES or total > MAX_TOKENIZER_BYTES:
            raise ValueError("tokenizer compatibility copy exceeds fixed limits")
        hashes[path.relative_to(root).as_posix()] = _hash_file(path)
    if not hashes or "tokenizer.json" not in hashes:
        raise ValueError("original tokenizer.json bytes are required")
    return hashes


def _inventory_digest(inventory: dict[str, str]) -> str:
    raw = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _expected_compatibility_config(path: Path) -> dict[str, Any]:
    """Only the two transformations in the pinned upstream Agent are allowed."""
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise ValueError("original tokenizer_config must be a JSON object")
    result = dict(raw)
    if result.get("tokenizer_class") in (None, "TokenizersBackend"):
        result["tokenizer_class"] = "PreTrainedTokenizerFast"
        result.pop("backend", None)
        result.pop("is_local", None)
    extra = result.get("extra_special_tokens")
    if isinstance(extra, list):
        result["extra_special_tokens"] = {f"extra_{i}": item for i, item in enumerate(extra)}
    return result


def load_laya_cpu_isolated(snapshot: Path, agent_factory: Callable[..., Any]) -> tuple[Any, dict]:
    """Load genuine weight bytes but permit tokenizer rewrites only in a 0700 copy.

    Agent tensors/tokenizer are already resident after the constructor returns.
    The temporary view is deleted before the actual CPU shadow forward pass.
    """
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("original model snapshot must be an ordinary directory")
    tokenizer = snapshot / "tokenizer"
    original = _inventory(tokenizer)
    original_config = tokenizer / COMPAT_CONFIG
    expected_config = (
        _expected_compatibility_config(original_config)
        if COMPAT_CONFIG in original else None
    )
    fixed: dict[str, str] = {}
    for relative in ("model.safetensors", "rl_agent_config.json", "encoder/config.json"):
        fixed[relative] = _hash_file(snapshot / relative)
    if (snapshot / "encoder").is_symlink() or not (snapshot / "encoder").is_dir():
        raise ValueError("pinned Encoder directory must not be linked")

    with tempfile.TemporaryDirectory(prefix="hepta-laya-tokenizer-view-") as temporary:
        view = Path(temporary)
        shutil.copytree(tokenizer, view / "tokenizer", symlinks=False)
        if _inventory(view / "tokenizer") != original:
            raise ValueError("private tokenizer copy differs from original bytes")
        shutil.copy2(snapshot / "rl_agent_config.json", view / "rl_agent_config.json")
        (view / "encoder").symlink_to((snapshot / "encoder").resolve(strict=True),
                                     target_is_directory=True)
        (view / "model.safetensors").symlink_to(
            (snapshot / "model.safetensors").resolve(strict=True)
        )
        agent = agent_factory(str(view), device="cpu")
        if _inventory(tokenizer) != original:
            raise ValueError("Laya loader changed original tokenizer checkpoint bytes")
        for relative, digest in fixed.items():
            if _hash_file(snapshot / relative) != digest:
                raise ValueError(f"Laya loader changed original {relative} bytes")
        effective = _inventory(view / "tokenizer")
        if any(original[key] != effective.get(key)
               for key in original if key != COMPAT_CONFIG):
            raise ValueError("Laya loader unexpectedly changed tokenizer input bytes")
        if set(effective) != set(original):
            raise ValueError("Laya loader created or deleted tokenizer files")
        if expected_config is not None:
            actual_config = json.loads((view / "tokenizer" / COMPAT_CONFIG).read_bytes())
            if actual_config != expected_config:
                raise ValueError("Laya loader applied an unregistered tokenizer rewrite")
        if _hash_file(view / "rl_agent_config.json") != fixed["rl_agent_config.json"]:
            raise ValueError("Laya loader changed typed-policy config inside private view")
        report = {
            "isolation": "private_tokenizer_copy_original_weight_symlink",
            "original_tokenizer_inventory_sha256": _inventory_digest(original),
            "effective_tokenizer_inventory_sha256": _inventory_digest(effective),
            "original_tokenizer_config_sha256": original.get(COMPAT_CONFIG),
            "effective_tokenizer_config_sha256": effective.get(COMPAT_CONFIG),
            "registered_config_rewrite": original != effective,
            "original_weight_sha256": fixed["model.safetensors"],
            "no_original_snapshot_mutation_observed": True,
        }
        return agent, report
