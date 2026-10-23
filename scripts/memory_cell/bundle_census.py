"""Complete same-reader contrasts; model size is never a memory gain.

A supplied publisher support set is NOT independently verified sufficient context.
Missing oracle/context-budget failures remain explicit, never smaller denominators.
"""

import math
import re

from native import digest


def summarize(records, plan):
    expected = {
        (q["question"]["identity"], arm)
        for q in plan["cases"]
        for arm in q["conditions"]
    }
    keys = [(r["question_id"], r["arm"]) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("incomplete, duplicated or extra reader census")
    profiles = {
        (r["receipt"]["reader_identity"], r["receipt"]["reader_profile"])
        for r in records
        if r["status"] == "succeeded"
    }
    if len(profiles) != 1:
        raise ValueError("same-reader experiment requires one model/profile")
    lookup = {c["question"]["identity"]: c for c in plan["cases"]}
    for row in records:
        case = lookup[row["question_id"]]
        condition = case["conditions"][row["arm"]]
        if row["status"] not in ("succeeded", "failed", "unavailable"):
            raise ValueError("unknown execution state")
        if row["family"] != case["family"] or row["phase"] != case["phase"]:
            raise ValueError("changed family/phase")
        for key in ("f1", "exact_match"):
            v = row.get(key)
            if v is not None and (
                type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1
            ):
                raise ValueError("invalid diagnostic score")
            if row["status"] != "succeeded" and v is not None:
                raise ValueError("failed/unavailable answer cannot be scored")
        if row["status"] == "succeeded":
            rec = row["receipt"]
            if (
                rec["bundle_digest"] != condition["bundle_digest"]
                or rec["token_limit"] != condition["token_limit"]
                or rec["input_tokens"] > rec["token_limit"]
                or rec["delivered_evidence"] != condition["delivered_evidence"]
            ):
                raise ValueError("actual reader input differs from frozen condition")
    summaries = {}
    for phase in sorted({r["phase"] for r in records}):
        for arm in sorted({r["arm"] for r in records}):
            rows = [r for r in records if (r["phase"], r["arm"]) == (phase, arm)]
            good = [r for r in rows if r["status"] == "succeeded"]
            scored = [r for r in good if r.get("f1") is not None]
            answerable = [r for r in scored if r.get("target_unanswerable") is False]
            citations = [
                m for r in good for m in re.findall(r"\[E[1-9][0-9]*\]", r["answer"])
            ]
            summaries[f"{phase}/{arm}"] = dict(
                planned=len(rows),
                succeeded=len(good),
                failed=sum(r["status"] == "failed" for r in rows),
                unavailable=sum(r["status"] == "unavailable" for r in rows),
                scored=len(scored),
                unscored=len(rows) - len(scored),
                f1=sum(r["f1"] for r in scored) / len(scored) if scored else None,
                answerable_n=len(answerable),
                answerable_f1=sum(r["f1"] for r in answerable) / len(answerable)
                if answerable
                else None,
                all_planned_f1_bounds=[
                    sum(r["f1"] for r in scored) / len(rows),
                    (sum(r["f1"] for r in scored) + len(rows) - len(scored))
                    / len(rows),
                ]
                if rows
                else [0, 1],
                protocol_abstentions=sum(
                    r["answer"].strip() == "I do not have enough evidence."
                    for r in good
                ),
                citation_markers=len(citations),
                input_tokens=sum(r["receipt"]["input_tokens"] for r in good),
                generated_tokens=sum(r["receipt"]["generated_tokens"] for r in good),
                semantic_citation_precision=None,
            )
    contrasts = {}
    pairs = (
        ("single", "ranked4"),
        ("ranked2", "coverage2"),
        ("ranked4", "coverage4"),
        ("ranked8", "coverage8"),
        ("coverage8", "adaptive8"),
        ("ranked4", "ranked4_large"),
    )
    grouped = {
        qid: {r["arm"]: r for r in records if r["question_id"] == qid}
        for qid, _ in expected
    }
    for phase in sorted({r["phase"] for r in records}):
        for left, right in pairs:
            values = {}
            for rows in grouped.values():
                a, b = rows.get(left), rows.get(right)
                if a is None or b is None or a["phase"] != phase:
                    continue
                valid = (
                    a["status"] == b["status"] == "succeeded"
                    and a.get("f1") is not None
                    and b.get("f1") is not None
                )
                pair = (b["f1"] - a["f1"],) * 2 if valid else (-1.0, 1.0)
                values.setdefault(a["family"], []).append(pair)
            n = len(values)
            means = (
                [
                    sum(sum(v[i] for v in vs) / len(vs) for vs in values.values()) / n
                    for i in (0, 1)
                ]
                if n
                else [-1, 1]
            )
            radius = (
                math.sqrt(
                    2
                    * math.log(
                        2 * len(pairs) * len({r["phase"] for r in records}) / 0.05
                    )
                    / n
                )
                if n
                else 2
            )
            contrasts[f"{phase}/{left}->{right}"] = dict(
                source_family_groups=n,
                family_delta_bounds=means,
                simultaneous_95_interval=[
                    max(-1, means[0] - radius),
                    min(1, means[1] + radius),
                ],
            )
    return dict(
        schema="hepta.bundle-diagnostic.report.v1",
        plan_digest=digest(plan),
        summaries=summaries,
        same_reader_contrasts=contrasts,
        raw_census=len(records),
        diagnostic_f1_not_official_judge=True,
        independent_human_oracle_verified=False,
        learned_selector=False,
        reader_training=False,
        production_accepted=False,
        superiority_claim=False,
        semantic_citation_precision=None,
    )
