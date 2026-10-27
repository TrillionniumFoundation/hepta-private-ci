"""Formal fitting is admitted only under the verified project source freeze."""

from pathlib import Path
import re


PROJECT = Path(__file__).resolve().parents[1]
REQUIRED_TRAINING_SOURCES = (
    "train_routing.py", "read_router.py", "tests/test_router.py", "V5B_PREDECLARATION.md",
    "v5/__init__.py", "v5/artifacts.py", "v5/config.py", "v5/contracts.py",
    "v5/corpus.py", "v5/development_language.py", "v5/features.py", "v5/metrics.py",
    "v5/router.py", "v5/selection_language.py", "v5/training.py", "v5/training_language.py",
    "v5/training_guard.py", "v5/joint_cases.py",
)


def verify_training_freeze(source_commit):
    # The verifier checks hashes only. Never call its held materializer here.
    from .joint_cases import verify_freeze

    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("formal training source must be a full commit SHA")
    frozen, identity = verify_freeze(PROJECT / "FREEZE.json")
    if frozen.get("source_commit") != source_commit:
        raise ValueError("formal training source commit differs from the project freeze")
    missing = sorted(set(REQUIRED_TRAINING_SOURCES) - set(frozen["source_files"]))
    if missing:
        raise ValueError("formal freeze omits required training sources: " + ", ".join(missing))
    return frozen, identity
