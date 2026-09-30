#!/usr/bin/env python3
"""Execute bounded source mutations against learning.operator fail-closed tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "codex-rs/Cargo.toml"

MUTANTS = (
    {
        "name": "omit-training-error-budget-from-profile-digest",
        "path": "codex-rs/hepta-bellman-operator/src/profiles.rs",
        "old": "        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());\n",
        "new": "        // MUTANT: maximum error omitted from canonical identity.\n",
        "test": "mutation_profile_digest_covers_runtime_and_error_budget",
    },
    {
        "name": "omit-runtime-profile-from-training-profile-digest",
        "path": "codex-rs/hepta-bellman-operator/src/profiles.rs",
        "old": "        bytes.extend_from_slice(runtime_profile_digest.as_array());\n",
        "new": "        // MUTANT: runtime profile omitted from canonical identity.\n",
        "test": "mutation_profile_digest_covers_runtime_and_error_budget",
    },
    {
        "name": "disable-cooperative-cancellation",
        "path": "codex-rs/hepta-bellman-operator/src/budget.rs",
        "replacements": (
            ("        if control.is_cancelled() {\n", "        if false {\n"),
            ("        if self.control.is_cancelled() {\n", "        if false {\n"),
        ),
        "test": "mutation_cancelled_work_is_rejected_before_fit",
    },
)


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def mutate(path: Path, mutant: dict[str, object]) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = mutant.get("replacements")
    if replacements is None:
        replacements = ((mutant["old"], mutant["new"]),)
    for old, new in replacements:
        if text.count(old) != 1:
            raise RuntimeError(
                f"{mutant['name']}: expected exactly one mutation anchor in {path}"
            )
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=".hepta-evidence/learning-operator/mutation.json",
    )
    args = parser.parse_args()

    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    target = os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target" / "mutation"))
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = target
    results: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="hepta-learning-operator-mutants-") as raw:
        worktree = Path(raw) / "source"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), source_sha],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            for mutant in MUTANTS:
                subprocess.run(
                    ["git", "reset", "--hard", source_sha],
                    cwd=worktree,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                mutate(worktree / str(mutant["path"]), mutant)
                command = [
                    "cargo",
                    "test",
                    "--manifest-path",
                    str(worktree / MANIFEST.relative_to(ROOT)),
                    "--locked",
                    "-p",
                    "codex-hepta-bellman-operator",
                    "--all-features",
                    str(mutant["test"]),
                    "--",
                    "--test-threads=1",
                ]
                completed = run(command, cwd=worktree, env=env)
                output = completed.stdout
                if "could not compile" in output or "error: could not compile" in output:
                    raise RuntimeError(
                        f"{mutant['name']}: mutant was invalid because compilation failed\n{output}"
                    )
                if completed.returncode == 0:
                    raise RuntimeError(
                        f"{mutant['name']}: mutant survived\n{output}"
                    )
                results.append(
                    {
                        "name": mutant["name"],
                        "path": mutant["path"],
                        "test": mutant["test"],
                        "status": "killed",
                        "outputSha256": hashlib.sha256(output.encode()).hexdigest(),
                    }
                )
                print(f"killed mutation: {mutant['name']}")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            shutil.rmtree(worktree, ignore_errors=True)

    report = {
        "schema": "hepta.learning-operator.mutation.v1",
        "module": "learning.operator",
        "sourceSha": source_sha,
        "status": "pass",
        "mutants": results,
        "killed": len(results),
        "survived": 0,
    }
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
