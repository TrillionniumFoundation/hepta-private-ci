#!/usr/bin/env python3
"""Bind small real-platform operation probes and the original complete Fleet suite."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
QUAL = Path(__file__).resolve().parent
EXPECTED = {
    "registry::tests::workspace_sweep_agrees_with_pairwise_oracle_for_nested_and_sibling_paths",
    "release::copy_tests::readonly_source_is_copied_synced_and_preserved_on_duplicate_install",
    "release::tests::catalog_resolves_only_digest_bound_per_agent_allowances",
    "release::tests::program_mutation_is_detected_and_release_state_survives_reopen",
    "release::tests::schema_v2_bundle_binds_both_exact_programs_and_closed_world",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot():
    paths = subprocess.check_output([
        "git", "ls-files", "-z", "--", "codex-rs/hepta-fleet",
        "codex-rs/hepta-paths", "codex-rs/hepta-contracts", "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml", "justfile",
        "scripts/run-nextest.py", "codex-rs/.config/nextest.toml",
        "qualification/fleet-macos-permissions",
        ".github/workflows/hepta-fleet-macos-qualification.yml",
    ], cwd=ROOT).decode().split("\0")
    return {p: digest((ROOT / p).read_bytes()) for p in paths if p}


def extract(source, name):
    start = source.index("fn " + name + "(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    receipt = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "platform": platform.platform(), "machine": platform.machine(), "uid": os.getuid(),
               "source_before": before, "status": "failed", "commands": [],
               "scope": "Operation probes report observations only; the original Fleet tests retain all assertions."}

    def run(name, argv, env=None):
        started = time.monotonic()
        path = output / (name + ".log")
        with path.open("wb") as stream:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"name": name, "argv": argv, "exit": result.returncode,
                                    "seconds": time.monotonic() - started, "log_sha256": digest(path.read_bytes())})
        return result.returncode

    try:
        if os.getuid() == 0:
            raise RuntimeError("permission probes require the ordinary unprivileged runner")
        source = (ROOT / "codex-rs/hepta-fleet/src/release.rs").read_text()
        functions = "\n".join(extract(source, name) for name in ["copy_immutable_program", "set_mode", "sync_directory"])
        extracted = output / "production-functions.rs"
        extracted.write_text(functions)
        receipt["extracted_functions_sha256"] = digest(extracted.read_bytes())
        env = os.environ.copy()
        env["HEPTA_FLEET_FUNCTIONS"] = str(extracted)
        for version in ["1.95.0", "1.96.0"]:
            if run("compiler-" + version, ["rustup", "run", version, "rustc", "--version", "--verbose"]):
                raise RuntimeError("selected compiler is unavailable")
            if not (output / ("compiler-" + version + ".log")).read_text().startswith("rustc " + version + " "):
                raise RuntimeError("compiler version does not match the selected release")
            binary = output.parent / ("fleet-operations-" + version)
            if run("probe-build-" + version, ["rustup", "run", version, "rustc", "--edition=2024", str(QUAL / "probe.rs"), "-o", str(binary)], env):
                raise RuntimeError("operation probe compilation failed")
            receipt.setdefault("probe_binaries", {})[version] = digest(binary.read_bytes())
            if run("probe-run-" + version, [str(binary), str(output.parent / ("fleet-operation-files-" + version))]):
                raise RuntimeError("operation probe setup or observation failed")
            rows = [json.loads(line) for line in (output / ("probe-run-" + version + ".log")).read_text().splitlines()]
            if rows[-1] != {"probe_complete": True, "acceptance_claim": False}:
                raise RuntimeError("incomplete operation observation")
            receipt.setdefault("operation_observations", {})[version] = rows
        junit = ROOT / "codex-rs/target/nextest/local/junit.xml"
        junit.unlink(missing_ok=True)
        code = run("original-fleet-suite", ["just", "test", "-p", "codex-hepta-fleet", "--lib", "--locked", "--no-tests=fail", "--no-fail-fast", "--retries", "0"])
        if junit.exists():
            raw = junit.read_bytes()
            (output / "fleet.junit.xml").write_bytes(raw)
            tree = ET.fromstring(raw)
            cases = tree.findall(".//testcase")
            names = {c.get("name") for c in cases}
            failures = [c.get("name") for c in cases if any(e.tag in {"failure", "error", "skipped"} for e in c)]
            receipt["tests"] = {"count": len(cases), "names": sorted(names), "failed_or_skipped": failures,
                                "sha256": digest(raw), "original_five_present": EXPECTED <= names}
            if len(cases) < 41 or int(tree.get("tests", "-1")) != len(cases) or not EXPECTED <= names or failures:
                raise RuntimeError("original complete Fleet tests contain failures, skips or missing cases")
        else:
            raise RuntimeError("original Fleet tests produced no JUnit report")
        if code:
            raise RuntimeError("original Fleet suite exited " + str(code))
        receipt["source_after"] = snapshot()
        if receipt["source_after"] != before:
            raise RuntimeError("source changed during original qualification")
        receipt["status"] = "passed"
    finally:
        if "source_after" not in receipt:
            receipt["source_after"] = snapshot()
        receipt["source_unchanged"] = receipt["source_after"] == before
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
