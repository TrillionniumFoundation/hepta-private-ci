"""Real evaluator-owned mutation campaign over exact clock-policy source bytes."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .candidate import CandidateEnvelope, Mutation, generate_candidates
from .mutation_testing import run_mutation_testing
from .sandbox_control import SandboxCoordinator, SandboxExecutionPolicy

_SCHEMA = "hepta.control-engineering-mutation-campaign.v1"
_SOURCE = "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py"
_MUTATIONS = (
    (
        "if future_skew > policy.maximum_future_skew_ns:",
        "if future_skew < policy.maximum_future_skew_ns:",
    ),
    (
        "if now_ns >= expires_unix_ns:",
        "if now_ns < expires_unix_ns:",
    ),
    (
        "if age > policy.maximum_observation_age_ns:",
        "if age < policy.maximum_observation_age_ns:",
    ),
)


def _git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
    )
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    ).stdout.strip()


def mutation_definitions(source: str) -> tuple[Mutation, ...]:
    result = []
    for expected, replacement in _MUTATIONS:
        if source.count(expected) != 1:
            raise ValueError("mutation_campaign_source_drift")
        result.append(
            Mutation(
                "replace_text",
                "subject/clock_policy.py",
                expected,
                replacement,
            )
        )
    return tuple(result)


def build_mutation_campaign(repository: str | Path) -> dict[str, object]:
    repository_path = Path(repository).resolve()
    source_path = repository_path / _SOURCE
    source = source_path.read_text(encoding="utf-8")
    source_blob = _git(repository_path, "rev-parse", f"HEAD:{_SOURCE}")
    if _git(repository_path, "hash-object", str(source_path)) != source_blob:
        raise ValueError("mutation_campaign_checkout_drift")
    mutations = mutation_definitions(source)

    with tempfile.TemporaryDirectory(prefix="hepta-mutation-campaign-") as temporary:
        root = Path(temporary)
        (root / "subject").mkdir()
        (root / "oracle").mkdir()
        (root / "subject/__init__.py").write_text("", encoding="utf-8")
        (root / "subject/control_plane.py").write_text(
            "class EngineeringError(ValueError):\n    pass\n",
            encoding="utf-8",
        )
        (root / "subject/clock_policy.py").write_text(source, encoding="utf-8")
        (root / "oracle/run_checks.py").write_text(
            """from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from subject.clock_policy import ClockPolicy, EngineeringError, validate_signed_window
policy = ClockPolicy(maximum_future_skew_ns=5, maximum_observation_age_ns=20, minimum_validity_ns=1, maximum_validity_ns=100)
validate_signed_window(100, 150, now_ns=100, policy=policy)
for args, expected in [
    ((106, 150, 100), 'receipt_from_future'),
    ((100, 110, 110), 'receipt_stale'),
    ((100, 150, 121), 'receipt_too_old'),
]:
    observed, expires, now = args
    try:
        validate_signed_window(observed, expires, now_ns=now, policy=policy)
    except EngineeringError as error:
        assert str(error) == expected, (str(error), expected)
    else:
        raise AssertionError(expected)
""",
            encoding="utf-8",
        )
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "Mutation qualification")
        _git(root, "config", "user.email", "mutation@example.invalid")
        _git(root, "config", "commit.gpgsign", "false")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "exact source mutation subject")
        base = _git(root, "rev-parse", "HEAD")
        envelope = CandidateEnvelope(
            "control-engineering-mutation-campaign",
            base,
            ("subject",),
            maximum_candidates=len(mutations) + 1,
            maximum_changed_files=1,
            wall_time_seconds=30,
            memory_bytes=512 * 1024 * 1024,
            processes=32,
            require_network_isolation=True,
        )
        candidates = generate_candidates(envelope, mutations)
        coordinator = SandboxCoordinator(
            SandboxExecutionPolicy(maximum_parallel_sandboxes=1, infrastructure_retries=0)
        )
        receipt = run_mutation_testing(
            str(root),
            envelope,
            candidates[0],
            candidates[1:],
            ((sys.executable, "-I", "oracle/run_checks.py"),),
            coordinator=coordinator,
        )
    value: dict[str, object] = {
        "schema": _SCHEMA,
        "sourcePath": _SOURCE,
        "sourceBlob": source_blob,
        "sourceSha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "mutants": len(mutations),
        "receipt": asdict(receipt),
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    value["campaignDigest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        value = build_mutation_campaign(args.repository)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
