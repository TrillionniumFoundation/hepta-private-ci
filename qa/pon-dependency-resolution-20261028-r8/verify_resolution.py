#!/usr/bin/env python3
"""Read and verify the retained hosted proposal without invoking native tools."""

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tomllib
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = "366dc9374ab554036873fdb66e3497151d36d273"
TREE = "fc1a413a036ebef783d6e1d6e04facbc0448fb44"
MERGE = "6b07dcdbd4e44ea31758db6df015aa7fe27ca165"
BASE = "3e9efb15faa261a4dc3ffc3205cd259aaee41a3f"
ARCHIVE_SHA = "7cb5ad030c5d63ae3dce23cc35a6aeb05d6882571b096ef724afc5a66649f330"
INPUTS = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel.lock")
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
TARGETS = {"ctutils": "0.4.6", "zstd": "0.14.3", "zstd-safe": "8.2.0"}
COMMANDS = (
    ("cargo-version", ".", ["cargo", "+1.96.0", "--version", "--verbose"]),
    ("bazel-version", ".", ["bazel", "--version"]),
    ("just-version", ".", ["just", "--version"]),
    (
        "cargo-update",
        "codex-rs",
        ["cargo", "+1.96.0", "update", "--package", "ctutils", "--precise", "0.4.6"],
    ),
    (
        "cargo-metadata",
        "codex-rs",
        [
            "cargo",
            "+1.96.0",
            "metadata",
            "--locked",
            "--all-features",
            "--format-version",
            "1",
        ],
    ),
    ("bazel-lock-update", ".", ["just", "bazel-lock-update"]),
    ("bazel-lock-check", ".", ["just", "bazel-lock-check"]),
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def json_value(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def package_key(package):
    return package["name"], package["version"], package.get("source") or ""


def dependency_key(dependency, packages):
    match = re.fullmatch(r"([^ ]+)(?: ([^ ]+))?(?: \((.+)\))?", dependency)
    require(match is not None, "invalid locked dependency")
    name, version, source = match.groups()
    selected = [
        key
        for key in packages
        if key[0] == name
        and (version is None or key[1] == version)
        and (source is None or key[2] == source)
    ]
    require(len(selected) == 1, "ambiguous or missing locked dependency: " + dependency)
    return selected[0]


def verify(current_kind):
    archive = (HERE / "artifact-12791038108.zip").read_bytes()
    require(
        len(archive) == 1270736 and sha256(archive) == ARCHIVE_SHA, "archive identity"
    )
    payload = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        infos = zipped.infolist()
        require(len(infos) == 23, "unexpected archive member count")
        require(
            sum(item.file_size for item in infos) <= 20_000_000, "archive total limit"
        )
        for item in infos:
            path = PurePosixPath(item.filename)
            require(
                item.filename not in payload
                and item.filename == path.as_posix()
                and not path.is_absolute()
                and not any(part in {".", ".."} for part in path.parts)
                and "\\" not in item.filename
                and ":" not in item.filename
                and stat.S_ISREG(item.external_attr >> 16)
                and not item.flag_bits & 1
                and item.file_size <= 10_000_000,
                "unsafe, duplicate or oversized archive member",
            )
            with zipped.open(item) as stream:
                raw = stream.read(item.file_size + 1)
            require(len(raw) == item.file_size, "archive member size mismatch")
            payload[item.filename] = raw

    listing = json_value(payload["files.json"])
    require(
        listing["schema"] == "hepta-proposal-file-manifest-v1", "file manifest schema"
    )
    listed = {entry["path"]: entry for entry in listing["files"]}
    require(len(listed) == len(listing["files"]), "duplicate file manifest path")
    expected_names = {"record.json", "proposal.patch"}
    expected_names.update(
        f"{kind}/{path}" for kind in ("original", "proposal") for path in INPUTS
    )
    expected_names.update(
        f"logs/{name}.{stream}.txt"
        for name, _, _ in COMMANDS
        for stream in ("stdout", "stderr")
    )
    require(
        set(listed) == expected_names == set(payload) - {"files.json"},
        "file manifest coverage",
    )
    for name, entry in listed.items():
        require(
            entry["bytes"] == len(payload[name])
            and entry["sha256"] == sha256(payload[name]),
            "file identity: " + name,
        )

    readbacks = {
        name: json_value((HERE / "github" / (name + ".json")).read_bytes())
        for name in (
            "artifacts",
            "jobs",
            "pull_request",
            "source_git",
            "merge_git",
            "run_raw",
        )
    }
    source, merge, run, pr = (
        readbacks[name]
        for name in ("source_git", "merge_git", "run_raw", "pull_request")
    )
    require(
        source["sha"] == SOURCE and source["tree"]["sha"] == TREE,
        "source object identity",
    )
    require(
        merge["sha"] == MERGE
        and merge["tree"]["sha"] == TREE
        and [p["sha"] for p in merge["parents"]] == [BASE, SOURCE],
        "merge object identity",
    )
    require(
        pr["head_sha"] == SOURCE
        and pr["base_sha"] == BASE
        and pr["merge_commit_sha"] == MERGE
        and pr["number"] == 4080,
        "PR readback identity",
    )
    require(
        run["id"] == 40630710054
        and run["run_attempt"] == 1
        and run["head_sha"] == SOURCE
        and run["event"] == "pull_request"
        and run["status"] == "completed"
        and run["conclusion"] == "failure",
        "run identity/status",
    )
    artifacts = readbacks["artifacts"]["artifacts"]
    require(len(artifacts) == 1, "artifact multiplicity")
    artifact = artifacts[0]
    require(
        artifact["id"] == 12791038108
        and artifact["size_in_bytes"] == len(archive)
        and artifact["digest"] == "sha256:" + ARCHIVE_SHA
        and artifact["workflow_run"]["head_sha"] == SOURCE
        and artifact["workflow_run"]["id"] == run["id"],
        "artifact API identity",
    )
    jobs = readbacks["jobs"]["jobs"]
    require(len(jobs) == 1, "job multiplicity")
    job = jobs[0]
    require(
        job["id"] == 122626157535
        and job["run_id"] == run["id"]
        and job["conclusion"] == "failure",
        "job identity/status",
    )
    require(
        [step["number"] for step in job["steps"] if step["conclusion"] != "success"]
        == [11],
        "unexpected failed/unknown job step",
    )
    require(
        next(step for step in job["steps"] if step["number"] == 11)["name"]
        == "Reject qualification of an uncommitted dependency graph",
        "failure is not the dirty-tree guard",
    )

    record = json_value(payload["record.json"])
    require(
        record["schema"] == "hepta-pon-dependency-proposal-v1"
        and record["source"] == SOURCE
        and record["source_tree"] == TREE
        and record["github_run_sha"] == MERGE
        and record["github_ref"] == "refs/pull/4080/merge"
        and record["run_id"] == str(run["id"])
        and record["run_attempt"] == "1",
        "record source identity",
    )
    require(
        record["ready_for_review"] is True
        and record["state"] == "generated"
        and not record["review_errors"]
        and not record["interrupted_or_unknown_stages"],
        "proposal is not complete and reviewable",
    )
    require(
        record["proposal_only"] is True
        and record["committed_source_qualified"] is False
        and record["all_advisories_closed"] is False
        and record["native_builds_or_tests_requested"] is False,
        "proposal overclaims qualification",
    )
    require(
        set(record["changed_tracked_paths"]) == set(INPUTS),
        "unexpected proposal mutation",
    )
    require(len(record["stages"]) == len(COMMANDS), "stage count")
    for stage, (name, cwd, command) in zip(record["stages"], COMMANDS, strict=True):
        require(
            (stage["name"], stage["cwd"], stage["command"]) == (name, cwd, command)
            and stage["state"] == "succeeded"
            and stage["exit_code"] == 0,
            "unexpected or incomplete hosted command",
        )

    identities = {}
    for path in INPUTS:
        original, proposal = (
            payload[f"{kind}/{path}"] for kind in ("original", "proposal")
        )
        source_bytes = subprocess.check_output(
            ["git", "show", TREE + ":" + path], cwd=ROOT
        )
        require(
            source_bytes == original, "original does not equal source tree: " + path
        )
        require(
            record["original"][path]
            == {"bytes": len(original), "sha256": sha256(original)},
            "recorded original identity",
        )
        require(
            (ROOT / path).read_bytes() == payload[f"{current_kind}/{path}"],
            "worktree bytes do not match declared current kind: " + path,
        )
        identities[path] = {
            kind: {"bytes": len(raw), "sha256": sha256(raw)}
            for kind, raw in (("original", original), ("proposal", proposal))
        }
    before_manifest = payload["original/codex-rs/Cargo.toml"]
    old_line, new_line = b'\nzstd = "0.13"\n', b'\nzstd = "0.14.3"\n'
    require(
        before_manifest.count(old_line) == 1
        and payload["proposal/codex-rs/Cargo.toml"]
        == before_manifest.replace(old_line, new_line),
        "manifest byte scope",
    )

    before_lock, after_lock = (
        tomllib.loads(payload[f"{kind}/codex-rs/Cargo.lock"].decode())
        for kind in ("original", "proposal")
    )
    old = {package_key(p): p for p in before_lock["package"]}
    new = {package_key(p): p for p in after_lock["package"]}
    require(
        len(old) == len(before_lock["package"])
        and len(new) == len(after_lock["package"]),
        "duplicate locked package",
    )
    removed = {
        ("ctutils", "0.4.2", REGISTRY),
        ("zstd", "0.13.3", REGISTRY),
        ("zstd-safe", "7.2.4", REGISTRY),
    }
    added = {("ctutils", "0.4.6", REGISTRY)}
    require(
        old.keys() - new.keys() == removed and new.keys() - old.keys() == added,
        "unexpected package identity change",
    )
    require(
        {k: v for k, v in before_lock.items() if k != "package"}
        == {k: v for k, v in after_lock.items() if k != "package"},
        "lock header/metadata change",
    )
    replacements = {
        "zstd 0.13.3": "zstd",
        "zstd 0.14.3": "zstd",
        "zstd-safe 8.2.0": "zstd-safe",
    }
    token_changes = []
    edge_changes = []
    for key in sorted(old.keys() & new.keys()):
        expected = copy.deepcopy(old[key])
        if "dependencies" in expected:
            expected["dependencies"] = [
                replacements.get(dep, dep) for dep in expected["dependencies"]
            ]
        require(
            new[key] == expected,
            "unreviewed package fields or dependency tokens: " + str(key),
        )
        if old[key] != new[key]:
            token_changes.append(key)
        old_edges = {
            dependency_key(dep, old) for dep in old[key].get("dependencies", [])
        }
        new_edges = {
            dependency_key(dep, new) for dep in new[key].get("dependencies", [])
        }
        if old_edges != new_edges:
            edge_changes.append(
                {
                    "package": key,
                    "removed": sorted(old_edges - new_edges),
                    "added": sorted(new_edges - old_edges),
                }
            )
    old_ct = copy.deepcopy(old[("ctutils", "0.4.2", REGISTRY)])
    new_ct = new[("ctutils", "0.4.6", REGISTRY)]
    old_ct.update(version=new_ct["version"], checksum=new_ct["checksum"])
    require(old_ct == new_ct, "unexpected ctutils locked-field mutation")

    upstream_saved = json_value(
        (
            ROOT / "qa/pon-dependency-proposal-20261028/upstream-versions.json"
        ).read_bytes()
    )
    selected = {}
    for name, version in TARGETS.items():
        index_raw = (HERE / "upstream" / (name + ".index")).read_bytes()
        candidates = [json_value(line) for line in index_raw.splitlines() if line]
        matched = [p for p in candidates if p["name"] == name and p["vers"] == version]
        require(
            len(matched) == 1 and matched[0]["yanked"] is False,
            "official fixed-index identity",
        )
        indexed = matched[0]
        saved = [
            entry["record"]
            for entry in upstream_saved["records"]
            if entry["record"]["name"] == name and entry["record"]["vers"] == version
        ]
        require(
            saved == [indexed],
            "independent official readback differs from retained review",
        )
        require(
            len([key for key in new if key[0] == name]) == 1
            and new[(name, version, REGISTRY)]["checksum"] == indexed["cksum"],
            "duplicate or checksum-mismatched target",
        )
        selected[name] = {
            "version": version,
            "checksum": indexed["cksum"],
            "index_sha256": sha256(index_raw),
            "index_commit": upstream_saved["index_commit"],
            "yanked": False,
        }

    metadata = json_value(payload["logs/cargo-metadata.stdout.txt"])
    ids = {p["id"]: package_key(p) for p in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    require(
        len(ids) == len(metadata["packages"]) == len(new)
        and set(ids.values()) == set(new)
        and set(nodes) == set(ids),
        "metadata does not cover the complete lock graph",
    )
    for node_id, node in nodes.items():
        locked_edges = {
            dependency_key(dep, new)
            for dep in new[ids[node_id]].get("dependencies", [])
        }
        require(
            locked_edges == {ids[dep] for dep in node["dependencies"]},
            "metadata dependency edge mismatch",
        )
        require(
            set(node["dependencies"]) == {dep["pkg"] for dep in node["deps"]},
            "metadata named dependency mismatch",
        )
    wanted = set(TARGETS) | {
        "zstd-sys",
        "aws-config",
        "crypto-bigint",
        "p256",
        "elliptic-curve",
    }
    feature_review = {
        f"{p['name']}@{p['version']}": nodes[p["id"]]["features"]
        for p in metadata["packages"]
        if p["name"] in wanted
    }
    require(
        "credentials-login" in feature_review["aws-config@1.8.12"],
        "AWS login feature removed",
    )
    aws_auth = next(p for p in metadata["packages"] if p["name"] == "codex-aws-auth")
    require(
        any(
            dep["name"] == "aws-config" and "credentials-login" in dep["features"]
            for dep in aws_auth["dependencies"]
        ),
        "original AWS caller feature request absent",
    )
    require(
        [key for key in new if key[0] == "crypto-bigint"]
        == [("crypto-bigint", "0.5.5", REGISTRY)],
        "bigint scope changed",
    )

    bazel_before, bazel_after = (
        json_value(payload[f"{kind}/MODULE.bazel.lock"])
        for kind in ("original", "proposal")
    )
    expected_bazel = copy.deepcopy(bazel_before)
    fact_key = "@@rules_rs+//rs:extensions.bzl%crate"
    facts = expected_bazel["facts"][fact_key]
    deleted_facts = ("ctutils_0.4.2", "zstd_0.13.3", "zstd-safe_7.2.4")
    for name in deleted_facts:
        del facts[name]
    facts["ctutils_0.4.6"] = bazel_after["facts"][fact_key]["ctutils_0.4.6"]
    require(
        expected_bazel == bazel_after,
        "unreviewed Bazel graph/platform/registry mutation",
    )
    ct_fact = json_value(facts["ctutils_0.4.6"])
    ct_index = next(
        entry["record"]
        for entry in upstream_saved["records"]
        if entry["record"]["name"] == "ctutils" and entry["record"]["vers"] == "0.4.6"
    )
    fact_deps = [
        {
            "name": dep["name"],
            "req": dep["req"],
            "kind": dep.get("kind", "normal"),
            "features": dep.get("features", []),
            "optional": dep.get("optional", False),
            "default_features": dep.get("default_features", True),
            "target": dep.get("target"),
        }
        for dep in ct_fact["dependencies"]
    ]
    require(
        fact_deps == ct_index["deps"]
        and ct_fact["features"]
        == {**ct_index["features"], **ct_index.get("features2", {})},
        "new Bazel fact differs from official package metadata",
    )
    require(
        all(f"{name}_{version}" in facts for name, version in TARGETS.items()),
        "Bazel fixed target absent",
    )

    return {
        "schema": "hepta-pon-dependency-resolution-static-review-v1",
        "result": "PASS",
        "current_worktree_kind": current_kind,
        "source": SOURCE,
        "source_tree": TREE,
        "synthetic_merge": MERGE,
        "merge_parents": [BASE, SOURCE],
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "job_id": job["id"],
        "artifact_id": artifact["id"],
        "archive_sha256": ARCHIVE_SHA,
        "archive_bytes": len(archive),
        "archive_members": len(payload),
        "manifest_files_verified": len(listed),
        "decompressed_bytes": sum(len(raw) for raw in payload.values()),
        "hosted_stages": record["stages"],
        "files": identities,
        "cargo_packages_before": len(old),
        "cargo_packages_after": len(new),
        "cargo_removed": sorted(removed),
        "cargo_added": sorted(added),
        "changed_dependency_tokens": token_changes,
        "changed_resolved_edges": edge_changes,
        "metadata_packages_and_nodes_verified": len(nodes),
        "metadata_dependency_edges_verified": sum(
            len(node["dependencies"]) for node in nodes.values()
        ),
        "workspace_members": len(metadata["workspace_members"]),
        "selected_registry_packages": selected,
        "resolved_target_features": feature_review,
        "bazel_removed_facts": deleted_facts,
        "bazel_added_facts": ["ctutils_0.4.6"],
        "bazel_other_sections_and_facts_unchanged": True,
        "credentials_login_retained": True,
        "crypto_bigint_blocker_closed": False,
        "local_cargo_rust_bazel_executed": False,
        "native_qualification": False,
        "all_advisories_closed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-kind", choices=("original", "proposal"), default="proposal"
    )
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.current_kind), indent=2) + "\n", end="")
