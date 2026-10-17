"""Read-only, byte-pinned frozen Reader diagnosis by actual source correctness.

The original benchmark's post-policy native-document support annotations are
weak labels, not independently reviewed window-level entailment. A successful
Reader call, an original support-source hit, and an answer token-F1 score are
three DIFFERENT outcomes. This audit does not call any model or change policy.
"""

from collections import Counter
import math

PHASES = ("select", "retention", "test", "transfer")
ORACLE_KINDS = frozenset(
    {
        "no-admitted-literal-reference-span",
        "native-source-literal-span",
        "annotated-unanswerable",
    }
)


def frozen_condition(plan, scored, oracles):
    """Audit 32 unique final-stage frozen questions, never triple-count stages.

    Answerability comes from the archived, post-generation oracle *category*,
    not a fresh adjudication or source-content inference. Preserve all failures.
    """
    registered = plan["questions"]
    if (
        not isinstance(registered, dict)
        or any(len(registered.get(phase, ())) != 8 for phase in PHASES)
        or len({q for phase in PHASES for q in registered[phase]}) != 32
    ):
        raise ValueError("32 original source-registered questions required")
    expected = {(phase, q) for phase in PHASES for q in registered[phase]}
    targets, oracle_counts = {}, Counter()
    for row in oracles:
        key = (row["phase"], row["question_id"])
        kind = row["oracle_kind"]
        status = row["status"]
        if (
            key not in expected
            or key in targets
            or kind not in ORACLE_KINDS
            or row.get("policy_comparator") is not False
            or row.get("semantic_entailment_independently_verified") is not False
            or status not in ("succeeded", "failed", "unavailable")
            or (
                kind == "no-admitted-literal-reference-span" and status != "unavailable"
            )
            or (kind == "annotated-unanswerable" and status == "unavailable")
        ):
            raise ValueError("unregistered or promoted diagnostic oracle provenance")
        targets[key] = (
            "native-unanswerable"
            if kind == "annotated-unanswerable"
            else "answerable-native-document"
        )
        oracle_counts[(row["phase"], kind, status)] += 1
    if set(targets) != expected:
        raise ValueError("missing original oracle-answerability classification")
    frozen = {}
    for row in scored:
        if row["stage"] != 48 or row["arm"] != "frozen_rerank":
            continue
        key = (row["phase"], row["question_id"])
        if key not in expected or key in frozen:
            raise ValueError("duplicate or unregistered final frozen-reader question")
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unrecognized original fixed-Reader outcome")
        val = row.get("source_choice_correct")
        if type(val) is not int or val not in (0, 1):
            raise ValueError("native weak source comparison not reproducible")
        if row["status"] == "succeeded":
            if not isinstance(row.get("answer"), str) or not row["answer"].strip():
                raise ValueError("empty successful model answer")
            score = row.get("diagnostic_answer_f1")
            if score is not None and (
                type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError("invalid observed Reader token-F1 diagnostic")
            if not isinstance(row.get("receipt"), dict):
                raise ValueError("missing original Reader result receipt")
        if (
            targets[key] == "native-unanswerable"
            and val == 1
            and row.get("selected") is not None
        ):
            raise ValueError("native abstention success cannot select a source")
        frozen[key] = row
    if set(frozen) != expected:
        raise ValueError("missing final frozen-Reader attempt")

    reports = {}
    for phase in PHASES:
        selected = [(key, frozen[key]) for key in sorted(expected) if key[0] == phase]
        strata = {}
        total = Counter()
        for label in ("answerable-native-document", "native-unanswerable"):
            for hit in (0, 1):
                subset = [
                    row
                    for key, row in selected
                    if targets[key] == label and row["source_choice_correct"] == hit
                ]
                n = len(subset)
                successful = [row for row in subset if row["status"] == "succeeded"]
                f1 = [
                    row["diagnostic_answer_f1"]
                    for row in successful
                    if row["diagnostic_answer_f1"] is not None
                ]
                token_sum = math.fsum(f1)
                name = f"{label}/" + (
                    "source-or-abstention-correct"
                    if hit
                    else "source-or-abstention-incorrect"
                )
                strata[name] = dict(
                    original_questions=n,
                    original_reader_success=len(successful),
                    original_reader_failed=n - len(successful),
                    answer_diagnostic_scored=len(f1),
                    answer_diagnostic_unscored=n - len(f1),
                    observed_answer_token_f1_mean=(token_sum / len(f1) if f1 else None),
                    all_planned_answer_token_f1_lower_bound=(
                        token_sum / n if n else None
                    ),
                    all_planned_answer_token_f1_upper_bound=(
                        (token_sum + n - len(f1)) / n if n else None
                    ),
                    answer_token_f1_not_entailed_by_weak_source_hit=True,
                )
                total[(label, hit)] = n
        if sum(total.values()) != 8:
            raise ValueError("split source correctness denominator drift")
        reports[phase] = dict(
            planned_questions=8,
            answerable_native_document_questions=sum(
                total[("answerable-native-document", hit)] for hit in (0, 1)
            ),
            unanswerable_native_questions=sum(
                total[("native-unanswerable", hit)] for hit in (0, 1)
            ),
            native_answerable_support_selected=total[("answerable-native-document", 1)],
            native_answerable_support_not_selected=total[
                ("answerable-native-document", 0)
            ],
            original_reader_success=sum(
                row["status"] == "succeeded" for _, row in selected
            ),
            oracle_literal_span_available=sum(
                oracle_counts[(phase, "native-source-literal-span", s)]
                for s in ("succeeded", "failed")
            ),
            oracle_literal_span_unavailable=oracle_counts[
                (phase, "no-admitted-literal-reference-span", "unavailable")
            ],
            source_and_answerability_strata=strata,
            independently_sufficient_excerpt_verified=False,
        )
    return dict(
        schema="hepta.stem-pinned-frozen-conditional-reader.v1",
        final_checkpoint=48,
        unique_original_questions=32,
        stages_16_32_48_not_independent_subjects=True,
        original_oracle_categories_are_not_independent_review=True,
        answer_f1_diagnostic_not_semantic_citation_precision=True,
        by_phase=reports,
        semantic_citation_precision=None,
        production_accepted=False,
    )
