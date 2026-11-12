"""Post-episode macro realization from retained native bytes, never policy input.

This checks receipt consistency, not native-owner authority. Missing acquisition
or legacy selection evidence remains unknown; absent candidates do not prove
that the source image lacks information. References are used only after the
completed macro has passed the existing wire/delivery/scorer admission.
"""

import math
from pathlib import Path

from ndu_real_materials import common, evaluator
from . import content_identity, metacontrol_macro_contract, metering
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
            metacontrol_macro_contract,
            metering,
        )
    ]
    return {
        path.resolve().relative_to(root).as_posix(): sha(path.read_bytes())
        for path in paths
    }


def _valid_box(value):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) is int and 0 <= v <= 16_000_000 for v in value)
        and value[0] < value[2]
        and value[1] < value[3]
    )


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
    reference=None,
):
    """Observe one complete STOP/READ macro; optional bindings are root-relative.

    public_input is the original host reply immediately preceding WRITE_TEXT.
    reference is an original independently scored train/development reference.
    Both use the closed {path, bytes, sha256} binding; neither reaches an actor.
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
    candidates = step.get("candidate_metadata")
    if candidates is not None and (
        not isinstance(candidates, list)
        or not 1 <= len(candidates) <= 128
        or any(
            not isinstance(c, dict)
            or set(c) != {"text", "bbox", "origin"}
            or not isinstance(c["text"], str)
            or len(c["text"].encode()) > 8192
            or c["origin"]
            not in ("pixel_ocr", "registered_public_text", "no_recognized_text")
            or not isinstance(c["bbox"], list)
            or len(c["bbox"]) != 4
            or any(type(v) is not int or not 0 <= v <= 16_000_000 for v in c["bbox"])
            for c in candidates
        )
    ):
        raise ValueError("Invalid retained candidate inventory")
    acquisition = {
        "acquired": None,
        "packet_sha256": None,
        "new_information": None,
        "answer_available_in_source": None,
        "scope": "original_public_input_bytes_missing",
    }
    extra_pins = {}
    if public_input is not None:
        reply = common.read_bound(root, public_input, limit=131072)
        exchange = launch["host_exchanges"][index]
        if sha(reply) != exchange.get("reply_sha256") or len(reply) != exchange.get(
            "reply_bytes"
        ):
            raise ValueError("Retained public input differs from original host reply")
        public = common.strict_json(reply)
        if (
            set(public)
            != {
                "schema",
                "case_id",
                "step",
                "remaining_seconds",
                "prepared_roi",
                "observation",
                "delivery",
                "text_committed",
                "forced_action",
            }
            or public["schema"] != "ndu.real.actor-step.v1"
            or public["case_id"] != result["case_id"]
            or public["step"] != index
            or type(public["step"]) is not int
            or public["forced_action"] not in (None, "WRITE_TEXT")
            or type(public["text_committed"]) is not bool
            or type(public["remaining_seconds"]) not in (int, float)
            or not math.isfinite(public["remaining_seconds"])
            or public["remaining_seconds"] < 0
            or (
                public["prepared_roi"] is not None
                and not _valid_box(public["prepared_roi"])
            )
        ):
            raise ValueError(
                "Public input differs from finalizer state or leaks fields"
            )
        packet = public["observation"]
        if (
            not isinstance(packet, dict)
            or set(packet) != {"path", "sha256", "bbox", "kind"}
            or packet["kind"] not in ("overview", "roi")
            or not _valid_box(packet["bbox"])
        ):
            raise ValueError("Invalid retained public observation")
        delivery = public["delivery"]
        if (
            not isinstance(delivery, dict)
            or set(delivery) != {"schema", "case_id", "text", "image"}
            or delivery["schema"] != "ndu.real.delivery.v1"
            or delivery["case_id"] != result["case_id"]
            or (
                delivery["text"] is not None
                and (
                    not isinstance(delivery["text"], str)
                    or len(delivery["text"].encode()) > 8192
                )
            )
        ):
            raise ValueError("Invalid closed public delivery contract")
        delivered_image = delivery["image"]
        if delivered_image is not None:
            if (
                not isinstance(delivered_image, dict)
                or set(delivered_image) != {"path", "sha256", "bytes", "bbox"}
                or not _valid_box(delivered_image["bbox"])
            ):
                raise ValueError("Invalid closed public image contract")
            common.read_bound(
                root / "public",
                {k: delivered_image[k] for k in ("path", "sha256", "bytes")},
            )
        image_raw = common.read_relative(root / "public", packet["path"])
        if sha(image_raw) != packet["sha256"]:
            raise ValueError("Retained observation bytes differ from host input")
        evaluator.image_from_bytes(image_raw)
        acquisition.update(
            acquired=True,
            packet_sha256=packet["sha256"],
            scope="original_host_reply_and_retained_decodable_bytes; not_owner_attested",
        )
        extra_pins["public_input"] = dict(public_input)
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
