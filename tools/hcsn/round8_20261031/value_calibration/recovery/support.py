"""Admission to the frozen training domain, never a business-success decision.

This optional caller-side check does not alter the historical confirmation.
In-domain status alone does not authorize production or establish efficacy.
"""

import json
from pathlib import Path

from .. import finite
from ..run import digest, source_manifest


class UnsupportedDomain(ValueError):
    """The public state was not admitted by the immutable preparation."""


class FrozenTrainingSupport:
    def __init__(self, prepared, *, expected_freeze_sha256):
        prepared = Path(prepared)
        freeze_path = prepared / "FREEZE.json"
        if digest(freeze_path) != expected_freeze_sha256:
            raise ValueError("untrusted preparation freeze identity")
        frozen = json.loads(freeze_path.read_text())
        if source_manifest() != frozen["source"]:
            raise ValueError("scientific execution source changed")
        graph_path = prepared / "STATE_GRAPH.json"
        if digest(graph_path) != frozen["files"]["STATE_GRAPH.json"]:
            raise ValueError("training domain bytes differ from preparation")
        graph = json.loads(graph_path.read_text())
        self.states = frozenset(finite.canonical(finite.task.State.from_dict(s)) for s in graph["states"])
        self.contracts = frozenset(s.parameters for s in self.states)
        self.freeze_sha256 = expected_freeze_sha256

    def inspect(self, state):
        if not isinstance(state, finite.task.State):
            raise TypeError("a public task State is required")
        if state.terminated:
            reason = "terminal_state_has_no_decision"
        elif state.parameters not in self.contracts:
            reason = "parameters_outside_frozen_training_contracts"
        elif finite.canonical(state) not in self.states:
            reason = "public_state_absent_from_frozen_training_graph"
        else:
            reason = "within_frozen_training_domain"
        return {"supported": reason == "within_frozen_training_domain", "reason": reason,
            "freeze_sha256": self.freeze_sha256,
            "policy_executed": False, "business_completed": False,
            "production_activation_authorized": False}

    def require_supported(self, state):
        result = self.inspect(state)
        if not result["supported"]:
            raise UnsupportedDomain(result["reason"])
        return result
