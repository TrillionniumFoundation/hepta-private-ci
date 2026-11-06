"""Accept only the reviewed SDK/path utility edges in machine-generated output."""

from copy import deepcopy
import difflib
import json
from pathlib import PurePosixPath
import tomllib


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
WINDOWS_CHECKSUM = "282be5f36a8ce781fad8c8ae18fa3f9beff57ec1b52cb3de0789201425d9a33d"
WINDOWS_FEATURES = ["Win32_Foundation", "Win32_Storage_FileSystem"]
EDGES = {
    "codex-hepta-matrix-sdk": "codex-utils-path",
    "codex-utils-path": "windows-sys 0.52.0",
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unique(items, key):
    result = {key(item): item for item in items}
    require(len(result) == len(items), "DUPLICATE_IDENTITY")
    return result


def one_package(packages, name, version):
    matches = [p for p in packages if p["name"] == name and p["version"] == version]
    require(len(matches) == 1, "PACKAGE_ROSTER_MISMATCH")
    return matches[0]


def canonical_lock(value):
    value = deepcopy(value)
    for package in value["package"]:
        if "dependencies" in package:
            require(
                len(set(package["dependencies"])) == len(package["dependencies"]),
                "DUPLICATE_LOCK_EDGE",
            )
            package["dependencies"].sort()
    value["package"].sort(key=lambda p: (p["name"], p["version"], p.get("source", "")))
    unique(value["package"], lambda p: (p["name"], p["version"], p.get("source", "")))
    return value


def cargo_guard(before_raw, after_raw):
    before, after = [tomllib.loads(raw.decode()) for raw in (before_raw, after_raw)]
    expected = deepcopy(before)
    windows = one_package(expected["package"], "windows-sys", "0.52.0")
    require(
        windows["source"] == REGISTRY and windows["checksum"] == WINDOWS_CHECKSUM,
        "WINDOWS_PACKAGE_IDENTITY_MISMATCH",
    )
    for name, dependency in EDGES.items():
        package = one_package(expected["package"], name, "0.0.0")
        require(
            "source" not in package and "checksum" not in package,
            "WORKSPACE_SOURCE_MISMATCH",
        )
        require(dependency not in package["dependencies"], "EDGE_ALREADY_PRESENT")
        package["dependencies"].append(dependency)
    require(
        canonical_lock(after) == canonical_lock(expected), "UNRELATED_CARGO_GRAPH_DRIFT"
    )
    delta = list(
        difflib.ndiff(before_raw.decode().splitlines(), after_raw.decode().splitlines())
    )
    additions = [line[2:] for line in delta if line.startswith("+ ")]
    removals = [line[2:] for line in delta if line.startswith("- ")]
    require(
        not removals
        and sorted(additions) == sorted(' "' + dep + '",' for dep in EDGES.values()),
        "UNRELATED_CARGO_TEXT_DRIFT",
    )
    return {
        "added_edges": EDGES,
        "other_bytes_unchanged": True,
        "all_package_versions_sources_checksums_preserved": True,
        "package_count": len(before["package"]),
    }


def canonical_metadata(value):
    value = deepcopy(value)
    for package in value["packages"]:
        package["dependencies"].sort(
            key=lambda dependency: json.dumps(dependency, sort_keys=True)
        )
    value["packages"].sort(key=lambda package: package["id"])
    unique(value["packages"], lambda package: package["id"])
    for node in value["resolve"]["nodes"]:
        node["dependencies"].sort()
        node["deps"].sort(key=lambda dependency: json.dumps(dependency, sort_keys=True))
    value["resolve"]["nodes"].sort(key=lambda node: node["id"])
    unique(value["resolve"]["nodes"], lambda node: node["id"])
    return value


def metadata_guard(before, after):
    expected = deepcopy(before)
    packages = expected["packages"]
    sdk = one_package(packages, "codex-hepta-matrix-sdk", "0.0.0")
    paths = one_package(packages, "codex-utils-path", "0.0.0")
    windows = one_package(packages, "windows-sys", "0.52.0")
    require(
        sdk["source"] is paths["source"] is None, "WORKSPACE_METADATA_SOURCE_MISMATCH"
    )
    require(windows["source"] == REGISTRY, "WINDOWS_METADATA_SOURCE_MISMATCH")
    nodes = unique(expected["resolve"]["nodes"], lambda node: node["id"])
    require(
        set(WINDOWS_FEATURES) <= set(nodes[windows["id"]]["features"]),
        "BASE_WINDOWS_FEATURES_NOT_ENABLED",
    )
    for owner, target, condition in (
        (sdk, paths, None),
        (paths, windows, "cfg(windows)"),
    ):
        dependency = {
            "name": target["name"],
            "source": target["source"],
            "req": "*" if target is paths else "=0.52.0",
            "kind": None,
            "rename": None,
            "optional": False,
            "uses_default_features": True,
            "features": [] if target is paths else WINDOWS_FEATURES,
            "target": condition,
            "registry": None,
        }
        if target is paths:
            dependency["path"] = str(PurePosixPath(target["manifest_path"]).parent)
        require(
            not any(dep["name"] == target["name"] for dep in owner["dependencies"]),
            "METADATA_EDGE_ALREADY_PRESENT",
        )
        owner["dependencies"].append(dependency)
        node = nodes[owner["id"]]
        require(
            target["id"] not in node["dependencies"], "RESOLVED_EDGE_ALREADY_PRESENT"
        )
        node["dependencies"].append(target["id"])
        node["deps"].append(
            {
                "name": target["name"].replace("-", "_"),
                "pkg": target["id"],
                "dep_kinds": [{"kind": None, "target": condition}],
            }
        )
    require(
        canonical_metadata(after) == canonical_metadata(expected),
        "UNRELATED_METADATA_DRIFT",
    )
    return {
        "two_manifest_and_resolved_edges_only": True,
        "workspace_members_default_members_targets_all_other_fields_unchanged": True,
        "all_resolved_feature_sets_unchanged": True,
        "windows_features_already_enabled_in_fixed_workspace": WINDOWS_FEATURES,
    }


def module_guard(before_raw, after_raw):
    require(before_raw == after_raw, "MODULE_LOCK_NOT_BYTE_IDENTICAL")
    return {
        "all_module_lock_bytes_unchanged": True,
        "unexpected_changes_require_new_review": True,
    }
