"""A capability checks and public A/C/E protocol interfaces.

Registries and callbacks belong to the host, not an agent response. Hashes bind
content; they do not authenticate a capability, owner, or measurement. These
checks do not issue grants, create successful receipts, or dispatch execution.
"""

from ._causal_checks import (
    ACEValidationError,
    COST_STAGES,
    COST_UNITS,
    _fields,
    _pin,
    _require,
    _text,
)
from .causal_composition import (
    check_next_use,
    validate_c_design,
    validate_composition_manifest,
)
from .causal_improver import compare_improvers

__all__ = [
    "ACEValidationError",
    "COST_STAGES",
    "COST_UNITS",
    "assess_a_capabilities",
    "validate_composition_manifest",
    "validate_c_design",
    "check_next_use",
    "compare_improvers",
]


def assess_a_capabilities(arms, registry, *, source_commit, source_tree):
    """Check A against a separately audited, source-pinned host registry.

    A registry entry describes actual module/state/parameter ownership. Shared
    heads are explicitly unsupported. Passing this check only permits a matched
    execution; it is not evidence that the architecture was actually consumed.
    """
    _require(_pin(source_commit, 40) and _pin(source_tree, 40), "A_SOURCE_IDENTITY")
    _require(
        isinstance(registry, dict) and isinstance(arms, list) and arms,
        "A_REGISTRY_AND_ARMS_REQUIRED",
    )
    resources, identifiers, conditions, output = None, set(), set(), []
    for arm in arms:
        _fields(
            arm,
            (
                "arm_id",
                "architecture",
                "implementation_id",
                "ablation",
                "removed_role",
                "resources",
            ),
            "A_ARM_FIELDS",
        )
        _require(
            _text(arm["arm_id"]) and arm["arm_id"] not in identifiers, "A_DUPLICATE_ARM"
        )
        identifiers.add(arm["arm_id"])
        architecture, ablation = arm["architecture"], arm["ablation"]
        _require(
            _text(architecture)
            and _text(ablation)
            and _text(arm["implementation_id"])
            and architecture in {"single_agent", "fixed_roles", "cell"}
            and ablation
            in {"none", "reset_state", "freeze_differentiation", "remove_role"},
            "A_UNKNOWN_CONDITION",
        )
        _require(architecture == "cell" or ablation == "none", "A_ABLATION_TARGET")
        _require(
            (
                _text(arm["removed_role"])
                if ablation == "remove_role"
                else arm["removed_role"] is None
            ),
            "A_REMOVED_ROLE",
        )
        contract = arm["resources"]
        pins = (
            "model_family",
            "information",
            "tools",
            "training_opportunities",
            "tuning_opportunities",
            "full_budget",
        )
        _fields(contract, (*pins, "memory_bytes", "parameter_count"), "A_RESOURCES")
        _require(
            all(_pin(contract[key]) for key in pins)
            and all(
                type(contract[key]) is int and 0 < contract[key] < 2**63
                for key in ("memory_bytes", "parameter_count")
            ),
            "A_RESOURCE_VALUE",
        )
        _require(resources is None or resources == contract, "A_UNMATCHED_RESOURCES")
        resources = contract
        conditions.add((architecture, ablation))
        entry = registry.get(arm["implementation_id"])
        reason = "NO_SOURCE_BOUND_IMPLEMENTATION"
        if entry is not None:
            _fields(
                entry,
                (
                    "source_commit",
                    "source_tree",
                    "implementation_sha256",
                    "entrypoint",
                    "kind",
                    "roles",
                    "parameter_inventory",
                    "supported_ablations",
                ),
                "A_CAPABILITY_FIELDS",
            )
            _require(
                entry["source_commit"] == source_commit
                and entry["source_tree"] == source_tree,
                "A_CAPABILITY_SOURCE_MISMATCH",
            )
            _require(
                _pin(entry["implementation_sha256"]) and _text(entry["entrypoint"]),
                "A_IMPLEMENTATION_BINDING",
            )
            reason = "ARCHITECTURE_NOT_IMPLEMENTED"
            if entry["kind"] == architecture:
                roles = entry["roles"]
                inventory = entry["parameter_inventory"]
                _require(
                    isinstance(roles, list)
                    and roles
                    and isinstance(inventory, list)
                    and inventory
                    and all(_text(item) for item in inventory)
                    and len(set(inventory)) == len(inventory),
                    "A_COMPONENT_INVENTORY",
                )
                ids, modules, owners, parameters = set(), set(), set(), set()
                for role in roles:
                    _fields(
                        role,
                        ("role_id", "module_path", "state_owner", "local_parameters"),
                        "A_ROLE_FIELDS",
                    )
                    _require(
                        all(
                            _text(role[key])
                            for key in ("role_id", "module_path", "state_owner")
                        )
                        and role["role_id"] not in ids,
                        "A_ROLE_IDENTITY",
                    )
                    local = role["local_parameters"]
                    _require(
                        isinstance(local, list)
                        and all(_text(x) for x in local)
                        and len(local) == len(set(local))
                        and set(local) <= set(inventory),
                        "A_PARAMETER_BINDING",
                    )
                    if architecture == "cell":
                        _require(
                            local
                            and not parameters.intersection(local)
                            and role["module_path"] not in modules
                            and role["state_owner"] not in owners,
                            "A_SHARED_HEADS_ARE_NOT_LOCAL_CELLS",
                        )
                    ids.add(role["role_id"])
                    modules.add(role["module_path"])
                    owners.add(role["state_owner"])
                    parameters.update(local)
                _require(
                    len(roles) == 1
                    if architecture == "single_agent"
                    else len(roles) >= 2,
                    "A_ROLE_CARDINALITY",
                )
                supported = entry["supported_ablations"]
                _require(
                    isinstance(supported, list)
                    and all(_text(x) for x in supported)
                    and len(supported) == len(set(supported))
                    and set(supported)
                    <= {"none", "reset_state", "freeze_differentiation", "remove_role"},
                    "A_ABLATION_CAPABILITIES",
                )
                reason = None if ablation in supported else "ABLATION_NOT_IMPLEMENTED"
                if ablation == "remove_role":
                    _require(arm["removed_role"] in ids, "A_UNKNOWN_REMOVED_ROLE")
        output.append(
            {
                "arm_id": arm["arm_id"],
                "reason": reason,
                "status": "READY_FOR_MATCHED_EXECUTION"
                if reason is None
                else "BLOCKED_UNIMPLEMENTED",
            }
        )
    required = {(kind, "none") for kind in ("single_agent", "fixed_roles", "cell")}
    required.update(
        ("cell", mode)
        for mode in ("reset_state", "freeze_differentiation", "remove_role")
    )
    missing = sorted(required - conditions)
    return {
        "status": "READY_FOR_MATCHED_EXECUTION"
        if not missing and all(row["reason"] is None for row in output)
        else "BLOCKED_UNIMPLEMENTED",
        "arms": output,
        "missing_conditions": [list(x) for x in missing],
        "scope": "host_source_registry_compatibility_only",
        "runtime_consumption_verified": False,
        "authority_granted": False,
    }
