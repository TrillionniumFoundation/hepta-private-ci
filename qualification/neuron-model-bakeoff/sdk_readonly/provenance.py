"""Bind each opt-in workspace to reviewed source pins, not its own assertions."""
import hashlib
import json
from pathlib import Path

CODE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_workspace(workspace):
    pinned = json.loads((CODE / "upstream.json").read_text())
    manifest = json.loads((workspace / "source-manifest.json").read_text())
    for field in ("profile", "upstream_wheel", "source_files", "derived_files", "license_sha256", "patch_sha256"):
        if manifest.get(field) != pinned[field]:
            raise ValueError("workspace differs from reviewed source pin: " + field)
    if digest(CODE / "readonly_tokenizer.py") != pinned["derived_files"]["readonly_tokenizer.py"]:
        raise ValueError("checked-in tokenizer helper differs from reviewed pin")
    for file, field in (("sdk-source.patch", "patch_sha256"), ("LICENSE", "license_sha256")):
        if digest(CODE / file) != pinned[field] or digest(workspace / file) != pinned[field]:
            raise ValueError("patch/license differs from reviewed pin: " + file)
    vendor = workspace / "vendor/laya"
    actual = {str(path.relative_to(vendor)): digest(path) for path in sorted(vendor.rglob("*.py"))}
    if actual != pinned["derived_files"]:
        raise ValueError("derived SDK tree differs from reviewed source pins")
    return manifest
