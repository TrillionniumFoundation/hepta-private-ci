"""Read pinned historical content artifacts; emit only digests and diagnostics.

Optional references are admitted only for a predeclared post hoc training or
development scope. This program never launches an actor, changes an input, or
turns missing historical selection evidence into a selected-used label.
"""

import argparse
import hashlib
import json
from pathlib import Path

from ndu_real_materials.common import read_bound, read_relative, strict_json, write_json
from ndu_real_materials import evaluator
from .content_identity import check_selection, verify_evaluation
from .metering import canonical_sha

SCHEMA = "ndu.real.content-audit-manifest.v1"
MAX_TOTAL_BYTES = 256 * 1024 * 1024


def _read(root, binding, total, limit=8 * 1024 * 1024):
    total[0] += binding["bytes"]
    if total[0] > MAX_TOTAL_BYTES:
        raise ValueError("AUDIT_TOTAL_BYTES_EXCEEDED")
    try:
        raw = read_bound(root, binding, limit=limit)
        return raw, strict_json(raw)
    except (ValueError, OSError):
        raise ValueError("AUDIT_PINNED_ARTIFACT_ADMISSION_FAILED") from None


def _episode(root, entry, manifest, total):
    case_id = entry["case_id"]
    _, trajectory = _read(root, entry["trajectory"], total)
    _, launch = _read(root, entry["launch"], total)
    if launch.get("schema") != "ndu.real.actor-isolation.v1" or not isinstance(
        launch.get("stdout"), str
    ):
        raise ValueError("AUDIT_LAUNCH_SCHEMA")
    steps = trajectory["steps"]
    if not isinstance(steps, list) or not 0 <= len(steps) <= 8:
        raise ValueError("AUDIT_ACTION_BOUND")
    lines = [line.encode() for line in launch["stdout"].split("\n") if line.strip()]
    exchanges = launch["host_exchanges"]
    if len(lines) > 1024 or not isinstance(exchanges, list):
        raise ValueError("AUDIT_WIRE_BOUND")
    wire_receipts = len(lines) == len(exchanges) and all(
        hashlib.sha256(raw).hexdigest() == exchange.get("event_sha256")
        for raw, exchange in zip(lines, exchanges)
    )
    events = [strict_json(raw) for raw in lines]
    observations = [
        (raw, value)
        for raw, value in zip(lines, events)
        if value.get("schema") == "ndu.real.actor-observation.v1"
    ]
    ordered = len(observations) == len(steps) and all(
        value.get("case_id") == case_id and value.get("step") == index
        for index, (_, value) in enumerate(observations)
    )
    snapshots = {}
    if not isinstance(entry["snapshots"], list) or len(entry["snapshots"]) > 9:
        raise ValueError("AUDIT_SNAPSHOT_BOUND")
    for item in entry["snapshots"]:
        index = item["step"]
        if type(index) is not int or not -1 <= index < len(steps) or index in snapshots:
            raise ValueError("AUDIT_SNAPSHOT_IDENTITY")
        raw, delivery = _read(root, item["delivery"], total, 65536)
        evaluation = None
        if item.get("evaluation") is not None:
            _, evaluation = _read(root, item["evaluation"], total, 65536)
        snapshots[index] = (item, raw, delivery, evaluation)
    reference = None
    if entry.get("reference") is not None:
        if entry.get("role") not in {"train", "development", "retention_validation"}:
            raise ValueError("AUDIT_REFERENCE_SCOPE_REFUSED")
        local_source = hashlib.sha256(Path(evaluator.__file__).read_bytes()).hexdigest()
        if (
            manifest.get("normalizer_source_sha256") != local_source
            or manifest["evaluator_source_sha256"] != local_source
        ):
            raise ValueError("AUDIT_NORMALIZER_SOURCE_MISMATCH")
        _, reference = _read(root, entry["reference"], total, 2 * 1024 * 1024)
        if reference["case_id"] != case_id or reference["role"] != entry["role"]:
            raise ValueError("AUDIT_REFERENCE_IDENTITY")
        if evaluator.canonical(reference["expected_text"], reference["field"]) is None:
            raise ValueError("AUDIT_REFERENCE_UNSCORABLE")
    rows = []
    for index, step in enumerate(steps):
        if step["action"]["action"] != "WRITE_TEXT":
            continue
        action = step["action"]
        text = action["arguments"]["text"]
        if not isinstance(text, str) or len(text.encode()) > 8192:
            raise ValueError("AUDIT_TEXT_BOUND")
        candidates = step.get("candidate_metadata")
        if candidates is not None and (
            not isinstance(candidates, list)
            or not 1 <= len(candidates) <= 128
            or any(
                not isinstance(candidate.get("text"), str)
                or len(candidate["text"].encode()) > 8192
                for candidate in candidates
            )
        ):
            raise ValueError("AUDIT_CANDIDATE_BOUND")
        wire, wire_binding = None, False
        if ordered:
            wire, observed = observations[index]
            original = {
                key: value
                for key, value in step.items()
                if key != "observed_action_seconds"
            }
            wire_binding = original == observed
        selection = None
        if step.get("content_selection") is not None:
            try:
                selection = check_selection(step, required=True)
                selection_check = True
            except (ValueError, KeyError, TypeError):
                selection_check = False
        else:
            selection_check = None
        snapshot = snapshots.get(index)
        delivery_binding = evaluation_binding = None
        raw = delivery = evaluation = item = None
        if snapshot is not None:
            item, raw, delivery, evaluation = snapshot
            delivery_binding = (
                delivery.get("schema") == "ndu.real.delivery.v1"
                and delivery.get("case_id") == case_id
                and delivery.get("text") == text
            )
            if evaluation is not None:
                try:
                    verify_evaluation(
                        evaluation,
                        raw,
                        case_id=case_id,
                        evaluator_sha256=manifest["evaluator_source_sha256"],
                        rubric_sha256=manifest["rubric_sha256"],
                    )
                    evaluation_binding = reference is None or (
                        evaluation.get("reference_sha256")
                        == entry["reference"]["sha256"]
                    )
                except (ValueError, KeyError, TypeError):
                    evaluation_binding = False
        checks = {
            "isolated_actor_completed": (
                type(launch.get("exit_code")) is int
                and launch["exit_code"] == 0
                and launch.get("enforced_before_actor_exec") is True
            ),
            "candidate_selection": selection_check,
            "raw_actor_wire_receipt": wire_receipts,
            "wire_to_trajectory": wire_binding,
            "action_to_delivery": delivery_binding,
            "delivery_to_evaluator": evaluation_binding,
        }
        diagnostic = None
        if reference is not None:
            field = reference["field"]
            target = evaluator.canonical(reference["expected_text"], field)
            action_match = evaluator.canonical(text, field) == target
            delivered_match = (
                None
                if delivery is None
                else evaluator.canonical(delivery.get("text"), field) == target
            )
            scorer_matches = None
            if evaluation_binding and "text_quality" in evaluation:
                scorer_matches = evaluation.get("text_quality") == float(
                    delivered_match
                )
            diagnostic = {
                "reference_sha256": entry["reference"]["sha256"],
                "candidate_reference_match_present": None
                if candidates is None
                else any(
                    evaluator.canonical(candidate["text"], field) == target
                    for candidate in candidates
                ),
                "payload_reference_match": action_match,
                "delivery_reference_match": delivered_match,
                "scorer_text_quality_matches_normalizer": scorer_matches,
                "content_failure_present_at_actor_payload": not action_match
                if wire_receipts and wire_binding
                else None,
            }
        failures = [name for name, passed in checks.items() if passed is False]
        if diagnostic and diagnostic["scorer_text_quality_matches_normalizer"] is False:
            failures.append("evaluator_text_score")
        unknown = [name for name, passed in checks.items() if passed is None]
        rows.append(
            {
                "step": index,
                "checks": checks,
                "first_observed_discrepancy": failures[0] if failures else None,
                "first_unknown_link": unknown[0] if unknown else None,
                "selected_used": True
                if all(value is True for value in checks.values())
                else None,
                "selected_index": None
                if selection is None
                else selection["selected_index"],
                "candidate_count": None if candidates is None else len(candidates),
                "candidate_metadata_sha256": None
                if candidates is None
                else canonical_sha(candidates),
                "payload_matches_observed_candidate": None
                if candidates is None
                else any(candidate["text"] == text for candidate in candidates),
                "actor_payload_sha256": None
                if wire is None
                else hashlib.sha256(wire).hexdigest(),
                "action_sha256": canonical_sha(action),
                "payload_text_sha256": canonical_sha(text),
                "delivery_sha256": None
                if raw is None
                else hashlib.sha256(raw).hexdigest(),
                "evaluation_sha256": None
                if evaluation is None
                else item["evaluation"]["sha256"],
                "posthoc_reference_diagnostic": diagnostic,
            }
        )
    return {
        "case_id_sha256": canonical_sha(case_id),
        "trajectory_sha256": entry["trajectory"]["sha256"],
        "launch_sha256": entry["launch"]["sha256"],
        "launch_completed": type(launch.get("exit_code")) is int
        and launch["exit_code"] == 0
        and launch.get("enforced_before_actor_exec") is True,
        "rows": rows,
    }


def audit(root, manifest_raw, expected_manifest_sha256):
    if (
        len(manifest_raw) > 2 * 1024 * 1024
        or hashlib.sha256(manifest_raw).hexdigest() != expected_manifest_sha256
    ):
        raise ValueError("AUDIT_MANIFEST_BINDING_MISMATCH")
    manifest = strict_json(manifest_raw)
    if (
        manifest.get("schema") != SCHEMA
        or not isinstance(manifest.get("episodes"), list)
        or not 1 <= len(manifest["episodes"]) <= 64
    ):
        raise ValueError("AUDIT_MANIFEST_SCHEMA_OR_BOUND")
    expected = manifest["expected_write_text_count"]
    if type(expected) is not int or not 0 <= expected <= 512:
        raise ValueError("AUDIT_DENOMINATOR_BOUND")
    pins = [manifest["evaluator_source_sha256"], manifest["rubric_sha256"]]
    if manifest.get("normalizer_source_sha256") is not None:
        pins.append(manifest["normalizer_source_sha256"])
    if any(
        not isinstance(pin, str)
        or len(pin) != 64
        or any(char not in "0123456789abcdef" for char in pin)
        for pin in pins
    ):
        raise ValueError("AUDIT_PIN_SHAPE")
    total, episodes, seen = [0], [], set()
    for entry in manifest["episodes"]:
        identity = (entry["trajectory"]["sha256"], entry["launch"]["sha256"])
        if identity in seen:
            raise ValueError("AUDIT_DUPLICATE_EPISODE")
        seen.add(identity)
        episodes.append(_episode(root, entry, manifest, total))
    rows = [row for episode in episodes for row in episode["rows"]]
    return {
        "schema": "ndu.real.content-audit.v1",
        "execution_status": "completed",
        "manifest_sha256": expected_manifest_sha256,
        "episode_count": len(episodes),
        "distinct_case_count": len({episode["case_id_sha256"] for episode in episodes}),
        "evaluator_source_sha256": manifest["evaluator_source_sha256"],
        "normalizer_source_sha256": manifest.get("normalizer_source_sha256"),
        "rubric_sha256": manifest["rubric_sha256"],
        "expected_write_text_count": expected,
        "observed_write_text_count": len(rows),
        "denominator_matches": len(rows) == expected,
        "input_bytes_read": total[0],
        "chain_discrepancy_count": sum(
            row["first_observed_discrepancy"] is not None for row in rows
        ),
        "unknown_selection_count": sum(
            row["checks"]["candidate_selection"] is None for row in rows
        ),
        "episodes": episodes,
        "raw_text_published": False,
        "inputs_modified": False,
        "image_scoring_replayed": False,
        "promotion_evidence": False,
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "scope": "Post hoc consistency and text diagnosis; selected identity remains unknown when legacy evidence is absent.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = read_relative(
            args.manifest.parent, args.manifest.name, limit=2 * 1024 * 1024
        )
        report = audit(args.root, raw, args.expected_manifest_sha256)
        # The shared writer uses exclusive creation ("xb"), preserving existing evidence.
        write_json(args.output, report)
    except Exception as error:
        # Exception messages and paths may contain private source labels.
        code = str(error)
        if isinstance(error, FileExistsError):
            code = "AUDIT_OUTPUT_EXISTS"
        elif not code.startswith("AUDIT_") or not code.replace("_", "").isalnum():
            code = "AUDIT_REJECTED"
        print(
            json.dumps(
                {
                    "execution_status": "rejected",
                    "error_type": type(error).__name__,
                    "error_code": code,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "execution_status": "completed",
                "observed_write_text_count": report["observed_write_text_count"],
                "denominator_matches": report["denominator_matches"],
                "chain_discrepancy_count": report["chain_discrepancy_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
