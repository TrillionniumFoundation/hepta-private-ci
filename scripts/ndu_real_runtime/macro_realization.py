"""Post-episode macro realization from retained native bytes, never policy input.

This checks receipt consistency, not native-owner authority. Missing acquisition
or legacy selection evidence remains unknown; absent candidates do not prove
that the source image lacks information. References are used only after the
completed macro has passed the existing wire/delivery/scorer admission.
"""

import math
from pathlib import Path

from ndu_real_materials import common, evaluator
from . import content_identity, macro_attribution, metacontrol_macro_contract, metering
from .content_identity import SELECTION_SCHEMA, verify_content_identity
from .metacontrol_macro_contract import SEQUENCES, digest, observe_branch, sha


def source_manifest():
    """Pin the observer and all directly reused byte/selection/scoring contracts."""
    root = Path(__file__).resolve().parents[1]
    paths = [Path(__file__)] + [
        Path(module.__file__)
        for module in (
            common,
            evaluator,
            content_identity,
            macro_attribution,
            metacontrol_macro_contract,
            metering,
        )
    ]
    return {
        path.resolve().relative_to(root).as_posix(): sha(path.read_bytes())
        for path in paths
    }


def observe_realization(
    directory,
    result,
    macro,
    wall_seconds,
    tariff,
    config,
    *,
    expected_source_sha256,
    public_input=None,
    initial_public_input=None,
    reference=None,
):
    """Observe one complete STOP/READ macro; optional bindings are root-relative.

    public_input is the original host reply immediately preceding WRITE_TEXT.
    reference is an original independently scored train/development reference.
    initial_public_input optionally binds the original step-zero host reply.
    All use closed {path, bytes, sha256} bindings; none reaches an actor.
    Callers retain the planned denominator when admission fails or evidence is
    absent. This function cannot release sealed confirmation/retention-test data.
    """
    if digest(source_manifest()) != expected_source_sha256:
        raise ValueError("Realization observer source identity differs")
    if type(macro) is not str or macro not in SEQUENCES:
        raise ValueError("A declared complete macro is required")
    if (
        any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (wall_seconds, tariff)
        )
        or wall_seconds < 0
        or tariff <= 0
    ):
        raise ValueError("Finite measured wall time and positive tariff required")
    root = Path(directory)
    actions = SEQUENCES[macro]
    index = actions.index("WRITE_TEXT")
    snapshot = f"delivery-{len(actions):02d}"
    paths = [
        "launch.json",
        "trajectory.json",
        "result.json",
        f"{snapshot}/delivery.json",
        f"{snapshot}/evaluation.json",
    ]
    raw = {
        name: common.read_relative(root, name, limit=8 * 1024 * 1024) for name in paths
    }
    parsed = {name: common.strict_json(value) for name, value in raw.items()}
    branch = observe_branch(root, result, actions, wall_seconds, tariff, config)
    launch = parsed["launch.json"]
    lines = [line.encode() for line in launch["stdout"].split("\n") if line.strip()]
    events = [common.strict_json(line) for line in lines]
    steps = parsed["trajectory.json"]["steps"]
    if any(
        type(row.get("step")) is not int or row["step"] != ordinal
        for stream in (steps, events[1:])
        for ordinal, row in enumerate(stream)
    ):
        raise ValueError("Every retained actor ordinal must be an exact integer")
    profile = events[0].get("content_identity_profile")
    if profile not in (None, SELECTION_SCHEMA):
        raise ValueError("Unsupported original readiness profile")
    step = steps[index]
    if profile is None and step.get("content_selection") is not None:
        raise ValueError("Selection witness lacks its original readiness contract")
    score = parsed[f"{snapshot}/evaluation.json"]
    if type(score.get("quality")) not in (int, float) or not 0 <= score["quality"] <= 1:
        raise ValueError("Final scored quality is outside its declared numeric range")
    identity = verify_content_identity(
        step,
        raw[f"{snapshot}/delivery.json"],
        score,
        expected_evaluator_sha256=config["evaluator_sha256"],
        expected_rubric_sha256=config["rubric_sha256"],
        actor_payload_raw=lines[index + 1],
        expected_payload_sha256=launch["host_exchanges"][index + 1]["event_sha256"],
        require_selection=profile == SELECTION_SCHEMA,
    )
    candidates, _ = macro_attribution.candidate_view(step)
    acquisition = {
        "acquired": None,
        "packet_sha256": None,
        "new_information": None,
        "answer_available_in_source": None,
        "scope": "original_public_input_bytes_missing",
    }
    extra_pins = {}
    initial_packet = final_packet = None
    if public_input is not None:
        final_packet = macro_attribution.public_observation(
            root, public_input, launch, result["case_id"], index, "WRITE_TEXT"
        )
        acquisition.update(
            acquired=True,
            packet_sha256=final_packet,
            scope="original_host_reply_and_retained_decodable_bytes; not_owner_attested",
        )
        extra_pins["public_input"] = dict(public_input)
    if initial_public_input is not None:
        initial_packet = macro_attribution.public_observation(
            root, initial_public_input, launch, result["case_id"], 0, actions[0]
        )
        extra_pins["initial_public_input"] = dict(initial_public_input)
    elif index == 0:
        initial_packet = final_packet
    truth = None
    candidate_match = selected_match = delivered_match = reference_pin = None
    if reference is not None:
        # Decide whether reference access is permitted from the already-admitted
        # scorer metadata, before opening or parsing any target bytes.
        if score.get("role") not in ("train", "development", "retention_validation"):
            raise ValueError("Posthoc reference role is sealed or unsupported")
        if not isinstance(reference, dict) or reference.get("sha256") != score.get(
            "reference_sha256"
        ):
            raise ValueError("Posthoc reference binding differs from admitted scorer")
        reference_raw = common.read_bound(root, reference, limit=2 * 1024 * 1024)
        truth = common.strict_json(reference_raw)
        reference_pin = sha(reference_raw)
        if (
            sha(Path(evaluator.__file__).read_bytes()) != config["evaluator_sha256"]
            or score.get("reference_sha256") != reference_pin
            or truth.get("case_id") != result["case_id"]
            or truth.get("source_group") != result["source_group_id"]
            or score.get("source_group") != result["source_group_id"]
            or truth.get("role") not in ("train", "development", "retention_validation")
            or score.get("role") != truth["role"]
            or truth.get("field") not in ("company", "address", "date", "total")
            or not isinstance(truth.get("expected_text"), str)
            or len(truth["expected_text"].encode()) > 8192
        ):
            raise ValueError(
                "Posthoc reference differs from original source/scorer/role"
            )
        target = evaluator.canonical(truth["expected_text"], truth["field"])
        if target is None:
            raise ValueError("Posthoc reference is unscorable")
        candidate_match = (
            None
            if candidates is None
            else any(
                evaluator.canonical(c["text"], truth["field"]) == target
                for c in candidates
            )
        )
        if identity["selected_used"] is True:
            selected_match = (
                evaluator.canonical(
                    step["content_selection"]["selected_candidate"]["text"],
                    truth["field"],
                )
                == target
            )
        delivered_match = (
            evaluator.canonical(step["action"]["arguments"]["text"], truth["field"])
            == target
        )
        if type(score.get("text_quality")) not in (int, float) or score[
            "text_quality"
        ] != float(delivered_match):
            raise ValueError(
                "Final text score differs from pinned reference normalization"
            )
        extra_pins["reference"] = dict(reference)
    attribution = macro_attribution.read_changes(
        steps, index, macro, initial_packet, final_packet, truth
    )
    if digest(source_manifest()) != expected_source_sha256 or any(
        common.read_relative(root, name, limit=8 * 1024 * 1024) != value
        for name, value in raw.items()
    ):
        raise ValueError(
            "Observer source or retained artifacts changed during inspection"
        )
    for name, pin in extra_pins.items():
        common.read_bound(root, pin, limit=2 * 1024 * 1024)
    return {
        "schema": "ndu.real.macro-realization.v1",
        "macro": macro,
        "operation_id": branch["operation_id"],
        "case_id_sha256": digest(result["case_id"]),
        "source_group_sha256": digest(result["source_group_id"]),
        "observer_source_sha256": expected_source_sha256,
        "artifact_sha256s": {name: sha(value) for name, value in raw.items()},
        "optional_inputs": extra_pins,
        "reference_sha256": reference_pin,
        "comparison_binding": {
            "initial_public_state_sha256": branch["initial_public_state_sha256"],
            "initial_packet_sha256": initial_packet,
            "source_sha256": result.get("source_sha256"),
            "model_sha256": result["model_sha256"],
            "control_profile_sha256": result.get("control_profile_sha256"),
            "utility_profile_sha256": result.get("utility_profile_sha256"),
            "evaluator_sha256": config["evaluator_sha256"],
            "rubric_sha256": config["rubric_sha256"],
            "scored_reference_sha256": score.get("reference_sha256"),
            "latency_tariff": tariff,
        },
        "read_attribution": attribution,
        "stages": {
            "observation": acquisition,
            "candidates": {
                "retained_count": None if candidates is None else len(candidates),
                "scorer_match_present": candidate_match,
                "scope": "current_retained_candidates_only; posthoc_reference_if_supplied",
            },
            "selection": {
                "selected_index": identity["selected_index"],
                "selected_used": identity["selected_used"],
                "selected_reference_match": selected_match,
                "status": identity["status"],
                "candidate_set_sha256": identity["candidate_set_sha256"],
                "actor_payload_sha256": identity["actor_payload_sha256"],
            },
            "execution": {
                "completed": True,
                "payload_delivered": identity["payload_delivered"],
                "scored": True,
                "quality": branch["quality"],
                "delivered_reference_match": delivered_match,
                "delivery_sha256": branch["delivery_sha256"],
                "evaluation_sha256": branch["evaluation_sha256"],
                "external_effect_occurred": None,
            },
        },
        "costs": {
            name: branch[name]
            for name in (
                "outer_wall_seconds",
                "latency_cost",
                "provider_cost",
                "energy_joules",
            )
        },
        "full_physical_cost_observed": False,
        "native_owner_authenticated": False,
        "policy_efficacy_evaluated": False,
        "production_admission": False,
    }


def observe_realization_pair(stop_inputs, read_inputs):
    """Read both complete originals; a single final score is never a READ effect."""
    stop, read = (
        observe_realization(**inputs) for inputs in (stop_inputs, read_inputs)
    )
    return compare_realizations(stop, read)


def compare_realizations(stop, read):
    """Compare already-admitted originals; callers retain responsibility for admission."""
    bindings = stop["comparison_binding"], read["comparison_binding"]
    if (
        stop["macro"] != "STOP"
        or read["macro"] != "READ"
        or stop["operation_id"] == read["operation_id"]
        or any(stop[k] != read[k] for k in ("case_id_sha256", "source_group_sha256"))
        or bindings[0] != bindings[1]
        or any(
            type(v) is not str
            or len(v) != 64
            or any(c not in "0123456789abcdef" for c in v)
            for k, v in bindings[0].items()
            if k != "latency_tariff"
        )
    ):
        raise ValueError(
            "Complete STOP/READ originals do not share the same frozen frontier"
        )
    initial = [
        r["read_attribution"]["initial_selected_text_sha256"] for r in (stop, read)
    ]
    if None not in initial and initial[0] != initial[1]:
        raise ValueError("Matched macro initial content selections differ")
    selection = [
        r["read_attribution"]["finalizer_selected_text_sha256"] for r in (stop, read)
    ]
    quality = (
        read["stages"]["execution"]["quality"] - stop["stages"]["execution"]["quality"]
    )
    cost = read["costs"]["latency_cost"] - stop["costs"]["latency_cost"]
    return {
        "schema": "ndu.real.matched-read-attribution.v1",
        "original_report_sha256s": {"STOP": digest(stop), "READ": digest(read)},
        "comparison_binding": bindings[0],
        "selected_text_changed": None
        if None in selection
        else selection[0] != selection[1],
        "delivered_content_changed": stop["stages"]["execution"]["delivery_sha256"]
        != read["stages"]["execution"]["delivery_sha256"],
        "terminal_quality_changed": quality != 0,
        "read_minus_stop_quality": quality,
        "read_minus_stop_observed_latency_cost": cost,
        "read_minus_stop_observed_latency_net": quality - cost,
        "full_physical_net_difference": None,
        "scope": "two matched completed executions; finite observed latency tariff, not a randomized population effect or full physical cost",
        "native_owner_authenticated": False,
        "policy_efficacy_proved": False,
        "production_admission": False,
    }
