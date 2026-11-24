"""Audit matched-evidence reader repeats; never claim a memory gain from noise.

The source-only evidence selection is matched, including order. A frozen,
deterministic reader should receive the same prompt token IDs for those arms.
Output disagreement is recorded, not silently repaired or counted as a gain.
"""

from collections import defaultdict
from itertools import combinations


def audit_repeats(rows, expected, arms):
    """Validate the complete scored census and compare truly identical inputs."""
    if (
        not expected
        or len(set(expected)) != len(expected)
        or not arms
        or len(set(arms)) != len(arms)
        or len(rows) != len(expected) * len(arms)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(qid, arm) for qid in expected for arm in arms}
    ):
        raise ValueError("complete unique matched-answer census required")
    grouped = defaultdict(list)
    for row in rows:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("invalid execution status")
        if not isinstance(row.get("selected"), list):
            raise ValueError("ordered selected sources required")
        if len(row["selected"]) != len(set(row["selected"])):
            raise ValueError("duplicate selected source")
        if row["status"] == "succeeded":
            if type(row.get("strict_task_success")) is not bool:
                raise ValueError("scored success must be a boolean")
            if type(row.get("required_sources_covered")) is not bool:
                raise ValueError("scored source coverage must be a boolean")
        grouped[row["question_id"]].append(row)
    compared = 0
    unobserved = 0
    divergent_answers = []
    divergent_task_results = []
    divergent_token_outputs = []
    kinds = defaultdict(lambda: dict(planned=0, observed=0, divergent=0))
    for qid in expected:
        by_question = grouped[qid]
        if len({r["kind"] for r in by_question}) != 1:
            raise ValueError("task kind changed between control arms")
        if len({r["candidate_digest"] for r in by_question}) != 1:
            raise ValueError("candidate pool changed between control arms")
        by_selection = defaultdict(list)
        for row in by_question:
            by_selection[tuple(row["selected"])].append(row)
        for matches in by_selection.values():
            for a, b in combinations(matches, 2):
                record = dict(
                    question_id=qid,
                    kind=a["kind"],
                    arms=[a["arm"], b["arm"]],
                )
                kind = kinds[a["kind"]]
                kind["planned"] += 1
                if a["status"] != "succeeded" or b["status"] != "succeeded":
                    unobserved += 1
                    continue
                compared += 1
                kind["observed"] += 1
                ar, br = a["receipt"], b["receipt"]
                # Prompt identity is a protocol invariant, not a model metric.
                for field in (
                    "reader_identity",
                    "reader_profile",
                    "token_limit",
                    "input_ids_digest",
                    "input_tokens",
                    "delivered_evidence",
                ):
                    if ar[field] != br[field]:
                        raise ValueError(
                            f"identical ordered evidence differs in {field}"
                        )
                if a["required_sources_covered"] != b["required_sources_covered"]:
                    raise ValueError("same evidence received different gold coverage")
                disagreement = False
                if a["answer"] != b["answer"]:
                    divergent_answers.append(record)
                    disagreement = True
                if ar["generated_ids_digest"] != br["generated_ids_digest"]:
                    divergent_token_outputs.append(record)
                    disagreement = True
                if a["strict_task_success"] != b["strict_task_success"]:
                    divergent_task_results.append(record)
                    disagreement = True
                kind["divergent"] += disagreement
    return dict(
        schema="hepta.memory-strong-rag.prompt-equivalence.v1",
        planned_questions=len(expected),
        identical_ordered_evidence_pairs=compared + unobserved,
        observed_identical_prompt_pairs=compared,
        unavailable_pairs=unobserved,
        answer_disagreements=divergent_answers,
        output_token_disagreements=divergent_token_outputs,
        task_result_disagreements=divergent_task_results,
        by_kind={k: dict(v) for k, v in sorted(kinds.items())},
        deterministic_repeatability_established=(
            compared > 0
            and unobserved == 0
            and not divergent_answers
            and not divergent_token_outputs
            and not divergent_task_results
        ),
        independent_statistical_significance=False,
        independent_semantic_adjudication=False,
        production_accepted=False,
    )
