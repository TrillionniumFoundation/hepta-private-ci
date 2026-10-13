"""Experiment 2: four-arm Reader capability diagnosis.

The four matched arms are:

* ``no_evidence``: no retrieved context;
* ``ordinary_retrieval``: the normal retrieval result;
* ``sufficient_evidence``: an independently prepared sufficient-evidence window;
* ``key_premise_removed``: the same sufficient window with the registered key
  premise removed.

The default Reader is deterministic and intentionally simple.  It exists to
exercise the data/receipt/scoring contract in CI; it is not a pretrained model.
A production or external model must implement ``ReaderBackend.answer`` and must
never see the gold answer or key-premise annotation.

Raw answers are appended before targets are read for scoring.  This preserves
the diagnostic boundary: evidence conditions are inputs, labels are evaluator
inputs, and a report never acts as model selection or promotion authority.
"""

from dataclasses import asdict, dataclass
import argparse
import os
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Protocol, Sequence

SCHEMA = "hepta.experiment2-reader-four-arm.v1"
RAW_SCHEMA = "hepta.reader-four-arm-raw.v1"
ARMS = ("no_evidence", "ordinary_retrieval", "sufficient_evidence", "key_premise_removed")
MAX_CASES = 4096
MAX_EVIDENCE = 64


class ValidationError(ValueError):
    pass


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def token_f1(answer: str, target: str) -> float:
    """Order-insensitive diagnostic F1; this is not semantic entailment."""
    a, b = Counter(_tokens(answer)), Counter(_tokens(target))
    if not a or not b:
        return float(not a and not b)
    overlap = sum((a & b).values())
    return 2.0 * overlap / (sum(a.values()) + sum(b.values()))


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    text: str
    kind: str = "ordinary"
    is_key_premise: bool = False

    def validate(self) -> None:
        if not self.evidence_id or not self.text.strip():
            raise ValidationError("evidence_id/text required")
        if len(self.text.encode("utf-8")) > 64 * 1024:
            raise ValidationError("evidence item too large")


@dataclass(frozen=True)
class ReaderEvidence:
    """Evidence view exposed to a Reader; evaluator annotations are removed."""

    evidence_id: str
    text: str
    kind: str = "ordinary"


@dataclass(frozen=True)
class ReaderCase:
    question_id: str
    question: str
    gold_answer: str
    ordinary_evidence: tuple[Evidence, ...]
    sufficient_evidence: tuple[Evidence, ...]
    family: str = "general"
    weight: float = 1.0

    def validate(self) -> None:
        if not self.question_id or not self.question.strip() or not self.gold_answer.strip():
            raise ValidationError("question_id/question/gold_answer required")
        if not self.family:
            raise ValidationError("family required")
        if type(self.weight) not in (int, float) or not math.isfinite(float(self.weight)) or not 0.0 <= self.weight <= 1000.0:
            raise ValidationError("weight outside bounded range")
        if len(self.ordinary_evidence) > MAX_EVIDENCE or len(self.sufficient_evidence) > MAX_EVIDENCE:
            raise ValidationError("too many evidence items")
        for item in self.ordinary_evidence + self.sufficient_evidence:
            item.validate()
        sufficient_ids = {x.evidence_id for x in self.sufficient_evidence}
        if len(sufficient_ids) != len(self.sufficient_evidence):
            raise ValidationError("duplicate sufficient evidence id")
        if not any(x.is_key_premise for x in self.sufficient_evidence):
            raise ValidationError("sufficient evidence needs a registered key premise")


class ReaderBackend(Protocol):
    """External Reader contract. Gold answer and annotations are never passed."""

    identity: str
    profile: str
    benchmark_mode: str

    def answer(self, question: str, evidence: Sequence[ReaderEvidence]) -> str:
        ...


class DeterministicReader:
    """Fixture Reader: echoes a supplied evidence span without evaluator labels."""

    identity = "deterministic-fixture-reader"
    profile = "keyword-v1"
    benchmark_mode = "synthetic_fixture"

    def answer(self, question: str, evidence: Sequence[ReaderEvidence]) -> str:
        del question
        if evidence:
            return evidence[0].text
        return "Insufficient evidence."


def _reader_request_digest(question: str, evidence: Sequence[ReaderEvidence]) -> str:
    """Digest the exact public Reader input, without arm or evaluator labels."""
    return _digest(
        {
            "question": question,
            "evidence": [asdict(item) for item in evidence],
        }
    )


class JsonlReaderBackend:
    """Replay answers sealed by an external Reader executor.

    Rows are keyed by the public input digest. This gives a real executor a
    deterministic handoff while keeping arm names, gold answers and evaluator
    annotations outside its input contract.
    """

    identity = "external-jsonl-reader"
    profile = "sealed-answer-v1"
    benchmark_mode = "external_observation"

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._answers: dict[str, str] = {}
        for item in rows:
            if not isinstance(item, dict):
                raise ValidationError("external Reader observation must be an object")
            request_digest = item.get("request_digest")
            answer = item.get("answer")
            if not isinstance(request_digest, str) or len(request_digest) != 64:
                raise ValidationError("external Reader request_digest must be sha256 hex")
            try:
                int(request_digest, 16)
            except ValueError as error:
                raise ValidationError("external Reader request_digest must be sha256 hex") from error
            if not isinstance(answer, str) or not answer.strip():
                raise ValidationError("external Reader answer must be nonempty text")
            if request_digest in self._answers:
                raise ValidationError("duplicate external Reader request_digest")
            self._answers[request_digest] = answer

    @classmethod
    def from_path(cls, path: Path) -> "JsonlReaderBackend":
        if not path.is_file():
            raise ValidationError(f"external Reader observation file does not exist: {path}")
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValidationError(f"invalid external Reader JSONL at line {line_number}") from error
        if not rows:
            raise ValidationError("external Reader observation file is empty")
        return cls(rows)

    def answer(self, question: str, evidence: Sequence[ReaderEvidence]) -> str:
        request_digest = _reader_request_digest(question, evidence)
        try:
            return self._answers[request_digest]
        except KeyError as error:
            raise ValidationError(f"missing external Reader answer for {request_digest}") from error


def default_cases() -> tuple[ReaderCase, ...]:
    rows = (
        ("q-001", "Which city hosted the launch?", "Kyoto", "Kyoto hosted the launch.", "Kyoto", "ordinary"),
        ("q-002", "Who approved the change?", "Mika", "Mika approved the change.", "Mika", "procedural"),
        ("q-003", "When did the migration finish?", "2024-03-12", "The migration finished on 2024-03-12.", "2024-03-12", "temporal"),
        ("q-004", "Which codec was selected?", "Opus", "The selected codec was Opus.", "Opus", "technical"),
        ("q-005", "What was the rollback trigger?", "error rate", "Rollback triggered when error rate rose.", "error rate", "operational"),
        ("q-006", "Which branch contains the fix?", "recovery", "The fix is on the recovery branch.", "recovery", "code"),
        ("q-007", "What is the retention window?", "30 days", "The retention window is 30 days.", "30 days", "policy"),
        ("q-008", "Who owns the snapshot?", "Iris", "Iris owns the snapshot.", "Iris", "ownership"),
    )
    cases = []
    for qid, question, answer, ordinary, sufficient, family in rows:
        cases.append(
            ReaderCase(
                qid,
                question,
                answer,
                (Evidence(f"{qid}-ordinary", ordinary),),
                (Evidence(f"{qid}-key", answer, "reviewed-literal-span", True),),
                family,
            )
        )
    return tuple(cases)


def _validate_cases(cases: Sequence[ReaderCase]) -> tuple[ReaderCase, ...]:
    if not 1 <= len(cases) <= MAX_CASES:
        raise ValidationError("case set outside bounded range")
    result = tuple(cases)
    ids = set()
    for case in result:
        case.validate()
        if case.question_id in ids:
            raise ValidationError("duplicate question_id")
        ids.add(case.question_id)
    return result


def _arm_evidence(case: ReaderCase, arm: str) -> tuple[Evidence, ...]:
    if arm == "no_evidence":
        return ()
    if arm == "ordinary_retrieval":
        return case.ordinary_evidence
    if arm == "sufficient_evidence":
        return case.sufficient_evidence
    if arm == "key_premise_removed":
        return tuple(x for x in case.sufficient_evidence if not x.is_key_premise)
    raise ValidationError(f"unknown Reader arm: {arm}")


def _reader_evidence(evidence: Sequence[Evidence]) -> tuple[ReaderEvidence, ...]:
    """Strip key-premise labels before invoking the Reader backend."""
    return tuple(ReaderEvidence(item.evidence_id, item.text, item.kind) for item in evidence)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> str:
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_diagnostic(
    cases: Sequence[ReaderCase],
    *,
    backend: ReaderBackend | None = None,
    output_dir: Path | None = None,
    seed: int = 20261013,
) -> dict[str, Any]:
    """Run all four arms, seal raw rows, then score against evaluator labels."""
    cases = _validate_cases(cases)
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValidationError("seed outside bounded range")
    backend = backend or DeterministicReader()
    if not getattr(backend, "identity", "") or not getattr(backend, "profile", ""):
        raise ValidationError("Reader backend identity/profile required")
    raw_rows: list[dict[str, Any]] = []
    for case in cases:
        for arm in ARMS:
            evidence = _arm_evidence(case, arm)
            started = time.perf_counter()
            row: dict[str, Any] = dict(
                schema=RAW_SCHEMA,
                question_id=case.question_id,
                family=case.family,
                arm=arm,
                evidence_ids=[x.evidence_id for x in evidence],
                evidence_count=len(evidence),
                request_digest=_digest(
                    {
                        "question_id": case.question_id,
                        "question": case.question,
                        "arm": arm,
                        "evidence": [asdict(x) for x in evidence],
                    }
                ),
                reader_identity=backend.identity,
                reader_profile=backend.profile,
                diagnostic_only=True,
                status="failed",
            )
            try:
                reader_evidence = _reader_evidence(evidence)
                row["reader_request_digest"] = _reader_request_digest(case.question, reader_evidence)
                answer = backend.answer(case.question, reader_evidence)
                if not isinstance(answer, str) or not answer.strip():
                    raise ValidationError("Reader returned an empty answer")
                row.update(status="succeeded", answer=answer, answer_digest=_digest(answer))
            except Exception as error:  # each arm is isolated; a failure is a row
                row.update(error_type=type(error).__name__, error=str(error)[:1024])
            row["elapsed_seconds"] = time.perf_counter() - started
            raw_rows.append(row)
    expected = len(cases) * len(ARMS)
    if len(raw_rows) != expected:
        raise ValidationError("incomplete raw Reader execution")
    raw_digest = _digest(raw_rows)
    raw_path = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=False)
        raw_path = output_dir / "raw-answers.jsonl"
        _write_jsonl(raw_path, raw_rows)

    # Gold answers are touched only after every raw attempt exists and is sealed.
    by_key = {(r["question_id"], r["arm"]): r for r in raw_rows}
    scored_rows: list[dict[str, Any]] = []
    for case in cases:
        for arm in ARMS:
            row = by_key[(case.question_id, arm)]
            f1 = token_f1(row.get("answer", ""), case.gold_answer) if row["status"] == "succeeded" else None
            scored_rows.append(
                dict(
                    question_id=case.question_id,
                    family=case.family,
                    arm=arm,
                    status=row["status"],
                    diagnostic_f1=f1,
                    exact=(f1 == 1.0 if f1 is not None else None),
                    evidence_count=row["evidence_count"],
                    key_premise_present=arm == "sufficient_evidence",
                )
            )
    by_case = {(r["question_id"], r["arm"]): r for r in scored_rows}
    report_arms: dict[str, Any] = {}
    for arm in ARMS:
        rows = [r for r in scored_rows if r["arm"] == arm]
        values = [r["diagnostic_f1"] for r in rows if r["diagnostic_f1"] is not None]
        report_arms[arm] = dict(
            planned=len(rows),
            succeeded=sum(r["status"] == "succeeded" for r in rows),
            failed=sum(r["status"] == "failed" for r in rows),
            mean_diagnostic_f1=(math.fsum(values) / len(values) if values else None),
            exact_count=sum(r["exact"] is True for r in rows),
            evaluated_count=len(values),
        )
    attribution: list[dict[str, Any]] = []
    for case in cases:
        row = {arm: by_case[(case.question_id, arm)] for arm in ARMS}
        sufficient = row["sufficient_evidence"]["diagnostic_f1"]
        ordinary = row["ordinary_retrieval"]["diagnostic_f1"]
        none = row["no_evidence"]["diagnostic_f1"]
        removed = row["key_premise_removed"]["diagnostic_f1"]
        if sufficient is None or sufficient < 0.5:
            diagnosis = "reader_or_prompt_or_task"
        elif ordinary is None or ordinary < sufficient - 0.05:
            diagnosis = "retrieval_or_head"
        elif removed is not None and removed >= sufficient - 0.05:
            diagnosis = "key_premise_not_necessary_or_control_leak"
        elif none is not None and none >= sufficient - 0.05:
            diagnosis = "evidence_not_used_or_task_memorized"
        else:
            diagnosis = "reader_and_retrieval_both_plausible"
        attribution.append(
            dict(
                question_id=case.question_id,
                family=case.family,
                sufficient_f1=sufficient,
                ordinary_f1=ordinary,
                no_evidence_f1=none,
                key_premise_removed_f1=removed,
                diagnosis=diagnosis,
            )
        )
    report = dict(
        schema=SCHEMA,
        arms=list(ARMS),
        reader_identity=backend.identity,
        reader_profile=backend.profile,
        benchmark_mode=getattr(backend, "benchmark_mode", type(backend).__name__),
        seed=seed,
        planned_cases=len(cases),
        planned_attempts=expected,
        raw_answers_digest=raw_digest,
        raw_answers_path=str(raw_path) if raw_path else None,
        arms_report=report_arms,
        per_question=attribution,
        production_accepted=False,
        model_selection_authority=False,
        semantic_entailment_independently_verified=False,
        note=(
            "Token F1 is a diagnostic score; sufficient evidence is a registered control, "
            "not an independent semantic oracle. The deterministic fixture cannot establish "
            "that a real retrieval system failed."
        ),
    )
    if output_dir is not None:
        with (output_dir / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
            stream.write("\n")
    return report


def _evidence_from_mapping(value: dict[str, Any]) -> Evidence:
    return Evidence(
        evidence_id=str(value.get("evidence_id", "")),
        text=str(value.get("text", "")),
        kind=str(value.get("kind", "ordinary")),
        is_key_premise=bool(value.get("is_key_premise", False)),
    )


def load_cases(path: Path) -> tuple[ReaderCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValidationError("cases JSON must be a list or {cases: [...]}")
    cases = []
    for item in values:
        if not isinstance(item, dict):
            raise ValidationError("case must be an object")
        cases.append(
            ReaderCase(
                question_id=str(item.get("question_id", "")),
                question=str(item.get("question", "")),
                gold_answer=str(item.get("gold_answer", "")),
                ordinary_evidence=tuple(_evidence_from_mapping(x) for x in item.get("ordinary_evidence", [])),
                sufficient_evidence=tuple(_evidence_from_mapping(x) for x in item.get("sufficient_evidence", [])),
                family=str(item.get("family", "general")),
                weight=item.get("weight", 1.0),
            )
        )
    return _validate_cases(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, help="JSON case list; default is deterministic local cases")
    parser.add_argument("--answers", type=Path, help="sealed external Reader answers in JSONL")
    parser.add_argument("--output-dir", type=Path, required=True, help="new output directory")
    parser.add_argument("--seed", type=int, default=20261013)
    args = parser.parse_args(argv)
    cases = load_cases(args.cases) if args.cases else default_cases()
    backend = JsonlReaderBackend.from_path(args.answers) if args.answers else None
    run_diagnostic(cases, backend=backend, output_dir=args.output_dir, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
