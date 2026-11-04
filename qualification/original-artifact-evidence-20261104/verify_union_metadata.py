#!/usr/bin/env python3
"""Project the failed union resolver's immutable metadata; never run product code."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tomllib

from verify import GitBytes, canonical, fetch_artifact, require, sha

LIMIT = 512 * 1024 * 1024
EXPECTED = {
    "arboard", "dirs-sys", "errno", "hyper-util", "iana-time-zone", "is-terminal",
    "jiff", "nu-ansi-term", "oauth2", "os_pipe", "prost-build", "prost-derive",
    "quinn", "quinn-udp", "rustix", "rustls-platform-verifier", "tempfile", "winapi-util",
}


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def document(raw):
    return json.loads(raw, object_pairs_hook=unique)


def identity(raw):
    return {"bytes": len(raw), "sha256": sha(raw),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def records(raw):
    rows = tomllib.loads(raw.decode())["package"]
    result = {}
    for row in rows:
        key = (row["name"], row["version"], row.get("source", ""))
        require(key not in result, "duplicate Cargo lock identity")
        result[key] = row
    return result


def parse_metadata(raw):
    candidates = []
    spans = []
    offset = 0
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(b"{"):
            try:
                value = document(stripped)
            except (ValueError, UnicodeDecodeError):
                value = None
            if isinstance(value, dict) and {"packages", "resolve", "version", "workspace_members"} <= set(value):
                candidates.append(value)
                spans.append({"offset": offset, "line_bytes": len(line), "json_sha256": sha(stripped)})
        offset += len(line)
    require(len(candidates) == 1, "expected one complete Cargo metadata JSON document")
    require(candidates[0]["version"] == 1, "unexpected metadata schema")
    return candidates[0], spans[0]


def project(metadata, before, after):
    packages = {}
    for package in metadata["packages"]:
        require(package["id"] not in packages, "duplicate metadata package")
        packages[package["id"]] = package
    nodes = {}
    for node in metadata["resolve"]["nodes"]:
        require(node["id"] not in nodes and node["id"] in packages, "unknown or duplicate resolve node")
        nodes[node["id"]] = node
    by_identity = {}
    for package in packages.values():
        key = (package["name"], package["version"], package.get("source") or "")
        require(key not in by_identity, "duplicate metadata identity")
        by_identity[key] = package
    require(set(by_identity) == set(after), "metadata package identities differ from actual resolved lock")
    changed = [key for key in set(before) & set(after)
               if key[2].startswith("registry+") and before[key] != after[key]]
    require(len(changed) == 18 and {key[0] for key in changed} == EXPECTED,
            "registry delta is not the requested eighteen records")
    result = []
    for key in sorted(changed):
        old, new = before[key], after[key]
        require({k: v for k, v in old.items() if k != "dependencies"}
                == {k: v for k, v in new.items() if k != "dependencies"},
                "registry change extends beyond dependency edges")
        if key[0] == "rustix":
            require(key[1] == "1.1.4", "unexpected changed rustix version")
        package = by_identity[key]
        node = nodes[package["id"]]
        selected = []
        for edge in node["deps"]:
            require(edge["pkg"] in packages, "selected dependency package is absent")
            dependency_package = packages[edge["pkg"]]
            matching = [
                d for d in package["dependencies"]
                if d["name"] == dependency_package["name"]
                and (d.get("rename") or d["name"]).replace("-", "_") == edge["name"]
            ]
            selected.append({
                "name": edge["name"], "pkg": edge["pkg"], "dep_kinds": edge["dep_kinds"],
                "selected_identity": {
                    "name": dependency_package["name"], "version": dependency_package["version"],
                    "source": dependency_package.get("source"),
                },
                "manifest_declarations": matching,
            })
        result.append({
            "identity": list(key), "package_id": package["id"],
            "manifest_path_recorded_by_original_cargo": package["manifest_path"],
            "manifest_dependencies": package["dependencies"], "manifest_features": package["features"],
            "resolve_node": node, "selected_edges": selected,
            "lock_before": old, "lock_after": new,
            "removed_lock_edges": sorted(set(old.get("dependencies", [])) - set(new.get("dependencies", []))),
            "added_lock_edges": sorted(set(new.get("dependencies", [])) - set(old.get("dependencies", []))),
        })
    return {
        "package_count": len(packages), "resolve_node_count": len(nodes),
        "registry_dependency_rebindings": result,
        "removed_package_identities": [list(k) for k in sorted(set(before) - set(after))],
        "added_package_identities": [list(k) for k in sorted(set(after) - set(before))],
        "local_record_changes": [
            {"identity": list(k), "before": before[k], "after": after[k]}
            for k in sorted(set(before) & set(after)) if not k[2] and before[k] != after[k]
        ],
        "boundary": "Original Cargo metadata declarations and selected resolve edges, not independent semver re-resolution or approval to adopt the rejected lock.",
    }


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    specs = [x for x in document(args.manifest.read_bytes()) if x["key"] == args.key]
    require(len(specs) == 1, "unknown or duplicate artifact")
    spec = specs[0]
    args.output.mkdir(parents=True, exist_ok=False)
    artifact, raw_zip, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(raw_zip)
    receipt = document(members["receipt.json"])
    require(receipt["source_commit"] == spec["source"] and receipt["status"] == "failed",
            "original failed source identity differs")
    outputs = receipt["outputs"]
    require(set(outputs) == set(members) - {"receipt.json"}, "output inventory is incomplete")
    for name, row in outputs.items():
        require(identity(members[name]) == row, "output bytes differ: " + name)
    commands = receipt["commands"]
    names = [x["name"] for x in commands]
    require(names == [
        "source-commit", "source-tree", "initial-clean-source", "rustc-identity",
        "committed-lock-first", "original-formatter", "original-formatter-check", "actual-cargo-metadata",
    ], "unexpected original command sequence")
    for command in commands:
        require(command["log"] == identity(members[command["name"] + ".log"]), "command log differs")
        if command["name"] != "committed-lock-first":
            require(command["exit_code"] == 0, "original prerequisite did not succeed")
    require(commands[-1]["argv"] == ["cargo", "metadata", "--all-features", "--format-version", "1"],
            "original Cargo metadata command differs")
    require("actual-locked-metadata.log" not in members, "later locked gate unexpectedly ran")
    git = GitBytes(args.source, spec["source"])
    try:
        require(git.command("rev-parse", "HEAD^{tree}").decode().strip() == receipt["source_tree"],
                "original source tree differs")
        config = document(git.read("qualification/complete-source-union-20261104/scope.json"))
        before = document(members["source-before.json"])
        formatted = document(members["source-after-format.json"])
        final = document(members["source-final.json"])
        require(set(before) == set(formatted) == set(final) == set(git.tree), "full source inventory differs")
        require(len(before) == receipt["source_input_count"], "input count differs")
        for name, row in before.items():
            mode, kind, oid = git.tree[name]
            require(kind == "blob" and row == {"mode": mode, **identity(git.read(name))},
                    "original Git input differs: " + name)
            require(row["git_blob"] == oid, "source Git object differs")
        format_changes = sorted(name for name in before if before[name] != formatted[name])
        require(format_changes == receipt["formatter_changes"]
                and set(format_changes) <= set(config["allowed_formatter_paths"]),
                "formatter scope differs")
        for name in format_changes:
            require(formatted[name] == {"mode": before[name]["mode"], **identity(members["formatted/" + name])},
                    "formatter output does not match source-after-format")
        require(members["committed-Cargo.lock"] == git.read("codex-rs/Cargo.lock")
                and members["committed-MODULE.bazel.lock"] == git.read("MODULE.bazel.lock"),
                "committed lock evidence differs")
        require(identity(members["baseline-Cargo.lock"])["git_blob"] == config["base_cargo_blob"],
                "immutable baseline Cargo lock differs")
        expected_final = dict(formatted)
        expected_final["codex-rs/Cargo.lock"] = {
            "mode": before["codex-rs/Cargo.lock"]["mode"], **identity(members["resolved-Cargo.lock"])
        }
        require(final == expected_final, "failure changed source outside formatter and actual Cargo lock")
        source_report = {
            "count": len(before), "all_match_exact_git_bytes": True,
            "before_sha256": sha(canonical(before)), "after_format_sha256": sha(canonical(formatted)),
            "final_sha256": sha(canonical(final)), "formatter_changes": format_changes,
            "only_other_change": "codex-rs/Cargo.lock",
        }
    finally:
        git.close()
    metadata_raw = members["actual-cargo-metadata.log"]
    with gzip.GzipFile(fileobj=io.BytesIO(members["actual-cargo-metadata.log.gz"])) as stream:
        uncompressed = stream.read(LIMIT + 1)
    require(len(uncompressed) <= LIMIT and uncompressed == metadata_raw, "metadata gzip bytes differ")
    metadata, span = parse_metadata(metadata_raw)
    before_lock = records(members["baseline-Cargo.lock"])
    after_lock = records(members["resolved-Cargo.lock"])
    recorded = document(members["resolved-cargo-records.json"])
    require(recorded["baseline"] == list(before_lock.values()) and recorded["resolved"] == list(after_lock.values()),
            "retained package records differ from original lock bytes")
    result = project(metadata, before_lock, after_lock)
    report = {
        "schema": 1, "key": spec["key"], "repository": spec["repository"], "source": spec["source"],
        "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
        "zip_bytes": len(raw_zip), "zip_sha256": sha(raw_zip), "crc_all_members": True,
        "original_qualification_status": "failed", "source_verification": source_report,
        "original_commands": commands, "metadata_log": identity(metadata_raw), "metadata_document": span,
        "result": result, "outputs": outputs,
        "evidence_verification": "passed",
        "scope": "Read-only extraction from the original failed resolver. No product execution, no lock adoption, no gate changes.",
    }
    (args.output / "VERIFIED.json").write_bytes(json.dumps(report, indent=2).encode() + b"\n")
    (args.output / "receipt.json").write_bytes(members["receipt.json"])
    (args.output / "artifact-metadata.json").write_bytes(json.dumps(artifact, indent=2).encode() + b"\n")
    print("UNION_METADATA_EVIDENCE_JSON=" + json.dumps({
        k: v for k, v in report.items() if k not in {"result", "outputs"}
    }, separators=(",", ":")), flush=True)
    for record in result["registry_dependency_rebindings"]:
        print("REGISTRY_DEPENDENCY_REBIND_JSON=" + json.dumps(record, separators=(",", ":")), flush=True)
    print("UNION_METADATA_SUMMARY_JSON=" + json.dumps({
        "package_count": result["package_count"], "resolve_node_count": result["resolve_node_count"],
        "removed_package_identities": result["removed_package_identities"],
        "added_package_identities": result["added_package_identities"],
        "local_record_changes": result["local_record_changes"],
        "verified_report_sha256": sha((args.output / "VERIFIED.json").read_bytes()),
    }, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
