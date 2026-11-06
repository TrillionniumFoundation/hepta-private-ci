"""Read-only rankability census from recorded frozen feature encodes.

A Cell cannot improve forced top-1 ranking on a one-candidate pool.
This is a structural capacity diagnostic, not a claim that a multi-candidate
Cell learned the correct selector or semantic entailment.
"""

from collections import Counter

from stem_audit_archive import require


def candidate_capacity(plan, encoding, raw, feature_failures):
    registered = {
        qid: phase for phase, qids in plan["questions"].items() for qid in qids
    }
    require(
        sum(len(x) for x in plan["questions"].values()) == len(registered),
        "candidate capacity cannot merge duplicate question identities",
    )
    candidates, duplicate_unchanged = {}, 0
    for row in encoding:
        if row["backend"] != "frozen" or row["cost"]["cache_hit"]:
            continue
        qid = row["question_id"]
        require(qid in registered, "unregistered candidate encoding")
        receipt = row["cost"]["extraction"]
        require(
            isinstance(receipt.get("encoder_identity"), str)
            and receipt["encoder_identity"],
            "missing frozen Encoder identity",
        )
        pairs = receipt["pairs"]
        require(
            type(pairs) is int and 0 <= pairs <= 64, "invalid bounded candidate count"
        )
        if qid in candidates:
            require(
                candidates[qid] == pairs,
                "candidate pool size changed within pinned run",
            )
            duplicate_unchanged += 1
        else:
            candidates[qid] = pairs
    missing = set(registered) - set(candidates)
    require(
        missing <= set(feature_failures), "missing successful frozen feature encoding"
    )
    phases = {}
    for phase, qids in plan["questions"].items():
        sizes = [candidates[q] for q in qids if q in candidates]
        h = Counter(sizes)
        phases[phase] = dict(
            attempted_questions=len(qids),
            successfully_encoded=len(sizes),
            missing_or_failed_feature_encoding=len(qids) - len(sizes),
            no_candidates=h[0],
            forced_top1_no_competition=h[1],
            rankable_two_or_more=sum(n >= 2 for n in sizes),
            candidate_count_histogram={str(k): v for k, v in sorted(h.items())},
        )

    eval_phases = ("select", "retention", "test", "transfer")
    by_case = {}
    for row in raw:
        identity = (row["stage"], row["phase"], row["question_id"])
        require(row["phase"] in eval_phases, "unexpected policy phase")
        key = str(identity)
        by_case.setdefault(key, candidates.get(row["question_id"]))
        require(
            by_case[key] == candidates.get(row["question_id"]),
            "different candidate size for matched task",
        )
    return dict(
        schema="hepta.stem-candidate-capacity.v1",
        phase_census=phases,
        fresh_question_encodings=len(candidates),
        repeated_pinned_frozen_misses=duplicate_unchanged,
        logical_policy_rows=len(raw),
        rankability_does_not_imply_correctness=True,
        training_labels_read=False,
        new_model_calls=0,
        production_accepted=False,
    )
