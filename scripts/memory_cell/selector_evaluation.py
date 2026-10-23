"""Isolated annotation side: source coverage, weak training labels, and calibration.

No function here is called from candidate_windows or the paired encoder. Gold
answers measure literal coverage only AFTER predictions; they are never features.
"""

from dataclasses import dataclass
import math
import re

from native import digest
from selector_head import Supervision
from sessions import source_id

HARD_KINDS = frozenset(
    {
        "same_person_different_time",
        "same_entity_different_relation",
        "superseded_fact",
        "nearby_irrelevant",
    }
)
OFFSETS = (-8.0, -4.0, -2.0, 0.0, 2.0, 4.0, 8.0)


@dataclass(frozen=True)
class ReviewedWindows:
    """Already-admitted training-window labels, not a self-issued attestation."""

    pool_digest: str
    admission_digest: str
    positives: tuple[str, ...]
    negatives: tuple[tuple[str, str], ...]
    unanswerable: bool

    def validate(self, pool, cut):
        ids = {w.identity() for w in pool.windows}
        positive, negative = set(self.positives), dict(self.negatives)
        if (
            self.pool_digest != pool.seal()
            or self.admission_digest != cut.admission_digest
            or type(self.unanswerable) is not bool
            or len(positive) != len(self.positives)
            or len(negative) != len(self.negatives)
            or positive & set(negative)
            or positive | set(negative) != ids
            or any(kind not in HARD_KINDS for kind in negative.values())
            or self.unanswerable != (not positive)
        ):
            raise ValueError("reviewed training-window census/admission mismatch")
        return tuple(
            i for i, w in enumerate(pool.windows) if w.identity() in positive
        ), negative


def support_indices(pool, target):
    supported = {source_id(s) for s in target.evidence}
    return tuple(
        i for i, w in enumerate(pool.windows) if source_id(w.source_id) in supported
    )


def train_rows(
    queries,
    targets,
    pools,
    features,
    cut,
    *,
    reviewed_negatives=None,
    reviewed_windows=None,
):
    """Only predeclared training annotations can enter this function.

    Native source support is weak window supervision. Missing support is NOT turned
    into no-answer. Optional externally reviewed hard negatives are an input, never
    invented from dates/entity overlap; their source family and candidate binding are
    checked, but authenticating their independent reviewer belongs to the owner.
    """
    rows, skipped, tags = [], [], {}
    for q in queries:
        if q.identity not in cut.question_ids:
            raise ValueError("attempt to read nontraining annotations")
        f, pool = features[q.identity], pools[q.identity]
        if f.family not in cut.families or f.pool_digest != pool.seal():
            raise ValueError("family or candidate feature mismatch")
        explicit = (reviewed_windows or {}).get(q.identity)
        if explicit is not None:
            pos, negative = explicit.validate(pool, cut)
        else:
            t = targets[q.identity]
            pos = support_indices(pool, t)
            if t.unresolved_evidence or (not t.unanswerable and not pos):
                skipped.append(
                    dict(
                        question_id=q.identity,
                        reason="unresolved_or_missing_positive_not_abstention",
                    )
                )
                continue
            if t.unanswerable:
                pos = ()
            negative = (reviewed_negatives or {}).get(q.identity, {})
        by_id = {w.identity(): i for i, w in enumerate(pool.windows)}
        for identity, kind in negative.items():
            if (
                identity not in by_id
                or by_id[identity] in pos
                or kind not in HARD_KINDS
            ):
                raise ValueError("invalid reviewed hard-negative binding")
            tags[kind] = tags.get(kind, 0) + 1
        rows.append(Supervision(f, pos, tuple(sorted(negative.values()))))
    return tuple(rows), dict(
        skipped_training=skipped,
        reviewed_negative_counts=tags,
        unannotated_candidates_are_weak_distractors=True,
        missing_support_used_as_null=False,
        supervision_level="native-document-support-not-window-entailment",
    )


def correctness(pool, target, selected):
    if target.unresolved_evidence:
        return None
    if target.unanswerable:
        return int(selected is None)
    if not target.evidence:
        return None
    return int(selected is not None and selected in support_indices(pool, target))


def calibration(
    head, entries, targets, *, mode, permitted_questions, permitted_families
):
    trials = []
    for offset in OFFSETS:
        families = {}
        for query, family, pool, features in entries:
            if (
                query.identity not in permitted_questions
                or family not in permitted_families
            ):
                raise ValueError("nonselection target would be read")
            selected, _ = head.decide(features, revoked=set(), offset=offset, mode=mode)
            value = correctness(pool, targets[query.identity], selected)
            if value is not None:
                families.setdefault(family, []).append(value)
        means = {f: sum(v) / len(v) for f, v in families.items()}
        score = sum(means.values()) / len(means) if means else -1
        trials.append(dict(offset=offset, family_means=means, score=score))
    # Preregistered tie-break; never search offsets on test data.
    best = min(trials, key=lambda t: (-t["score"], abs(t["offset"]), t["offset"]))
    return dict(
        chosen=best,
        trials=trials,
        mode=mode,
        selection_only=True,
        probabilities_calibrated=False,
        selection_roots=sorted(set().union(*(f.roots for _, _, _, f in entries))),
    )


def coverage(documents, pool, target):
    if target.unanswerable or target.unresolved_evidence or not target.evidence:
        return dict(
            retrieved_source_fraction=None,
            scanned_literal_answer=None,
            candidate_literal_answer=None,
            candidate_source_fraction=None,
        )
    gold = {source_id(s) for s in target.evidence}
    fraction = lambda ids: len(gold & set(ids)) / len(gold)
    needle = target.answer.casefold().strip() if target.answer else ""
    return dict(
        retrieved_source_fraction=fraction(source_id(d.identity) for d in documents),
        candidate_source_fraction=fraction(
            source_id(w.source_id) for w in pool.windows
        ),
        scanned_literal_answer=(
            any(needle in s["excerpt"].casefold() for s in pool.inspected)
            if needle
            else None
        ),
        candidate_literal_answer=(
            any(needle in w.text.casefold() for w in pool.windows) if needle else None
        ),
    )


def diagnose(answer, target):
    from collections import Counter

    if target.answer is None:
        return None
    norm = lambda s: re.findall(r"\w+", re.sub(r"\b(a|an|the)\b", " ", s.casefold()))
    a, b = norm(answer), norm(target.answer)
    return (
        2 * sum((Counter(a) & Counter(b)).values()) / (len(a) + len(b))
        if a and b
        else float(a == b)
    )


def summarize(rows):
    grouped, f1s, decisions = {}, [], []
    for r in rows:
        if r.get("source_choice_correct") is not None:
            grouped.setdefault(r["family"], []).append(r["source_choice_correct"])
        if r.get("diagnostic_f1") is not None:
            f1s.append(r["diagnostic_f1"])
        if r["status"] == "succeeded":
            decisions.append(r)
    means = {k: sum(v) / len(v) for k, v in grouped.items()}
    n = len(means)
    average = sum(means.values()) / n if n else None
    radius = math.sqrt(math.log(2 * 5 / 0.05) / (2 * n)) if n else 1
    return dict(
        planned=len(rows),
        succeeded=len(decisions),
        failed=len(rows) - len(decisions),
        family_means=means,
        independent_family_count=n,
        source_choice_family_mean=average,
        simultaneous_source_choice_interval=[
            max(0, average - radius),
            min(1, average + radius),
        ]
        if n
        else None,
        diagnostic_f1=sum(f1s) / len(f1s) if f1s else None,
        diagnostic_scored_n=len(f1s),
        abstained=sum(r["selected"] is None for r in decisions),
        structural_citation_count=sum(r["selected"] is not None for r in decisions),
        semantic_citation_precision=None,
        production_accepted=False,
        omitted_score_cases=len(rows) - len(f1s),
        census_digest=digest(rows),
    )


def factorial_contrasts(rows):
    """Paired differences, not comparisons of unrelated denominators/pools."""
    contrasts = (
        ("coverage", "prefix_frozen_top1", "windows_frozen_top1"),
        ("abstention", "windows_frozen_top1", "windows_frozen_null"),
        ("learning", "windows_frozen_null", "windows_trained_null"),
    )
    result = {}
    for phase in sorted({r["phase"] for r in rows}):
        for name, base, candidate in contrasts:
            pair = {}
            for arm in (base, candidate):
                group = [r for r in rows if r["phase"] == phase and r["arm"] == arm]
                pair[arm] = {r["question_id"]: r for r in group}
                if len(pair[arm]) != len(group):
                    raise ValueError("duplicated contrast observation")
            if set(pair[base]) != set(pair[candidate]) or not pair[base]:
                raise ValueError("unpaired contrast census")
            families, matched = {}, 0
            for qid, a in pair[base].items():
                b = pair[candidate][qid]
                if a["family"] != b["family"]:
                    raise ValueError("contrast family drift")
                if name != "coverage" and a["status"] == b["status"] == "succeeded":
                    if any(
                        a[k] != b[k]
                        for k in (
                            "pool_digest",
                            "scored_features_digest",
                            "candidate_ids",
                        )
                    ):
                        raise ValueError(
                            "head/abstention comparison changed candidate inputs"
                        )
                av, bv = a.get("source_choice_correct"), b.get("source_choice_correct")
                if av is not None and bv is not None:
                    families.setdefault(a["family"], []).append(bv - av)
                    matched += 1
            means = {k: sum(v) / len(v) for k, v in families.items()}
            n = len(means)
            delta = sum(means.values()) / n if n else None
            radius = math.sqrt(2 * math.log(2 * 3 / 0.05) / n) if n else 2
            result[f"{phase}/{name}"] = dict(
                base=base,
                candidate=candidate,
                planned_pairs=len(pair[base]),
                annotated_pairs=matched,
                family_deltas=means,
                family_mean_delta=delta,
                simultaneous_95_interval=[
                    max(-1, delta - radius),
                    min(1, delta + radius),
                ]
                if n
                else None,
                interval_scope="three contrasts within this dataset; supplied families assumed independent",
                same_candidates_required=name != "coverage",
                production_accepted=False,
            )
    return result
