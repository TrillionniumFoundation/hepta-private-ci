#!/usr/bin/env python3
"""Prepare the exact reviewed SDK clipboard source from an existing Git clone.

No network, tool installation, Cargo cache modification, or global config
change. Creates one new checkout only and reports its exact source tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

BASE = "337566c8b25d47f7e4fff6a202157b65bf183330"
SOURCE = "https://github.com/kevinaboos/makepad"
ORIGINAL_SOURCE = "git+" + SOURCE + "?rev=" + BASE + "#" + BASE
UI_FEATURE = "native-clipboard-sdk"


def require_clipboard_feature(metadata):
    """Require actual resolved opt-in, including Desktop forwarding when present."""
    nodes = {entry["id"]: entry for entry in (metadata.get("resolve") or {}).get("nodes", [])}
    for name, feature, required in (
            ("hepta-robrix-ui", UI_FEATURE, True),
            ("trill-ui-core", "hepta-native-clipboard-sdk", False),
            ("trill-shell", "hepta-native-clipboard-sdk", False)):
        packages = [entry for entry in metadata.get("packages", []) if entry["name"] == name]
        if not packages and not required:
            continue
        if len(packages) != 1 or feature not in nodes.get(packages[0]["id"], {}).get("features", []):
            raise ValueError("SDK candidate requires resolved feature " + name + "/" + feature)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Git source preparation failed: " + result.stderr.decode(errors="replace"))
    return result.stdout


def cargo_override(metadata, destination):
    """Patch every resolved crate from this SDK, not just makepad-platform.

    A platform-only path patch would introduce path copies of its siblings
    alongside the original Git crates, producing incompatible Cx/Script types.
    The input is the complete Cargo metadata for the product's exact features.
    """
    require_clipboard_feature(metadata)
    candidates = [entry for entry in metadata["packages"]
                  if (entry.get("source") or "").startswith("git+" + SOURCE)]
    if not candidates or any(entry["source"] != ORIGINAL_SOURCE for entry in candidates):
        raise ValueError("Cargo metadata must resolve one exact original SDK revision")
    widgets = [entry for entry in candidates if entry["name"] == "makepad-widgets"]
    if len(widgets) != 1:
        raise ValueError("Cargo metadata must contain one original widgets crate")
    original_root = Path(widgets[0]["manifest_path"]).parent.parent
    entries = []
    keys = set()
    for entry in sorted(candidates, key=lambda value: (value["name"], value["version"])):
        relative = Path(entry["manifest_path"]).relative_to(original_root)
        if any(part in ("", ".", "..") for part in relative.parts):
            raise ValueError("Invalid original SDK manifest path")
        path = destination / relative
        package = tomllib.loads(path.read_text())["package"]
        if package["name"] != entry["name"] or package["version"] != entry["version"]:
            raise ValueError("Prepared SDK crate differs from Cargo metadata")
        key = entry["name"] + "-" + entry["version"]
        if key in keys:
            raise ValueError("Duplicate original SDK package identity")
        keys.add(key)
        entries.append({"key": key, "name": entry["name"], "version": entry["version"],
                        "path": str(path.parent), "manifest": relative.as_posix()})
    required = {"makepad-widgets", "makepad-draw", "makepad-platform", "makepad-script", "unicode-segmentation"}
    if not required.issubset({entry["name"] for entry in entries}):
        raise ValueError("Metadata omits a required original SDK crate; use full native features")
    lines = ["# Generated from complete original Cargo metadata and the exact prepared SDK tree.",
             "[patch." + json.dumps(SOURCE) + "]"]
    for entry in entries:
        lines.append(json.dumps(entry["key"]) + " = { package = " + json.dumps(entry["name"])
                     + ", version = " + json.dumps("=" + entry["version"])
                     + ", path = " + json.dumps(entry["path"]) + " }")
    return entries, "\n".join(lines) + "\n"


def check(data, digest, size=None):
    if hashlib.sha256(data).hexdigest() != digest or (size is not None and len(data) != size):
        raise ValueError("Source or patch identity differs")


def prepare(upstream, destination, hepta):
    patch_root = hepta / "third_party/makepad-patches"
    manifest_bytes = (patch_root / "MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest["schema_version"] != 1 or manifest["upstream_commit"] != BASE
            or manifest["upstream_repository"] != SOURCE
            or manifest["package"] != {"name": "makepad-platform", "version": "2.0.0"}
            or manifest["effects_authority"] is not False or manifest["automatic_update"] is not False):
        raise ValueError("Unexpected SDK patch manifest")
    if not destination.is_absolute() or destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Choose a new absolute destination with an existing parent")
    if git(upstream, "rev-parse", BASE + "^{commit}").decode().strip() != BASE:
        raise ValueError("Exact original SDK Git object is unavailable")
    patches = []
    for record in manifest["patches"]:
        name = record["file"]
        if Path(name).name != name or not name.endswith(".patch"):
            raise ValueError("Patch path must be a plain filename")
        data = (patch_root / name).read_bytes()
        check(data, record["sha256"], record["bytes"])
        patches.append((name, data))
    result = subprocess.run(["git", "clone", "--shared", "--no-checkout", str(upstream), str(destination)],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Cannot create the independent SDK checkout: " + result.stderr.decode(errors="replace"))
    git(destination, "checkout", "--detach", BASE)
    changed = set()
    for record in manifest["changed_files"]:
        relative = Path(record["path"])
        if (relative.is_absolute() or relative.parts[0] != "platform"
                or any(part in ("", ".", "..") for part in relative.parts) or str(relative) in changed):
            raise ValueError("Invalid or duplicate SDK source path")
        changed.add(str(relative))
        path = destination / relative
        if record["upstream_sha256"] is None:
            if path.exists() or path.is_symlink():
                raise ValueError("A supposedly new SDK source already exists")
        else:
            check(path.read_bytes(), record["upstream_sha256"])
    for name, _data in patches:
        git(destination, "apply", "--check", str(patch_root / name))
        git(destination, "apply", str(patch_root / name))
    for record in manifest["changed_files"]:
        check((destination / record["path"]).read_bytes(), record["patched_sha256"], record["bytes"])
    license = manifest["license"]
    check((destination / license["path"]).read_bytes(), license["sha256"], license["bytes"])
    git(destination, "add", "--all")
    actual_paths = set(git(destination, "diff", "--cached", "--name-only", BASE).decode().splitlines())
    if actual_paths != changed:
        raise ValueError("Patch changed undeclared SDK files")
    tree = git(destination, "write-tree").decode().strip()
    if tree != manifest["patched_tree"]:
        raise ValueError("Prepared SDK tree differs from the exact reviewed tree")
    if git(destination, "diff", "--name-only"):
        raise ValueError("Source changed while being prepared")
    return {"schema": "hepta.original-sdk-patch-source.v1", "upstream_commit": BASE,
            "patched_tree": tree, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "patches": manifest["patches"], "package": manifest["package"],
            "package_manifest": str(destination / "platform/Cargo.toml"),
            "cargo_patch_source": manifest["upstream_repository"],
            "network_used": False, "compiled": False, "runtime_qualified": False,
            "effects_authority": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--hepta-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--metadata", type=Path, help="Complete original Cargo metadata for the exact native product features")
    parser.add_argument("--cargo-config-output", type=Path, help="New TOML file for the explicit all-SDK Cargo override")
    args = parser.parse_args()
    if bool(args.metadata) != bool(args.cargo_config_output):
        parser.error("--metadata and --cargo-config-output must be supplied together")
    if args.cargo_config_output and (args.cargo_config_output.exists() or not args.cargo_config_output.parent.is_dir()):
        parser.error("Cargo config output must be a new file in an existing directory")
    metadata_bytes = args.metadata.read_bytes() if args.metadata else None
    metadata = json.loads(metadata_bytes) if metadata_bytes is not None else None
    if metadata is not None:
        require_clipboard_feature(metadata)
    result = prepare(args.upstream_repo.resolve(strict=True), args.destination, args.hepta_root.resolve(strict=True))
    if args.metadata:
        entries, config = cargo_override(metadata, args.destination)
        with args.cargo_config_output.open("x") as stream:
            stream.write(config)
        result.update(cargo_patch_packages=entries, original_metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest(),
                      cargo_config=str(args.cargo_config_output.resolve()),
                      cargo_config_sha256=hashlib.sha256(config.encode()).hexdigest())
    print(json.dumps(result, indent=2))
