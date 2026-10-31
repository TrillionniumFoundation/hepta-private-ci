"""Reproduce the bounded lock candidate; generation never establishes qualification."""

import argparse
import hashlib
import io
import json
import re
import tomllib
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def checked(raw, expected, label):
    if identity(raw) != expected:
        raise ValueError(f"identity mismatch: {label}")
    return raw


def package_key(package):
    return package["name"], package["version"], package.get("source", "")


def package_map(raw):
    document = tomllib.loads(raw.decode())
    packages = document["package"]
    result = {package_key(package): package for package in packages}
    if len(result) != len(packages):
        raise ValueError("duplicate Cargo package identity")
    return result


def dependency_key(value, packages):
    match = re.fullmatch(r"([^ ]+)(?: ([^ ]+))?(?: \((.+)\))?", value)
    if match is None:
        raise ValueError(f"unsupported Cargo dependency syntax: {value}")
    name, version, source = match.groups()
    candidates = [
        key
        for key in packages
        if key[0] == name
        and (version is None or key[1] == version)
        and (source is None or key[2] == source)
    ]
    if len(candidates) != 1:
        raise ValueError(f"ambiguous or absent Cargo dependency: {value}")
    return candidates[0]


def graph(raw):
    packages = package_map(raw)
    return {
        key: {
            dependency_key(value, packages) for value in package.get("dependencies", [])
        }
        for key, package in packages.items()
    }


def display(key):
    return " ".join(key[:2]) + (f" ({key[2]})" if key[2] else "")


def graph_delta(before, after):
    old, new = graph(before), graph(after)
    changes = []
    for key in sorted(old.keys() & new.keys()):
        if old[key] != new[key]:
            changes.append(
                {
                    "package": display(key),
                    "removed_edges": [display(k) for k in sorted(old[key] - new[key])],
                    "added_edges": [display(k) for k in sorted(new[key] - old[key])],
                }
            )
    return {
        "added_packages": [display(k) for k in sorted(new.keys() - old.keys())],
        "removed_packages": [display(k) for k in sorted(old.keys() - new.keys())],
        "retained_parent_edge_changes": changes,
    }


def reconcile(original, candidate, restorations):
    """Replace exact parent dependency lists; every other candidate byte is retained."""
    old, new = package_map(original), package_map(candidate)
    pieces = re.split(rb"(?m)(?=^\[\[package\]\]$)", candidate)
    blocks = {}
    for index, piece in enumerate(pieces[1:], 1):
        package = tomllib.loads(piece.decode())["package"][0]
        blocks[package_key(package)] = index
    keys = [tuple(item["parent"]) for item in restorations]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate restoration parent")
    old_graph, candidate_graph = graph(original), graph(candidate)
    for item, key in zip(restorations, keys):
        if key not in old or key not in new or key not in blocks:
            raise ValueError(f"restoration parent missing: {key}")
        expected_old = {tuple(k) for k in item["old_edges"]}
        expected_new = {tuple(k) for k in item["candidate_edges"]}
        if old_graph[key] != expected_old or candidate_graph[key] != expected_new:
            raise ValueError(f"restoration edge identity mismatch: {key}")
        if {k: v for k, v in old[key].items() if k != "dependencies"} != {
            k: v for k, v in new[key].items() if k != "dependencies"
        }:
            raise ValueError(f"nondependency parent fields changed: {key}")
        if any(edge not in new for edge in expected_old):
            raise ValueError(f"old dependency is absent from candidate: {key}")
        dependencies = old[key].get("dependencies", [])
        for value in dependencies:
            dependency_key(value, new)
        replacement = (
            b"dependencies = [\n"
            + b"".join(
                (" " + json.dumps(value) + ",\n").encode() for value in dependencies
            )
            + b"]\n"
        )
        index = blocks[key]
        pieces[index], count = re.subn(
            rb"(?ms)^dependencies = \[\n.*?^\]\n", lambda _: replacement, pieces[index]
        )
        if count != 1:
            raise ValueError(f"expected one dependency block: {key}")
    result = b"".join(pieces)
    repaired, repaired_graph = package_map(result), graph(result)
    if repaired.keys() != new.keys():
        raise ValueError("package identity set changed during edge restoration")
    for key in new:
        expected = dict(new[key])
        if key in keys:
            expected["dependencies"] = old[key].get("dependencies", [])
        if repaired[key] != expected:
            raise ValueError(f"unregistered package change: {key}")
        if repaired_graph[key] != (
            old_graph[key] if key in keys else candidate_graph[key]
        ):
            raise ValueError(f"unregistered resolved edge change: {key}")
    return result


def generate(artifact, baseline_root, output, constraints):
    raw = checked(
        artifact.read_bytes(), constraints["artifact"]["identity"], "artifact"
    )
    baseline = {}
    for path, expected in constraints["original_inputs"].items():
        data = checked((baseline_root / path).read_bytes(), expected, path)
        if path in LOCKS:
            baseline[path] = data
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        candidates = {}
        for path in LOCKS:
            member = "payload/effective-locks/" + Path(path).name
            info = archive.getinfo(member)
            expected = constraints["historical_candidate"][path]
            if info.file_size != expected["bytes"]:
                raise ValueError(f"archive member size mismatch: {member}")
            candidates[path] = checked(archive.read(member), expected, member)
    candidates[LOCKS[0]] = reconcile(
        baseline[LOCKS[0]], candidates[LOCKS[0]], constraints["restorations"]
    )
    for path in LOCKS:
        checked(candidates[path], constraints["repaired_candidate"][path], path)
    delta = graph_delta(baseline[LOCKS[0]], candidates[LOCKS[0]])
    if delta != constraints["repaired_graph_delta"]:
        raise ValueError("repaired graph delta differs from registered constraints")
    output.mkdir(parents=True, exist_ok=False)
    for path, data in candidates.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    receipt = {
        "schema": "hepta.parameter-field.lock-repair-generation.1",
        "source_base": constraints["source_base"],
        "artifact": constraints["artifact"],
        "output_locks": constraints["repaired_candidate"],
        "restored_parent_count": len(constraints["restorations"]),
        "graph_delta": delta,
        "generation_passed": True,
        "cargo_locked_validation": "NOT_RUN",
        "bazel_validation": "NOT_RUN",
        "qualification": False,
        "dependency_graph_approved": False,
        "graph_review_required": True,
    }
    (output / "GENERATION_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    constraints = json.loads((HERE / "constraints.json").read_text())
    try:
        receipt = generate(
            args.artifact, args.baseline_root, args.output_dir, constraints
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(2, f"Lock candidate generation failed: {error}\n")
    print(
        json.dumps(
            {
                key: receipt[key]
                for key in (
                    "generation_passed",
                    "restored_parent_count",
                    "cargo_locked_validation",
                    "qualification",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
