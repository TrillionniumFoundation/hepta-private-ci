#!/usr/bin/env python3
"""Exercise exact Git inputs against complete-history scope, using local remotes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    inputs = [
        ".github/workflows/blocking-ci.yml",
        "scripts/hepta_ci_history.py",
        "scripts/hepta_ci_scope.py",
        "scripts/hepta_ci_dependencies.py",
        str(Path(__file__).resolve().relative_to(repository)),
    ]
    before = {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
        for name in inputs
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_CONFIG_", "GIT_TRACE"))
        and key not in {"GH_TOKEN", "GITHUB_TOKEN", "GIT_CURL_VERBOSE"}
    }
    environment.update(
        GIT_AUTHOR_NAME="Local CI fixture",
        GIT_AUTHOR_EMAIL="ci@example.invalid",
        GIT_COMMITTER_NAME="Local CI fixture",
        GIT_COMMITTER_EMAIL="ci@example.invalid",
        GIT_AUTHOR_DATE="2026-11-03T16:50:00Z",
        GIT_COMMITTER_DATE="2026-11-03T16:50:00Z",
        GIT_TERMINAL_PROMPT="0",
    )
    commands = []

    def run(cwd, argv, *, success=True):
        result = subprocess.run(
            argv, cwd=cwd, env=environment, capture_output=True, text=True
        )
        commands.append(
            {"argv": argv, "cwd": str(cwd), "exit_code": result.returncode,
             "stdout": result.stdout, "stderr": result.stderr}
        )
        if success and result.returncode != 0:
            raise RuntimeError(f"fixture command failed: {argv!r}")
        return result

    def git(cwd, *argv, success=True):
        return run(cwd, ["git", *argv], success=success)

    def write(root, name, data):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)

    def commit(root, message):
        git(root, "add", "--all")
        git(root, "commit", "-qm", message)
        return git(root, "rev-parse", "HEAD").stdout.strip()

    cases = []
    accepted = False
    error = None
    try:
        with tempfile.TemporaryDirectory(prefix="yaml-exact-inputs-") as temporary:
            root = Path(temporary)
            origin = root / "origin"
            origin.mkdir()
            git(origin, "init", "-q", "--initial-branch=main")
            git(origin, "config", "uploadpack.allowFilter", "true")
            write(origin, "README.md", "Fixture navigation.\n")
            write(origin, "docs/guide.md", "Guide.\n")
            write(origin, "docs/obsolete.md", "Old guide.\n")
            write(origin, "codex-rs/Cargo.toml", '[workspace]\nmembers = ["hepta-types", "hepta-fleet"]\n')
            for name in ["hepta-types", "hepta-fleet"]:
                write(origin, f"codex-rs/{name}/Cargo.toml", f'[package]\nname = "{name}"\nversion = "0.1.0"\n')
                write(origin, f"codex-rs/{name}/src/lib.rs", "pub fn value() {}\n")
            write(origin, "codex-rs/hepta-types/src/lib.rs", 'pub const INPUT: &str = include_str!("catalog.json");\n')
            write(origin, "codex-rs/hepta-types/src/catalog.json", '{"value": 1}\n')
            base = commit(origin, "base")
            git(origin, "checkout", "-qb", "unrelated")
            write(origin, "unrelated.txt", "Not a comparison input.\n")
            unrelated = commit(origin, "unrelated")
            git(origin, "tag", "unrelated-tag")
            for case in ["prose", "embedded-rename-delete", "unknown"]:
                git(origin, "checkout", "-qb", case, base)
                if case == "prose":
                    write(origin, "README.md", "Changed navigation.\n")
                elif case == "embedded-rename-delete":
                    write(origin, "codex-rs/hepta-types/src/catalog.json", '{"value": 2}\n')
                    (origin / "docs/guide.md").rename(origin / "docs/moved.md")
                    (origin / "docs/obsolete.md").unlink()
                else:
                    write(origin, "assets/runtime.cfg", "unknown input\n")
                head = commit(origin, case)
                scope_argv = [sys.executable, str(repository / "scripts/hepta_ci_scope.py"), "--base", base, "--head", head]
                complete = json.loads(run(origin, scope_argv).stdout)
                shallow = root / case
                git(root, "clone", "--quiet", "--depth=1", "--single-branch", "--no-tags", "--branch", case, origin.as_uri(), str(shallow))
                assert git(shallow, "cat-file", "-e", f"{base}^{{commit}}", success=False).returncode != 0
                missing = run(shallow, scope_argv, success=False)
                assert missing.returncode != 0
                run(shallow, [sys.executable, str(repository / "scripts/hepta_ci_history.py"), "--commit", base, "--commit", head])
                exact = json.loads(run(shallow, scope_argv).stdout)
                assert exact == complete
                assert exact["scope"]["native"] == (case != "prose")
                assert exact["scope"]["full_repo"] == (case == "unknown")
                if case == "embedded-rename-delete":
                    assert {"docs/guide.md", "docs/moved.md", "docs/obsolete.md"} <= set(exact["paths"])
                assert git(shallow, "cat-file", "-e", f"{unrelated}^{{commit}}", success=False).returncode != 0
                assert git(shallow, "tag", "--list").stdout == ""
                bad = run(shallow, [sys.executable, str(repository / "scripts/hepta_ci_history.py"), "--commit", "f" * 40], success=False)
                assert bad.returncode != 0
                cases.append({"name": case, "base": base, "head": head, "before_fetch_failed": True, "complete_and_exact_equal": True, "unrelated_commit_and_tag_absent": True, "unavailable_input_rejected": True, "scope": exact})
            accepted = len(cases) == 3
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"
    after = {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
        for name in inputs
    }
    accepted = accepted and before == after
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema": "exact-input-checkout-fixture-v1", "accepted": accepted, "error": error, "source_sha256_before": before, "source_sha256_after": after, "cases": cases, "commands": commands, "scope": "Local Git transport and unchanged scope behavior only; the original hosted five-minute job must also pass."}, indent=2) + "\n")
    print(json.dumps({"accepted": accepted, "cases": len(cases), "error": error, "receipt": str(args.output)}))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
