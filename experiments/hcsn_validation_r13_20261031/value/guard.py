"""A policy wrapper for the inherited finite observation contract only."""

from experiments.hcsn_regeneration_content_20261031 import policy


class TailStop:
    """Stop now if the frozen public policy would only SKIP before stopping.

    Required contract: the wrapped policy is deterministic and has no mutable
    decision state; SKIP leaves content h and its terminal readout unchanged;
    SKIP fees are nonnegative; the finite schedule is public. Simulated READ is
    never executed. This is not a guard for processes that evolve h while waiting.

    Scores remain the original trained predictor's scores. Calibration against
    this wrapper's actual Qpi therefore measures the unchanged critic after the
    declared policy transformation, not an invented refitted critic.
    """

    def __init__(self, following):
        self.following = following.following if isinstance(following, TailStop) else following
        self.reset_counts()

    def reset_counts(self):
        self.counts = dict(actor_calls=0, base_calls=0, simulated_skips=0,
                           replacements=0, max_simulated_skips=0)

    def choose(self, model, state, config):
        if config.skip_cost < 0:
            raise ValueError("Tail dominance requires nonnegative SKIP fees")
        self.counts["actor_calls"] += 1
        self.counts["base_calls"] += 1
        action, scores = self.following.choose(model, state, config)
        if action != "SKIP" or "SKIP" not in policy.legal_actions(state, config):
            return action, scores
        simulated, depth = state, 0
        while action == "SKIP" and "SKIP" in policy.legal_actions(simulated, config):
            simulated = policy.after_skip(simulated, config)
            depth += 1
            self.counts["base_calls"] += 1
            action, _ = self.following.choose(model, simulated, config)
        self.counts["simulated_skips"] += depth
        self.counts["max_simulated_skips"] = max(self.counts["max_simulated_skips"], depth)
        if action == "STOP":
            self.counts["replacements"] += 1
            return "STOP", scores
        return "SKIP", scores


def trajectory_dominance(base, guarded, skip_cost):
    """Check complete paired actual trajectories, including terminal charges."""
    left = [s for s in base["steps"] if s["executed"] == "READ"]
    right = [s for s in guarded["steps"] if s["executed"] == "READ"]
    for a, b in zip(left, right):
        if a != b:
            raise AssertionError("A real READ or accepted successor changed")
    if len(left) != len(right) or base["raw_accesses"] != guarded["raw_accesses"]:
        raise AssertionError("Raw observation access changed")
    if (base["prediction"], base["correct"]) != (guarded["prediction"], guarded["correct"]):
        raise AssertionError("Terminal content changed")
    tail = 0
    for step in reversed(base["steps"][:-1]):
        if step["executed"] != "SKIP":
            break
        tail += 1
    expected = tail * skip_cost
    errors = dict(fee=abs(base["fee"]-guarded["fee"]-expected),
                  utility=abs(guarded["return"]-base["return"]-expected))
    if max(errors.values()) > 2e-10 or guarded["return"] < base["return"]-2e-10:
        raise AssertionError(errors)
    return dict(eliminated_skips=tail, saved_task_fee=expected, errors=errors)
