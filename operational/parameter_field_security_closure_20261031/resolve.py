"""Run Cargo's real resolver and retain the complete candidate graph for review."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import tarfile
import time
import tomllib

from . import prepare


def load_module(root, path, name, expected_blob):
    raw = (root / path).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected_blob:
        raise ValueError("inherited command-capture source changed")
    spec = importlib.util.spec_from_file_location(name, root / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_map(document):
    result = {}
    for item in document["package"]:
        key = (item["name"], item["version"], item.get("source", ""))
        if key in result:
            raise ValueError("duplicate locked package identity")
        result[key] = item
    return result


def graph_contract(document):
    packages = document["package"]
    by_name = {}
    for item in packages:
        by_name.setdefault(item["name"], []).append(item)
    for name in ("basic-toml", "zbus_names", "zvariant", "zvariant_derive", "libbz2-rs-sys", "bzip2-sys"):
        if name in by_name:
            raise ValueError("retired or rejected implementation remains: " + name)
    for name, version in (("ctutils", "0.4.7"), ("crypto-bigint", "0.7.10")):
        if [item["version"] for item in by_name.get(name, [])] != [version]:
            raise ValueError("patched registry version not selected: " + name)
    for name, version in (
        ("anymap2", "0.13.0"), ("aws-config", "1.8.12"), ("i18n-config", "0.4.8"),
        ("keyring", "3.6.3"), ("matrix-sdk-crypto", "0.18.0"), ("oxiarc-bzip2", "0.4.2"),
        ("secret-service", "6.0.0"), ("zip", "9.1.2"),
    ):
        found = by_name.get(name, [])
        if len(found) != 1 or found[0]["version"] != version or found[0].get("source"):
            raise ValueError("reviewed local implementation not selected: " + name)
    if not any(item["version"] == "1.1.8+spec-1.1.0" for item in by_name.get("toml", [])):
        raise ValueError("reviewed maintained TOML parser is not selected")
    if not any(item["version"] == "1.1.0" for item in by_name.get("anymap3", [])):
        raise ValueError("maintained type-map implementation is missing")
    return {name: [{key: item.get(key) for key in ("name", "version", "source", "checksum")}
                   for item in by_name[name]] for name in (
        "anymap2", "anymap3", "aws-config", "crypto-bigint", "ctutils", "i18n-config",
        "keyring", "matrix-sdk-crypto", "oxiarc-bzip2", "secret-service", "toml", "zip", "zbus",
    )}


def run(root, output):
    root, output = root.resolve(), output.resolve()
    plan = json.loads((prepare.HERE / "INPUTS.json").read_text())
    preparation = json.loads((output / "PREPARATION.json").read_text())
    if preparation["status"] != "complete":
        raise ValueError("candidate source preparation is not complete")
    for path, expected in plan["candidate_files"].items():
        prepare.check((root / path).read_bytes(), expected, path)
    capture = load_module(root, "scripts/capture_cargo_deny_diagnostic.py", "security_capture",
                          plan["capture_git_blob"])
    started = time.monotonic()
    receipt = {
        "schema": "hepta.dependency-security-resolution.1", "status": "in_progress",
        "source_head": prepare.git(root, "rev-parse", "HEAD").decode().strip(),
        "source_base": plan["source_base"], "input_plan": prepare.identity((prepare.HERE / "INPUTS.json").read_bytes()),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "qualification": False, "dependency_graph_approved": False, "commands": [],
        "semantic_validation_required": [
            "Matrix: literal upstream security patch identity AND original panic regression executed successfully.",
            "AnyMap: actual clone/send/sync and ordinary non-Clone Any API tests.",
            "i18n: actual maintained parser compatibility regressions.",
            "AWS: actual DPoP signature verification and original tests with maintained arithmetic.",
            "Credentials: native original/candidate interoperability on an isolated Secret Service.",
            "ZIP: independent libbz2 interoperability, legacy blocks, CRC, truncation and container boundaries.",
        ],
        "advisory_scope": "A path backport may not match registry advisories. cargo-deny alone cannot establish its security or compatibility.",
    }

    def save():
        receipt["wall_seconds"] = time.monotonic() - started
        temporary = output / "RESOLUTION.json.tmp"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temporary.replace(output / "RESOLUTION.json")

    def invoke(label, command, maximum=1200):
        save()
        result = capture.capture(command, root / "codex-rs", output, label,
                                 timeout=maximum, limit=32 * 1024 * 1024)
        result["label"] = label
        receipt["commands"].append(result)
        save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("real command failed: " + label)
        return result

    before_raw = (root / "codex-rs/Cargo.lock").read_bytes()
    prepare.check(before_raw, plan["base_files"]["codex-rs/Cargo.lock"], "base Cargo.lock")
    (output / "Cargo.lock.before").write_bytes(before_raw)
    before = tomllib.loads(before_raw.decode())
    save()
    try:
        for tool in ("cargo", "rustc"):
            invoke(tool + "_version", [tool, "--version"], 60)
            if not (output / (tool + "_version.stdout.log")).read_text().startswith(tool + " 1.95.0 "):
                raise ValueError("Rust toolchain is not the inherited 1.95.0")
        invoke("cargo_update", ["cargo", "update", "-p", "aws-config", "-p", "keyring",
                               "-p", "anymap2", "-p", "i18n-config", "-p", "matrix-sdk-crypto",
                               "-p", "zip", "-p", "ctutils"])
        for name, version in plan["lock_pins"].items():
            current = tomllib.loads((root / "codex-rs/Cargo.lock").read_text())["package"]
            selected = [item for item in current if item["name"] == name
                        and (name != "toml" or item["version"].startswith("1."))]
            if len(selected) != 1:
                raise ValueError("ambiguous security dependency version: " + name)
            if selected[0]["version"] != version:
                invoke("pin_" + name.replace("-", "_"), [
                    "cargo", "update", "-p", name + "@" + selected[0]["version"], "--precise", version,
                ])
        after_raw = (root / "codex-rs/Cargo.lock").read_bytes()
        after = tomllib.loads(after_raw.decode())
        receipt["selected_implementations"] = graph_contract(after)
        old, new = package_map(before), package_map(after)
        for key in old.keys() & new.keys():
            if old[key].get("checksum") != new[key].get("checksum"):
                raise ValueError("checksum changed for an unchanged package identity")
        delta = {
            "removed": [old[key] for key in sorted(old.keys() - new.keys())],
            "added": [new[key] for key in sorted(new.keys() - old.keys())],
            "changed": [{"before": old[key], "after": new[key]} for key in sorted(old.keys() & new.keys())
                        if old[key] != new[key]],
            "dependency_graph_approved": False,
        }
        (output / "LOCK_DELTA.json").write_text(json.dumps(delta, indent=2) + "\n")
        result = invoke("metadata", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"])
        stream = result["streams"]["stdout"]
        if not stream["complete"]:
            raise ValueError("Cargo metadata was not retained completely")
        metadata_raw = (output / "metadata.stdout.log").read_bytes() + (output / "metadata.stdout.tail.log").read_bytes()
        if hashlib.sha256(metadata_raw).hexdigest() != stream["observed_sha256"]:
            raise ValueError("Cargo metadata capture identity mismatch")
        metadata = json.loads(metadata_raw)
        if metadata.get("resolve") is None:
            raise ValueError("Cargo metadata omitted the resolved graph")
        (output / "METADATA.json").write_bytes(metadata_raw)
        for path, expected in plan["candidate_files"].items():
            prepare.check((root / path).read_bytes(), expected, path)
        for path in plan["policy_files_unchanged"]:
            prepare.check((root / path).read_bytes(), plan["base_files"][path], path)
        if (root / "codex-rs/Cargo.lock").read_bytes() != after_raw:
            raise ValueError("locked metadata changed the resolved lock")
        (output / "Cargo.lock").write_bytes(after_raw)
        receipt["cargo_lock"] = prepare.identity(after_raw)
        receipt["candidate_sources"] = plan["candidate_files"]
        archive_path = output / "CANDIDATE_SOURCE.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(set(plan["candidate_files"]) | {"codex-rs/Cargo.lock"}):
                archive.add(root / path, arcname=path, recursive=False)
        receipt["candidate_source_archive"] = prepare.identity(archive_path.read_bytes())
        receipt["status"] = "complete"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        if (root / "codex-rs/Cargo.lock").is_file():
            (output / "Cargo.lock.observed").write_bytes((root / "codex-rs/Cargo.lock").read_bytes())
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.repo, args.output)
    print(json.dumps({"status": receipt["status"], "qualification": False,
                      "cargo_lock": receipt["cargo_lock"]}))


if __name__ == "__main__":
    main()
