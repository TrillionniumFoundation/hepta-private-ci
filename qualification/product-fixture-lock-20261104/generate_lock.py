#!/usr/bin/env python3
"""Generate an artifact-only Bazel lock for the reviewed test-helper inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tomllib


REPOSITORY = Path(__file__).resolve().parents[2]
HELPER_MANIFEST = Path(__file__).with_name("helper-source-manifest.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_text(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPOSITORY, text=True).strip()


def snapshot(helper_paths: list[str]) -> dict[str, str]:
    specs = [
        "MODULE.bazel", ".bazelrc", ".bazelversion", "defs.bzl",
        "cargo_bazel_template", "justfile", "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
        "codex-rs/**/Cargo.toml", "codex-rs/**/BUILD.bazel",
        "codex-rs/third_party", "patches", "scripts/update_cargo_bazel.py",
        "scripts/check-module-bazel-lock.sh",
        ".github/scripts/run_bazel_with_buildbuddy.py",
        ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
        ".github/actions/prepare-bazel-ci",
        ".github/workflows/hepta-product-fixture-lock.yml",
        "qualification/product-fixture-lock-20261104",
        *helper_paths,
    ]
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *specs], cwd=REPOSITORY
    ).decode().split("\0")
    return {name: sha256(REPOSITORY / name) for name in sorted(set(names)) if name}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--verify-inputs-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1,
        "status": "failed",
        "steps": [],
        "product_qualification": False,
        "verify_inputs_only": args.verify_inputs_only,
        "workflow": {
            name: os.environ.get(name)
            for name in ("GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
        },
    }
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.expected_source):
            raise RuntimeError("expected source must be an immutable Git SHA")
        commit = git_text("rev-parse", "HEAD")
        receipt["commit"] = commit
        if commit != args.expected_source:
            raise RuntimeError("checkout differs from the requested immutable source")
        if git_text("diff", "--name-only") or git_text("diff", "--cached", "--name-only"):
            raise RuntimeError("tracked checkout inputs must be unmodified before generation")

        helper_manifest = json.loads(HELPER_MANIFEST.read_text())
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for variable, expected in (
                ("GITHUB_REPOSITORY", helper_manifest["expected_repository"]),
                ("GITHUB_REF", helper_manifest["expected_ref"]),
                ("GITHUB_SHA", commit),
            ):
                if os.environ.get(variable) != expected:
                    raise RuntimeError(f"artifact source identity differs: {variable}")
        parents = git_text("show", "-s", "--format=%P", "HEAD").split()
        if parents != [helper_manifest["expected_parent"]] or len(parents) != helper_manifest["required_parent_count"]:
            raise RuntimeError("artifact commit must have the reviewed prior helper source as its only parent")
        source_base = helper_manifest["source_base"]
        subprocess.run(["git", "merge-base", "--is-ancestor", source_base, commit], cwd=REPOSITORY, check=True)
        changed = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", "-z", source_base, commit, "--"],
            cwd=REPOSITORY,
        ).decode().split("\0")
        changed_paths = sorted(name for name in changed if name)
        allowed_paths = sorted(
            [entry["path"] for entry in helper_manifest["files"]]
            + helper_manifest["artifact_generation_paths"]
        )
        if changed_paths != allowed_paths or len(changed_paths) != helper_manifest["required_changed_path_count"]:
            raise RuntimeError("artifact source must differ from e729 only in the six reviewed helper and three generator paths")
        receipt.update(parent=parents[0], source_base=source_base, changed_paths=changed_paths)
        observed_helper = {}
        for entry in helper_manifest["files"]:
            name = entry["path"]
            observed_helper[name] = sha256(REPOSITORY / name)
            if observed_helper[name] != entry["expected_sha256"]:
                raise RuntimeError(f"reviewed helper source differs: {name}")
            if git_text("rev-parse", f"{commit}:{name}") != entry["expected_git_blob"]:
                raise RuntimeError(f"reviewed helper Git blob differs: {name}")
        packages = tomllib.loads((REPOSITORY / "codex-rs/Cargo.lock").read_text())["package"]
        if len(packages) != helper_manifest["expected_cargo_package_count"]:
            raise RuntimeError("Cargo package count differs from the reviewed test-edge-only graph")
        exec_server = [p for p in packages if p["name"] == "codex-exec-server"]
        if len(exec_server) != 1 or "codex-utils-cargo-bin" not in exec_server[0].get("dependencies", []):
            raise RuntimeError("reviewed existing cargo-bin dev dependency is missing")

        before = snapshot(list(observed_helper))
        original_lock = (REPOSITORY / "MODULE.bazel.lock").read_bytes()
        original_lock_sha256 = hashlib.sha256(original_lock).hexdigest()
        if original_lock_sha256 != helper_manifest["initial_module_lock"]["sha256"]:
            raise RuntimeError("initial lock differs from the reviewed parent lock")
        if git_text("rev-parse", f"{commit}:MODULE.bazel.lock") != helper_manifest["initial_module_lock"]["git_blob"]:
            raise RuntimeError("initial lock Git blob differs from the reviewed parent lock")
        (output / "source-commit.txt").write_text(commit + "\n")
        (output / "source-parent.txt").write_text(parents[0] + "\n")
        (output / "source-changed-paths.json").write_text(json.dumps(changed_paths, indent=2) + "\n")
        (output / "source.patch").write_text(git_text("diff", "--no-ext-diff", source_base, commit, "--") + "\n")
        (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
        (output / "helper-source-inputs.json").write_text(json.dumps(observed_helper, indent=2) + "\n")
        shutil.copyfile(HELPER_MANIFEST, output / "helper-source-manifest.json")
        receipt["committed_lock_sha256"] = original_lock_sha256
        if args.verify_inputs_only:
            receipt.update(status="inputs_verified_only", source_inputs_unchanged=True)
            return
        commands = [
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["just", "bazel-lock-check"]),
        ]
        for name, command in commands:
            started = time.monotonic()
            with (output / f"{name}.stdout").open("wb") as stdout, (output / f"{name}.stderr").open("wb") as stderr:
                result = subprocess.run(command, cwd=REPOSITORY, stdout=stdout, stderr=stderr, check=False)
            receipt["steps"].append({"name": name, "command": command, "exit_code": result.returncode, "elapsed_seconds": time.monotonic() - started})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "original-lock-update":
                shutil.copyfile(REPOSITORY / "MODULE.bazel.lock", output / "MODULE.bazel.lock")

        generated = (output / "MODULE.bazel.lock").read_bytes()
        json.loads(generated)
        if (REPOSITORY / "MODULE.bazel.lock").read_bytes() != generated:
            raise RuntimeError("original lock check changed the generated bytes")
        after = snapshot(list(observed_helper))
        (output / "source-inputs-after.json").write_text(json.dumps(after, indent=2) + "\n")
        if after != before:
            raise RuntimeError("lock generation changed a source/manifest/tooling input")
        if set(git_text("diff", "--name-only").splitlines()) - {"MODULE.bazel.lock"} or git_text("diff", "--cached", "--name-only"):
            raise RuntimeError("generation changed tracked source other than MODULE.bazel.lock")
        (output / "MODULE.bazel.lock.patch").write_text(git_text("diff", "--", "MODULE.bazel.lock") + "\n")
        receipt.update(
            status="generated_candidate_only",
            generated_lock_sha256=hashlib.sha256(generated).hexdigest(),
            generated_lock_bytes=len(generated),
            committed_lock_matches=generated == original_lock,
            source_inputs_unchanged=True,
        )
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        receipt["outputs"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(output.iterdir()) if path.is_file() and path.name != "receipt.json"
        }
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
