"""Bind risk, paired checker effects and advisory VOI at one observed frontier.

The trusted caller retains permissions, schema checks, original-owner checks and
fresh terminal acceptance. This module cannot execute a check or accept a task.
All losses include residual repair errors and downstream mandatory work; omitting
that work can make a redundant optional check appear valuable. Declared costs
are not physical cost measurements. This path is shadow-only until qualification.
"""

from dataclasses import asdict, dataclass

from .checker_effects import EffectScope, EffectsModel, OUTCOMES
from .check_voi import DecisionProblem, select_check_voi
from .contracts import _require, _sha, _text, digest
from .shadow_risk import Prediction


def observation_context(snapshot):
    """A public pre-check stratum, excluding identity, outcome and checker history."""
    return digest({"observed_step": snapshot.observed_step,
                   "features": snapshot.features})


@dataclass(frozen=True)
class CheckObservation:
    checker_id: str
    version_sha256: str
    snapshot_sha256: str
    outcome: str
    evidence_sha256: str

    def __post_init__(self):
        _text(self.checker_id, "checker_id")
        for name in ("version_sha256", "snapshot_sha256", "evidence_sha256"):
            _sha(getattr(self, name), name)
        _require(type(self.outcome) is str and self.outcome in OUTCOMES,
                 "unregistered checker outcome")


def select_shadow_check(prediction, effects, observations, actions, losses,
                        remaining_budget, *, hard_checks_complete):
    """Choose an optional check using the original pre-history risk probability.

`hard_checks_complete` is a trusted-host input, not a serialized capability. False
blocks this optional path; a checker model cannot satisfy a mandatory owner gate.
`actions` and `losses` describe feasible follow-up decisions (including repair
cost and residual risk). Recommendations never perform those decisions.
"""
    _require(type(prediction) is Prediction and type(effects) is EffectsModel,
             "typed risk prediction and checker model required")
    _require(type(hard_checks_complete) is bool, "explicit host gate required")
    snapshot = prediction.snapshot
    _require(snapshot.source_group in effects.heldout_groups
             and snapshot.source_group not in effects.training_groups,
             "checker evaluation group is not frozen or leaks into training")
    _require(type(observations) in (tuple, list) and len(observations) <= 8,
             "bounded checker history required")
    history, versions = {}, {item.checker_id: item.version_sha256
                             for item in effects.checkers}
    for item in observations:
        _require(type(item) is CheckObservation, "invalid checker observation")
        _require(item.checker_id not in history, "duplicate checker history")
        _require(versions.get(item.checker_id) == item.version_sha256,
                 "checker version/identity changed")
        _require(item.snapshot_sha256 == digest(asdict(snapshot)),
                 "checker observation belongs to a different snapshot")
        history[item.checker_id] = item.outcome
    target = snapshot.target
    scope = EffectScope(domain=target.domain, event=target.event,
                        horizon_start=snapshot.observed_step,
                        horizon_end=target.horizon_end,
                        continuation_policy_sha256=target.continuation_policy_sha256,
                        context_sha256=observation_context(snapshot))
    # Validate declared decision quantities even when a host gate blocks selection.
    problem = DecisionProblem(("correct", "error"), (0.5, 0.5), actions, losses)
    select_check_voi(problem, (), remaining_budget)
    result = {"schema": "hepta.verify.shadow-choice.v1",
              "snapshot_sha256": digest(asdict(snapshot)),
              "risk_model_sha256": prediction.model_sha256,
              "checker_model_sha256": effects.model_sha256,
              "checker_data_sha256": effects.data_sha256,
              "history_sha256": digest([asdict(item) for item in observations]),
              "scope": asdict(scope), "pre_history_risk": prediction.probability,
              "decision_contract": {"states": problem.states, "actions": problem.actions,
                                    "losses": problem.losses,
                                    "remaining_budget": float(remaining_budget),
                                    "hard_checks_complete": hard_checks_complete,
                                    "cost_units": "declared_decision_loss"},
              "posterior_error": None, "selection": None,
              "production_authority": "NONE", "full_physical_cost_complete": False}
    if not hard_checks_complete:
        result.update(status="blocked", reason="mandatory_host_checks_pending")
    elif prediction.probability is None:
        result.update(status="unsupported", reason="risk_context_unseen")
    else:
        conditioned = effects.condition(prediction.probability, history, scope=scope)
        result.update(status=conditioned.status, reason=conditioned.reason)
        if conditioned.status == "supported":
            posterior = conditioned.posterior_error
            problem = DecisionProblem(problem.states, (1 - posterior, posterior),
                                      problem.actions, problem.losses)
            selection = select_check_voi(problem, conditioned.channels, remaining_budget)
            result.update(status=selection.status, reason=selection.reason,
                          posterior_error=posterior, selection=asdict(selection))
    result["record_sha256"] = digest(result)
    return result
