#!/usr/bin/env python3
"""Generate the real Cargo/Bazel locks before original process qualification."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot():
    paths = subprocess.check_output([
        "git", "--no-replace-objects", "ls-files", "-z", "--",
        "codex-rs", ".github", "scripts", "bazel", "patches", "third_party",
        "cargo_bazel_template", "justfile", "defs.bzl", "BUILD.bazel", "MODULE.bazel",
        "MODULE.bazel.lock", ".bazelrc", ".bazelversion", "workspace_root_test_launcher.*",
        "qualification/windows-process-fixtures-current",
        "qualification/keyring-sync-provider/build_pinned_client.py",
        "qualification/windows-process-env-current",
    ], cwd=ROOT).decode().split("\0")
    result = {}
    for name in filter(None, paths):
        path = ROOT / name
        raw = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        result[name] = digest(raw)
    return result


def lock_records(raw):
    document = tomllib.loads(raw.decode())
    records = {}
    for row in document["package"]:
        key = (row["name"], row["version"], row.get("source", ""))
        require(key not in records, "duplicate Cargo package")
        records[key] = row
    return document, records


def compare_cargo(baseline, generated, config):
    old_doc, old = lock_records(baseline)
    new_doc, new = lock_records(generated)
    require(len(old) == len(new) == config["package_count"] and set(old) == set(new),
            "package version or source set changed")
    require({k: v for k, v in old_doc.items() if k != "package"} ==
            {k: v for k, v in new_doc.items() if k != "package"}, "Cargo lock header changed")
    observed = {}
    for key, previous in old.items():
        current = new[key]
        additions = config["expected_added_dependencies"].get(key[0])
        if additions is None:
            require(previous == current, "unrelated Cargo record changed: " + key[0])
            continue
        require(not key[2], "expected workspace package resolved externally")
        require({k: v for k, v in previous.items() if k != "dependencies"} ==
                {k: v for k, v in current.items() if k != "dependencies"},
                "workspace package identity changed")
        wanted = sorted([*previous.get("dependencies", []), *additions])
        require(current.get("dependencies") == wanted, "unexpected dependency delta: " + key[0])
        observed[key[0]] = additions
    require(observed == config["expected_added_dependencies"], "required workspace edges missing")
    return {"packages": len(new), "added_dependencies": observed,
            "versions_sources_checksums_unchanged": True}


def emit_generated(path, raw):
    encoded = base64.b64encode(raw).decode()
    chunks = [encoded[index:index + 65536] for index in range(0, len(encoded), 65536)]
    print("GENERATED_FILE_BEGIN=" + json.dumps({
        "path": path, "bytes": len(raw), "sha256": digest(raw), "chunks": len(chunks)
    }), flush=True)
    for index, chunk in enumerate(chunks):
        print("GENERATED_FILE_CHUNK=" + json.dumps({"path": path, "index": index, "base64": chunk}),
              flush=True)
    print("GENERATED_FILE_END=" + json.dumps({"path": path}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-lock", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((HERE / "scope.json").read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"],
                                   cwd=ROOT, text=True).strip()
    require(head == os.environ["HEPTA_EXPECTED_COMMIT"], "unexpected source commit")
    original_cargo = (WORKSPACE / "Cargo.lock").read_bytes()
    original_bazel = (ROOT / "MODULE.bazel.lock").read_bytes()
    baseline = args.baseline_lock.read_bytes()
    require(hashlib.sha1(b"blob " + str(len(baseline)).encode() + b"\0" + baseline).hexdigest()
            == config["base_cargo_blob"], "baseline lock is not the reviewed original blob")
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    (output / "committed-Cargo.lock").write_bytes(original_cargo)
    (output / "committed-MODULE.bazel.lock").write_bytes(original_bazel)
    receipt = {"source_commit": head, "base_commit": config["base_commit"],
               "status": "failed", "commands": [], "source_before": before,
               "scope": "Real lock generation and formatting; native product qualification is separate."}

    def run(name, argv, cwd=ROOT, required=True):
        started = time.monotonic()
        path = output / (name + ".log")
        with path.open("wb") as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"name": name, "argv": argv, "exit_code": result.returncode,
                                    "seconds": time.monotonic() - started,
                                    "log_sha256": digest(path.read_bytes())})
        print(json.dumps(receipt["commands"][-1]), flush=True)
        if required:
            require(result.returncode == 0, name + " failed")
        return result.returncode

    try:
        run("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"])
        first = run("committed-lock-first", ["just", "bazel-lock-check"], required=False)
        run("original-formatter", ["just", "fmt", "--base", config["base_commit"]])
        run("original-formatter-check", ["just", "fmt", "--check", "--base", config["base_commit"]])
        run("actual-cargo-metadata", ["cargo", "metadata", "--all-features", "--format-version", "1"],
            WORKSPACE)
        generated_cargo = (WORKSPACE / "Cargo.lock").read_bytes()
        receipt["cargo_delta"] = compare_cargo(baseline, generated_cargo, config)
        run("actual-locked-metadata", ["cargo", "metadata", "--locked", "--all-features",
                                       "--format-version", "1"], WORKSPACE)
        metadata = json.loads((output / "actual-locked-metadata.log").read_bytes())
        require(len(metadata["packages"]) == config["package_count"], "metadata graph count changed")
        run("original-lock-update", ["just", "bazel-lock-update"])
        run("original-lock-check", ["just", "bazel-lock-check"])
        generated_bazel = (ROOT / "MODULE.bazel.lock").read_bytes()
        json.loads(generated_bazel)
        after = snapshot()
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        allowed = set(config["allowed_generated_source_paths"]) | {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}
        require(set(changed) <= allowed, "generation changed an unowned source")
        receipt["changed_paths"] = changed
        generated = output / "generated"
        for name in changed:
            path = generated / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (ROOT / name).read_bytes()
            path.write_bytes(raw)
            emit_generated(name, raw)
        for name in ("Cargo.lock", "MODULE.bazel.lock"):
            raw = generated_cargo if name == "Cargo.lock" else generated_bazel
            (output / name).write_bytes(raw)
        receipt["committed_cargo_equals_generated"] = original_cargo == generated_cargo
        receipt["committed_bazel_equals_generated"] = original_bazel == generated_bazel
        receipt["source_after"] = after
        qualified = first == 0 and before == after
        receipt["status"] = "committed-lock-qualified" if qualified else "generated-needs-adoption"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("qualified=" + str(qualified).lower() + "\n")
    finally:
        receipt.setdefault("source_after", snapshot())
        receipt["source_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {}
        # Retain metadata without duplicating its full JSON in the artifact.
        for name in ("actual-cargo-metadata.log", "actual-locked-metadata.log"):
            path = output / name
            if path.is_file():
                (output / (name + ".gz")).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.name != "receipt.json":
                raw = path.read_bytes()
                receipt["outputs"][path.relative_to(output).as_posix()] = {
                    "bytes": len(raw), "sha256": digest(raw)}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("LOCK_GENERATION_RESULT=" + json.dumps({
            key: value for key, value in receipt.items()
            if key not in {"source_before", "source_after", "outputs"}
        }), flush=True)


if __name__ == "__main__":
    main()
