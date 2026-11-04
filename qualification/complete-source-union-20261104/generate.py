#!/usr/bin/env python3
"""Resolve the composed sources with the repository's original formatter and lock commands."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def snapshot(*, verify_index=False):
    result = {}
    records = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-files", "--stage", "-z"], cwd=ROOT
    )
    for record in filter(None, records.split(b"\0")):
        header, name_raw = record.split(b"\t", 1)
        mode, expected, stage = header.decode("ascii").split()
        require(stage == "0", "unresolved index stage")
        name = os.fsdecode(name_raw)
        require(name not in result, "duplicate tracked input")
        require(mode in {"100644", "100755", "120000"}, "unsupported tracked object mode")
        path = ROOT / name
        raw = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        row = {"mode": mode, **identity(raw)}
        if verify_index:
            require(row["git_blob"] == expected, "checkout differs from immutable Git input: " + name)
        result[name] = row
    return result


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def records(raw):
    document = tomllib.loads(raw.decode("utf-8"))
    packages = {}
    for row in document["package"]:
        key = (row["name"], row["version"], row.get("source", ""))
        require(key not in packages, "duplicate Cargo package identity")
        packages[key] = row
    return document, packages


def compare_cargo(baseline, generated, config):
    old_document, old = records(baseline)
    new_document, new = records(generated)
    require(
        {key: value for key, value in old_document.items() if key != "package"}
        == {key: value for key, value in new_document.items() if key != "package"},
        "Cargo lock header changed",
    )
    old_unicode = config["unicode_before"]
    new_unicode = config["unicode_after"]
    new_control = config["new_local_package"]
    key_for = lambda row: (row["name"], row["version"], row.get("source", ""))
    old_key, new_key, control_key = map(key_for, (old_unicode, new_unicode, new_control))
    require(old.get(old_key) == old_unicode, "baseline Unicode package changed")
    require(set(new) == (set(old) - {old_key}) | {new_key, control_key},
            "unreviewed registry, Git, or local package identity change")
    require(new[new_key] == new_unicode, "Unicode version/source/checksum/dependencies differ")
    require(new[control_key] == new_control, "new UI core package differs from its reviewed manifest")
    reviewed_registry = {}
    for transition in config["reviewed_registry_dependency_changes"]:
        previous, current = transition["before"], transition["after"]
        key = key_for(previous)
        require(key not in reviewed_registry, "duplicate reviewed registry identity")
        require(key_for(current) == key and key[2].startswith("registry+"),
                "reviewed registry package identity changed")
        require(previous != current, "reviewed registry transition is empty")
        require(
            {field: value for field, value in previous.items() if field != "dependencies"}
            == {field: value for field, value in current.items() if field != "dependencies"},
            "reviewed registry non-dependency field changed",
        )
        for row in (previous, current):
            dependencies = row.get("dependencies", [])
            require(len(dependencies) == len(set(dependencies)),
                    "duplicate reviewed registry dependency")
        require(old.get(key) == previous, "reviewed registry baseline differs: " + key[0])
        require(new.get(key) == current, "reviewed registry result differs: " + key[0])
        reviewed_registry[key] = transition
    require(len(reviewed_registry) == config["expected_registry_record_change_count"],
            "reviewed registry transition count differs")
    local_deltas, registry_deltas, seen_registry = [], [], set()
    for key in sorted(set(old) & set(new)):
        previous, current = old[key], new[key]
        if previous == current:
            continue
        if key in reviewed_registry:
            require(previous == reviewed_registry[key]["before"]
                    and current == reviewed_registry[key]["after"],
                    "registry transition differs from complete reviewed records")
            seen_registry.add(key)
            registry_deltas.append({"package": list(key), "before": previous, "after": current})
            continue
        require(not key[2] and key[0] in config["allowed_local_dependency_packages"],
                "unrelated Cargo package record changed: " + key[0])
        require(
            {field: value for field, value in previous.items() if field != "dependencies"}
            == {field: value for field, value in current.items() if field != "dependencies"},
            "local package identity or non-dependency metadata changed: " + key[0],
        )
        local_deltas.append({"package": list(key), "before": previous, "after": current})
    require(seen_registry == set(reviewed_registry), "reviewed registry transition was not applied")
    return {
        "baseline_packages": len(old),
        "generated_packages": len(new),
        "registry_changes": [{"before": old_unicode, "after": new_unicode}],
        "registry_dependency_changes": registry_deltas,
        "new_local_package": new_control,
        "local_dependency_changes": local_deltas,
        "all_other_versions_sources_checksums_unchanged": True,
    }


def metadata_document(raw):
    candidates = []
    for line in raw.splitlines():
        if line.startswith(b"{"):
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(value, dict) and "packages" in value and "resolve" in value:
                candidates.append(value)
    require(len(candidates) == 1 and candidates[0].get("version") == 1,
            "expected exactly one complete Cargo metadata v1 document")
    return candidates[0]


def verify_metadata_graph(metadata, locked_packages, config):
    require(metadata.get("version") == 1, "Cargo metadata format changed")
    by_identity, by_id = {}, {}
    for package in metadata["packages"]:
        key = (package["name"], package["version"], package.get("source") or "")
        require(key not in by_identity and package["id"] not in by_id,
                "duplicate actual Cargo metadata identity")
        by_identity[key] = package
        by_id[package["id"]] = package
    require(set(by_identity) == set(locked_packages),
            "actual locked metadata package identities differ from generated lock")
    nodes = {}
    for node in metadata["resolve"]["nodes"]:
        require(node["id"] not in nodes, "duplicate actual Cargo resolver node")
        nodes[node["id"]] = node
    require(set(nodes) == set(by_id), "actual resolver node inventory is incomplete")
    expected = {}
    for row in config["reviewed_registry_metadata"]:
        key = tuple(row["identity"])
        require(key not in expected, "duplicate reviewed registry metadata identity")
        expected[key] = row
    reviewed_records = {
        (row["before"]["name"], row["before"]["version"], row["before"].get("source", ""))
        for row in config["reviewed_registry_dependency_changes"]
    }
    require(set(expected) == reviewed_records, "registry metadata review inventory differs")
    fields = ("name", "source", "req", "kind", "rename", "optional",
              "uses_default_features", "features", "target", "registry")
    for key, row in expected.items():
        package = by_identity[key]
        require(package["id"] == row["package_id"], "registry metadata package ID changed")
        declarations = [
            {field: dependency.get(field) for field in fields}
            for dependency in package["dependencies"]
        ]
        require(declarations == row["manifest_dependencies"],
                "registry manifest declarations differ: " + key[0])
        require(package["features"] == row["manifest_features"],
                "registry manifest features differ: " + key[0])
        require(nodes[package["id"]] == row["resolve_node"],
                "registry resolved edges, kinds, targets or features differ: " + key[0])
    return {
        "packages": len(by_identity),
        "resolve_nodes": len(nodes),
        "reviewed_registry_records": len(expected),
        "all_lock_package_identities_match_actual_metadata": True,
        "reviewed_manifest_declarations_and_resolve_nodes_unchanged": True,
    }


def emit_file(prefix, name, raw):
    require(len(raw) <= 16 * 1024 * 1024, "file exceeds bounded byte transport")
    print(prefix + "_BEGIN=" + json.dumps({"path": name, **identity(raw)}), flush=True)
    for offset in range(0, len(raw), 32768):
        chunk = raw[offset:offset + 32768]
        print(prefix + "_PART=" + json.dumps({
            "path": name, "offset": offset, "bytes": len(chunk),
            "base64": base64.b64encode(chunk).decode("ascii"),
        }), flush=True)
    print(prefix + "_END=" + json.dumps({"path": name}), flush=True)


def main():
    require(__debug__, "optimized Python execution is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(platform.system() == "Linux", "generation requires the original native Linux host")
    config = json.loads((HERE / "scope.json").read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"status": "failed", "commands": [], "scope": (
        "Actual composed source formatting and Cargo/Bazel resolution only; "
        "product qualification requires the committed generated successor and original gates."
    )}

    def run(name, argv, cwd=ROOT, required=True):
        started = time.monotonic()
        path = output / (name + ".log")
        with path.open("wb") as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        step = {"name": name, "argv": argv, "exit_code": result.returncode,
                "elapsed_seconds": time.monotonic() - started, "log": identity(path.read_bytes())}
        receipt["commands"].append(step)
        print("UNION_COMMAND=" + json.dumps(step), flush=True)
        if result.returncode:
            print(path.read_text(encoding="utf-8", errors="replace")[-18000:], flush=True)
        if required:
            require(result.returncode == 0, name + " failed")
        return result.returncode

    before = None
    try:
        run("source-commit", ["git", "--no-replace-objects", "rev-parse", "HEAD"])
        head = (output / "source-commit.log").read_text().strip()
        require(head == os.environ["GITHUB_SHA"], "checkout is not the dispatched source")
        receipt["source_commit"] = head
        run("source-tree", ["git", "--no-replace-objects", "rev-parse", "HEAD^{tree}"])
        receipt["source_tree"] = (output / "source-tree.log").read_text().strip()
        run("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"])
        run("rustc-identity", ["rustc", "--version"], WORKSPACE)
        require((output / "rustc-identity.log").read_text().startswith("rustc 1.96.0 "),
                "product compiler is not the maintained Rust 1.96.0")
        before = snapshot(verify_index=True)
        write_json(output / "source-before.json", before)
        receipt["source_input_count"] = len(before)
        # These donor archives were copied by exact Git ID. Read their actual
        # bytes on the native host before making any complete-readback claim.
        for item in config["copied_binary_inputs"]:
            name = item["path"]
            raw = (ROOT / name).read_bytes()
            require(identity(raw)["git_blob"] == item["git_blob"] and len(raw) == item["bytes"],
                    "copied original archive identity differs")
            emit_file("COPIED_SOURCE_FILE", name, raw)
        baseline = subprocess.check_output(
            ["git", "--no-replace-objects", "show", config["base_commit"] + ":codex-rs/Cargo.lock"],
            cwd=ROOT,
        )
        require(identity(baseline)["git_blob"] == config["base_cargo_blob"],
                "baseline lock is not the reviewed immutable input")
        (output / "baseline-Cargo.lock").write_bytes(baseline)
        committed_cargo = (WORKSPACE / "Cargo.lock").read_bytes()
        committed_bazel = (ROOT / "MODULE.bazel.lock").read_bytes()
        (output / "committed-Cargo.lock").write_bytes(committed_cargo)
        (output / "committed-MODULE.bazel.lock").write_bytes(committed_bazel)
        first = run("committed-lock-first", ["just", "bazel-lock-check"], required=False)
        run("original-formatter", ["just", "fmt", "--base", config["base_commit"]])
        run("original-formatter-check", ["just", "fmt", "--check", "--base", config["base_commit"]])
        after_format = snapshot()
        formatter_changes = sorted(
            name for name in set(before) | set(after_format) if before.get(name) != after_format.get(name)
        )
        require(set(formatter_changes) <= set(config["allowed_formatter_paths"]),
                "formatter changed a path outside the reviewed source scope")
        write_json(output / "source-after-format.json", after_format)
        receipt["formatter_changes"] = formatter_changes
        for name in formatter_changes:
            raw = (ROOT / name).read_bytes()
            destination = output / "formatted" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            emit_file("ORIGINAL_FORMATTED_FILE", name, raw)
        run("actual-cargo-metadata", ["cargo", "metadata", "--all-features", "--format-version", "1"],
            WORKSPACE)
        generated_cargo = (WORKSPACE / "Cargo.lock").read_bytes()
        # Retain the actual resolver proposal even when the strict adoption
        # boundary rejects it. Exporting bytes does not qualify or adopt them.
        (output / "resolved-Cargo.lock").write_bytes(generated_cargo)
        emit_file("PROPOSED_CARGO_LOCK", "codex-rs/Cargo.lock", generated_cargo)
        write_json(output / "resolved-cargo-records.json", {
            "baseline": list(records(baseline)[1].values()),
            "resolved": list(records(generated_cargo)[1].values()),
        })
        receipt["cargo_delta"] = compare_cargo(baseline, generated_cargo, config)
        run("actual-locked-metadata",
            ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], WORKSPACE)
        metadata = metadata_document((output / "actual-locked-metadata.log").read_bytes())
        _, locked_packages = records(generated_cargo)
        receipt["metadata_verification"] = verify_metadata_graph(metadata, locked_packages, config)
        write_json(output / "reviewed-registry-metadata-verification.json",
                   receipt["metadata_verification"])
        run("original-lock-update", ["just", "bazel-lock-update"])
        run("original-lock-check", ["just", "bazel-lock-check"])
        generated_bazel = (ROOT / "MODULE.bazel.lock").read_bytes()
        json.loads(generated_bazel)
        after = snapshot()
        require(set(after) == set(before), "generation added or removed a tracked input")
        allowed = {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
        require(all(after[name] == after_format[name] for name in before if name not in allowed),
                "lock generation modified a non-lock source input")
        changed = sorted(name for name in before if before[name] != after[name])
        receipt["changed_paths"] = changed
        run("untracked-inputs", ["git", "ls-files", "--others", "--exclude-standard"])
        require(not (output / "untracked-inputs.log").read_text().strip(),
                "generation left an undeclared untracked source")
        run("complete-generated-diff", ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"])
        total = sum((ROOT / name).stat().st_size for name in changed)
        require(total <= 32 * 1024 * 1024, "generated delta exceeds bounded transport")
        for name in changed:
            raw = (ROOT / name).read_bytes()
            destination = output / "generated" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            emit_file("GENERATED_FILE", name, raw)
        (output / "Cargo.lock").write_bytes(generated_cargo)
        (output / "MODULE.bazel.lock").write_bytes(generated_bazel)
        write_json(output / "source-after.json", after)
        receipt["committed_cargo_equals_generated"] = committed_cargo == generated_cargo
        receipt["committed_bazel_equals_generated"] = committed_bazel == generated_bazel
        receipt["source_unchanged"] = before == after
        qualified = first == 0 and before == after
        receipt["status"] = "committed-lock-qualified" if qualified else "generated-needs-adoption"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("qualified=" + str(qualified).lower() + "\n")
    finally:
        if before is not None:
            write_json(output / "source-final.json", snapshot())
        for name in ("actual-cargo-metadata.log", "actual-locked-metadata.log"):
            path = output / name
            if path.is_file():
                (output / (name + ".gz")).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        receipt["outputs"] = {
            path.relative_to(output).as_posix(): identity(path.read_bytes())
            for path in sorted(output.rglob("*")) if path.is_file() and path.name != "receipt.json"
        }
        write_json(output / "receipt.json", receipt)
        print("UNION_GENERATION_RESULT=" + json.dumps(
            {key: value for key, value in receipt.items() if key != "outputs"}), flush=True)


if __name__ == "__main__":
    main()
