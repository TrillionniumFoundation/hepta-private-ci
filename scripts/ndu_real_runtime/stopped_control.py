"""Research control of one action followed by an actual terminal STOP.

The empirical law must be calibrated on the same macro: terminal quality and
action-plus-STOP duration, not an intermediate score and action-only time.
This finite profile does not replace the v4 recursive training objective.
"""

from dataclasses import dataclass
import math
import time

from .conditional_particles import UnsupportedCondition
from .controllers import PublicState
from .objective import canonical_sha, certainty_equivalent, edge_value, forecast_seed

PROFILE = "hepta.ndu.conditional-stopped.v1"
PROFILE_SPEC = {
    "id": PROFILE,
    "macro": "one_legal_action_then_STOP; STOP_is_terminal_only",
    "utility": "observed_terminal_delivery_rubric_in_unit_interval",
    "duration": "observed_action_plus_terminal_STOP_seconds",
    "planning": "separately_metered_common_sunk_cost_at_decision_cut",
    "cost_limit": "latency_only; no_money_energy_or_complete_lifecycle_claim",
    "forecast": "conditional_equal_source_group_joint_empirical_residuals",
}
PROFILE_SHA256 = canonical_sha(PROFILE_SPEC)


@dataclass(frozen=True)
class TerminalCenter:
    next_features: tuple
    utility: float
    duration_seconds: float

    def validate(self, width):
        try:
            finite = isinstance(self.next_features, tuple) and all(
                type(v) in (int, float) and math.isfinite(v)
                for v in (*self.next_features, self.utility, self.duration_seconds)
            )
        except OverflowError as error:
            raise ValueError(
                "Terminal prediction exceeds the finite numeric domain"
            ) from error
        if (
            not finite
            or len(self.next_features) != width
            or not 0 <= self.utility <= 1
            or not 0 < self.duration_seconds <= 3600
        ):
            raise ValueError("Invalid frozen terminal-macro center")


class StoppedController:
    """Use joint empirical terminal outcomes without online reference labels.

    predictor.center(PublicState, action) supplies a frozen mean forecast. The
    residual bank supplies joint utility/duration scenarios conditioned only on
    current public features and action. Its nearest-neighbor support is an
    empirical restriction, not a confidence certificate or a deadline guarantee.
    """

    def __init__(
        self,
        predictor,
        bank,
        plan,
        *,
        practical_margin=0.0,
        seed=0,
        clock=time.perf_counter,
    ):
        if plan.horizon != 1 or plan.particles < 2:
            raise ValueError(
                "Stopped control requires horizon one and multiple particles"
            )
        if (
            type(practical_margin) not in (int, float)
            or not math.isfinite(practical_margin)
            or not 0 <= practical_margin <= 1
            or type(seed) is not int
            or not 0 <= seed < 2**64
        ):
            raise ValueError("Invalid frozen margin or seed")
        self.predictor, self.bank, self.plan = predictor, bank, plan
        self.margin, self.seed, self.clock = practical_margin, seed, clock
        self.binding = bank.to_dict()["binding"]
        if self.binding["profile_sha256"] != PROFILE_SHA256:
            raise ValueError(
                "Calibration law does not declare terminal-macro cost semantics"
            )
        if predictor.binding != self.binding:
            raise ValueError(
                "Active frozen predictor differs from the calibration identity"
            )

    def scenarios(self, state, action):
        if not isinstance(state, PublicState) or action not in state.legal_actions:
            raise ValueError("A legal action and checked public state are required")
        residuals, diagnostic = self.bank.sample(
            state.features,
            action,
            particles=self.plan.particles,
            seed=forecast_seed(self.seed, state.step, action),
        )
        center = self.predictor.center(state, action)
        if not isinstance(center, TerminalCenter):
            raise TypeError("Frozen predictor must return a terminal-macro center")
        center.validate(len(state.features))
        scenarios, clipped = [], 0
        for residual in residuals:
            raw_utility = center.utility + residual.utility_residual
            log_seconds = (
                math.log(center.duration_seconds) + residual.log_duration_residual
            )
            if not math.isfinite(log_seconds) or log_seconds > math.log(3600):
                raise ValueError("Joint duration scenario exceeds the finite profile")
            seconds = math.exp(log_seconds)
            if not math.isfinite(seconds) or not 0 < seconds <= 3600:
                raise ValueError("Joint duration scenario exceeds the finite profile")
            utility = min(1.0, max(0.0, raw_utility))
            clipped += utility != raw_utility
            scenarios.append((utility, seconds, residual.probability))
        values = [edge_value(t, u, self.plan) for u, t, _ in scenarios]
        return tuple(scenarios), {
            **diagnostic,
            "utility_clipped_particles": clipped,
            "distinct_terminal_values": len(set(values)),
            "terminal_value_risk_sensitive": len(set(values)) > 1,
        }

    def choose(self, state):
        if not isinstance(state, PublicState):
            raise TypeError("A checked public state is required")
        if self.predictor.binding != self.binding:
            raise ValueError(
                "Active predictor identity changed after controller admission"
            )
        started = self.clock()
        receipt = {
            "profile": PROFILE,
            "law_sha256": self.bank.sha256,
            "horizon": 1,
            "macro": PROFILE_SPEC["macro"],
            "profile_sha256": PROFILE_SHA256,
            "risk": self.plan.risk,
            "practical_margin": self.margin,
            "predicted_values": {},
            "unsupported_actions": {},
            "over_budget_actions": [],
            "forecast_calls": 0,
            "prediction_is_external_evidence": False,
            "conditional_coverage_established": False,
            "net_benefit_established": False,
            "cost_scope": "observed_macro_latency; planning_recorded_separately; money_energy_unknown",
        }
        if len(state.legal_actions) > self.plan.max_forecasts:
            return "STOP", {
                **receipt,
                "planner_budget_exhausted": True,
                "reason": "cannot_cover_all_legal_roots",
                "planning_seconds": self.clock() - started,
                "required_execution_macro": ["STOP"],
            }
        outcomes, diagnostics = {}, {}
        # STOP gets the same forecast/CE treatment as every continuation macro.
        actions = ("STOP", *(a for a in state.legal_actions if a != "STOP"))
        for action in actions:
            receipt["forecast_calls"] += 1
            try:
                outcomes[action], diagnostics[action] = self.scenarios(state, action)
            except UnsupportedCondition as error:
                receipt["unsupported_actions"][action] = str(error)
        if "STOP" not in outcomes:
            raise UnsupportedCondition(
                "No supported terminal STOP law; no value claim admitted"
            )
        for action, rows in outcomes.items():
            receipt["predicted_values"][action] = certainty_equivalent(
                [
                    edge_value(seconds, utility, self.plan)
                    for utility, seconds, _ in rows
                ],
                [probability for _, _, probability in rows],
                self.plan.risk,
            )
        # Already spent planning is charged once by the episode owner. Here the
        # decision compares incremental macros from this common decision cut.
        elapsed = self.clock() - started
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid monotonic planning observation")
        remaining = max(0.0, state.remaining_seconds - elapsed)
        eligible = ["STOP"]
        for action, rows in outcomes.items():
            if any(seconds > remaining for _, seconds, _ in rows):
                receipt["over_budget_actions"].append(action)
            elif action != "STOP":
                eligible.append(action)
        scores = receipt["predicted_values"]
        best = max(eligible, key=lambda action: scores[action])
        if scores[best] <= scores["STOP"] + self.margin:
            best = "STOP"
        return best, {
            **receipt,
            "terminal_scenarios": outcomes,
            "diagnostics": diagnostics,
            "planning_seconds": self.clock() - started,
            "remaining_seconds_at_budget_check": remaining,
            "planner_budget_exhausted": False,
            "selected_action": best,
            "required_execution_macro": ["STOP"] if best == "STOP" else [best, "STOP"],
            "predicted_increment_over_stop": scores[best] - scores["STOP"],
            "deadline_guarantee": False,
        }
