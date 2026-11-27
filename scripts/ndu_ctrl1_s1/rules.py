"""Cheap explicit baselines under the existing public kernel and price model.

These rules are post-pilot controls, not independently confirmed learned gains.
One declared credit prices each decision; actual forecasts and CPU remain metered.
"""

from dataclasses import replace

from ndu_ctrl1.model import backup, legal_actions, transitions
from ndu_ctrl1.policies import Controller, Decision, after_compute


class RuleController(Controller):
    RULES = ("execute_if_legal", "repair_then_execute", "terminal_value")

    def __init__(self, rule, profile):
        if rule not in self.RULES:
            raise ValueError("Unknown frozen rule")
        super().__init__("fixed", profile)
        self.rule = rule

    def _choose(self, scenario, state):
        charge = self.compute_charge(state)
        if charge.route == "emergency_stop":
            return charge
        admitted = after_compute(state, charge)
        self.counters["legal_mask_calls"] += 1
        legal = legal_actions(scenario, admitted)
        if self.rule == "repair_then_execute" and admitted.steps_left > 1:
            if "repair" in legal:
                return replace(charge, action="repair")
        if self.rule == "terminal_value":
            choices = [action for action in legal if action in ("stop", "execute")]
            values = {}
            for action in choices:
                outcomes = transitions(scenario, admitted, action)
                values[action] = backup(
                    outcomes, [o.reward for o in outcomes], self.profile
                )
            return Decision(max(values, key=values.get), 1, 0, len(values), len(values))
        return replace(charge, action="execute" if "execute" in legal else "stop")
