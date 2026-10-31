"""Initial STOP and an explicit repeated-observation policy, with unchanged weights."""

from dataclasses import dataclass

import torch

from ..model import ACTIONS, JointGenerator as ParentGenerator, State as ParentState


@dataclass
class State(ParentState):
    content_revision: int = 0
    verified_revision: int = -1

    def tensors(self):
        return {**super().tensors(), "content_revision": self.content_revision,
                "verified_revision": self.verified_revision}


class JointGenerator(ParentGenerator):
    """Preserve the content model; admit delivery at every nonterminal boundary.

    `deduplicate` only suppresses verification of the same content against the
    same episode-bound public observation. It does not claim a general value of
    information oracle, and must not be used for newly arriving observations.
    """

    def __init__(self, width=32, depth=1, mode="dual", boundary="direct", verify_mode="allow"):
        if verify_mode not in {"allow", "deduplicate"}:
            raise ValueError("Unknown verification policy")
        super().__init__(width, depth, mode, boundary)
        self.verify_mode = verify_mode
        self.config = {**self.config, "verify_mode": verify_mode}

    def encode(self, public):
        state = super().encode(public)
        return State(**vars(state))

    def policy(self, state, remaining, horizon=6):
        if state.stopped:
            raise ValueError("No policy query after committed STOP")
        features = self.features(state, remaining)
        logits = self.actor(features)
        legal = torch.ones_like(logits, dtype=torch.bool)
        if state.steps >= horizon:
            legal[:, :-1] = False
        elif self.verify_mode == "deduplicate" and state.verified_revision == state.content_revision:
            legal[:, ACTIONS.index("verify")] = False
        return logits.masked_fill(~legal, -torch.inf).log_softmax(-1), self.critic(features.detach())[:, 0]

    def advance(self, state, action, public, feedback_override=None):
        child, auxiliary = super().advance(state, action, public, feedback_override)
        revision = state.content_revision + int(action in ACTIONS[:5])
        verified = state.content_revision if action == "verify" else state.verified_revision
        return State(**vars(child), content_revision=revision, verified_revision=verified), auxiliary
