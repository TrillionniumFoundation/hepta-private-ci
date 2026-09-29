"""Pure paired prediction metrics; NOT a second evaluator or holdout owner.

The native signed-evaluation and durable final-holdout owners remain responsible
for authorization, final-window consumption, source authenticity and admission.
This leaf accepts a frozen labeled batch and two complete prediction tables. It
neither trains models, infers outcomes, chooses thresholds nor promotes artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_ROWS = 256


@dataclass(frozen=True)
class LabeledChoices:
    row_id: str
    group_id: str
    outcome_digest: str
    option_ids: tuple[str, ...]
    gold_id: str


def _distribution(value, size):
    if (type(value) is not tuple or len(value) != size or any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in value)
            or abs(math.fsum(value) - 1) > 1e-6):
        raise ValueError("complete finite normalized prediction required")
    return value


def paired_metrics(labels: tuple[LabeledChoices, ...], baseline: dict, candidate: dict) -> dict:
    """Equal weight per independent *declared* group, then per row in that group.

    Group identity is supplied by the observing owner; merely choosing different
    strings is not evidence of independence. Empty/missing/duplicate observations
    reject, instead of disappearing from the denominator. Identical predictions
    represent the mandatory no-change comparison. There is no acceptance boolean.
    """
    if type(labels) is not tuple or not 1 <= len(labels) <= MAX_ROWS:
        raise ValueError("bounded nonempty labeled batch required")
    if type(baseline) is not dict or type(candidate) is not dict:
        raise ValueError("prediction table type")
    rows, outcomes = {}, set()
    for row in labels:
        if type(row) is not LabeledChoices:
            raise ValueError("label type")
        if any(not isinstance(x, str) or not ID.fullmatch(x) for x in (row.row_id, row.group_id)):
            raise ValueError("label identity")
        if (not isinstance(row.outcome_digest, str) or not HEX.fullmatch(row.outcome_digest)
                or row.outcome_digest == "0" * 64 or row.outcome_digest in outcomes):
            raise ValueError("duplicate or invalid independently observed outcome")
        options = row.option_ids
        if (type(options) is not tuple or not 2 <= len(options) <= 9 or options[0] != "abstain"
                or any(not isinstance(x, str) or not ID.fullmatch(x) for x in options)
                or len(set(options)) != len(options) or tuple(sorted(options[1:])) != options[1:]
                or row.gold_id not in options or row.row_id in rows):
            raise ValueError("label or complete ordered candidate set")
        rows[row.row_id] = row
        outcomes.add(row.outcome_digest)
    if set(baseline) != set(rows) or set(candidate) != set(rows):
        raise ValueError("prediction coverage differs from fixed observation batch")
    groups = {}
    digest_rows = []
    for row_id, row in sorted(rows.items()):
        gold = row.option_ids.index(row.gold_id)
        values = []
        distributions = []
        for table in (baseline, candidate):
            p = _distribution(table[row_id], len(row.option_ids))
            distributions.append(p)
            chosen = max(range(len(p)), key=p.__getitem__)
            values.append((float(chosen == gold), -math.log(max(p[gold], 1e-12)),
                           math.fsum((v - float(i == gold)) ** 2 for i, v in enumerate(p))))
        groups.setdefault(row.group_id, []).append(values)
        digest_rows.append([row_id, row.group_id, row.outcome_digest, row.option_ids,
                            row.gold_id, *distributions])
    def aggregate(side):
        return {name: math.fsum(math.fsum(v[side][i] for v in group) / len(group)
                               for group in groups.values()) / len(groups)
                for i, name in enumerate(("accuracy", "log_loss", "brier"))}
    old, new = aggregate(0), aggregate(1)
    return {"schema": "hepta.cell-paired-metrics.v1", "rows": len(rows), "groups": len(groups),
            "weighting": "equal-declared-group-then-row", "log_probability_floor": 1e-12,
            "batch_digest": hashlib.sha256(json.dumps(digest_rows, separators=(",", ":"),
                                                       allow_nan=False).encode()).hexdigest(),
            "baseline": old, "candidate": new,
            "candidate_minus_baseline": {name: new[name] - old[name] for name in old},
            "source_authentication": False, "independent_acceptance": False,
            "final_holdout_consumed": False, "production_selection": False}
