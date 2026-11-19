"""Inspect new comparison declarations without granting scientific admission.

This opt-in schema leaves historical research protocols unchanged. Original
artifact checks establish byte bindings, not prospective custody, sufficient
training, equal opportunity, implementation semantics or hidden evaluation.
"""

import re


SCHEMA = "hepta.prospective-comparison.v1"
COMMON = frozenset(
    "source_snapshot fixed_graph base_model data_exposure evaluation_profile "
    "resource_envelope training_tuning_plan task_time_domains initial_system "
    "original_history".split()
)
ROLES = {
    "fixed_local_learning": {
        "no_update": "retain_parent",
        "exact_bm25": "exact_retrieval",
        "fixed_expert": "fixed",
        "local_update": "train_local",
    },
    "cell_differentiation": {
        "monolith": "train_from_scratch",
        "fixed_expert": "fixed",
        "shared_stem_differentiation": "train_from_scratch",
    },
    "action_controller": {
        "fixed": "fixed",
        "greedy": "greedy",
        "mpc": "planning",
        "trained_router": "train_from_scratch",
        "ndu": "train_from_scratch",
    },
    "temporal_kernel": {
        role: "train_from_scratch"
        for role in ("gru", "cfc", "ssm", "attention", "hcsn")
    },
    "improver_inheritance": {
        "old_improver": "parent",
        "new_improver": "inherited_update",
        "frozen_improver": "frozen",
        "history_only": "history_without_update",
    },
}


def review(document, evidence):
    """Read originals through the research gate's descriptor-relative Evidence.

    Every arm binds the same registered inputs, including the original system
    and history. The tuning plan may allocate different steps by architecture;
    this inspector does not mistake equal step counts for adequate training.
    No observations or scientific outcome flags belong in this declaration.
    """
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "comparison",
        "registration",
        "common",
        "arms",
    }:
        raise ValueError("unknown or missing prospective comparison fields")
    kind = document["comparison"]
    if document["schema"] != SCHEMA or not isinstance(kind, str) or kind not in ROLES:
        raise ValueError("unsupported prospective comparison")
    common = document["common"]
    if not isinstance(common, dict) or set(common) != COMMON:
        raise ValueError("complete fixed input contract required")
    registration = evidence.read(document["registration"], document=False)["sha256"]
    pins = {
        name: evidence.read(binding, document=False)["sha256"]
        for name, binding in common.items()
    }
    arms = document["arms"]
    if not isinstance(arms, list) or len(arms) != len(ROLES[kind]):
        raise ValueError("complete comparison arms required")
    implementations, parents = {}, {}
    for arm in arms:
        if not isinstance(arm, dict) or set(arm) != {
            "role",
            "mode",
            "implementation",
            "parent_improver_sha256",
            "fixed_inputs",
        }:
            raise ValueError("unknown or missing comparison arm fields")
        role = arm["role"]
        if (
            not isinstance(role, str)
            or role not in ROLES[kind]
            or role in implementations
            or arm["mode"] != ROLES[kind][role]
        ):
            raise ValueError("duplicate, unknown or incorrectly configured arm")
        if arm["fixed_inputs"] != pins:
            raise ValueError("comparison arm changes a fixed input")
        implementations[role] = evidence.read(arm["implementation"], document=False)[
            "sha256"
        ]
        parent = arm["parent_improver_sha256"]
        if kind != "improver_inheritance":
            if parent is not None:
                raise ValueError("only improver comparisons declare inheritance")
        elif (
            not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{64}", parent) is None
        ):
            raise ValueError("original parent improver digest required")
        parents[role] = parent
    if kind == "improver_inheritance":
        parent = implementations["old_improver"]
        if (
            set(parents.values()) != {parent}
            or implementations["frozen_improver"] != parent
            or implementations["history_only"] != parent
            or implementations["new_improver"] == parent
        ):
            raise ValueError("inheritance controls must use original parent bytes")
    return {
        "schema": "hepta.prospective-comparison-review.v1",
        "comparison": kind,
        "registration_sha256": registration,
        "fixed_inputs": pins,
        "implementation_sha256": implementations,
        "mechanical_ready": True,
        "research_advancement": False,
        "authority_granted": False,
        "preregistration_verified": False,
        "implementation_semantics_verified": False,
        "matched_opportunity_verified": False,
        "hidden_evaluation_verified": False,
        "trusted_review_required": True,
    }
