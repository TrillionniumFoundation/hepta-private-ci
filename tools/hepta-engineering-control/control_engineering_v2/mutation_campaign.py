"""Run an evaluator-owned mutation campaign against real control.engineering source.

The campaign archives the exact committed source without ``.git``, changes one
security-relevant expression per mutant, and runs the corresponding unchanged
unit-test oracle. It is qualification evidence only and grants no authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time

MAX_OUTPUT_BYTES = 1_048_576


@dataclass(frozen=True)
class SourceMutant:
    mutant_id: str
    path: str
    expected_text: str
    replacement_text: str
    test_file: str


MUTANTS = (
    SourceMutant(
        "clock-future-skew-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py",
        "if observed_unix_ns > now_unix_ns + policy.maximum_future_skew_ns:\n        raise EngineeringError(error_code)",
        "if False:\n        raise EngineeringError(error_code)",
        "tools/hepta-engineering-control/test_clock_policy.py",
    ),
    SourceMutant(
        "capacity-hard-limit-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py",
        "write_admitted=not hard,",
        "write_admitted=True,",
        "tools/hepta-engineering-control/test_capacity_policy.py",
    ),
    SourceMutant(
        "fixture-provider-independence-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/production_providers.py",
        "if value.fixture or not value.external_to_repository:\n        raise EngineeringError(\"external_provider_not_independent\")",
        "if False:\n        raise EngineeringError(\"external_provider_not_independent\")",
        "tools/hepta-engineering-control/test_production_providers.py",
    ),
    SourceMutant(
        "production-authority-default-escalation",
        "tools/hepta-engineering-control/control_engineering_v2/production_providers.py",
        "production_implementation: bool = False",
        "production_implementation: bool = True",
        "tools/hepta-engineering-control/test_production_providers.py",
    ),
    SourceMutant(
        "active-worker-key-rotation-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/worker_registration.py",
        "if active_claims and profile_changed:\n            raise EngineeringError(\"worker_registration_rotation_active_claims\")",
        "if False:\n            raise EngineeringError(\"worker_registration_rotation_active_claims\")",
        "tools/hepta-engineering-control/test_worker_registration_renewal.py",
    ),
    SourceMutant(
        "backup-overwrite-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/recovery_rehearsal.py",
        "if target.exists():\n        raise EngineeringError(\"recovery_rehearsal_backup_exists\")",
        "if False:\n        raise EngineeringError(\"recovery_rehearsal_backup_exists\")",
        "tools/hepta-engineering-control/test_recovery_rehearsal.py",
    ),
    SourceMutant(
        "startup-reconciliation-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py",
        "if not self._startup_reconciled:\n            raise EngineeringError(\"product_startup_reconciliation_required\")",
        "if False:\n            raise EngineeringError(\"product_startup_reconciliation_required\")",
        "tools/hepta-engineering-control/test_product_runtime.py",
    ),
    SourceMutant(
        "audit-suffix-integrity-bypass",
        "tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py",
        "if (\n            str(row[\"previous_digest\"]) != previous\n            or str(row[\"event_digest\"]) != digest\n            or str(row[\"event_id\"]) != digest[:32]\n        ):\n            raise EngineeringError(\"audit_chain_broken\")",
        "if False:\n            raise EngineeringError(\"audit_chain_broken\")",
        "tools/hepta-engineering-control/test_audit_checkpoint.py",
    ),
)


def _git(root: Path, *args: str, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        timeout=120,
    )
    return result.stdout


def _archive(root: Path) -> bytes:
    return bytes(
        _git(
            root,
            "archive",
            "--format=tar",
            "HEAD",
            "tools/hepta-engineering-control",
            binary=True,
        )
    )


def _extract(archive: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination)


def _run_test(root: Path, test_file: str, *, timeout_seconds: int) -> dict[str, object]:
    home = root / ".quality-home"
    home.mkdir(mode=0o700, exist_ok=True)
    started = time.monotonic_ns()
    result = subprocess.run(
        [sys.executable, "-B", test_file],
        cwd=root,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "PYTHONPATH": str(root / "tools/hepta-engineering-control"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_seconds,
        check=False,
    )
    output = bytes(result.stdout)
    return {
        "exitCode": int(result.returncode),
        "durationMillis": round((time.monotonic_ns() - started) / 1_000_000, 3),
        "outputBytes": len(output),
        "outputTruncated": len(output) > MAX_OUTPUT_BYTES,
        "outputDigest": hashlib.sha256(output).hexdigest(),
        "outputTail": output[-min(len(output), 4096):].decode("utf-8", "replace"),
    }


def run_campaign(
    repository: str | Path,
    *,
    minimum_score: float = 100.0,
    timeout_seconds: int = 180,
) -> dict[str, object]:
    root = Path(repository).resolve()
    if not 0 <= minimum_score <= 100:
        raise ValueError("mutation_minimum_score")
    if not 1 <= timeout_seconds <= 1800:
        raise ValueError("mutation_timeout")
    if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("mutation_repository_not_clean")
    source_commit = str(_git(root, "rev-parse", "HEAD")).strip()
    source_tree = str(_git(root, "rev-parse", "HEAD^{tree}")).strip()
    archive = _archive(root)
    unique_tests = tuple(dict.fromkeys(mutant.test_file for mutant in MUTANTS))

    baseline_results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="hepta-mutation-baseline-") as temporary:
        baseline = Path(temporary)
        _extract(archive, baseline)
        for test_file in unique_tests:
            result = _run_test(baseline, test_file, timeout_seconds=timeout_seconds)
            baseline_results.append({"testFile": test_file, **result})
            if result["exitCode"] != 0:
                raise RuntimeError("mutation_baseline_failed:" + test_file)

    executions: list[dict[str, object]] = []
    killed = 0
    for mutant in MUTANTS:
        with tempfile.TemporaryDirectory(prefix="hepta-mutant-") as temporary:
            candidate = Path(temporary)
            _extract(archive, candidate)
            path = candidate / mutant.path
            text = path.read_text(encoding="utf-8")
            occurrences = text.count(mutant.expected_text)
            if occurrences != 1:
                raise RuntimeError(
                    f"mutation_source_drift:{mutant.mutant_id}:{occurrences}"
                )
            path.write_text(
                text.replace(mutant.expected_text, mutant.replacement_text, 1),
                encoding="utf-8",
            )
            result = _run_test(
                candidate,
                mutant.test_file,
                timeout_seconds=timeout_seconds,
            )
            was_killed = result["exitCode"] != 0
            killed += int(was_killed)
            executions.append(
                {
                    "mutantId": mutant.mutant_id,
                    "path": mutant.path,
                    "testFile": mutant.test_file,
                    "killed": was_killed,
                    **result,
                }
            )

    total = len(MUTANTS)
    score = round(100.0 * killed / total, 3)
    passed = score >= minimum_score
    report = {
        "schema": "hepta.control-engineering-real-mutation-campaign.v1",
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "mutants": total,
        "killed": killed,
        "survived": total - killed,
        "scorePercent": score,
        "minimumScorePercent": minimum_score,
        "baseline": baseline_results,
        "executions": executions,
        "passed": passed,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["reportDigest"] = hashlib.sha256(canonical).hexdigest()
    if not passed:
        survivors = [row["mutantId"] for row in executions if not row["killed"]]
        raise RuntimeError("mutation_score_failed:" + ",".join(survivors))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--minimum-score", type=float, default=100.0)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        report = run_campaign(
            args.repository,
            minimum_score=args.minimum_score,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(
            json.dumps(
                {
                    "schema": "hepta.control-engineering-real-mutation-campaign.v1",
                    "status": "rejected",
                    "error": str(error),
                    "authorityGranted": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "passed", "scorePercent": report["scorePercent"], "reportDigest": report["reportDigest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
