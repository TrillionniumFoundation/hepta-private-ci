"""No-evidence Reader diagnostic with the SAME frozen Reader and prompt contract.

Run only after all preregistered policy answers and independent of their
training/selection outputs. No targets or support annotations enter this
generation function. A failed Reader call never silently vanishes from the
planned denominator. This control is not a trained Cell or a gold oracle.
"""

from collections import defaultdict
from dataclasses import asdict
import math
import re

from native import digest


PHASES = ("select", "retention", "test", "transfer")


def generate_empty_evidence_controls(
    phase_questions,
    generate,
    *,
    reader_identity,
    reader_profile,
    family_by_question=None,
):
    """Yield original control records, without examining benchmark answers."""
    if (
        not callable(generate)
        or not reader_identity
        or not reader_profile
        or len(phase_questions) != 32
        or tuple(phase_questions)
        != tuple(
            (phase, q) for phase in PHASES for p, q in phase_questions if p == phase
        )
        or {phase: sum(p == phase for p, _ in phase_questions) for phase in PHASES}
        != {phase: 8 for phase in PHASES}
        or len({q.identity for _, q in phase_questions}) != 32
        or (
            family_by_question is not None
            and (
                set(family_by_question) != {q.identity for _, q in phase_questions}
                or any(
                    not isinstance(family, str) or not family
                    for family in family_by_question.values()
                )
            )
        )
    ):
        raise ValueError("exactly 32 unique preregistered controls required")
    rows = []
    for phase, q in phase_questions:
        if not q.identity or not q.scope or not q.content or not q.observed_at:
            raise ValueError("unbound Reader diagnostic question")
        row = dict(
            schema="hepta.stem-no-evidence-reader-control.v1",
            phase=phase,
            question_id=q.identity,
            family=(
                q.family
                if family_by_question is None
                else family_by_question[q.identity]
            ),
            scope=q.scope,
            request_query_sha256=digest(asdict(q)),
            evidence_count=0,
            role="post-policy-no-evidence-diagnostic-not-trained-cell",
            answer_target_opened_by_generation=False,
            supports_independently_verified=False,
        )
        try:
            raw, receipt = generate(q, (), f"no-evidence/{phase}/{q.identity}")
            if (
                not isinstance(raw, str)
                or not raw.strip()
                or receipt["generator_identity"] != reader_identity
                or receipt["generator_profile"] != reader_profile
                or receipt["observable_query"] != asdict(q)
                or receipt["delivered_evidence"] != []
                or receipt["canonical_request_digest"]
                != digest((reader_identity, reader_profile, asdict(q), []))
                or type(receipt["actual_reader_execution"]) is not bool
            ):
                raise ValueError("detached no-evidence Reader receipt")
            row.update(status="succeeded", answer=raw, receipt=receipt)
        except Exception as exc:
            row.update(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc)[:1024],
            )
        rows.append(row)
    return rows


def evaluate_empty_evidence_controls(rows, targets, diagnose):
    """Answer targets are read only after all no-evidence outputs exist."""
    if len(rows) != 32 or not callable(diagnose):
        raise ValueError("incomplete zero-evidence reader control census")
    seen, scored, grouped = set(), [], defaultdict(list)
    for row in rows:
        if row["phase"] not in PHASES:
            raise ValueError("unknown no-evidence phase")
        key = (row["phase"], row["question_id"])
        if key in seen or key[1] not in targets:
            raise ValueError("duplicate or unregistered no-evidence record")
        seen.add(key)
        result = dict(
            phase=row["phase"],
            question_id=row["question_id"],
            family=row["family"],
            status=row["status"],
            was_zero_evidence=True,
            semantic_citation_precision=None,
            evidence_support_measured=False,
        )
        if row["status"] == "succeeded":
            answer = row["answer"]
            target = targets[key[1]]
            value = diagnose(answer, target)
            if value is not None and (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("invalid diagnostic Reader token F1")
            result["diagnostic_answer_f1"] = value
            # Any generated evidence marker is unsupported: no source was
            # delivered. This is a structural census, NOT semantic precision.
            result["unbound_evidence_marker_count"] = len(
                re.findall(r"\[E\d+\]", answer)
            )
        elif row["status"] == "failed":
            result.update(
                diagnostic_answer_f1=None,
                unbound_evidence_marker_count=0,
            )
        else:
            raise ValueError("unrecognized no-evidence control status")
        scored.append(result)
        grouped[row["phase"]].append(result)
    if {phase: len(rows) for phase, rows in grouped.items()} != {p: 8 for p in PHASES}:
        raise ValueError("zero-evidence phase coverage drift")
    per_phase = {}
    for phase, attempts in sorted(grouped.items()):
        observed = [
            a["diagnostic_answer_f1"]
            for a in attempts
            if a["diagnostic_answer_f1"] is not None
        ]
        n = len(attempts)
        per_phase[phase] = dict(
            attempted=n,
            succeeded=sum(a["status"] == "succeeded" for a in attempts),
            failed=sum(a["status"] == "failed" for a in attempts),
            answer_scored=len(observed),
            answer_unscored=n - len(observed),
            diagnostic_f1_mean=(
                math.fsum(observed) / len(observed) if observed else None
            ),
            all_planned_diagnostic_f1_bounds=[
                math.fsum(observed) / n,
                (math.fsum(observed) + n - len(observed)) / n,
            ],
            unbound_evidence_marker_count=sum(
                a["unbound_evidence_marker_count"] for a in attempts
            ),
            semantic_citation_precision=None,
            qualified_reader_sufficiency=False,
        )
    return dict(
        schema="hepta.stem-no-evidence-reader-report.v1",
        planned_controls=32,
        source_arms=0,
        no_source_delivered_by_design=True,
        policy_scores_modified=False,
        independent_gold_evidence_verified=False,
        per_phase=per_phase,
        results=scored,
        production_accepted=False,
    )
