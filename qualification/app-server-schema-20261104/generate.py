#!/usr/bin/env python3
"""Regenerate protocol exports with the original recipes and verify the full library."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
SCHEMA_PREFIX = "codex-rs/app-server-protocol/schema/"
PACKAGE = "codex-app-server-protocol"
IGNORED_GENERATOR = "schema_fixtures_tests::write_schema_fixtures_from_env"
REQUIRED = {
    "schema_fixtures_tests::typescript_schema_fixtures_match_generated",
    "schema_fixtures_tests::json_schema_fixtures_match_generated",
    "schema_fixtures_tests::stable_precomputed_exports_match_schema_fixtures",
    "schema_fixtures_tests::experimental_precomputed_exports_match_generated",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def tracked_inputs():
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT).decode().split("\0")
    result = {}
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, expected_blob, stage = metadata.split()
        require(stage == "0", "unmerged source input")
        if name.startswith(SCHEMA_PREFIX):
            continue
        path = ROOT / name
        require(mode in ("100644", "100755", "120000"), "unsupported source mode")
        data = os.readlink(path).encode("utf-8") if mode == "120000" else path.read_bytes()
        value = identity(data)
        require(value["git_blob"] == expected_blob, "source differs from exact Git bytes: " + name)
        result[name] = {"mode": mode, **value}
    return dict(sorted(result.items()))


def schema_inventory():
    base = ROOT / SCHEMA_PREFIX
    return {
        path.relative_to(ROOT).as_posix(): identity(path.read_bytes())
        for path in sorted(base.rglob("*")) if path.is_file()
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def complete_native_report(listing_path, report_path):
    listing = json.loads(listing_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    suites = list(listing["rust-suites"].values())
    require(len(suites) == 1 and suites[0]["package-name"] == PACKAGE and
            suites[0]["kind"] == "lib" and suites[0]["status"] == "listed",
            "inventory is not the complete selected library")
    inventory = suites[0]["testcases"]
    require(listing["test-count"] == len(inventory), "compiled case denominator disagrees")
    require(all(isinstance(item["ignored"], bool) for item in inventory.values()),
            "invalid ignored-case inventory")
    require(all(item["filter-match"]["status"] == "matches"
                for item in inventory.values() if not item["ignored"]),
            "an original runnable library case was filtered")
    ignored = {name for name, item in inventory.items() if item["ignored"]}
    runnable = set(inventory) - ignored
    require(ignored == {IGNORED_GENERATOR}, "original ignored-generator inventory changed")
    require(REQUIRED <= runnable, "an original schema comparison is missing")
    root = ET.parse(report_path).getroot()
    require(root.tag == "testsuites", "missing complete native JUnit document")
    cases = list(root.iter("testcase"))
    names = [case.get("name") for case in cases]
    require(len(names) == len(set(names)), "duplicate native JUnit case")
    require(not list(root.iter("failure")) and not list(root.iter("error")),
            "original library has failures or errors")
    require(not list(root.iter("rerunFailure")) and not list(root.iter("flakyFailure")),
            "retry evidence is not accepted")
    passed = {case.get("name") for case in cases if case.find("skipped") is None}
    skipped = {case.get("name") for case in cases if case.find("skipped") is not None}
    require(passed == runnable and skipped <= ignored,
            "JUnit does not cover every original runnable library case exactly once")
    return {
        "runnable_cases": sorted(runnable), "passed": len(passed),
        "failed": 0, "errors": 0, "retries": 0,
        "original_ignored_cases": sorted(ignored),
        "junit_skipped_cases": sorted(skipped),
        "required_schema_cases": sorted(REQUIRED),
        "inventory": identity(listing_path.read_bytes()),
        "junit": identity(report_path.read_bytes()),
    }


def main():
    require(__debug__, "optimized Python execution is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.exists(), "evidence output already exists")
    output.mkdir(parents=True)
    receipt = {"schema": 1, "status": "failed", "steps": [], "native": None,
               "host": platform.platform(), "generation_completed": False}
    generated = []

    def run(name, command, cwd=WORKSPACE):
        started = time.monotonic()
        stdout_path, stderr_path = output / (name + ".stdout"), output / (name + ".stderr")
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr)
        step = {"name": name, "command": command, "exit": result.returncode,
                "elapsed_seconds": time.monotonic() - started}
        receipt["steps"].append(step)
        print("SCHEMA_COMMAND " + json.dumps(step), flush=True)
        if result.returncode:
            for path in (stdout_path, stderr_path):
                print(path.read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)
            raise RuntimeError(name + " failed with exit " + str(result.returncode))
        return stdout_path.read_text(encoding="utf-8").strip()

    try:
        require(platform.system() == "Linux", "requires the original native Linux host")
        receipt["commit"] = run("source-commit", ["git", "rev-parse", "HEAD"], ROOT)
        receipt["tree"] = run("source-tree", ["git", "rev-parse", "HEAD^{tree}"], ROOT)
        require(receipt["commit"] == os.environ["GITHUB_SHA"], "source differs from dispatched head")
        run("source-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"], ROOT)
        receipt["rustc"] = run("rustc-version", ["rustc", "--version"])
        require(receipt["rustc"].startswith("rustc 1.96.0 "), "pinned Rust compiler changed")
        before = tracked_inputs()
        write_json(output / "source-inputs-before.json", before)
        original_schema = schema_inventory()
        write_json(output / "original-schema.json", original_schema)

        run("original-format", ["just", "fmt", "--base",
                               "fcedede3f945bc75cec6dc7730c7cf0ef9056eda"])
        run("source-clean-after-format", ["git", "diff", "--exit-code", "HEAD", "--"], ROOT)
        run("original-stable-generator", ["just", "write-app-server-schema"])
        run("original-experimental-generator", ["just", "write-app-server-schema", "--experimental"])
        require(tracked_inputs() == before, "generation modified a non-schema source input")
        candidate_schema = schema_inventory()
        write_json(output / "generated-schema.json", candidate_schema)
        names = sorted(set(original_schema) | set(candidate_schema))
        for name in names:
            if original_schema.get(name) == candidate_schema.get(name):
                continue
            require(name.startswith(SCHEMA_PREFIX), "generated path outside schema subtree")
            row = {"path": name, "before": original_schema.get(name),
                   "after": candidate_schema.get(name)}
            generated.append(row)
            if row["after"] is not None:
                destination = output / "generated" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, destination)
        require(generated, "original generation produced no correction")
        receipt["generated_deltas"] = generated
        receipt["generation_completed"] = True
        write_json(output / "generated-deltas.json", generated)
        run("generated-source-diff", ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--",
                                      SCHEMA_PREFIX], ROOT)

        run("complete-original-library-inventory",
            ["cargo", "nextest", "list", "--locked", "-p", PACKAGE, "--lib", "--message-format", "json"])
        # The repository scoped-metadata launcher stores nextest reports under
        # the workspace target directory, even with a separate Cargo build cache.
        report = WORKSPACE / "target" / "nextest" / "local" / "junit.xml"
        require(not report.exists(), "native JUnit exists before the original test")
        run("complete-original-library", ["just", "test", "--locked", "-p", PACKAGE,
                                          "--lib", "--retries", "0"])
        require(report.is_file(), "fresh native JUnit was not written")
        shutil.copyfile(report, output / "original-library.junit.xml")
        receipt["native"] = complete_native_report(
            output / "complete-original-library-inventory.stdout", output / "original-library.junit.xml")
        require(schema_inventory() == candidate_schema, "native tests changed the generated bytes")
        after = tracked_inputs()
        write_json(output / "source-inputs-after.json", after)
        require(after == before, "format/generation/tests changed a non-schema source input")
        changed = run("tracked-changed-paths", ["git", "diff", "--name-only", "HEAD", "--"], ROOT)
        untracked = run("untracked-changed-paths",
                        ["git", "ls-files", "--others", "--exclude-standard"], ROOT)
        require(all(name.startswith(SCHEMA_PREFIX) for name in changed.splitlines() + untracked.splitlines()),
                "checkout contains changes outside the exact generated subtree")
        receipt["non_schema_inputs_unchanged"] = True
        receipt["generated_bytes_unchanged_through_native"] = True
        receipt["status"] = "passed"
    finally:
        receipt["outputs"] = {
            path.relative_to(output).as_posix(): identity(path.read_bytes())
            for path in sorted(output.rglob("*")) if path.is_file() and path != output / "receipt.json"
        }
        write_json(output / "receipt.json", receipt)
        print("SCHEMA_GENERATION_RECEIPT " + json.dumps(
            {key: receipt.get(key) for key in ("status", "commit", "tree", "generation_completed",
             "non_schema_inputs_unchanged", "generated_bytes_unchanged_through_native")}), flush=True)
        if receipt["status"] == "passed":
            total = sum(row["after"]["bytes"] for row in generated if row["after"] is not None)
            require(total <= 32 * 1024 * 1024, "generated byte export exceeds the bounded transport")
            for row in generated:
                print("EXACT_GENERATED_FILE " + json.dumps(row), flush=True)
                if row["after"] is None:
                    continue
                data = (output / "generated" / row["path"]).read_bytes()
                for offset in range(0, len(data), 32768):
                    chunk = data[offset:offset + 32768]
                    print("EXACT_GENERATED_FILE_PART " + json.dumps({
                        "path": row["path"], "offset": offset, "bytes": len(chunk),
                        "base64": base64.b64encode(chunk).decode("ascii"),
                    }), flush=True)


if __name__ == "__main__":
    main()
