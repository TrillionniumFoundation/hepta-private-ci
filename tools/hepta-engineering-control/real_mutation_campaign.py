#!/usr/bin/env python3
"""Run a real strong-sandbox mutation campaign over capacity_policy.py."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from control_engineering_v2.candidate import CandidateEnvelope, Mutation, generate_candidates
from control_engineering_v2.mutation_testing import run_mutation_testing
from control_engineering_v2.sandbox_control import SandboxCoordinator, SandboxExecutionPolicy


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def build_campaign(repository: Path, output: Path) -> dict[str, object]:
    target = (
        repository
        / "tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py"
    )
    source = target.read_text(encoding="utf-8")
    source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    with tempfile.TemporaryDirectory(prefix="hepta-real-mutation-") as temporary:
        root = Path(temporary)
        package = root / "src/control_engineering_v2"
        tests = root / "tests"
        package.mkdir(parents=True)
        tests.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "capacity_policy.py").write_text(source, encoding="utf-8")
        (package / "control_plane.py").write_text(
            "from __future__ import annotations\n"
            "import hashlib,json\n"
            "class EngineeringError(ValueError):\n    pass\n"
            "def checked_id(value,label='id'):\n"
            "    if not isinstance(value,str) or not value: raise EngineeringError('invalid_'+label)\n"
            "    return value\n"
            "def semantic_digest(value):\n"
            "    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()\n",
            encoding="utf-8",
        )
        (tests / "test_capacity.py").write_text(
            "from pathlib import Path\nimport sys,unittest\n"
            "sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))\n"
            "from control_engineering_v2.capacity_policy import *\n"
            "class T(unittest.TestCase):\n"
            "  def policy(self): return SQLiteCapacityPolicy('p',1000,100,10000,100,100,50,500,80)\n"
            "  def test_exact_hard_limit_is_allowed(self):\n"
            "    d=evaluate_sqlite_capacity(self.policy(),SQLiteCapacityObservation(1000,1,1,1,1,1,1)); self.assertTrue(d.within_hard_limits)\n"
            "  def test_exact_warning_threshold_migrates_without_hard_failure(self):\n"
            "    d=evaluate_sqlite_capacity(self.policy(),SQLiteCapacityObservation(800,1,1,1,1,1,1)); self.assertTrue(d.within_hard_limits); self.assertTrue(d.migration_required)\n"
            "  def test_hard_limit_fails(self):\n"
            "    d=evaluate_sqlite_capacity(self.policy(),SQLiteCapacityObservation(1001,1,1,1,1,1,1)); self.assertFalse(d.within_hard_limits); self.assertTrue(d.migration_required)\n"
            "if __name__=='__main__': unittest.main()\n",
            encoding="utf-8",
        )
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "Hepta Mutation Qualification")
        _git(root, "config", "user.email", "mutation@invalid.example")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "mutation fixture bound to source")
        base = _git(root, "rev-parse", "HEAD")
        path = "src/control_engineering_v2/capacity_policy.py"
        mutations = (
            Mutation("replace_text", path, "actual > maximum", "actual >= maximum"),
            Mutation(
                "replace_text",
                path,
                "actual * 100 >= maximum * policy.migrate_at_utilization_percent",
                "actual * 100 > maximum * policy.migrate_at_utilization_percent",
            ),
            Mutation(
                "replace_text",
                path,
                "migration_required=bool(hard or warning)",
                "migration_required=bool(hard and warning)",
            ),
            Mutation(
                "replace_text",
                path,
                "within_hard_limits=not hard",
                "within_hard_limits=not warning",
            ),
        )
        envelope = CandidateEnvelope(
            "real-capacity-policy-campaign",
            base,
            (path,),
            protected_paths=(),
            maximum_candidates=8,
            maximum_changed_files=1,
            wall_time_seconds=60,
            memory_bytes=512 * 1024 * 1024,
            processes=64,
            require_network_isolation=True,
        )
        candidates = generate_candidates(envelope, mutations)
        receipt = run_mutation_testing(
            str(root),
            envelope,
            candidates[0],
            candidates[1:],
            ((sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests"),),
            SandboxCoordinator(
                SandboxExecutionPolicy(maximum_parallel_sandboxes=1, infrastructure_retries=0)
            ),
        )
        result: dict[str, object] = {
            "schema": "hepta.control-engineering-real-mutation-campaign.v1",
            "targetPath": str(target.relative_to(repository)),
            "targetSha256": source_digest,
            "mutants": len(receipt.mutant_candidate_ids),
            "killed": len(receipt.killed_mutant_ids),
            "survived": len(receipt.surviving_mutant_ids),
            "scorePercent": round(
                100.0 * len(receipt.killed_mutant_ids) / len(receipt.mutant_candidate_ids),
                2,
            ),
            "receipt": asdict(receipt),
        }
        if receipt.passed is not True:
            raise RuntimeError("real mutation campaign has surviving mutants")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_campaign(args.repository.resolve(), args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
