#!/usr/bin/env python3
"""Run original consumer/lock commands and preserve failures with source identity."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    "codex-utils-yaml",
    "codex-skills",
    "codex-skills-extension",
    "codex-core-plugins",
    "codex-external-agent-migration",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("native", "graph", "bazel"))
    parser.add_argument("--package", choices=PACKAGES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "native" and args.package is None:
        parser.error("native qualification requires an exact package")
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = [ROOT / "codex-rs/Cargo.toml", ROOT / "codex-rs/Cargo.lock"]
    for relative in ("codex-rs/utils/yaml", "codex-rs/third_party/serde-saphyr-2.1.0"):
        inputs.extend(p for p in (ROOT / relative).rglob("*") if p.is_file())
    before = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    receipt = {
        "schema": "yaml-consumer-qualification-v1",
        "mode": args.mode,
        "package": args.package,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
        "source_sha256_before": before,
        "commands": [],
        "accepted": False,
    }
    result = 1

    def run(name, command, cwd=ROOT):
        start = time.monotonic()
        stdout = args.out / f"{name}.stdout"
        stderr = args.out / f"{name}.stderr"
        with stdout.open("wb") as out, stderr.open("wb") as err:
            completed = subprocess.run(command, cwd=cwd, stdout=out, stderr=err, check=False)
        receipt["commands"].append({
            "name": name,
            "argv": command,
            "cwd": str(cwd),
            "exit_code": completed.returncode,
            "seconds": time.monotonic() - start,
            "stdout_sha256": sha(stdout),
            "stderr_sha256": sha(stderr),
        })
        print(json.dumps(receipt["commands"][-1]), flush=True)
        if completed.returncode:
            raise RuntimeError(f"{name} failed with exit {completed.returncode}")

    try:
        if args.mode == "native":
            run("original-just-test", ["just", "test", "--locked", "-p", args.package], ROOT / "codex-rs")
        elif args.mode == "graph":
            run("cargo-metadata-all-features", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], ROOT / "codex-rs")
            graph = json.loads((args.out / "cargo-metadata-all-features.stdout").read_text())
            forbidden = [p["name"] for p in graph["packages"] if p["name"] in ("serde_yaml", "unsafe-libyaml")]
            parser_packages = [p for p in graph["packages"] if p["name"] == "serde-saphyr"]
            expected = ROOT / "codex-rs/third_party/serde-saphyr-2.1.0/Cargo.toml"
            if forbidden or len(parser_packages) != 1 or Path(parser_packages[0]["manifest_path"]).resolve() != expected.resolve():
                raise RuntimeError("Cargo graph retained the legacy parser or did not select the reviewed fork")
            receipt["graph"] = {"package_count": len(graph["packages"]), "forbidden_packages": forbidden, "parser_package": parser_packages[0]["id"]}
        else:
            run("original-bazel-lock-update", ["just", "bazel-lock-update"])
            shutil.copy2(ROOT / "MODULE.bazel.lock", args.out / "MODULE.bazel.lock")
            run("original-bazel-lock-check", ["just", "bazel-lock-check"])
            run("bazel-yaml-utility-tests", [str(ROOT / ".github/scripts/run_bazel_with_buildbuddy.py"), "test", "//codex-rs/utils/yaml:yaml-unit-tests"])
        after = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
        receipt["source_sha256_after"] = after
        receipt["inputs_unchanged"] = before == after
        if before != after:
            raise RuntimeError("qualification inputs changed while running")
        receipt["accepted"] = True
        result = 0
    except (OSError, RuntimeError, ValueError) as error:
        receipt["error"] = str(error)
        print(str(error), flush=True)
    finally:
        receipt["environment"] = {name: os.environ.get(name) for name in ("CARGO_INCREMENTAL", "CARGO_BUILD_JOBS", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG", "RUST_MIN_STACK")}
        receipt["original_just_test_stack_bytes"] = 8388608
        (args.out / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
