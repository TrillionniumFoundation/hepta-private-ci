#!/usr/bin/env python3
"""Run the original committed check, regeneration and post-check without hiding drift."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def snapshot():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "MODULE.bazel", "BUILD.bazel", ".bazelrc", ".bazelversion", "defs.bzl",
        "bazel", "third_party", "cargo_bazel_template", "justfile", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml", "codex-rs/**/Cargo.toml", "codex-rs/third_party", "patches",
        "tools/argument-comment-lint", "scripts/update_cargo_bazel.py", "scripts/check-module-bazel-lock.sh",
        ".github/scripts/run_bazel_with_buildbuddy.py", ".github/actions/setup-ci",
        ".github/actions/setup-bazel-ci", ".github/actions/prepare-bazel-ci", ".github/workflows/rust-ci.yml",
        ".github/workflows/rust-ci-full.yml", ".github/workflows/rust-release-argument-comment-lint.yml",
        ".github/workflows/hepta-windows-archive-input-qualification.yml", "qualification/windows-archive-inputs-20261104",
    ], cwd=ROOT).decode().split("\0")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    original = (ROOT / "MODULE.bazel.lock").read_bytes()
    receipt = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "index_tree": subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip(),
        "committed_lock_required": args.require_committed,
        "committed_lock_sha256": hashlib.sha256(original).hexdigest(),
        "status": "failed", "steps": [], "checkout_checks": [],
    }
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    (output / "committed-MODULE.bazel.lock").write_bytes(original)
    def require_clean_checkout(stage):
        command = ["git", "diff", "--exit-code", "HEAD", "--"]
        result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output / ("git-clean-" + stage + ".stdout")).write_bytes(result.stdout)
        (output / ("git-clean-" + stage + ".stderr")).write_bytes(result.stderr)
        receipt["checkout_checks"].append({"stage": stage, "command": command, "exit": result.returncode})
        if result.returncode:
            raise RuntimeError("checkout differs from HEAD " + stage + " lock qualification")

    try:
        if args.require_committed:
            committed = subprocess.check_output(["git", "show", "HEAD:MODULE.bazel.lock"], cwd=ROOT)
            if original != committed:
                raise RuntimeError("entry lock bytes differ from the committed Git blob")
            require_clean_checkout("before")
        commands = []
        if args.require_committed:
            commands.append(("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"]))
        commands.extend([
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"]),
        ])
        for name, command in commands:
            started = time.monotonic()
            with (output / (name + ".stdout")).open("wb") as stdout, (output / (name + ".stderr")).open("wb") as stderr:
                result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                     "elapsed_seconds": time.monotonic() - started})
            if name == "original-lock-update" and (ROOT / "MODULE.bazel.lock").is_file():
                shutil.copyfile(ROOT / "MODULE.bazel.lock", output / "MODULE.bazel.lock")
        if any(step["exit"] for step in receipt["steps"]):
            raise RuntimeError("an original lock gate failed; generation and all logs retained")
        generated = (output / "MODULE.bazel.lock").read_bytes()
        json.loads(generated)
        if (ROOT / "MODULE.bazel.lock").read_bytes() != generated or snapshot() != before:
            raise RuntimeError("original checking changed the generated lock or another source input")
        if args.require_committed and generated != original:
            raise RuntimeError("regeneration changed the committed lock")
        if args.require_committed:
            require_clean_checkout("after")
        receipt.update(status="passed" if args.require_committed else "generated-not-committed-qualification",
                       generated_lock_sha256=hashlib.sha256(generated).hexdigest(),
                       generated_lock_bytes=len(generated), committed_lock_matches=generated == original)
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("LOCK_RECEIPT " + json.dumps({k: receipt[k] for k in
              ["commit", "index_tree", "committed_lock_required", "status", "steps", "checkout_checks", "source_inputs_unchanged"]}), flush=True)
        generated_path = output / "MODULE.bazel.lock"
        if generated_path.is_file() and generated_path.read_bytes() != original:
            generated = generated_path.read_bytes()
            if len(generated) > 8 * 1024 * 1024:
                raise RuntimeError("generated lock exceeds the bounded readback size")
            encoded = base64.b64encode(generated).decode("ascii")
            chunks = [encoded[i:i + 8192] for i in range(0, len(encoded), 8192)]
            print("GENERATED_LOCK_METADATA " + json.dumps({
                "bytes": len(generated), "sha256": hashlib.sha256(generated).hexdigest(),
                "chunks": len(chunks), "encoding": "base64",
            }), flush=True)
            for i, chunk in enumerate(chunks):
                print("GENERATED_LOCK_CHUNK " + str(i) + " " + chunk, flush=True)
        for step in receipt["steps"]:
            if step["exit"]:
                for suffix in ["stdout", "stderr"]:
                    print((output / (step["name"] + "." + suffix)).read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)


if __name__ == "__main__":
    main()
