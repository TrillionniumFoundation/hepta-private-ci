"""Read-only fixed-Reader comparison with the published answer-literal reference.

The literal reference is selected WITH knowledge of the target answer; its
success is a privileged diagnostic, not an independently certified sufficient
evidence window, a retrieval-policy candidate, or a learning result.
No models are invoked and nothing in this module changes the 576 policy rows.
"""

from collections import Counter, defaultdict
import math

from stem_audit_archive import require
from stem_native_reader_stratification import BUCKETS, _bucket
from stem_cell_time import source_not_after_question

PHASES = ("select", "retention", "test", "transfer")
KINDS = (
    "native-source-literal-span",
    "annotated-unanswerable",
    "unresolved-reference",
    "no-admitted-literal-reference-span",
)


def _index(rows, expected, label):
    found = {}
    for row in rows:
        key = row["phase"], row["question_id"]
        require(
            key in expected and key not in found,
            "duplicate, unknown or unregistered " + label,
        )
        found[key] = row
    require(set(found) == expected, "incomplete 32-question " + label)
    return found


def _score(row, name):
    if row["status"] not in ("succeeded", "failed", "unavailable"):
        raise ValueError("unknown fixed-Reader diagnostic status")
    if row["status"] != "succeeded":
        return None
    score = row.get(name)
    if score is None:
        return None
    require(
        type(score) in (float, int) and math.isfinite(score) and 0 <= score <= 1,
        "invalid Reader diagnostic F1",
    )
    return score


def _aligned_reader(frozen, other):
    a, b = frozen["receipt"], other["receipt"]
    require(
        isinstance(a, dict)
        and isinstance(b, dict)
        and bool(a.get("generator_identity"))
        and bool(a.get("generator_profile"))
        and a["generator_identity"] == b.get("generator_identity")
        and a["generator_profile"] == b.get("generator_profile")
        and isinstance(a.get("observable_query"), dict)
        and a["observable_query"] == b.get("observable_query")
        and a["observable_query"].get("identity") == frozen["question_id"],
        "different Reader weights, prompt or native question in comparison",
    )
    require(
        isinstance(b.get("delivered_evidence"), list),
        "reader reference receipt lacks actual delivered evidence",
    )


def _difference(a, b):
    return a - b if a is not None and b is not None else None


def reference_reader_capacity(
    plan,
    original_scored,
    oracle_rows,
    empty_raw,
    empty_scored,
    native_ceiling,
):
    """Compare frozen top-1, empty Reader and answer-literal reference on 32 rows."""
    questions = plan["questions"]
    expected = {(phase, qid) for phase in PHASES for qid in questions[phase]}
    require(
        len(expected) == 32
        and all(len(questions[p]) == 8 for p in PHASES)
        and len(set(q for p in PHASES for q in questions[p])) == 32,
        "registered fixed Reader comparison cohort changed",
    )
    frozen_rows = [
        r for r in original_scored if r["stage"] == 48 and r["arm"] == "frozen_rerank"
    ]
    frozen = _index(frozen_rows, expected, "frozen policy")
    oracle = _index(oracle_rows, expected, "privileged oracle")
    empty = _index(empty_raw, expected, "zero-evidence raw Reader")
    zero = _index(empty_scored["results"], expected, "zero-evidence scores")
    coverage = _index(native_ceiling["decisions"], expected, "native source ceiling")
    require(
        empty_scored["planned_controls"] == 32
        and empty_scored["production_accepted"] is False,
        "independent empty-context Reader accounting drift",
    )
    bucketed = defaultdict(list)
    observed_kinds = Counter()
    for key in sorted(expected):
        phase, qid = key
        f, o, e, z, n = (frozen[key], oracle[key], empty[key], zero[key], coverage[key])
        require(
            f["status"] == "succeeded"
            and f["family"]
            == e["family"]
            == z["family"]
            == n["source_family"]
            == plan["question_families"][qid]
            and e["status"] == z["status"]
            and e.get("evidence_count") == 0
            and o.get("oracle_kind") in KINDS
            and o["policy_comparator"] is False
            and o["semantic_entailment_independently_verified"] is False
            and n["native_weak_support_not_window_entailment"] is True,
            "oracle/frozen/empty Reader cohort or semantic authority drift",
        )
        require(
            o["oracle_kind"] != "annotated-unanswerable"
            or n["native_source_unanswerable"] is True,
            "answerable question relabelled as native abstention",
        )
        require(
            n["native_source_unanswerable"] is not True
            or o["oracle_kind"] == "annotated-unanswerable",
            "unanswerable native question provided a literal answer oracle",
        )
        require(
            o["status"] in ("succeeded", "failed", "unavailable"),
            "unknown oracle attempt state",
        )
        if o["status"] == "unavailable":
            require(
                o["oracle_kind"]
                in ("unresolved-reference", "no-admitted-literal-reference-span")
                and not any(k in o for k in ("answer", "receipt", "diagnostic_f1")),
                "absent reference attempt manufactured an answer",
            )
        if o["status"] == "succeeded":
            require(
                o["oracle_kind"]
                in ("native-source-literal-span", "annotated-unanswerable")
                and isinstance(o.get("answer"), str)
                and bool(o["answer"].strip()),
                "unsupported or missing privileged Oracle answer",
            )
            _aligned_reader(f, o)
            provided = o["receipt"]["delivered_evidence"]
            if o["oracle_kind"] == "native-source-literal-span":
                require(
                    len(provided) == 1
                    and provided[0].get("offset_encoding") == "original-utf8-bytes"
                    and provided[0].get("label") == "E1",
                    "literal-answer privileged reference not source-bound",
                )
                source = provided[0]
                source_start, source_end, excerpt = (
                    source.get("source_start"),
                    source.get("source_end"),
                    source.get("excerpt"),
                )
                require(
                    type(source_start) is int
                    and type(source_end) is int
                    and 0 <= source_start < source_end <= 100_000_000
                    and isinstance(excerpt, str)
                    and 0 < len(excerpt.encode("utf-8", "strict")) <= 4096
                    and source_end - source_start
                    == len(excerpt.encode("utf-8", "strict"))
                    and isinstance(source.get("root"), str)
                    and bool(source["root"])
                    and isinstance(source.get("id"), str)
                    and bool(source["id"])
                    and source.get("scope") == f["receipt"]["observable_query"]["scope"]
                    and isinstance(source.get("observed_at"), str)
                    and source_not_after_question(
                        source["observed_at"],
                        f["receipt"]["observable_query"]["observed_at"],
                    ),
                    "reference UTF-8 source offset, scope or as-of time drift",
                )
            else:
                require(provided == [], "native abstention Oracle received evidence")
        if e["status"] == "succeeded":
            _aligned_reader(f, e)
            require(
                e["receipt"]["delivered_evidence"] == [],
                "zero-evidence Reader received a source",
            )
        require(
            e["status"] in ("succeeded", "failed")
            and o["status"] in ("succeeded", "unavailable", "failed"),
            "invalid native Reader control status",
        )
        original_f1 = _score(f, "diagnostic_answer_f1")
        oracle_f1 = _score(o, "diagnostic_f1")
        empty_f1 = _score(z, "diagnostic_answer_f1")
        if o["status"] != "succeeded":
            require(oracle_f1 is None, "unavailable oracle scored as available")
        if e["status"] != "succeeded":
            require(empty_f1 is None, "failed zero-evidence Reader scored")
        observed_kinds[o["oracle_kind"]] += 1
        bucketed[_bucket(n)].append(
            dict(
                phase=phase,
                question_id=qid,
                source_family=plan["question_families"][qid],
                oracle_kind=o["oracle_kind"],
                oracle_status=o["status"],
                no_evidence_status=e["status"],
                frozen_token_f1=original_f1,
                oracle_token_f1=oracle_f1,
                no_evidence_token_f1=empty_f1,
                oracle_minus_frozen=_difference(oracle_f1, original_f1),
                oracle_minus_empty=_difference(oracle_f1, empty_f1),
                frozen_minus_empty=_difference(original_f1, empty_f1),
                oracle_selected_with_target_answer=True,
                oracle_sufficient_evidence_independently_certified=False,
            )
        )
    outputs = {}
    for kind in BUCKETS:
        rows = bucketed[kind]
        n = len(rows)
        deltas = {}
        for field in (
            "oracle_minus_frozen",
            "oracle_minus_empty",
            "frozen_minus_empty",
        ):
            values = [row[field] for row in rows if row[field] is not None]
            total, missing = math.fsum(values), n - len(values)
            deltas[field] = dict(
                compared=len(values),
                omitted=missing,
                compared_mean=(total / len(values) if values else None),
                all_planned_delta_bounds=(
                    [(total - missing) / n, (total + missing) / n] if n else None
                ),
                positive_pairs=sum(v > 0 for v in values),
                negative_pairs=sum(v < 0 for v in values),
            )
        outputs[kind] = dict(
            planned=n,
            oracle_literal_reference_available=sum(
                row["oracle_kind"] == "native-source-literal-span"
                and row["oracle_status"] == "succeeded"
                for row in rows
            ),
            oracle_native_abstention=sum(
                row["oracle_kind"] == "annotated-unanswerable" for row in rows
            ),
            oracle_unavailable=sum(
                row["oracle_status"] == "unavailable" for row in rows
            ),
            oracle_execution_failed=sum(
                row["oracle_status"] == "failed" for row in rows
            ),
            comparisons=deltas,
            evidence_sufficiency_not_adjudicated=True,
        )
    return dict(
        schema="hepta.stem-answer-dependent-oracle-reader-diagnostic.v1",
        original_fixed_question_count=len(expected),
        actual_oracle_statuses=dict(
            sorted(
                Counter(
                    x["oracle_status"] for rows in bucketed.values() for x in rows
                ).items()
            )
        ),
        oracle_kind_census=dict(sorted(observed_kinds.items())),
        per_original_native_source_coverage=outputs,
        rows=[
            dict(native_source_bucket=k, **row) for k in BUCKETS for row in bucketed[k]
        ],
        independently_reviewed_sufficient_context=False,
        answer_literal_reference_is_privileged=True,
        real_model_calls_added=0,
        generation_prompt_modified=False,
        frozen_source_policy_modified=False,
        unused_for_train_or_hyperparameter_selection=True,
        semantic_citation_precision=None,
        production_accepted=False,
    )
