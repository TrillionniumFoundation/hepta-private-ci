"""Privileged publisher-source Reader probe; no answer-literal span selection.

This source choice is NOT an ordinary RAG policy. It reads only published
document-support identities, not answer text, strictly after a separately
sealed complete native policy run. Within that source it uses question-only
lexical overlap and the identical bounded window projector, never an answer
substring or a hidden test-selected hyperparameter.
"""

from dataclasses import asdict
import math
import re

from native import digest
from selector_windows import WindowBudget, candidate_windows
from sessions import source_id
from stem_cell_temporal import admit_history

PHASES = ("select", "retention", "test", "transfer")


def _pick_window(query, pool):
    pool.revalidate(query, set())
    terms = set(re.findall(r"\w+", query.content.lower()))
    if not pool.windows:
        return None

    def key(i):
        window = pool.windows[i]
        tokens = re.findall(r"\w+", window.text.lower())
        overlap = len(terms.intersection(tokens)) / math.sqrt(max(1, len(tokens)))
        return (-overlap, window.start, window.identity())

    return min(range(len(pool.windows)), key=key)


def make_publisher_source_cases(plan, queries, source_for):
    """Build exactly 32 fixed Reader inputs; no target.answer access.

    Predeclared public annotation source IDs are a *privileged* diagnostic
    input, never a training label, serving entitlement or window entailment.
    Unknown as-of dates reject rather than invent a source history.
    """
    cohorts = plan["questions"]
    expected = [(phase, qid) for phase in PHASES for qid in cohorts[phase]]
    if (
        tuple(plan["arms"])
        != (
            "frozen_rerank",
            "prototype",
            "linear",
            "gated",
            "lineage_lora_gated",
            "independent_lora_gated",
        )
        or set(cohorts) != {"train", *PHASES}
        or any(len(cohorts[p]) != 8 for p in PHASES)
        or len(expected) != len(set(expected)) != 32
        or len({qid for _, qid in expected}) != 32
        or not set(qid for _, qid in expected).issubset(queries)
        or not set(qid for _, qid in expected).issubset(source_for)
        or plan["source_visibility_policy"]
        != "strict-as-of-before-index-and-every-Encoder-v1"
    ):
        raise ValueError("source-guided Reader cohort is not the original 32")
    budget = WindowBudget(**plan["window_budget"])
    budget.validate()
    results = []
    for phase, qid in expected:
        q, benchmark = queries[qid], source_for[qid]
        if (
            q.identity != qid
            or benchmark.name not in plan["dataset_sha256"]
            or benchmark.source_sha256 != plan["dataset_sha256"][benchmark.name]
            or benchmark.families[q.family] != plan["question_families"][qid]
        ):
            raise ValueError("original native question/benchmark family drift")
        # No access to target.answer; an opaque-answer fixture tests that.
        target = benchmark.targets[qid]
        if (
            type(target.unanswerable) is not bool
            or not isinstance(target.evidence, (list, tuple))
            or not isinstance(target.unresolved_evidence, (list, tuple))
        ):
            raise ValueError("invalid published source-only annotation")
        summary = dict(
            schema="hepta.stem-publisher-source-reader-plan.v1",
            phase=phase,
            question_id=qid,
            source_family=benchmark.families[q.family],
            query_sha256=digest(asdict(q)),
            original_dataset_sha256=benchmark.source_sha256,
            answer_text_read_by_planner=False,
            published_support_source_used_for_selection=True,
            independently_reviewed_source_sufficiency=False,
            original_window_projection_budget=asdict(budget),
            source_window_chosen_by="query-overlap-not-target-answer",
            nonqualifying_privileged_diagnostic=True,
        )
        evidence = ()
        if target.unanswerable:
            summary.update(status="unavailable", reason="native-unanswerable")
        elif target.unresolved_evidence or not target.evidence:
            summary.update(status="unavailable", reason="unresolved-native-support")
        else:
            history, temporal = admit_history(q, benchmark.history(q), revoked=set())
            admissible = {source_id(d.identity) for d in history}
            published = {source_id(s) for s in target.evidence}
            matches = sorted(
                (doc for doc in history if source_id(doc.identity) in published),
                key=lambda x: x.identity,
            )
            if not matches:
                summary.update(
                    status="unavailable",
                    reason="published-support-source-not-admissible",
                    admitted_history_size=temporal["admitted_count"],
                )
            else:
                doc = matches[0]
                pool = candidate_windows(
                    (doc,),
                    q,
                    revoked=set(),
                    budget=budget,
                    profile="query_windows",
                )
                selected = _pick_window(q, pool)
                if selected is None:
                    summary.update(
                        status="unavailable",
                        reason="published-source-window-projection-empty",
                    )
                else:
                    window = pool.windows[selected]
                    evidence = (
                        dict(
                            label="E1",
                            id=window.identity(),
                            original_id=window.source_id,
                            root=window.root,
                            scope=window.scope,
                            excerpt=window.text,
                            source_start=window.start,
                            source_end=window.end,
                            observed_at=window.observed_at,
                            inspected_sha256=window.inspected_sha256,
                        ),
                    )
                    summary.update(
                        status="planned",
                        matched_published_source_count=len(matches),
                        selected_source_identity_sha256=digest(doc.identity),
                        selected_window_identity_sha256=window.identity(),
                        selected_window_start=window.start,
                        selected_window_end=window.end,
                        selected_window_bytes=len(window.text.encode("utf-8")),
                        projected_source_prefix_bytes=pool.scanned_bytes,
                        unscanned_source_characters=len(doc.content)
                        - len(pool.inspected[0]["excerpt"]),
                        selected_pool_digest=pool.seal(),
                        published_native_source_ids_sha256=digest(sorted(published)),
                        admitted_history_size=temporal["admitted_count"],
                        excluded_future_history_size=temporal["excluded_future_count"],
                    )
        results.append((q, evidence, summary))
    if len(results) != 32:
        raise ValueError("lost a preregistered Reader diagnostic case")
    return results
