#!/usr/bin/env python3
"""Repair deterministic cognitive.read qualification drift on the authored branch.

This is an ordinary source-authoring helper. It does not qualify, activate, merge,
or release anything. The caller must pin the exact remote source SHA and use a
normal non-force push after the resulting commits are reviewed by the existing
source-preparation workflow.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONSUMER_AUDIT = ROOT / "scripts/cognitive_read_consumers.py"
FULL_EVIDENCE = ROOT / "scripts/cognitive_read_full_evidence.py"
LOCKFILE = ROOT / "codex-rs/Cargo.lock"

ALLOWED_PATHS = {
    "codex-rs/Cargo.lock",
    "scripts/cognitive_read_consumers.py",
    "scripts/cognitive_read_full_evidence.py",
}


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text(encoding="utf-8")
    if old not in body and body.count(new) == 1:
        return
    if body.count(old) != 1:
        raise ValueError(f"qualification source shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def repair_consumer_audit() -> None:
    replace_once(
        CONSUMER_AUDIT,
        '''    ("final_use", "codex-rs/hepta-agentd/src/cognitive_context.rs", "pub(crate) async fn revalidate_with_retrieval_context("),
''',
        '''    ("final_use", "codex-rs/hepta-agentd/src/cognitive_context_final_use.rs", "pub(crate) async fn revalidate_with_retrieval_context("),
''',
    )


def repair_evidence_import_isolation() -> None:
    old = '''base.commands = commands
base.validate_measurement = validate_measurement
base.validate_evidence = validate_evidence
base.emit = emit
base.TEST_GATES = set(base.TEST_GATES) | set(EXACT_CASES) | set(CONSUMER_PACKAGES) | set(DELIVERY_GATES) | {
    "consumer-intelligence-product-e2e"
}
base.BENCHMARK_SCHEMAS = dict(base.BENCHMARK_SCHEMAS)
base.BENCHMARK_SCHEMAS["sqlite-capacity"] = SQLITE_CAPACITY_SCHEMA


if __name__ == "__main__":
    base.main()
'''
    new = '''def install_base_overrides() -> None:
    """Install full-suite hooks only for the full qualification entry point.

    Importing this module from unit tests must not mutate the base validator.
    Otherwise a focused base-gate fixture silently acquires unrelated delivery
    gates and becomes dependent on unittest discovery order.
    """
    base.commands = commands
    base.validate_measurement = validate_measurement
    base.validate_evidence = validate_evidence
    base.emit = emit
    base.TEST_GATES = (
        set(base.TEST_GATES)
        | set(EXACT_CASES)
        | set(CONSUMER_PACKAGES)
        | set(DELIVERY_GATES)
        | {"consumer-intelligence-product-e2e"}
    )
    base.BENCHMARK_SCHEMAS = dict(base.BENCHMARK_SCHEMAS)
    base.BENCHMARK_SCHEMAS["sqlite-capacity"] = SQLITE_CAPACITY_SCHEMA


def main() -> None:
    install_base_overrides()
    base.main()


if __name__ == "__main__":
    main()
'''
    replace_once(FULL_EVIDENCE, old, new)


def refresh_lockfile() -> None:
    # Cargo metadata performs the minimal normal lock refresh required by the
    # current workspace manifests. Qualification itself remains --locked.
    run(
        "cargo",
        "metadata",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--format-version",
        "1",
        "--no-deps",
    )
    if not LOCKFILE.is_file():
        raise ValueError("Cargo metadata did not preserve the workspace lockfile")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None:
        raise ValueError("expected SHA must be lowercase hexadecimal")
    if git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("qualification repair requires the exact authored candidate")
    if git("status", "--porcelain"):
        raise ValueError("qualification repair requires a clean checkout")

    repair_consumer_audit()
    repair_evidence_import_isolation()
    refresh_lockfile()
    run("python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_cognitive_read_*.py")
    run("git", "diff", "--check")

    changed = set(git("diff", "--name-only").splitlines())
    unexpected = changed - ALLOWED_PATHS
    if unexpected:
        raise ValueError(f"qualification repair escaped reviewed paths: {sorted(unexpected)}")
    if not changed:
        print(f"COGNITIVE_READ_QUALIFICATION_REPAIR_HEAD={git('rev-parse', 'HEAD')}")
        return

    run("git", "add", "--", *sorted(changed))
    run(
        "git",
        "commit",
        "-m",
        "fix(cognitive.read): close deterministic qualification drift",
    )
    print(f"COGNITIVE_READ_QUALIFICATION_REPAIR_HEAD={git('rev-parse', 'HEAD')}")


if __name__ == "__main__":
    main()
