"""Paired source question/value interaction; never a new model result.

Reuse ORIGINAL source-only K-way likelihoods. A question-independent identifier
prior cancels in the symmetric swapped-value comparison. Candidate values are
still taken from sources, not learned entirely in parameters.
"""
import math

from native import digest


def question_binding(rows, cases):
    """Contrast two different questions and their respective source targets."""
    if not isinstance(cases, (list, tuple)) or not 1 <= len(cases) <= 32:
        raise ValueError("bounded source question census required")
    groups, seen, expected = {}, set(), set()
    for case in cases:
        q, values = case["query"], case["candidates"]
        qid, scope, target = q["identity"], q["scope"], case["target"]
        if (
            not isinstance(qid, str) or not qid or qid in seen
            or not isinstance(scope, str) or not scope
            or scope != case["scope"]
            or not isinstance(values, (tuple, list))
            or not 2 <= len(values) <= 16 or len(set(values)) != len(values)
            or target not in values
            or any(not isinstance(v, str) or not v for v in values)
        ):
            raise ValueError("incomplete original source lexicon")
        seen.add(qid)
        groups.setdefault(scope, []).append(case)
        expected.update(
            (qid, arm, digest(v))
            for arm in ("base", "memory") for v in values
        )
    keys = [
        (row["question_id"], row["arm"], row["candidate_digest"])
        for row in rows
    ]
    if len(keys) != len(expected) or len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError("missing/duplicate original candidate model call")
    indexed = dict(zip(keys, rows, strict=True))
    reader_profiles, prompt_ids = set(), {}
    for case in cases:
        qid, scope = case["query"]["identity"], case["scope"]
        prompts, questions = set(), set()
        for arm in ("base", "memory"):
            for v in case["candidates"]:
                row = indexed[qid, arm, digest(v)]
                if (
                    row.get("status") not in ("succeeded", "failed")
                    or row.get("scope") != scope
                    or row.get("delivered_evidence") != []
                    or not isinstance(row.get("prompt_digest"), str)
                    or not row["prompt_digest"]
                    or not isinstance(row.get("reader_profile"), str)
                    or not row["reader_profile"]
                    or not isinstance(row.get("actual_reader_question_id"), str)
                    or not row["actual_reader_question_id"]
                ):
                    raise ValueError("source-only input/reader drift")
                prompts.add(row["prompt_digest"])
                questions.add(row["actual_reader_question_id"])
                reader_profiles.add(row["reader_profile"])
                if row["status"] == "succeeded":
                    if any(
                        type(row.get(k)) not in (int, float)
                        or not math.isfinite(row[k]) or row[k] < 0
                        for k in ("mean_nll", "seconds")
                    ):
                        raise ValueError("invalid measured likelihood")
                    if (
                        type(row.get("supervised_tokens")) is not int
                        or not 1 <= row["supervised_tokens"] <= 64
                        or type(row.get("input_tokens")) is not int
                        or row["input_tokens"] <= row["supervised_tokens"]
                    ):
                        raise ValueError("invalid measured token count")
        if len(prompts) != 1 or len(questions) != 1:
            raise ValueError("source question drift between score calls")
        prompt_ids[qid] = next(iter(prompts))
    if len(reader_profiles) != 1 or len(set(prompt_ids.values())) != len(prompt_ids):
        raise ValueError("mixed reader or indistinguishable question prompts")
    pairs, completed, missing, unequal, repeated = [], 0, 0, 0, 0
    improved, dual_gains = 0, 0
    for scope, scoped in sorted(groups.items()):
        ordered = sorted(scoped, key=lambda c: c["query"]["identity"])
        for i in range(0, len(ordered) - 1, 2):
            first, second = ordered[i], ordered[i + 1]
            if set(first["candidates"]) != set(second["candidates"]):
                raise ValueError("paired questions have different source lexicons")
            q1, q2 = first["query"]["identity"], second["query"]["identity"]
            a, b = first["target"], second["target"]
            report = dict(
                scope_digest=digest(scope),
                question_digests=[digest(q1), digest(q2)],
                source_value_digests=[digest(a), digest(b)],
            )
            if a == b:
                repeated += 1
                report["disposition"] = "same_target_not_comparable"
            else:
                observed = [
                    indexed[q, arm, digest(v)]
                    for arm in ("base", "memory")
                    for q in (q1, q2) for v in (a, b)
                ]
                if any(x["status"] == "failed" for x in observed):
                    missing += 1
                    report["disposition"] = "failed_model_call"
                elif len({x["supervised_tokens"] for x in observed}) != 1:
                    unequal += 1
                    report["disposition"] = "different_completion_token_length"
                else:
                    margins, dual = {}, {}
                    for arm in ("base", "memory"):
                        def loss(q, v):
                            return indexed[q, arm, digest(v)]["mean_nll"]

                        left = loss(q1, b) - loss(q1, a)
                        right = loss(q2, a) - loss(q2, b)
                        margins[arm] = (left + right) / 2
                        dual[arm] = left > 0 and right > 0
                    delta = margins["memory"] - margins["base"]
                    completed += 1
                    improved += int(delta > 1e-9)
                    dual_gains += int(dual["memory"] and not dual["base"])
                    report.update(
                        disposition="complete",
                        frozen_specificity=margins["base"],
                        adapter_specificity=margins["memory"],
                        adapter_minus_frozen=delta,
                        frozen_both_correct=dual["base"],
                        adapter_both_correct=dual["memory"],
                    )
            pairs.append(report)
    return dict(
        schema="hepta.source-question-value-binding.v1",
        planned_pairs=len(pairs),
        complete_pairs=completed,
        failed_pairs=missing,
        unequal_length_pairs=unequal,
        same_value_pairs=repeated,
        adapter_specificity_improved_pairs=improved,
        new_dual_correct_pairs=dual_gains,
        pairs=pairs,
        additional_model_calls=0,
        source_lexicon_is_nonparametric=True,
        source_training_facts_not_independent_holdout=True,
        statistical_superiority=False,
        independent_semantic_citation_precision=None,
        production_accepted=False,
    )
