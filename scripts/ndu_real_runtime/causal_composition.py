"""C composition and original-owner readback checks; no grants or execution."""

from ._causal_checks import _fields, _number, _pin, _require, _sha, _text


def validate_composition_manifest(manifest, *, tensor_inventory=None):
    """Validate a bounded encoder/base/A/B/heads composition, not a native grant.

    Version 1 supports dense and low-rank linear component interfaces. Shapes
    are [output_width, input_width]; low-rank tensors are [rank, input_width]
    and [output_width, rank]. An optional inventory comes from the actual loader.
    It checks shapes against observations without claiming byte authenticity.
    """
    _fields(
        manifest,
        ("schema", "bundle_digest", "components", "order", "compatibility"),
        "C_MANIFEST_FIELDS",
    )
    _require(
        manifest["schema"] == "ndu.causal.composition.v1"
        and _pin(manifest["bundle_digest"]),
        "C_MANIFEST_IDENTITY",
    )
    order = ["encoder", "base", "A", "B", "heads"]
    _require(manifest["order"] == order, "C_COMPONENT_ORDER")
    components = manifest["components"]
    _fields(components, order, "C_COMPONENT_SET")
    compatibility = manifest["compatibility"]
    _fields(
        compatibility,
        (
            "tokenizer",
            "normalizer",
            "calibration",
            "numeric_profile",
            "output_schema",
            "state_schema",
            "state_semantics",
        ),
        "C_COMPATIBILITY_FIELDS",
    )
    _require(all(_pin(value) for value in compatibility.values()), "C_SCHEMA_BINDINGS")
    names, previous = set(), None
    for index, name in enumerate(order):
        component = components[name]
        _fields(
            component,
            (
                "sha256",
                "implementation_sha256",
                "version",
                "kind",
                "shape",
                "rank",
                "scale",
                "input_schema",
                "output_schema",
                "base_sha256",
                "dependencies",
                "tensors",
            ),
            "C_COMPONENT_FIELDS",
        )
        _require(
            all(
                _pin(component[key])
                for key in (
                    "sha256",
                    "implementation_sha256",
                    "input_schema",
                    "output_schema",
                )
            )
            and type(component["version"]) is int
            and 0 < component["version"] < 2**64,
            "C_COMPONENT_VERSION_OR_PIN",
        )
        shape, rank = component["shape"], component["rank"]
        _require(
            isinstance(shape, list)
            and len(shape) == 2
            and all(type(x) is int and 0 < x <= 1048576 for x in shape)
            and type(rank) is int
            and _number(component["scale"])
            and component["scale"] != 0,
            "C_SHAPE_RANK_SCALE",
        )
        _require(
            component["dependencies"] == ([] if index == 0 else [order[index - 1]]),
            "C_DEPENDENCY_ORDER",
        )
        _require(
            component["base_sha256"]
            == (components["base"]["sha256"] if name in {"A", "B"} else None),
            "C_BASE_INCOMPATIBLE",
        )
        tensors = component["tensors"]
        _require(
            isinstance(tensors, dict)
            and tensors
            and len(tensors) <= 2
            and all(_text(key) and key not in names for key in tensors)
            and all(
                isinstance(dims, list)
                and dims
                and all(type(x) is int and x > 0 for x in dims)
                for dims in tensors.values()
            ),
            "C_TENSOR_INVENTORY",
        )
        names.update(tensors)
        shapes = sorted(tensors.values())
        if component["kind"] == "low_rank":
            _require(
                name in {"A", "B"}
                and 0 < rank <= min(shape)
                and shapes == sorted([[rank, shape[1]], [shape[0], rank]]),
                "C_LOW_RANK_FACTORS",
            )
        else:
            _require(
                component["kind"] == "dense"
                and rank == 0
                and (shapes == [shape] or shapes == sorted([shape, [shape[0]]])),
                "C_DENSE_TENSORS",
            )
        if previous is not None:
            _require(
                previous["shape"][0] == shape[1]
                and previous["output_schema"] == component["input_schema"],
                "C_INTERFACE_INCOMPATIBLE",
            )
        previous = component
        if tensor_inventory is not None:
            _require(
                isinstance(tensor_inventory, dict)
                and name in tensor_inventory
                and _sha(tensor_inventory[name])
                == _sha({"sha256": component["sha256"], "tensors": tensors}),
                "C_LOADED_TENSOR_MISMATCH",
            )
    _require(
        compatibility["output_schema"] == previous["output_schema"],
        "C_OUTPUT_SCHEMA_MISMATCH",
    )
    if tensor_inventory is not None:
        _require(set(tensor_inventory) == set(order), "C_LOADED_COMPONENT_SET")
    return {
        "status": "MANIFEST_STRUCTURALLY_VALID",
        "manifest_sha256": _sha(manifest),
        "bundle_digest": manifest["bundle_digest"],
        "component_digests": {
            key: value["sha256"] for key, value in components.items()
        },
        "tensor_inventory_checked": tensor_inventory is not None,
        "runtime_consumption_verified": False,
        "authority_granted": False,
    }


def validate_c_design(design, manifests):
    """Check none/A/B/AB/shared-base crossed with reset/migrate before execution."""
    _fields(
        design,
        (
            "schema",
            "baseline_manifest",
            "state_modes",
            "conditions",
            "recovery_domains",
        ),
        "C_DESIGN_FIELDS",
    )
    _require(
        design["schema"] == "ndu.causal.composition-design.v1"
        and design["state_modes"] == ["reset", "migrate"]
        and design["recovery_domains"] == ["model", "external_effects"],
        "C_REQUIRED_CONTRASTS",
    )
    _require(
        isinstance(manifests, dict)
        and _text(design["baseline_manifest"])
        and design["baseline_manifest"] in manifests,
        "C_BASELINE_MISSING",
    )
    checked = {
        key: validate_composition_manifest(value) for key, value in manifests.items()
    }
    baseline = manifests[design["baseline_manifest"]]
    expected_changes = {"none": set(), "A": {"A"}, "B": {"B"}, "AB": {"A", "B"}}
    seen, arms, paired = set(), set(), {}
    _require(isinstance(design["conditions"], list), "C_CONDITIONS")
    for condition in design["conditions"]:
        _fields(
            condition,
            ("arm_id", "update", "state_mode", "manifest"),
            "C_CONDITION_FIELDS",
        )
        update, mode = condition["update"], condition["state_mode"]
        _require(
            _text(update)
            and _text(mode)
            and _text(condition["manifest"])
            and update in {*expected_changes, "shared_base"}
            and mode in design["state_modes"]
            and (update, mode) not in seen
            and _text(condition["arm_id"])
            and condition["arm_id"] not in arms,
            "C_DUPLICATE_OR_UNKNOWN_CONDITION",
        )
        _require(condition["manifest"] in manifests, "C_MANIFEST_MISSING")
        seen.add((update, mode))
        arms.add(condition["arm_id"])
        current = manifests[condition["manifest"]]
        _require(
            current["compatibility"] == baseline["compatibility"],
            "C_UNCONTROLLED_SCHEMA_CHANGE",
        )
        changed = {
            name
            for name, value in current["components"].items()
            if value["sha256"] != baseline["components"][name]["sha256"]
        }
        _require(
            changed == expected_changes[update]
            if update != "shared_base"
            else "base" in changed and changed <= {"base", "A", "B"},
            "C_WRONG_UPDATE_TARGET",
        )
        _require(
            current == baseline
            if update == "none"
            else current["bundle_digest"] != baseline["bundle_digest"],
            "C_BUNDLE_IDENTITY",
        )
        for name, value in current["components"].items():
            old = baseline["components"][name]
            _require(
                value["implementation_sha256"] == old["implementation_sha256"],
                "C_UNCONTROLLED_IMPLEMENTATION_CHANGE",
            )
            if name in changed:
                _require(
                    value["version"] > old["version"],
                    "C_NONMONOTONIC_COMPONENT_VERSION",
                )
            else:
                permitted = {
                    **old,
                    "base_sha256": current["components"]["base"]["sha256"],
                }
                _require(
                    value
                    == (
                        permitted
                        if update == "shared_base" and name in {"A", "B"}
                        else old
                    ),
                    "C_UNDECLARED_COMPONENT_CHANGE",
                )
        pin = checked[condition["manifest"]]["manifest_sha256"]
        _require(
            update not in paired or paired[update] == pin, "C_STATE_PAIR_CHANGED_MODEL"
        )
        paired[update] = pin
    _require(
        seen
        == {
            (update, mode)
            for update in (*expected_changes, "shared_base")
            for mode in design["state_modes"]
        },
        "C_INCOMPLETE_FACTORIAL",
    )
    return {
        "status": "DESIGN_STRUCTURALLY_VALID",
        "conditions": len(seen),
        "next_use_verified": False,
        "model_recovery_verified": False,
        "external_effect_recovery_verified": False,
        "authority_granted": False,
    }


def check_next_use(
    expected, receipt_reference, *, read_original=None, verify_owner=None
):
    """Read original NextUse and state-owner records through independent ports.

    read_original(kind, reference) returns an existing record or None. The host's
    verify_owner(kind, record, expected_owner) must validate the complete native
    receipt and its trust/currentness rules, returning exactly True. The state
    port returns a normalized, verified cutover/task-publication readback with
    actor_id, state_partition, candidate_bundle, checkpoint_digest and transition.
    A Python digest comparison is deliberately not a substitute for that port.
    """
    keys = (
        "operation_id",
        "predecessor",
        "next_use_owner",
        "state_owner",
        "principal_id",
        "agent_id",
        "cell_id",
        "source_run_id",
        "next_run_id",
        "candidate_bundle",
        "selection_digest",
        "checkpoint_digest",
        "source_checkpoint_digest",
        "state_receipt_digest",
        "state_mode",
        "retained",
    )
    _fields(expected, keys, "C_NEXT_USE_EXPECTATION")
    _require(
        all(_text(expected[key]) for key in keys[:9])
        and _text(receipt_reference)
        and all(_pin(expected[key]) for key in (*keys[9:14], "predecessor"))
        and expected["source_run_id"] != expected["next_run_id"]
        and _text(expected["state_mode"])
        and expected["state_mode"] in {"preserve", "reset", "migrate"}
        and type(expected["retained"]) is bool,
        "C_NEXT_USE_IDENTITY",
    )
    if not callable(read_original) or not callable(verify_owner):
        return {
            "status": "HOLD_ORIGINAL_OWNER_PORT_REQUIRED",
            "authority_granted": False,
        }
    receipt = read_original("next_use", receipt_reference)
    state = read_original("state_transition", expected["state_receipt_digest"])
    if receipt is None or state is None:
        return {
            "status": "HOLD_ORIGINAL_RECEIPT_UNAVAILABLE",
            "authority_granted": False,
        }
    _require(
        isinstance(receipt, dict) and isinstance(state, dict), "C_OWNER_READBACK_TYPE"
    )
    _require(
        verify_owner("next_use", receipt, expected["next_use_owner"]) is True
        and verify_owner("state_transition", state, expected["state_owner"]) is True,
        "C_OWNER_AUTHENTICATION_REJECTED",
    )
    _require(
        receipt.get("actor_id") == expected["next_use_owner"]
        and receipt.get("operation_id") == expected["operation_id"]
        and receipt.get("predecessor") == expected["predecessor"]
        and _pin(receipt.get("evidence_digest"))
        and type(receipt.get("observed_unix_seconds")) is int
        and 0 < receipt["observed_unix_seconds"] < 2**63,
        "C_ORIGINAL_RECEIPT_BINDING",
    )
    observation = receipt.get("observation")
    retained = expected["retained"]
    bundle_key = "retained_bundle" if retained else "candidate_bundle"
    state_key = "task_owner_publication" if retained else "state_cutover_receipt"
    partition = {key: expected[key] for key in ("principal_id", "agent_id", "cell_id")}
    partition["run_id"] = expected["next_run_id"]
    _require(
        isinstance(observation, dict)
        and observation.get("kind")
        == ("RetainedModelNextUse" if retained else "NextUse")
        and observation.get(bundle_key) == expected["candidate_bundle"]
        and observation.get("state_partition") == partition
        and observation.get("selection_digest") == expected["selection_digest"]
        and observation.get("checkpoint_digest") == expected["checkpoint_digest"]
        and observation.get(state_key) == expected["state_receipt_digest"]
        and _pin(observation.get("committed_step_receipt")),
        "C_NEXT_USE_MISMATCH",
    )
    _require(
        state.get("actor_id") == expected["state_owner"]
        and state.get("state_partition") == partition
        and state.get("candidate_bundle") == expected["candidate_bundle"]
        and state.get("checkpoint_digest") == expected["checkpoint_digest"],
        "C_STATE_OWNER_BINDING",
    )
    transition = state.get("transition", {})
    mode = expected["state_mode"]
    transition_fields = {
        "preserve": ("kind", "checkpoint"),
        "reset": ("kind", "initializer", "target_checkpoint"),
        "migrate": (
            "kind",
            "transform",
            "source_checkpoint",
            "target_checkpoint",
            "qualification",
        ),
    }
    _fields(transition, transition_fields[mode], "C_STATE_TRANSITION_FIELDS")
    _require(
        transition["kind"] == mode
        and all(_pin(value) for key, value in transition.items() if key != "kind")
        and transition.get("target_checkpoint", transition.get("checkpoint"))
        == expected["checkpoint_digest"],
        "C_STATE_TRANSITION_MISMATCH",
    )
    if mode in {"preserve", "migrate"}:
        _require(
            transition.get("source_checkpoint", transition.get("checkpoint"))
            == expected["source_checkpoint_digest"],
            "C_STATE_SOURCE_CHECKPOINT",
        )
    return {
        "status": "ORIGINAL_NEXT_USE_BINDINGS_MATCH",
        "state_mode": mode,
        "authentication": "delegated_to_host_original_owner_verifier",
        "model_recovery_verified": False,
        "external_effect_recovery_verified": False,
        "authority_granted": False,
    }
