#!/usr/bin/env python3
"""Prewarm dependencies without replacing the source that CI will validate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(argv: list[str], cwd: Path) -> None:
    print(json.dumps({"argv": argv, "cwd": str(cwd)}), flush=True)
    subprocess.run(argv, cwd=cwd, check=True)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(repo), *args], text=True
    ).strip()


def checkout_identity(repo: Path, expected_sha: str) -> dict[str, str]:
    head = git(repo, "rev-parse", "HEAD")
    if head != expected_sha:
        raise RuntimeError(f"CI checkout changed: expected {expected_sha}, got {head}")
    git(repo, "diff", "--exit-code", "--quiet")
    git(repo, "diff", "--cached", "--exit-code", "--quiet")
    return {"head": head, "tree": git(repo, "rev-parse", "HEAD^{tree}")}


def prewarm(
    repo: Path,
    *,
    target: str,
    expected_sha: str,
    runner_temp: Path,
    target_dir: Path,
    cargo: tuple[str, ...] = ("cargo",),
) -> None:
    repo = repo.resolve()
    target_dir = target_dir.resolve()
    receipt = {"before": checkout_identity(repo, expected_sha), "target": target,
               "target_dir": str(target_dir)}
    receipt["cargo_chef_version"] = subprocess.check_output(
        [*cargo, "chef", "--version"], cwd=repo, text=True
    ).strip()
    if receipt["cargo_chef_version"] not in ("cargo-chef 0.1.78", "cargo-chef-chef 0.1.78"):
        raise RuntimeError("Unexpected cargo-chef version: " + receipt["cargo_chef_version"])
    runner_temp.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="chef-", dir=runner_temp) as temporary:
            root = Path(temporary)
            source = root / "source"
            recipe = root / "recipe.json"
            run(["git", "--no-replace-objects", "-C", str(repo), "worktree", "add",
                 "--detach", str(source), expected_sha], repo)
            try:
                receipt["prewarm_checkout"] = checkout_identity(source, expected_sha)
                workspace = source / "codex-rs"
                run([*cargo, "chef", "prepare", "--recipe-path", str(recipe)], workspace)
                receipt["recipe_sha256"] = hashlib.sha256(recipe.read_bytes()).hexdigest()
                # cargo-chef overwrites local manifests and entrypoints. Its
                # cleanup also needs the explicit target-dir, not only the env.
                run([*cargo, "chef", "cook", "--recipe-path", str(recipe),
                     "--target", target, "--release", "--target-dir", str(target_dir)],
                    workspace)
            finally:
                receipt["prewarm_source_changes"] = git(
                    source, "diff", "--name-only", "HEAD", "--"
                ).splitlines()
                # This path belongs only to the TemporaryDirectory above.
                run(["git", "--no-replace-objects", "-C", str(repo), "worktree",
                     "remove", "--force", str(source)], repo)
    finally:
        receipt["after"] = checkout_identity(repo, expected_sha)
        data = json.dumps(receipt, indent=2) + "\n"
        (runner_temp / "cargo-chef-source-custody.json").write_text(data, encoding="utf-8")
        print(data, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    workspace = repo / "codex-rs"
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(workspace / "target")))
    if not target_dir.is_absolute():
        target_dir = workspace / target_dir
    prewarm(
        repo,
        target=args.target,
        expected_sha=os.environ["GITHUB_SHA"],
        runner_temp=Path(os.environ["RUNNER_TEMP"]),
        target_dir=target_dir,
    )


if __name__ == "__main__":
    main()
