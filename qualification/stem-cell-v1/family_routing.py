"""Parent-first routing for a 16-to-32 offline candidate, not a new runtime owner.

Top-2 PARENT groups keep their original softmax mass; one of the two children
per group executes. Identical children therefore preserve the parent function
in real arithmetic, regardless of the sibling selector. Finite-precision parity
is separately checked on bounded training probes, never inferred globally.

Hard sibling selection has no pathwise derivative. Training uses an explicit
auxiliary classifier: detached per-Head losses on TRAIN rows label which sibling
is better. Both counterfactual Head calls are charged and counted. This local
supervision is neither an unbiased policy gradient nor an NDU credit estimator.
"""
from __future__ import annotations

import torch
from torch import nn

from matrix_bank import CellBank

POLICY_SCHEMA = "hepta.cell-growth-policy.v2"
ROUTING_PROFILE = "parent_top2_one_child_per_group.v1"
PRESERVATION_SCOPE = "initialization_identical_children_unchanged_parent_routes_real_arithmetic"
ROUTE_MARGIN = 1e-6


class FamilyCellBank(CellBank):
    """32 independent Heads; 16 parent logits and 16 binary-selector logits.

    No extra/dummy parameters: the existing 32-row gate is partitioned by role.
    Parent/child index order is [0..15, 0..15]. Only two Heads per row execute
    during inference. The auxiliary training probe executes four additional
    Head/row pairs and is included in actual training work, not inference caps.
    """

    def __init__(self, dimension, classes, profile, width_units, *, sibling_loss_weight):
        if (profile.get("logical_cells") != 32 or profile.get("active_cells_per_round_cap") != 2
                or type(sibling_loss_weight) not in (int, float) or not 0 < sibling_loss_weight <= 1):
            raise ValueError("32-Cell top-2 family geometry and positive auxiliary weight required")
        super().__init__(dimension, classes, profile, width_units)
        self.sibling_loss_weight = sibling_loss_weight
        self.sibling_probe_rows = [0] * 32
        self.sibling_supervised_rows = 0

    def _routing(self, features):
        if (features.ndim != 2 or features.shape[1] != self.dimension
                or not 1 <= len(features) <= 4096 or features.dtype != torch.float32
                or features.device.type != "cpu" or not torch.isfinite(features).all().item()):
            raise ValueError("bounded CPU FP32 features required")
        # Keep the parent's GEMM geometry, including near-tied group scores.
        # Indexed parameter views use the registered gather/scatter backward
        # path. Temporary gathered weights are not new stored parameters.
        root_ids, sibling_ids = torch.arange(16), torch.arange(16, 32)
        roots = nn.functional.linear(features, self.gate.weight.index_select(0, root_ids),
                                     self.gate.bias.index_select(0, root_ids))
        selectors = nn.functional.linear(features, self.gate.weight.index_select(0, sibling_ids),
                                         self.gate.bias.index_select(0, sibling_ids))
        if not torch.isfinite(roots).all().item() or not torch.isfinite(selectors).all().item():
            raise ValueError("nonfinite family router")
        groups = torch.argsort(roots, dim=1, descending=True, stable=True)[:, :2]
        weights = roots.gather(1, groups).softmax(1)
        sides = selectors.gather(1, groups) > 0
        return groups, weights, sides, selectors

    def _selected(self, features, routing):
        groups, weights, sides, _ = routing
        output = features.new_zeros((len(features), self.classes))
        # Parent-index accumulation order is retained. Siblings of a selected
        # parent partition its samples; they cannot consume two parent slots.
        for parent in range(16):
            rows, slot = torch.where(groups == parent)
            for side in (0, 1):
                use = torch.where(sides[rows, slot] == side)[0]
                selected, positions = rows[use], slot[use]
                if selected.numel():
                    child = parent + 16 * side
                    output = output.index_add(0, selected, self.heads[child](features[selected])
                                              * weights[selected, positions, None])
                    self.executed_rows[child] += len(selected)
        self.calls += 1
        return output

    def forward(self, features):
        return self._selected(features, self._routing(features))

    def training_loss(self, features, targets):
        routing = self._routing(features)
        loss = nn.functional.cross_entropy(self._selected(features, routing), targets)
        groups, _, _, selectors = routing
        # The detached counterfactual is only a LOCAL sibling target. It must
        # not backpropagate through labels or silently rerun external effects.
        auxiliary = selectors.sum() * 0
        for parent in range(16):
            rows, _ = torch.where(groups == parent)
            if not rows.numel():
                continue
            with torch.no_grad():
                costs = []
                for child in (parent, parent + 16):
                    self.sibling_probe_rows[child] += len(rows)
                    logits = self.heads[child](features[rows])
                    cost = -logits.log_softmax(1).gather(1, targets[rows, None])[:, 0]
                    if not torch.isfinite(cost).all().item():
                        raise ValueError("nonfinite counterfactual sibling loss")
                    costs.append(cost)
                separated = torch.where((costs[0] - costs[1]).abs() > ROUTE_MARGIN)[0]
                preferred = (costs[1][separated] < costs[0][separated]).to(torch.long)
            if separated.numel():
                selected = rows[separated]
                scores = selectors[selected, torch.full_like(selected, parent)]
                pair = torch.stack((torch.zeros_like(scores), scores), dim=1)
                auxiliary = auxiliary + nn.functional.cross_entropy(pair, preferred) * len(separated)
                self.sibling_supervised_rows += len(separated)
        return loss + self.sibling_loss_weight * auxiliary / (2 * len(targets))

    def inventory(self):
        return {**super().inventory(), "routing_profile": ROUTING_PROFILE,
                "sibling_loss_weight": self.sibling_loss_weight,
                "sibling_probe_rows": list(self.sibling_probe_rows),
                "sibling_supervised_rows": self.sibling_supervised_rows}


def transition_parity(parent, child, features, policy):
    """Bounded numerical TRAIN probe; the algebraic identity has separate premises."""
    if (features.ndim != 2 or features.shape[1] != parent.dimension
            or not 1 <= len(features) <= 4096 or features.requires_grad):
        raise ValueError("bounded frozen transition probe required")
    maximum, max_ratio, passed = 0., 0., True
    with torch.inference_mode():
        for start in range(0, len(features), 64):
            before = parent(features[start:start + 64])
            after = child(features[start:start + 64])
            delta = (after - before).abs()
            if not torch.isfinite(before).all().item() or not torch.isfinite(after).all().item():
                raise ValueError("nonfinite transition output")
            maximum = max(maximum, delta.max().item())
            ratio = delta / (policy["transition_atol"] + policy["transition_rtol"] * before.abs())
            max_ratio = max(max_ratio, ratio.max().item())
            passed = bool((ratio <= 1).all().item()) and passed
    return {"schema": "hepta.family-transition-probe.v1", "examples": len(features),
            "atol": policy["transition_atol"], "rtol": policy["transition_rtol"],
            "max_absolute_logit_error": maximum, "max_tolerance_ratio": max_ratio, "passed": passed,
            "data_role": "training_only", "global_float_parity_established": False}


def validate_family_record(growth, inventory, policy):
    """Reject inconsistent family-routing exports; no independent attestation."""
    if (inventory.get("routing_profile") != ROUTING_PROFILE
            or inventory.get("sibling_loss_weight") != policy["sibling_loss_weight"]
            or growth.get("routing_profile") != ROUTING_PROFILE):
        raise ValueError("missing or incompatible family routing identity")
    probes = inventory.get("sibling_probe_rows")
    if not isinstance(probes, list) or len(probes) != 32 or any(type(n) is not int or n < 0 for n in probes):
        raise ValueError("complete auxiliary training-work inventory required")
    count = inventory.get("sibling_supervised_rows")
    if type(count) is not int or not 0 <= 2 * count <= sum(probes):
        raise ValueError("invalid sibling supervision denominator")
    if growth["split_performed"]:
        import math
        probe = growth.get("transition_probe")
        if (growth.get("function_preserving") is not True
                or growth.get("preservation_scope") != PRESERVATION_SCOPE
                or not isinstance(probe, dict) or set(probe) != {"schema", "examples", "atol", "rtol",
                    "max_absolute_logit_error", "max_tolerance_ratio", "passed", "data_role", "global_float_parity_established"}
                or probe.get("schema") != "hepta.family-transition-probe.v1"
                or type(probe.get("examples")) is not int or not 1 <= probe["examples"] <= 4096
                or probe["examples"] != growth["probe_examples"]
                or probe["atol"] != policy["transition_atol"] or probe["rtol"] != policy["transition_rtol"]
                or probe["passed"] is not True or probe["data_role"] != "training_only"
                or probe["global_float_parity_established"] is not False):
            raise ValueError("family transition parity evidence is incomplete")
        error = probe["max_absolute_logit_error"]
        if type(error) not in (int, float) or not math.isfinite(error) or error < 0:
            raise ValueError("invalid transition error")
        ratio = probe["max_tolerance_ratio"]
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError("transition violates its frozen numerical tolerance")
        if growth.get("training_probe_max_logit_delta") != error:
            raise ValueError("transition diagnostics disagree")
