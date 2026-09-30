#!/usr/bin/env python3
"""Run the reviewed cognitive.read convergence repair with narrow shape fixes.

The authored repair intentionally rejects semantic source drift. This launcher
normalizes only the presence or absence of one terminal newline and upgrades the
nextest-version gate to parse the exact structured metadata emitted by the
pinned runner before ordinary non-force authoring commits are created.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "scripts/repair-cognitive-read-qualification.py"
EVIDENCE = ROOT / "scripts/cognitive_read_evidence.py"


def load_repair_module():
    spec = importlib.util.spec_from_file_location(
        "cognitive_read_convergence_repair",
        REPAIR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load cognitive.read convergence repair")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once_tolerating_terminal_newline(
    path: Path,
    old: str,
    new: str,
) -> None:
    body = path.read_text(encoding="utf-8")
    new_variants = {new, new.rstrip("\n")}
    if any(variant and body.count(variant) == 1 for variant in new_variants):
        return

    candidates = (
        (old, new),
        (old.rstrip("\n"), new.rstrip("\n")),
    )
    for candidate, replacement in candidates:
        if candidate and body.count(candidate) == 1:
            path.write_text(body.replace(candidate, replacement, 1), encoding="utf-8")
            return

    raise ValueError(f"convergence source shape drift: {path.relative_to(ROOT)}")


def harden_pinned_runner_validation() -> None:
    old = '''        if label == "test-runner":
            runner_lines = log.read_text(errors="replace").splitlines()
            first_line = runner_lines[0].strip() if runner_lines else ""
            version = re.escape(NEXTEST_VERSION)
            if re.fullmatch(rf"cargo-nextest {version}(?:[ \\t][^\\r\\n]*)?", first_line) is None:
                problems.append("test-runner: missing or unexpected pinned nextest version")
'''
    new = '''        if label == "test-runner":
            runner_lines = [
                line.strip()
                for line in log.read_text(errors="replace").splitlines()
                if line.strip()
            ]
            version = re.escape(NEXTEST_VERSION)
            valid_runner = len(runner_lines) == 5
            first = None
            full_hash = None
            commit_date = None
            if valid_runner:
                first = re.fullmatch(
                    rf"cargo-nextest {version} \\((?P<short>[0-9a-f]{{7,40}}) "
                    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\\)",
                    runner_lines[0],
                )
                release = re.fullmatch(rf"release: {version}", runner_lines[1])
                full_hash = re.fullmatch(
                    r"commit-hash: (?P<hash>[0-9a-f]{40})", runner_lines[2]
                )
                commit_date = re.fullmatch(
                    r"commit-date: (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})",
                    runner_lines[3],
                )
                host = re.fullmatch(
                    r"host: [A-Za-z0-9_.-]+", runner_lines[4]
                )
                valid_runner = all(
                    item is not None
                    for item in (first, release, full_hash, commit_date, host)
                )
            if valid_runner and first is not None and full_hash is not None and commit_date is not None:
                valid_runner = (
                    full_hash.group("hash").startswith(first.group("short"))
                    and commit_date.group("date") == first.group("date")
                )
            if not valid_runner:
                problems.append("test-runner: missing or unexpected pinned nextest version")
'''
    replace_once_tolerating_terminal_newline(EVIDENCE, old, new)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()

    module = load_repair_module()
    module.replace_once = replace_once_tolerating_terminal_newline
    module.SOURCE_ALLOWED_PATHS.add("scripts/cognitive_read_evidence.py")
    repair_source_files = module.repair_source_files

    def repair_source_files_with_runner_hardening() -> None:
        repair_source_files()
        harden_pinned_runner_validation()

    module.repair_source_files = repair_source_files_with_runner_hardening
    sys.argv = [str(REPAIR), "--expected-sha", args.expected_sha]
    module.main()


if __name__ == "__main__":
    main()
