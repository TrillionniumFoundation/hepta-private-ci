"""Inspect original arm configurations, never actual execution or scientific strength.

The caller binds this document to its experiment design. Equality of seven
declared component artifacts does not certify complete implementation scope,
prospective registration, actual spending, or sufficiently strong controls.
"""

import re


SCHEMA = "hepta.cell-component-controls.v1"
COMMON = frozenset(
    "base_model tools resource_envelope data_exposure evaluation_profile "
    "training_tuning_plan task_time_domains initial_system original_history".split()
)


def review(binding, evidence, expected_arms, experiment):
    """Read exact arm JSON and every fixed/component artifact through Evidence."""
    document = evidence.read(binding)
    if (
        not isinstance(document, dict)
        or set(document)
        != {"schema", "comparison", "target_component", "common", "arms"}
        or document["schema"] != SCHEMA
    ):
        raise ValueError("unknown or missing component control fields")
    kind, target = document["comparison"], document["target_component"]
    if not isinstance(kind, str) or kind not in {"single_class", "full_system"}:
        raise ValueError("unsupported component comparison")
    if (kind == "full_system" and target is not None) or (
        kind == "single_class"
        and (
            not isinstance(target, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", target) is None
        )
    ):
        raise ValueError("single-class comparison requires an explicit target")
    if (
        kind == "single_class"
        and experiment in {"PERC-1", "MEM-1", "PRED-1", "CTRL-1", "VERIFY-1", "ACT-1"}
        and target != experiment[:-2]
    ):
        raise ValueError("target component differs from the named experiment")
    if kind == "full_system" and experiment != "ORG-1":
        raise ValueError("full-system controls require the organization experiment")
    if experiment == "ORG-1" and kind != "full_system":
        raise ValueError("organization experiment requires full-system controls")
    common = document["common"]
    if not isinstance(common, dict) or set(common) != COMMON:
        raise ValueError(
            "complete model, tools and resource opportunity contract required"
        )
    pins = {
        key: evidence.read(value, document=False)["sha256"]
        for key, value in common.items()
    }
    arms = document["arms"]
    if (
        not isinstance(arms, dict)
        or set(arms) != expected_arms
        or not 2 <= len(arms) <= 33
    ):
        raise ValueError("component controls must cover every registered arm exactly")
    configurations, roles, configuration_pins = {}, {}, {}
    for name, binding in arms.items():
        config = evidence.read(binding)
        if (
            not isinstance(config, dict)
            or set(config)
            != {
                "schema",
                "arm_id",
                "role",
                "fixed_inputs",
                "components",
                "organization",
                "implementation",
            }
            or config["schema"] != "hepta.cell-arm-configuration.v1"
        ):
            raise ValueError("unknown or missing original arm configuration fields")
        role = config["role"]
        allowed = (
            {"candidate"}
            if name == "candidate"
            else (
                {"matched_control"}
                if kind == "single_class"
                else {"strong_agent", "strong_workflow"}
            )
        )
        if config["arm_id"] != name or not isinstance(role, str) or role not in allowed:
            raise ValueError(
                "original arm configuration has a different identity or role"
            )
        fixed = config["fixed_inputs"]
        if not isinstance(fixed, dict) or set(fixed) != COMMON:
            raise ValueError("original arm configuration omits fixed input artifacts")
        if {
            key: evidence.read(value, document=False)["sha256"]
            for key, value in fixed.items()
        } != pins:
            raise ValueError("original arm configuration changes a fixed input")
        components = config["components"]
        if components is None and kind == "full_system" and name != "candidate":
            component_pins = None
        else:
            if (
                not isinstance(components, dict)
                or len(components) != 7
                or any(
                    not isinstance(key, str)
                    or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", key) is None
                    for key in components
                )
            ):
                raise ValueError("seven original named component artifacts required")
            component_pins = {
                key: evidence.read(value, document=False)["sha256"]
                for key, value in components.items()
            }
        configurations[name] = {
            "components": component_pins,
            "organization": evidence.read(config["organization"], document=False)[
                "sha256"
            ],
            "implementation": evidence.read(config["implementation"], document=False)[
                "sha256"
            ],
        }
        roles[name] = role
        configuration_pins[name] = binding["sha256"]
    if "candidate" not in configurations:
        raise ValueError("candidate configuration required")
    candidate = configurations["candidate"]
    if kind == "single_class":
        if target not in candidate["components"]:
            raise ValueError("target is absent from the seven component roles")
        for name, config in configurations.items():
            if name == "candidate":
                continue
            if set(config["components"]) != set(candidate["components"]):
                raise ValueError("single-class arms require the same seven roles")
            if config["organization"] != candidate["organization"] or any(
                value != candidate["components"][key]
                for key, value in config["components"].items()
                if key != target
            ):
                raise ValueError("single-class control changes a non-target mechanism")
            if config["components"][target] == candidate["components"][target]:
                raise ValueError("single-class control does not change the target")
    return {
        "schema": "hepta.cell-component-controls-review.v1",
        "comparison": kind,
        "target_component": target,
        "fixed_inputs": pins,
        "arm_configuration_sha256": configuration_pins,
        "arm_roles": roles,
        "declared_configurations": configurations,
        "configuration_integrity_verified": True,
        "component_isolation_integrity_verified": kind == "single_class",
        "component_semantics_verified": False,
        "research_advancement": False,
        "authority_granted": False,
        "preregistration_verified": False,
        "implementation_semantics_verified": False,
        "matched_opportunity_verified": False,
        "actual_execution_verified": False,
        "complete_cost_verified": False,
        "strong_control_quality_verified": False,
        "hidden_evaluation_verified": False,
        "trusted_review_required": True,
    }
