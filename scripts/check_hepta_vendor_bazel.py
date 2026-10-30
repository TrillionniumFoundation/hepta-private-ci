#!/usr/bin/env python3
"""Audit the six real path-vendor spokes after canonical Bazel lock generation.

This uses actual generated rules, not a hand-written replacement BUILD or a
default-feature approximation. Query proves graph/source inclusion; it does not
claim Rust compilation, linking, execution, or cross-platform correctness.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET

from run_hepta_vendor_compatibility import VENDORS


REQUIRED_FEATURES = {
    "aws-config": {"credentials-login", "credentials-process", "default-https-client", "rt-tokio", "sso"},
    "matrix-sdk": {"e2e-encryption", "sqlite"},
    "matrix-sdk-sqlite": {"crypto-store", "event-cache-store", "media-store", "state-store"},
    "i18n-config": set(),
    "starlark": set(),
    "zip": {"aes-crypto", "bzip2-rs", "deflate64", "deflate", "lzma", "ppmd", "time", "zstd", "xz", "_bzip2_any"},
}
EXACT_FEATURES = {
    "matrix-sdk": {"e2e-encryption", "sqlite"},
    "matrix-sdk-sqlite": {"crypto-store", "event-cache-store", "media-store", "state-store"},
    "starlark": set(),
}
REQUIRED_DATA = {
    "aws-config": {"src/profile/location_of_profile_files.md"},
    "matrix-sdk": {"README.md", "src/docs/encryption.md", ".cargo/mermaid.html"},
    "matrix-sdk-sqlite": {
        "migrations/state_store/001_init.sql", "migrations/crypto_store/001_init.sql",
        "migrations/event_cache_store/001_init.sql", "migrations/media_store/001_init.sql",
    },
    "i18n-config": set(),
    "starlark": set(),
    "zip": set(),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def values(rule, attribute):
    result = []
    for child in rule:
        if child.get("name") == attribute:
            if child.get("value") is not None:
                result.append(child.get("value"))
            result.extend(node.get("value") for node in child.iter() if node is not child and node.get("value") is not None)
    return result


def audit_rules(xml, repo):
    tree = ET.fromstring(xml)
    rows = []
    for name, directory in VENDORS.items():
        candidates = [rule for rule in tree.iter("rule")
                      if rule.get("class") == "rust_library"
                      and values(rule, "crate_name") == [name.replace("-", "_")]]
        if len(candidates) != 1:
            raise ValueError(f"expected exactly one generated library for {name}, got {len(candidates)}")
        rule = candidates[0]
        features = set(values(rule, "crate_features"))
        if not REQUIRED_FEATURES[name] <= features:
            raise ValueError(f"generated features missing for {name}: {sorted(REQUIRED_FEATURES[name] - features)}")
        if name in EXACT_FEATURES and features != EXACT_FEATURES[name]:
            raise ValueError(f"unexpected generated feature set for {name}: {sorted(features)}")
        if name == "zip" and features & {"default", "bzip2"}:
            raise ValueError("ZIP unexpectedly activates its default Rust bzip2 backend")
        inputs = set(values(rule, "srcs") + values(rule, "compile_data") + values(rule, "crate_root"))
        required = REQUIRED_DATA[name] | {"src/lib.rs"}
        missing = [path for path in required if not any(label.endswith(":" + path) or label.endswith("/" + path) for label in inputs)]
        if missing:
            raise ValueError(f"generated compile inputs omit required source/data for {name}: {sorted(missing)}")
        dependencies = values(rule, "deps")
        if name in {"matrix-sdk", "starlark"} and not any("_bs" in label or "build_script" in label for label in dependencies):
            raise ValueError(f"generated library omits build-script dependency for {name}")
        manifest = tomllib.loads((repo / "codex-rs/third_party" / directory / "Cargo.toml").read_text())
        edition = str(manifest["package"].get("edition", "2015"))
        if values(rule, "edition") != [edition]:
            raise ValueError(f"generated edition differs from normalized manifest for {name}")
        rows.append({
            "package": name, "directory": directory, "generated_rule": rule.get("name"),
            "edition": edition, "features": sorted(features), "required_inputs_checked": sorted(required),
            "compile_input_count": len(inputs), "dependencies": dependencies,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "hepta.vendor-bazel-audit.v2", "status": "running",
        "cargo_lock_before_sha256": sha(repo / "codex-rs/Cargo.lock"),
        "bazel_lock_before_sha256": sha(repo / "MODULE.bazel.lock"),
        "helper_sha256": sha(Path(__file__)),
        "scope": "Actual generated query graph, feature sets and compile-time source/data inclusion; no compilation or runtime pass claimed.",
    }
    path = output / "RECEIPT.json"
    write_json(path, receipt)
    try:
        command = ["cargo", "metadata", "--no-deps", "--locked", "--format-version=1"]
        with (output / "metadata.json").open("wb") as stdout, (output / "metadata.stderr.log").open("wb") as stderr:
            metadata_run = subprocess.run(command, cwd=repo / "codex-rs", stdout=stdout, stderr=stderr)
        receipt["metadata_command"] = command
        receipt["metadata_exit_code"] = metadata_run.returncode
        if metadata_run.returncode:
            raise RuntimeError("root workspace metadata failed")
        metadata = json.loads((output / "metadata.json").read_text())
        metadata_bytes = (output / "metadata.json").read_bytes()
        (output / "metadata.json.gz").write_bytes(gzip.compress(metadata_bytes, mtime=0))
        (output / "metadata.json").unlink()
        receipt["metadata_sha256"] = hashlib.sha256(metadata_bytes).hexdigest()
        members = set(metadata["workspace_members"])
        unexpected = [package["name"] for package in metadata["packages"] if package["id"] in members and package["name"] in VENDORS]
        if unexpected:
            raise ValueError(f"path-vendored dependencies unexpectedly became first-party workspace members: {unexpected}")
        receipt["workspace_member_count"] = len(members)
        labels = [f"@crates//:{directory}" for directory in VENDORS.values()]
        query = f"deps(set({' '.join(labels)}), 1)"
        command = ["bazel", "query", query, "--output=xml", "--lockfile_mode=error"]
        started = time.monotonic()
        with (output / "query.stderr.log").open("wb") as stderr:
            run = subprocess.run(command, cwd=repo, stdout=subprocess.PIPE, stderr=stderr)
        xml = run.stdout
        (output / "generated-rules.xml.gz").write_bytes(gzip.compress(xml, mtime=0))
        receipt.update(query_command=command, query_exit_code=run.returncode,
                       query_seconds=time.monotonic() - started,
                       query_xml_bytes=len(xml), query_xml_sha256=hashlib.sha256(xml).hexdigest())
        if run.returncode:
            raise RuntimeError("actual Bazel spoke query failed; no graph pass claimed")
        receipt["vendors"] = audit_rules(xml, repo)
        if sha(repo / "codex-rs/Cargo.lock") != receipt["cargo_lock_before_sha256"] or sha(repo / "MODULE.bazel.lock") != receipt["bazel_lock_before_sha256"]:
            raise RuntimeError("a lock changed during the read-only generated graph audit")
        receipt["status"] = "passed generated graph/source contract only"
        return 0
    except Exception as error:
        receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(receipt["error"], file=sys.stderr)
        return 1
    finally:
        receipt["cargo_lock_after_sha256"] = sha(repo / "codex-rs/Cargo.lock")
        receipt["bazel_lock_after_sha256"] = sha(repo / "MODULE.bazel.lock")
        receipt["logs"] = []
        for name in ("metadata.stderr.log", "query.stderr.log"):
            log = output / name
            if not log.is_file():
                continue
            data = log.read_bytes()
            compressed = log.with_suffix(log.suffix + ".gz")
            compressed.write_bytes(gzip.compress(data, mtime=0))
            log.unlink()
            receipt["logs"].append({"path": compressed.name, "uncompressed_bytes": len(data), "uncompressed_sha256": hashlib.sha256(data).hexdigest()})
        write_json(path, receipt)


if __name__ == "__main__":
    raise SystemExit(main())
