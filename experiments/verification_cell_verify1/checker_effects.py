"""Empirical joint checker channels for one frozen task/event/continuation scope.

Panels contain actual paired observations of the same candidate snapshot. Exact
history conditioning preserves shared failures; it never multiplies marginal
checker likelihoods. Counts are descriptive, without IID or confidence claims.
Hashes bind supplied evidence but do not authenticate its issuer or truth.
"""

from collections import Counter
from dataclasses import asdict, dataclass
import math
import re

from .check_voi import CheckerChannel
from .contracts import digest


OUTCOMES = ("pass", "fail", "unknown")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _require(type(value) is str and 0 < len(value) <= 128 and value.strip() == value
             and value.isprintable(),
             "expected bounded nonempty text")


def _sha(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             "expected lowercase SHA256")


def _number(value, maximum=1e12):
    _require(type(value) in (int, float), "expected numeric value excluding bool")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("expected finite number") from error
    _require(math.isfinite(result) and result >= 0
             and (maximum is None or result <= maximum), "number outside range")
    return result


def _groups(values):
    _require(type(values) in (tuple, list) and values, "source groups required")
    for value in values:
        _text(value)
    _require(len(set(values)) == len(values), "duplicate source group")
    return tuple(sorted(values))


@dataclass(frozen=True)
class EffectScope:
    domain: str
    event: str
    horizon_start: int
    horizon_end: int
    continuation_policy_sha256: str
    context_sha256: str

    def __post_init__(self):
        _text(self.domain)
        _text(self.event)
        _sha(self.continuation_policy_sha256)
        _sha(self.context_sha256)
        _require(type(self.horizon_start) is int and type(self.horizon_end) is int
                 and 0 <= self.horizon_start <= self.horizon_end, "invalid horizon")


@dataclass(frozen=True)
class CheckerSpec:
    checker_id: str
    version_sha256: str
    cost: float

    def __post_init__(self):
        _text(self.checker_id)
        _sha(self.version_sha256)
        object.__setattr__(self, "cost", _number(self.cost))


@dataclass(frozen=True)
class PairedPanel:
    panel_id: str
    source_group: str
    snapshot_sha256: str
    scope: EffectScope
    checker_ids: tuple[str, ...]
    checker_versions: tuple[str, ...]
    outcomes: tuple[str, ...]
    error: bool | None
    label_evidence_sha256: str | None
    checker_evidence_sha256: tuple[str, ...]
    missing_label_reason: str | None = None

    def __post_init__(self):
        _text(self.panel_id)
        _text(self.source_group)
        _sha(self.snapshot_sha256)
        _require(type(self.scope) is EffectScope, "invalid effect scope")
        for name in ("checker_ids", "checker_versions", "outcomes", "checker_evidence_sha256"):
            values = getattr(self, name)
            _require(type(values) in (tuple, list) and 1 <= len(values) <= 8,
                     "panel needs one to eight paired checker observations")
            object.__setattr__(self, name, tuple(values))
        _require(len(self.checker_ids) == len(self.checker_versions) == len(self.outcomes)
                 == len(self.checker_evidence_sha256), "incomplete paired panel")
        for value in self.checker_ids:
            _text(value)
        _require(len(set(self.checker_ids)) == len(self.checker_ids), "duplicate checker ID")
        _require(all(type(value) is str and value in OUTCOMES for value in self.outcomes), "unknown outcome")
        for value in self.checker_versions + self.checker_evidence_sha256:
            _sha(value)
        _require(self.error is None or type(self.error) is bool, "invalid outcome label")
        if self.error is None:
            _require(self.label_evidence_sha256 is None, "missing label has label evidence")
            _text(self.missing_label_reason)
        else:
            _sha(self.label_evidence_sha256)
            _require(self.missing_label_reason is None, "known label has missing reason")


@dataclass(frozen=True)
class ConditionedEffects:
    status: str
    reason: str
    posterior_error: float | None
    channels: tuple[CheckerChannel, ...]
    class_counts: tuple[int, int]
    history_counts: tuple[int, int]
    model_sha256: str


@dataclass(frozen=True)
class EffectsModel:
    scope: EffectScope
    checkers: tuple[CheckerSpec, ...]
    training_groups: tuple[str, ...]
    heldout_groups: tuple[str, ...]
    table: tuple[tuple[bool, tuple[str, ...], int], ...]
    observed_group_counts: tuple[tuple[str, int, int], ...]
    missing_labels: int
    min_class_count: int
    data_sha256: str
    model_sha256: str

    def condition(self, prior_error, history=None, *, scope):
        """Condition the *pre-history* prior and return correct/error row channels.

        The prior and panel channels must share the exact pre-check observable
        context bound by scope.context_sha256. Use the complete history and the
        original prior, not an already updated prior. Zero-support observed
        histories refuse; hypothetical zero cells remain empirical plug-in
        estimates for research, never proof of impossibility. Every truth class
        needs minimum support. Declared costs do not qualify full physical cost.
        """
        prior = _number(prior_error, 1)
        history = {} if history is None else history
        _require(type(history) is dict, "history must map checker IDs to outcomes")
        indices = {checker.checker_id: index for index, checker in enumerate(self.checkers)}
        _require(all(type(key) is str and key in indices and type(value) is str
                     and value in OUTCOMES for key, value in history.items()),
                 "history contains an unregistered checker or outcome")
        counts = tuple(sum(n for truth, _, n in self.table if truth is label)
                       for label in (False, True))
        selected = tuple((truth, outcomes, n) for truth, outcomes, n in self.table
                         if all(outcomes[indices[key]] == value for key, value in history.items()))
        matched = tuple(sum(n for truth, _, n in selected if truth is label)
                        for label in (False, True))
        reason = ("scope_mismatch" if type(scope) is not EffectScope or scope != self.scope
                  else "insufficient_class_support" if min(counts) < self.min_class_count
                  else "insufficient_history_support" if min(matched) < self.min_class_count
                  else None)
        if reason:
            return ConditionedEffects("unsupported", reason, None, (), counts, matched,
                                      self.model_sha256)
        weights = ((1 - prior) * matched[0] / counts[0], prior * matched[1] / counts[1])
        posterior = weights[1] / math.fsum(weights)
        channels = tuple(CheckerChannel(
            checker.checker_id, OUTCOMES,
            tuple(tuple(sum(n for truth, outcomes, n in selected
                            if truth is label and outcomes[index] == outcome) / matched[int(label)]
                        for outcome in OUTCOMES) for label in (False, True)), checker.cost)
            for index, checker in enumerate(self.checkers))
        return ConditionedEffects("supported", "empirical_joint_counts_only", posterior,
                                  channels, counts, matched, self.model_sha256)

    def diagnostics(self):
        """Keep counts/denominators and distinguish UNKNOWN from a false pass."""
        counts = tuple(sum(n for truth, _, n in self.table if truth is label)
                       for label in (False, True))

        def rate(label, predicate):
            denominator = counts[int(label)]
            numerator = sum(n for truth, outcomes, n in self.table
                            if truth is label and predicate(outcomes))
            return {"numerator": numerator, "denominator": denominator,
                    "value": numerator / denominator if denominator else None}

        return {
            "schema": "hepta.verify.checker-effects.v1", "data_sha256": self.data_sha256,
            "model_sha256": self.model_sha256, "scope": asdict(self.scope),
            "class_order": ["correct", "error"], "class_counts": list(counts),
            "missing_labels_excluded": self.missing_labels, "min_class_count": self.min_class_count,
            "training_groups": list(self.training_groups), "heldout_groups": list(self.heldout_groups),
            "observed_group_counts": {group: {"known_labels": known, "missing_labels": missing}
                                      for group, known, missing in self.observed_group_counts},
            "minimum_support_is_confidence_guarantee": False,
            "source_groups_establish_independent_samples": False,
            "full_physical_cost_complete": False, "cost_units": "declared_decision_loss",
            "checkers": [{"checker_id": checker.checker_id,
                          "version_sha256": checker.version_sha256, "cost": checker.cost,
                          "sensitivity": rate(True, lambda o: o[i] == "fail"),
                          "false_positive_rate": rate(False, lambda o: o[i] == "fail"),
                          "unknown_given_error": rate(True, lambda o: o[i] == "unknown"),
                          "unknown_given_correct": rate(False, lambda o: o[i] == "unknown")}
                         for i, checker in enumerate(self.checkers)],
            "paired_errors": [{"checkers": [left.checker_id, right.checker_id],
                               "common_miss_including_unknown": rate(True, lambda o: o[i] != "fail" and o[j] != "fail"),
                               "common_false_pass": rate(True, lambda o: o[i] == o[j] == "pass")}
                              for i, left in enumerate(self.checkers)
                              for j, right in enumerate(self.checkers) if i < j],
        }


def fit_checker_effects(panels, *, scope, checkers, training_groups, heldout_groups,
                        min_class_count=2):
    """Fit exact joint frequencies using labeled training panels only.

    All listed checkers must have run on each same snapshot without modifying it.
    This is a declared collection contract, not an authenticated execution proof.
    No label or outcome is silently imputed; UNKNOWN is an observed result.
    Missing labels are excluded, so the channels describe the labeled subset;
    missingness identification and transport to other contexts are unproved.
    """
    _require(type(scope) is EffectScope, "invalid scope")
    _require(type(checkers) in (tuple, list) and 1 <= len(checkers) <= 8,
             "one to eight checkers required")
    checkers = tuple(checkers)
    _require(all(type(checker) is CheckerSpec for checker in checkers), "invalid checker spec")
    _require(len({checker.checker_id for checker in checkers}) == len(checkers), "duplicate checker ID")
    train, heldout = _groups(training_groups), _groups(heldout_groups)
    _require(not set(train).intersection(heldout), "training/heldout group overlap")
    _require(type(min_class_count) is int and min_class_count >= 2, "minimum support must be >=2")
    _require(type(panels) in (tuple, list) and 0 < len(panels) <= 100000, "bounded panel roster required")
    _require(all(type(panel) is PairedPanel for panel in panels), "invalid paired panel")
    panels = tuple(sorted(panels, key=lambda panel: panel.panel_id))
    _require(len({panel.panel_id for panel in panels}) == len(panels), "duplicate panel ID")
    _require(len({panel.snapshot_sha256 for panel in panels}) == len(panels), "duplicate candidate snapshot")
    versions = tuple(checker.version_sha256 for checker in checkers)
    for panel in panels:
        _require(panel.source_group in train, "panel is outside declared training groups")
        _require(panel.scope == scope, "panel scope mismatch")
        _require(panel.checker_ids == tuple(checker.checker_id for checker in checkers),
                 "checker roster/order mismatch")
        _require(panel.checker_versions == versions, "checker roster/version mismatch")
    _require({panel.source_group for panel in panels} == set(train),
             "declared training groups must match observed groups")
    coverage = Counter((panel.source_group, panel.error is None) for panel in panels)
    group_counts = tuple((group, coverage[group, False], coverage[group, True]) for group in train)
    counts = Counter((panel.error, panel.outcomes) for panel in panels if panel.error is not None)
    table = tuple((truth, outcomes, n) for (truth, outcomes), n in sorted(counts.items()))
    missing = sum(panel.error is None for panel in panels)
    data_sha = digest([asdict(panel) for panel in panels])
    model_sha = digest({"schema": "hepta.verify.checker-effects.v1", "scope": asdict(scope),
                        "checkers": [asdict(checker) for checker in checkers], "training_groups": train,
                        "heldout_groups": heldout, "table": table, "observed_group_counts": group_counts,
                        "missing_labels": missing,
                        "min_class_count": min_class_count, "data_sha256": data_sha})
    return EffectsModel(scope=scope, checkers=checkers, training_groups=train, heldout_groups=heldout,
                        table=table, observed_group_counts=group_counts, missing_labels=missing,
                        min_class_count=min_class_count, data_sha256=data_sha, model_sha256=model_sha)
