"""One residual-triggered 16->32 population split in the bound training path.

The parent starts at the FINAL per-child width, so growth adds actual capacity.
V1 flat top-k cloning is NOT function preserving; its behavioral jump is kept.
Opt-in V2 preserves parent groups, checks training-probe parity and learns binary
sibling selectors with explicitly charged auxiliary work. No eval data is used to
choose growth. Direct controls use the same probe and optimizer-reset boundary.
This is offline candidate training, not native topology installation or NDU.
"""
from __future__ import annotations

import contextlib
import math

import torch
from torch import nn

from matrix_bank import CellBank, state_digest, train_bank
from family_routing import (POLICY_SCHEMA as FAMILY_SCHEMA, ROUTING_PROFILE, PRESERVATION_SCOPE,
                            FamilyCellBank, transition_parity)
from next_round_matrix import _digest

GROWTH_SCHEMA = "hepta.cell-growth-policy.v1"
GROWTH_ARMS = frozenset(("shared_421m_sparse_split_no_ndu", "shared_421m_sparse_split_64m_no_ndu"))
CONTROL_ARMS = frozenset(("shared_421m_sparse_direct32_no_ndu", "shared_421m_sparse_direct32_64m_no_ndu",
                          "shared_421m_sparse_fixed16_no_ndu"))


class GrowthNotAdmitted(ValueError):
    """No completed split arm may be emitted when its growth criterion fails."""

    def __init__(self, report):
        super().__init__(report["disposition"])
        self.report = report


def validate_growth_policy(policy, *, train_steps, width_units, arm_id):
    keys = {"schema", "decision_step", "loss_threshold", "minimum_source_groups", "gate_noise_scale"}
    family = isinstance(policy, dict) and policy.get("schema") == FAMILY_SCHEMA
    if family:
        keys |= {"sibling_loss_weight", "transition_atol", "transition_rtol"}
    if not isinstance(policy, dict) or set(policy) != keys or policy["schema"] not in (GROWTH_SCHEMA, FAMILY_SCHEMA):
        raise ValueError("complete, versioned growth policy required")
    if family:
        if arm_id == "shared_421m_sparse_fixed16_no_ndu":
            raise ValueError("family protocol requires a split or grouped direct-32 control")
        for key in ("sibling_loss_weight", "transition_atol", "transition_rtol"):
            value = policy[key]
            limit = 1 if key == "sibling_loss_weight" else 1e-4
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= limit:
                raise ValueError("invalid family supervision/parity coefficient")
    if arm_id not in GROWTH_ARMS | CONTROL_ARMS:
        raise ValueError("growth protocol requires a split or matched sparse control")
    if type(train_steps) is not int or type(policy["decision_step"]) is not int or not 1 <= policy["decision_step"] < train_steps:
        raise ValueError("growth needs positive pre/post training stages")
    if type(width_units) is not int or width_units < 2 or width_units % 2:
        raise ValueError("growth protocol requires an even width_units >= 2")
    if type(policy["minimum_source_groups"]) is not int or not 1 <= policy["minimum_source_groups"] <= 4096:
        raise ValueError("bounded independent training group count required")
    for key in ("loss_threshold", "gate_noise_scale"):
        if type(policy[key]) not in (int, float) or not math.isfinite(policy[key]):
            raise ValueError("finite growth coefficients required")
    if policy["loss_threshold"] < 0 or not 0 < policy["gate_noise_scale"] <= .01:
        raise ValueError("invalid residual threshold or symmetry-breaking scale")


def initial_bank(dimension, classes, profile, config, *, parameter_cap):
    """Build the actual 16-parent or direct-control population, no unused slots."""
    policy = config["growth_policy"]
    validate_growth_policy(policy, train_steps=config["train_steps"],
                           width_units=config["width_units"], arm_id=profile["arm_id"])
    recipe = dict(profile)
    units = config["width_units"]
    if profile["arm_id"] in GROWTH_ARMS:
        # Explicit parent recipe: same per-Head shape as final 32, half as many.
        recipe.update(logical_cells=16, initial_logical_cells=16, split=False)
        units //= 2
    expected = 32 * (dimension + classes + 1) * units * (profile["total_head_budget_params"] // 32_000_000)
    if type(parameter_cap) is not int or expected > parameter_cap:
        raise ValueError("initial population exceeds common live-parameter cap")
    if policy["schema"] == FAMILY_SCHEMA and recipe["logical_cells"] == 32:
        return FamilyCellBank(dimension, classes, recipe, units,
                              sibling_loss_weight=policy["sibling_loss_weight"])
    return CellBank(dimension, classes, recipe, units)


def split_population(parent, profile, config, *, seed, parameter_cap):
    """Create independent children without changing ANY parent tensors/state.

    Preflight counts cover simultaneously live parent+successor model parameters.
    Gradient/optimizer/activation storage is not included in this parameter cap.
    A cooperative failure abandons the entire candidate and never installs it.
    """
    if (profile["arm_id"] not in GROWTH_ARMS or len(parent.heads) != 16
            or parent.top_k != 2 or profile["ndu"] is not False):
        raise ValueError("unsupported growth source")
    validate_growth_policy(config["growth_policy"], train_steps=config["train_steps"],
                           width_units=config["width_units"], arm_id=profile["arm_id"])
    capacity = profile["total_head_budget_params"] // 32_000_000
    expected = 32 * (parent.dimension + parent.classes + 1) * config["width_units"] * capacity
    predecessor = parent.inventory()
    peak = predecessor["parameters"] + expected
    if type(parameter_cap) is not int or peak > parameter_cap:
        raise ValueError("growth transition exceeds common live-parameter cap")
    if any(head[0].out_features != config["width_units"] * capacity - 1 for head in parent.heads):
        raise ValueError("parent shape cannot be cloned at the final child width")
    before = state_digest(parent)
    recipe = {**profile, "initial_logical_cells": 32, "split": False}
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        family = config["growth_policy"]["schema"] == FAMILY_SCHEMA
        factory = FamilyCellBank if family else CellBank
        extra = {"sibling_loss_weight": config["growth_policy"]["sibling_loss_weight"]} if family else {}
        child = factory(parent.dimension, parent.classes, recipe, config["width_units"], **extra)
        with torch.no_grad():
            for index, head in enumerate(child.heads):
                head.load_state_dict(parent.heads[index % 16].state_dict(), strict=True)
            child.gate.weight[:16].copy_(parent.gate.weight)
            child.gate.weight[16:].copy_(parent.gate.weight)
            child.gate.bias[:16].copy_(parent.gate.bias)
            child.gate.bias[16:].copy_(parent.gate.bias)
            # Only the new gate rows are perturbed. Actual dispatched work is
            # charged in migration; the old population is left bit-identical.
            noise = torch.empty_like(parent.gate.weight)
            scale = config["growth_policy"]["gate_noise_scale"]
            noise.uniform_(-scale, scale)
            if family:
                # Independent sibling contrast, not another parent competitor.
                child.gate.weight[16:].copy_(noise)
                child.gate.bias[16:].zero_()
            else:
                child.gate.weight[16:].add_(noise)
    if before != state_digest(parent):
        raise ValueError("growth mutated the predecessor")
    inventory = child.inventory()
    if inventory["parameters"] != expected:
        raise ValueError("unexpected actual successor parameter count")
    return child, dict(parent_sha256=before, initialized_child_sha256=state_digest(child),
                       parent_parameters=predecessor["parameters"], final_parameters=expected,
                       peak_live_trainable_params=peak,
                       transition_model_weight_bytes=predecessor["unique_weight_bytes"] + inventory["unique_weight_bytes"],
                       transition_weight_scope="parent_and_successor_weights_only",
                       parent_for_child=[i % 16 for i in range(32)], function_preserving=family,
                       **({"routing_profile": ROUTING_PROFILE, "preservation_scope": PRESERVATION_SCOPE} if family else {}),
                       parent_executed_rows=predecessor["executed_rows"], parent_calls=predecessor["calls"])


def train_with_growth(bank, features, targets, config, contract, profile, source_groups, *, seed, meter=None):
    """Train, inspect training residuals, optionally grow, then specialize.

    One predeclared decision boundary, not general lifelong topology search.
    Identical minibatch seeds and resets are used by direct controls. Probe data
    remain training data; their residual is NOT independent efficacy evidence.
    """
    policy = config["growth_policy"]
    validate_growth_policy(policy, train_steps=config["train_steps"],
                           width_units=config["width_units"], arm_id=profile["arm_id"])
    if (len(source_groups) != len(targets) or any(not isinstance(s, str) or not s for s in source_groups)):
        raise ValueError("training-row source groups required")
    cap = contract.get("max_peak_trainable_params")
    if type(cap) is not int or bank.inventory()["parameters"] > cap:
        raise ValueError("growth training requires the common lifecycle cap")
    scope = meter.scope if meter else lambda *args: contextlib.nullcontext()
    step = policy["decision_step"]
    retention = None
    probe_features, probe_targets = features, targets
    first_features, first_targets = features, targets
    probe_groups = source_groups
    if "retention_policy" in config:
        from retention_training import RetentionSession, ROLES
        with scope("train", "bank"):
            retention = RetentionSession(features, targets, source_groups, config["retention_policy"],
                                         cache_budget=config["max_feature_bytes"] - features.numel() * features.element_size())
            old, new = retention.ids[ROLES[0]], retention.ids[ROLES[1]]
            first_features, first_targets = features[old], targets[old]
            fit_ids = torch.cat((old, new))
            probe_groups = [source_groups[i] for i in new.tolist()]
    with scope("train", "bank"):
        first = train_bank(bank, first_features, first_targets, {**config, "train_steps": step}, seed)
        # train_bank has released its optimizer. Clear stale gradients in BOTH
        # arms before the identical fresh-optimizer boundary.
        bank.zero_grad(set_to_none=True)
        if retention is not None:
            del first_features, first_targets
            probe_features, probe_targets = features[new], targets[new]
        # no_grad retains the registered log-softmax/NLL dispatch path.
        # inference_mode selects an unregistered fused cross_entropy overload.
        with torch.no_grad():
            residual = 0.
            for start in range(0, len(probe_targets), 64):
                logits = bank(probe_features[start:start + 64])
                residual += nn.functional.cross_entropy(logits, probe_targets[start:start + 64], reduction="mean").item() * len(logits)
            residual /= len(probe_targets)
        if not math.isfinite(residual):
            raise ValueError("nonfinite training residual")
    report = dict(schema="hepta.cell-growth-training.v1", policy_id=_digest(policy),
                  decision_step=step, training_residual=residual, probe_examples=len(fit_ids) if retention is not None else len(targets),
                  source_group_count=len(set(probe_groups)), split_performed=False,
                  optimizer_reset_count=1, optimizer_state_transport="reset_in_all_controls",
                  pre_growth_training=first, independent_gain_established=False)
    report["peak_live_trainable_params"] = bank.inventory()["parameters"]
    report["transition_model_weight_bytes"] = bank.inventory()["unique_weight_bytes"]
    if retention is not None:
        with scope("train", "bank"):
            report["residual_probe_examples"] = len(probe_targets)
            del probe_features, probe_targets
            retention.capture(bank)
    if profile["arm_id"] in GROWTH_ARMS:
        eligible = len(set(probe_groups)) >= policy["minimum_source_groups"] and residual > policy["loss_threshold"]
        if not eligible:
            report.update(disposition="growth_not_triggered", optimizer_reset_count=0)
            raise GrowthNotAdmitted(report)
        with scope("migration", "bank"):
            if policy["schema"] == FAMILY_SCHEMA:
                successor, transition = split_population(bank, profile, config, seed=seed + 1, parameter_cap=cap)
                probe = transition_parity(bank, successor, features[fit_ids] if retention is not None else features, policy)
                report.update(transition, split_performed=True, transition_probe=probe,
                              training_probe_max_logit_delta=probe["max_absolute_logit_error"])
                if not probe["passed"]:
                    report["disposition"] = "transition_parity_failed"
                    raise GrowthNotAdmitted(report)
            else:
                with torch.inference_mode():
                    prior_probe = bank(features[:64]).clone()
                successor, transition = split_population(bank, profile, config, seed=seed + 1, parameter_cap=cap)
                with torch.inference_mode():
                    jump = (successor(features[:64]) - prior_probe).abs().max().item()
                report.update(transition, split_performed=True, training_probe_max_logit_delta=jump)
                del prior_probe
            bank = successor
    if policy["schema"] == FAMILY_SCHEMA:
        report["routing_profile"] = ROUTING_PROFILE
    report["disposition"] = "split_candidate" if report["split_performed"] else "direct_control"
    with scope("train", "bank"):
        if retention is None:
            second = train_bank(bank, features, targets, {**config, "train_steps": config["train_steps"] - step}, seed + step)
        else:
            second = retention.train(bank, config, steps=config["train_steps"] - step, seed=seed + step)
            retention_report = retention.evaluate(bank)
    result = {"steps": first["steps"] + second["steps"],
                  "examples_seen": first["examples_seen"] + second["examples_seen"],
                  "losses": first["losses"] + second["losses"],
                  "optimizer_tensor_bytes": second["optimizer_tensor_bytes"],
                  "peak_optimizer_tensor_bytes": max(first["optimizer_tensor_bytes"], second["optimizer_tensor_bytes"]),
                  "growth": report}
    if retention is not None:
        result.update(retention=retention_report, retained_specialization={k: second[k] for k in
                      ("replay_examples_seen", "new_examples_seen", "reference_bank_rows")})
    if "consolidation_policy" in config:
        from consolidation_training import consolidate
        bank, result["consolidation"] = consolidate(
            bank, retention, config, contract, profile, report,
            seed=seed + config["train_steps"], meter=meter)
    return bank, result
