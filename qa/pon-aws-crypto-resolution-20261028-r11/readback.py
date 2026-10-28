"""Reconcile retained hosted bytes and the coherent import without native tools."""

import ast
import collections
from importlib import import_module
import json
from pathlib import Path
import sys
import tarfile
import tomllib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
source = import_module("hepta_pon_aws_crypto_source")
rust_format_review = import_module("rust_format_review")


def key(package):
    return package["name"], package["version"], package.get("source")


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    transport = json.loads((HERE / "generation-logs.json").read_text())
    raw = (HERE / "generation-logs.tar.xz").read_bytes()
    require(
        source.identity(raw) == transport["archive"], "original log archive differs"
    )
    expected = {entry["path"]: entry for entry in transport["members"]}
    with tarfile.open(HERE / "generation-logs.tar.xz") as archive:
        members = archive.getmembers()
        require(
            len(members) == len(expected)
            and {entry.name for entry in members} == set(expected),
            "log inventory differs",
        )
        require(all(entry.isfile() for entry in members), "non-regular retained log")
        data = {entry.name: archive.extractfile(entry).read() for entry in members}
    for name, raw in data.items():
        require(
            source.identity(raw)
            == {key: expected[name][key] for key in ("bytes", "sha256")},
            "log bytes differ: " + name,
        )
    hosted = json.loads(data["record.json"])
    require(
        hosted["source"] == "ec3171c55848c3ebef5558119b9238b3120c6e1f",
        "hosted source mismatch",
    )
    require(
        len(hosted["stages"]) == 11
        and all(
            stage["state"] == "succeeded" and stage["exit_code"] == 0
            for stage in hosted["stages"]
        ),
        "generation stage mismatch",
    )
    require(
        hosted["proposal_only"] and not hosted["committed_source_qualified"],
        "historical proposal was never qualified",
    )
    listed = {entry["path"]: entry for entry in json.loads(data["files.json"])["files"]}
    review = json.loads((HERE / "import-review.json").read_text())
    installed = {entry["path"]: entry for entry in review["installed_files"]}
    derived = {entry["path"]: entry for entry in review["derived_formatter_files"]}
    _, original, prepared = source.source_proposal()
    source.static_review(source.frozen_inputs())
    require(
        set(installed)
        == set(source.INPUTS) | {source.VENDOR + "/" + name for name in prepared},
        "import inventory mismatch",
    )
    changed = []
    for name, expected in installed.items():
        raw = (ROOT / source.safe_relative(name)).read_bytes()
        require(
            source.identity(raw) == {key: expected[key] for key in ("bytes", "sha256")},
            "installed bytes mismatch: " + name,
        )
        observed = source.identity(raw)
        generated = {
            key: listed["proposal/" + name][key] for key in ("bytes", "sha256")
        }
        if name in derived:
            require(
                observed == derived[name]["installed"]
                and generated == derived[name]["original_hosted"],
                "derived source mismatch",
            )
        else:
            require(observed == generated, "unexpected post-generation edit: " + name)
        if name.startswith(source.VENDOR + "/"):
            relative = name.removeprefix(source.VENDOR + "/")
            if raw != prepared[relative] and relative.endswith(".rs"):
                require(
                    rust_format_review.compare(prepared[relative], raw),
                    "non-format Rust delta",
                )
                changed.append(relative)
            elif relative not in {
                "BUILD.bazel",
                "integration-tests/eks-credentials/jest.config.js",
            }:
                require(raw == prepared[relative], "non-Rust source drift")
    require(
        sorted(changed) == sorted(hosted["hosted_rustfmt_changed_source_files"]),
        "hosted format inventory mismatch",
    )
    build = ROOT / source.VENDOR / "BUILD.bazel"
    require(
        ast.dump(ast.parse(build.read_text()), include_attributes=False)
        == ast.dump(
            ast.parse(prepared["BUILD.bazel"].decode()), include_attributes=False
        ),
        "Bazel declaration semantics changed",
    )
    packages = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())["package"]
    lock = {key(package): package for package in packages}
    require(len(lock) == len(packages), "duplicate lock identity")
    names = collections.defaultdict(list)
    for identity in lock:
        names[identity[0]].append(identity)

    def resolve_dependency(value):
        parts = value.split(" ", 2)
        candidates = names[parts[0]]
        if len(parts) > 1:
            candidates = [entry for entry in candidates if entry[1] == parts[1]]
        if len(parts) > 2:
            candidates = [entry for entry in candidates if entry[2] == parts[2][1:-1]]
        require(len(candidates) == 1, "ambiguous dependency identity")
        return candidates[0]

    edges = {
        identity: {
            resolve_dependency(value) for value in package.get("dependencies", [])
        }
        for identity, package in lock.items()
    }
    graphs = []
    all_metadata = None
    for name in ("all-features", "sigv4a"):
        metadata = json.loads(data[f"logs/cargo-metadata-{name}.stdout.txt"])
        ids = {package["id"]: key(package) for package in metadata["packages"]}
        nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
        require(
            len(ids) == len(lock)
            and set(ids.values()) == set(lock)
            and set(nodes) == set(ids),
            "full graph identity mismatch",
        )
        changes = []
        for node in nodes.values():
            actual = {ids[value] for value in node["dependencies"]}
            expected = edges[ids[node["id"]]]
            if actual != expected:
                changes.append(
                    {
                        "package": ids[node["id"]],
                        "removed": sorted(expected - actual),
                        "added": sorted(actual - expected),
                    }
                )
        if name == "all-features":
            require(not changes, "union metadata differs from complete lock")
            all_metadata = metadata
        else:
            require(
                {entry["package"][0] for entry in changes}
                == {"aws-runtime", "aws-sigv4"},
                "unexpected SigV4a delta owner",
            )
            require(
                sum(len(entry["added"]) for entry in changes) == 5
                and sum(len(entry["removed"]) for entry in changes) == 1,
                "unexpected feature-conditioned edge delta",
            )
        graphs.append(
            {
                "scenario": name,
                "nodes": len(nodes),
                "edges": sum(len(node["dependencies"]) for node in nodes.values()),
                "differences": changes,
            }
        )
    official = json.loads((HERE / "official-index-selected.json").read_text())
    indexed = {key(package): package for package in all_metadata["packages"]}
    for selected in official["records"]:
        record = selected["record"]
        package = indexed[(selected["name"], selected["version"], source.REGISTRY)]
        require(
            record["cksum"] == lock[key(package)]["checksum"] and not record["yanked"],
            "new registry package identity differs",
        )
        expected = [
            {
                "name": item["name"],
                "package": item.get("package") or item["name"],
                "req": item["req"],
                "kind": item.get("kind") or "normal",
                "target": item.get("target"),
                "optional": item["optional"],
                "default_features": item["default_features"],
                "features": sorted(item["features"]),
            }
            for item in record["deps"]
        ]
        actual = [
            {
                "name": item["rename"] or item["name"],
                "package": item["name"],
                "req": item["req"],
                "kind": item["kind"] or "normal",
                "target": item["target"],
                "optional": item["optional"],
                "default_features": item["uses_default_features"],
                "features": sorted(item["features"]),
            }
            for item in package["dependencies"]
        ]
        require(
            sorted(map(lambda item: json.dumps(item, sort_keys=True), expected))
            == sorted(map(lambda item: json.dumps(item, sort_keys=True), actual)),
            "new registry requirements differ: " + package["name"],
        )
        features = record["features"] | record.get("features2", {})
        # Cargo adds an implicit optional-dependency feature unless an explicit
        # dep:name entry suppresses it. See the Cargo Book, Optional dependencies.
        explicit = {
            value
            for values in features.values()
            for value in values
            if value.startswith("dep:")
        }
        for dependency in record["deps"]:
            name = dependency["name"]
            if (
                dependency["optional"]
                and name not in features
                and "dep:" + name not in explicit
            ):
                features[name] = ["dep:" + name]
        require(
            {name: sorted(values) for name, values in package["features"].items()}
            == {name: sorted(values) for name, values in features.items()},
            "new registry features differ: " + package["name"],
        )
    print(
        json.dumps(
            {
                "installed_files": len(installed),
                "hosted_Rust_format_files": len(changed),
                "derived_static_formatter_files": len(derived),
                "reviewed_new_registry_packages": len(official["records"]),
                "graphs": graphs,
                "native_executed": False,
                "bigint_blocker_closed": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
