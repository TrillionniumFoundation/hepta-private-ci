"""Fail-closed adapter for the repository's frozen SNG-R Reader fixture.

This module intentionally delegates evidence construction to
``scripts/hepta_sngr_reader_eval.py``.  It does not copy the fixture, invent
source excerpts, load a model, score a response, or choose a Cell.  Its only
job is to make the evaluator's model-visible request boundary explicit for a
future shared-Encoder experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any


ARM_NAMES = ("none", "distractor", "withheld", "full")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEYS = frozenset({
    "gold", "canonical_gold", "gold_answer", "evaluator_gold",
    "answer_key", "correct_answer",
})


class ReaderFixtureError(ValueError):
    """Raised when the registered Reader fixture cannot be adapted safely."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_repo_path(repo_root: Path, candidate: Path) -> Path:
    try:
        root = repo_root.resolve(strict=True)
        if candidate.is_symlink():
            raise ReaderFixtureError("Reader fixture path is missing, symlinked, or outside the repository")
        path = candidate.resolve(strict=True)
    except OSError as exc:
        raise ReaderFixtureError("Reader fixture path is missing, symlinked, or outside the repository") from exc
    if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ReaderFixtureError("Reader fixture path is missing, symlinked, or outside the repository")
    return path


def load_reader_evaluator(repo_root: Path, *, script_path: Path | None = None) -> ModuleType:
    """Load the pinned evaluator module without mutating ``sys.path``.

    The module identity and four arm names are part of the contract.  A
    missing or changed evaluator is an unavailable gate, never a reason to
    fall back to synthetic evidence.
    """
    root = repo_root.resolve(strict=True)
    path = _safe_repo_path(root, script_path or (root / "scripts" / "hepta_sngr_reader_eval.py"))
    source = path.read_bytes()
    if len(source) > 256 * 1024:
        raise ReaderFixtureError("Reader evaluator is unexpectedly large")
    name = "hepta_sngr_reader_eval_bridge_" + _sha256_bytes(source)[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReaderFixtureError("unable to load the registered Reader evaluator")
    module = importlib.util.module_from_spec(spec)
    # The module is not allowed to import repository-local code by accident;
    # its own imports are stdlib-only and it receives paths explicitly below.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - exact loader errors vary by Python
        sys.modules.pop(name, None)
        raise ReaderFixtureError("registered Reader evaluator failed to load") from exc
    if getattr(module, "SCHEMA", None) != "hepta.sngr.reader-evidence-fixture.v1":
        raise ReaderFixtureError("unexpected Reader fixture schema")
    if tuple(getattr(module, "ARM_NAMES", ())) != ARM_NAMES:
        raise ReaderFixtureError("Reader arm order changed; review the bridge contract")
    if not isinstance(getattr(module, "FROZEN_CASE_SHA256", None), str) or not _SHA256.fullmatch(module.FROZEN_CASE_SHA256):
        raise ReaderFixtureError("Reader evaluator has no registered frozen manifest digest")
    for symbol in ("load_cases", "evidence_for", "construct_request"):
        if not callable(getattr(module, symbol, None)):
            raise ReaderFixtureError(f"Reader evaluator is missing {symbol}()")
    return module


def load_registered_corpus(repo_root: Path, *, manifest_path: Path | None = None) -> tuple[ModuleType, dict[str, Any]]:
    """Load and hash-check the exact registered manifest."""
    module = load_reader_evaluator(repo_root)
    root = repo_root.resolve(strict=True)
    path = _safe_repo_path(root, manifest_path or (root / "scripts" / "hepta_sngr_reader_cases.json"))
    corpus = module.load_cases(path)
    if not isinstance(corpus, dict) or corpus.get("manifest_sha256") != module.FROZEN_CASE_SHA256:
        raise ReaderFixtureError("Reader manifest is not the registered frozen case set")
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ReaderFixtureError("registered Reader corpus is empty")
    return module, corpus


def _contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_KEYS:
                return str(key)
            found = _contains_forbidden_key(child)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = _contains_forbidden_key(child)
            if found is not None:
                return found
    return None


@dataclass(frozen=True)
class ReaderRequestV1:
    """One evaluator-generated model request; gold stays outside this object."""

    task_id: str
    arm: str
    source_path: str
    state: dict[str, Any]
    questions: dict[str, Any]
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ReaderFixtureError("Reader request has no task identity")
        if self.arm not in ARM_NAMES:
            raise ReaderFixtureError("Reader request has an unsupported arm")
        if not isinstance(self.source_path, str) or not self.source_path or Path(self.source_path).is_absolute():
            raise ReaderFixtureError("Reader request has an invalid source path")
        if not _SHA256.fullmatch(self.manifest_sha256):
            raise ReaderFixtureError("Reader request has an invalid manifest digest")
        forbidden = _contains_forbidden_key((self.state, self.questions))
        if forbidden is not None:
            raise ReaderFixtureError(f"evaluator gold leaked into model request as {forbidden!r}")

    def to_model_payload(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return only the two payloads accepted by the frozen Reader API."""
        return self.state, self.questions

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "hepta.reader.request.bridge.v1",
            "task_id": self.task_id,
            "arm": self.arm,
            "source_path": self.source_path,
            "state": self.state,
            "questions": self.questions,
            "manifest_sha256": self.manifest_sha256,
        }


def build_request(module: ModuleType, corpus: dict[str, Any], task: dict[str, Any], arm: str) -> ReaderRequestV1:
    """Delegate evidence and request construction to the frozen evaluator."""
    if arm not in ARM_NAMES:
        raise ReaderFixtureError("unknown Reader arm")
    try:
        evidence, source_path = module.evidence_for(corpus, task, arm)
        state, questions = module.construct_request(corpus, task, arm)
    except Exception as exc:
        raise ReaderFixtureError(f"registered Reader evaluator rejected {arm} request") from exc
    if not isinstance(evidence, str) or not isinstance(source_path, str):
        raise ReaderFixtureError("Reader evaluator returned malformed evidence metadata")
    if not isinstance(state, dict) or not isinstance(questions, dict):
        raise ReaderFixtureError("Reader evaluator returned malformed model payload")
    if state.get("repository_source") != source_path:
        raise ReaderFixtureError("model request source identity disagrees with evaluator evidence")
    return ReaderRequestV1(
        task_id=task["id"],
        arm=arm,
        source_path=source_path,
        state=state,
        questions=questions,
        manifest_sha256=corpus["manifest_sha256"],
    )


def build_four_condition_requests(repo_root: Path, task_id: str | None = None) -> tuple[ReaderRequestV1, ...]:
    """Build one request for each frozen arm, or fail closed."""
    module, corpus = load_registered_corpus(repo_root)
    tasks = corpus["tasks"]
    if task_id is None:
        if len(tasks) != 1:
            raise ReaderFixtureError("task_id is required for a multi-case Reader corpus")
        task = tasks[0]
    else:
        matches = [item for item in tasks if isinstance(item, dict) and item.get("id") == task_id]
        if len(matches) != 1:
            raise ReaderFixtureError("requested Reader task is not uniquely registered")
        task = matches[0]
    return tuple(build_request(module, corpus, task, arm) for arm in ARM_NAMES)


__all__ = [
    "ARM_NAMES",
    "ReaderFixtureError",
    "ReaderRequestV1",
    "build_four_condition_requests",
    "build_request",
    "load_reader_evaluator",
    "load_registered_corpus",
]
