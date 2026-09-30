"""Run a retained strong-sandbox mutation campaign over real package bytes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from .candidate import CandidateEnvelope, Mutation, generate_candidates
from .git_security import run_git
from .mutation_testing import run_mutation_testing
from .sandbox_control import SandboxCoordinator, SandboxExecutionPolicy

_SCHEMA = "hepta.control-engineering-mutation-campaign.v1"


def _git(root: Path, *args: str) -> str:
    # Subject preparation happens before the sandbox. Ambient repository
    # redirection, hooks, signing helpers and templates must never execute here.
    return run_git(
        root,
        "-c", "core.hooksPath=" + os.devnull,
        "-c", "commit.gpgSign=false",
        "-c", "init.templateDir=",
        *args,
    )


def build_mutation_campaign(repository: str | Path) -> dict[str, object]:
    source_root = Path(repository).resolve()
    package = source_root / "tools/hepta-engineering-control/control_engineering_v2"
    tests = source_root / "tools/hepta-engineering-control"
    required = (
        package / "time_policy.py",
        package / "capacity_policy.py",
        package / "deployment_evidence.py",
        tests / "test_control_engineering_extensions.py",
        tests / "test_deployment_evidence.py",
    )
    if any(not path.is_file() for path in required):
        raise ValueError("mutation_campaign_source_missing")
    # copytree follows symlinks by default. Keep evaluator preparation from
    # copying host files outside the package or blocking on special files.
    for path in (source_root / "tools", tests, package, *required):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("mutation_campaign_source_not_regular")
    for path in package.rglob("*"):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("mutation_campaign_source_not_regular")
    with tempfile.TemporaryDirectory(prefix="hepta-control-mutation-") as temporary:
        root = Path(temporary)
        shutil.copytree(
            package,
            root / "subject/control_engineering_v2",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            symlinks=True,
        )
        (root / "tests").mkdir()
        shutil.copy2(
            tests / "test_control_engineering_extensions.py",
            root / "tests/test_control_engineering_extensions.py",
            follow_symlinks=False,
        )
        shutil.copy2(
            tests / "test_deployment_evidence.py",
            root / "tests/test_deployment_evidence.py",
            follow_symlinks=False,
        )
        if any(path.is_symlink() for path in root.rglob("*")):
            raise ValueError("mutation_campaign_source_not_regular")
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "Hepta Mutation Evaluator")
        _git(root, "config", "user.email", "mutation@example.invalid")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "exact evaluator subject")
        base = _git(root, "rev-parse", "HEAD")
        envelope = CandidateEnvelope(
            "control-engineering-real-source-mutation",
            base,
            ("subject",),
            wall_time_seconds=120,
            memory_bytes=1024 * 1024 * 1024,
            processes=128,
            require_network_isolation=True,
        )
        mutations = (
            Mutation(
                "replace_text",
                "subject/control_engineering_v2/time_policy.py",
                "        return self.wall\n",
                "        return self.monotonic\n",
            ),
            Mutation(
                "replace_text",
                "subject/control_engineering_v2/time_policy.py",
                "    if observed_unix_ns > now_unix_ns + policy.max_future_skew_ns:\n",
                "    if observed_unix_ns >= now_unix_ns + policy.max_future_skew_ns:\n",
            ),
            Mutation(
                "replace_text",
                "subject/control_engineering_v2/capacity_policy.py",
                "    if database_bytes > policy.maximum_database_bytes:\n",
                "    if database_bytes < policy.maximum_database_bytes:\n",
            ),
            Mutation(
                "replace_text",
                "subject/control_engineering_v2/deployment_evidence.py",
                "    if len(identities) != 4:\n",
                "    if len(identities) == 4:\n",
            ),
        )
        candidates = generate_candidates(envelope, mutations)
        baseline = candidates[0]
        mutants = candidates[1:]
        test_program = (
            "import sys,unittest;"
            "sys.path.insert(0,'subject');"
            "suite=unittest.defaultTestLoader.discover('tests');"
            "result=unittest.TextTestRunner(verbosity=2).run(suite);"
            "raise SystemExit(0 if result.wasSuccessful() else 1)"
        )
        receipt = run_mutation_testing(
            str(root),
            envelope,
            baseline,
            mutants,
            ((sys.executable, "-I", "-B", "-c", test_program),),
            SandboxCoordinator(
                SandboxExecutionPolicy(
                    maximum_parallel_sandboxes=1,
                    infrastructure_retries=0,
                )
            ),
        )
        result = asdict(receipt)
        result.update(
            {
                "schema": _SCHEMA,
                "mutants": len(mutants),
                "killed": len(receipt.killed_mutant_ids),
                "mutationScore": (
                    len(receipt.killed_mutant_ids) / len(mutants)
                ),
                "productionAccepted": False,
                "releaseAuthority": False,
            }
        )
        if not receipt.passed:
            raise RuntimeError("mutation_campaign_survivors")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_mutation_campaign(args.repository)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": _SCHEMA, "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
