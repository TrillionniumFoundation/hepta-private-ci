"""After-generation paired QA diagnostics; no semantic certificate is issued."""

from collections import Counter
import math
import re
import string

from native import digest
from selector_answering import ABSTAIN, ARMS


def normalized(text):
    # SQuAD-style answer normalization, with protocol citations removed only in
    # this diagnostic scorer. The raw generated answer is never rewritten.
    text = re.sub(r"\[E[1-9][0-9]*\]", "", text).lower()
    text = "".join(c for c in text if c not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def answer_scores(raw, answers, unanswerable):
    if answers is None or unanswerable is None:
        return dict(exact_match=None, f1=None)
    abstained = raw.strip() == ABSTAIN
    if unanswerable:
        return dict(exact_match=float(abstained), f1=float(abstained))
    if not answers:
        raise ValueError("missing gold answer is not unanswerability")
    pred = normalized(raw)
    values = []
    for gold in answers:
        expected = normalized(gold)
        a, b = pred.split(), expected.split()
        common = sum((Counter(a) & Counter(b)).values())
        f1 = 2 * common / (len(a) + len(b)) if a and b else float(a == b)
        values.append((float(pred == expected), f1))
    return dict(exact_match=max(v[0] for v in values), f1=max(v[1] for v in values))


def matched_report(records, planned_queries):
    expected = {(qid, arm) for qid in planned_queries for arm in ARMS}
    observed = {(r["question_id"], r["arm"]) for r in records}
    if observed != expected or len(records) != len(expected):
        raise ValueError("unmatched/duplicated end-to-end census")
    profiles = set()
    by_query = {}
    for r in records:
        by_query.setdefault(r["question_id"], {})[r["arm"]] = r
        if r["status"] == "succeeded":
            rec = r["receipt"]
            profiles.add((rec["generator_identity"], rec["generator_profile"]))
    if len(profiles) > 1:
        raise ValueError("generator or decoding profile changed between arms")
    for group in by_query.values():
        baseline = group[ARMS[0]]
        for r in group.values():
            if any(
                r[k] != baseline[k]
                for k in (
                    "pool_digest",
                    "feature_digest",
                    "candidate_ids",
                    "family",
                    "phase",
                )
            ):
                raise ValueError("e2e candidate/features/family mismatch")
    summaries, contrasts = {}, {}
    for phase in sorted({r["phase"] for r in records}):
        for arm in ARMS:
            rows = [r for r in records if r["phase"] == phase and r["arm"] == arm]
            successes = [r for r in rows if r["status"] == "succeeded"]
            scored = [r for r in successes if r.get("f1") is not None]
            summaries[f"{phase}/{arm}"] = dict(
                planned=len(rows),
                succeeded=len(successes),
                failed=len(rows) - len(successes),
                scored=len(scored),
                unscored=len(rows) - len(scored),
                answerable_scored=sum(
                    r.get("target_unanswerable") is False for r in scored
                ),
                unanswerable_scored=sum(
                    r.get("target_unanswerable") is True for r in scored
                ),
                answerable_f1=(
                    sum(
                        r["f1"] for r in scored if r.get("target_unanswerable") is False
                    )
                    / sum(r.get("target_unanswerable") is False for r in scored)
                )
                if any(r.get("target_unanswerable") is False for r in scored)
                else None,
                unanswerable_f1=(
                    sum(r["f1"] for r in scored if r.get("target_unanswerable") is True)
                    / sum(r.get("target_unanswerable") is True for r in scored)
                )
                if any(r.get("target_unanswerable") is True for r in scored)
                else None,
                f1=sum(r["f1"] for r in scored) / len(scored) if scored else None,
                exact_match=sum(r["exact_match"] for r in scored) / len(scored)
                if scored
                else None,
                generated_abstentions=sum(
                    r["answer"].strip() == ABSTAIN for r in successes
                ),
                selector_abstentions=sum(r["selected"] is None for r in rows),
                literal_citation_markers=sum(
                    len(re.findall(r"\[E[1-9][0-9]*\]", r["answer"])) for r in successes
                ),
                semantic_citation_precision=None,
            )
        for mode in ("forced", "null", "calibrated"):
            family_values, changes, ranking_changes, missing = {}, 0, 0, 0
            for group in by_query.values():
                a, b = group[f"frozen_{mode}"], group[f"trained_{mode}"]
                if a["phase"] != phase:
                    continue
                changes += a["selected"] != b["selected"]
                if a["candidate_ids"]:
                    rank = lambda r: min(
                        range(len(r["candidate_ids"])),
                        key=lambda i: (-r["selector_logits"][i], r["candidate_ids"][i]),
                    )
                    ranking_changes += rank(a) != rank(b)
                if (
                    a["status"] != "succeeded"
                    or b["status"] != "succeeded"
                    or a.get("f1") is None
                    or b.get("f1") is None
                ):
                    missing += 1
                    family_values.setdefault(a["family"], []).append((-1.0, 1.0))
                else:
                    delta = b["f1"] - a["f1"]
                    family_values.setdefault(a["family"], []).append((delta, delta))
            n = len(family_values)
            lo = (
                sum(sum(v[0] for v in vs) / len(vs) for vs in family_values.values())
                / n
            )
            hi = (
                sum(sum(v[1] for v in vs) / len(vs) for vs in family_values.values())
                / n
            )
            radius = math.sqrt(2 * math.log(2 * 3 / 0.05) / n)
            contrasts[f"{phase}/{mode}"] = dict(
                answer_f1_family_delta_interval=[lo, hi],
                conservative_95_interval=[max(-1, lo - radius), min(1, hi + radius)],
                supplied_family_groups=n,
                missing_or_failed_pairs=missing,
                changed_decisions=changes,
                changed_nonnull_top1=ranking_changes,
                coverage_changed=False,
                generator_changed=False,
                threshold_refit=mode == "calibrated",
                semantic_certification=False,
            )
    return dict(
        schema="hepta.selector.same-generator.e2e.v1",
        summaries=summaries,
        contrasts=contrasts,
        census_digest=digest(records),
        official_judge_executed=False,
        production_accepted=False,
        superiority_claim=False,
        independent_semantic_precision=None,
        missing_pairs_widen_uncertainty=True,
    )
