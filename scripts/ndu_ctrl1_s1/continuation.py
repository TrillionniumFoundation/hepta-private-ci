"""One paid root plan with an exactly frozen fast continuation.

This opt-in v2 adapter leaves the sealed CTRL-1 v1 study unchanged. Its root
state is BEFORE the current decision charge; no credit is refunded. Every root
action is forecast through the remaining finite horizon using the same fast
checkpoint, legal actions and base fees used after the real root decision.

The original bounded Search supplies nested entropic backups. Only the root
action is optimized. A complete comparison is exact for this finite known-model
policy (up to FP64); an exhausted comparison returns the admitted fast fallback,
keeps the full invocation fee, and exposes no purported complete value. This is
not an optimal policy, a repeated learned router, or a production adoption gate.
"""

from dataclasses import dataclass

from ndu_ctrl1.learning import Learner
from ndu_ctrl1.model import Profile, Scenario, State, legal_actions
from ndu_ctrl1.policies import (
    Controller,
    Decision,
    PlanningLimit,
    Search,
    after_compute,
)
from ndu_real_runtime.objective import edge_value


@dataclass(frozen=True)
class OneSlowForecast:
    """Scores include the root computation fee and all future fast fees."""

    complete: bool
    root_action_values: tuple[tuple[str, float], ...]
    selected_action: str
    expanded_nodes: int
    fast_checkpoint_sha256: str


class OneSlowControllerV2(Controller):
    """Pure state policy: one slow root, then the retained fast checkpoint.

    State steps decrease on every nonterminal task action, so a successor cannot
    revisit the bound root. Re-evaluating the same root is deterministic and does
    not depend on an episode-local mutable 'already planned' flag.
    """

    def __init__(self, scenario, root, profile, fast, node_limit=96):
        if (
            not isinstance(scenario, Scenario)
            or not isinstance(root, State)
            or not isinstance(profile, Profile)
            or not isinstance(fast, Learner)
            or fast.profile != profile
            or type(node_limit) is not int
            or not 1 <= node_limit <= 512
            or not legal_actions(scenario, root)
        ):
            raise ValueError(
                "One-slow v2 requires a valid public root and fast checkpoint"
            )
        # Own the snapshot: later training or caller mutations cannot change the
        # policy used by either forecasting or execution in this controller.
        snapshot = Learner.from_record(fast.record())
        super().__init__("mpc", profile, snapshot, node_limit)
        self.scenario, self.root = scenario, root
        self.fast_checkpoint_sha256 = snapshot.record()["checkpoint_sha256"]
        self._fast = Controller("fast", profile, snapshot)
        self.forecast = None

    def choose(self, scenario, state):
        if scenario != self.scenario:
            raise ValueError("One-slow v2 is bound to one scenario")
        return super().choose(scenario, state)

    def compute_charge(self, state):
        if state == self.root:
            return super().compute_charge(state)
        return self._fast.compute_charge(state)

    def _choose(self, scenario, state):
        if (
            self._fast.learner is not self.learner
            or self.learner.record()["checkpoint_sha256"] != self.fast_checkpoint_sha256
        ):
            raise ValueError("The retained fast checkpoint changed")
        if state != self.root:
            return super()._choose(scenario, state)
        self.forecast = None
        charge = self.compute_charge(state)
        if charge.route != "slow":
            return super()._choose(scenario, state)

        admitted = after_compute(state, charge)
        fallback = self.fast_action(scenario, admitted)
        self.counters["legal_mask_calls"] += 1
        legal = legal_actions(scenario, admitted)
        actions = (fallback,) + tuple(action for action in legal if action != fallback)
        before_masks = self._fast.counters["legal_mask_calls"]
        search = Search(scenario, self.profile, self.node_limit, owner=self._fast)
        scores, complete = [], True
        try:
            for action in actions:
                # Full remaining steps: Search's STOP leaf is reached only when
                # the real finite policy is also exhausted, never as a surrogate
                # for a fast action that would actually execute.
                value = search.q(admitted, action, admitted.steps_left)
                scores.append(
                    (
                        action,
                        -self.profile.resource_weight * charge.cost
                        + edge_value(charge.duration, value, self.profile),
                    )
                )
        except PlanningLimit:
            complete = False
            scores = []
        self.counters["legal_mask_calls"] += (
            search.legal_mask_calls
            + self._fast.counters["legal_mask_calls"]
            - before_masks
        )
        action = max(scores, key=lambda item: item[1])[0] if complete else fallback
        self.forecast = OneSlowForecast(
            complete,
            tuple(scores),
            action,
            search.nodes,
            self.fast_checkpoint_sha256,
        )
        return Decision(
            action,
            charge.cost,
            charge.duration,
            search.nodes,
            search.nodes,
            not complete,
            "slow",
        )
