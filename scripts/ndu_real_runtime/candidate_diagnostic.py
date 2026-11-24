"""Read-only DEVELOPMENT diagnosis of original candidate and ROI observations.

Accepts registered train v2 chains or linked development observations with schema
``ndu.real.development-transition.v1``. Never calls actors, OCR or training. Uses
the frozen scorer's normalizer; observed ROI coverage is not a causal benefit.
Hashes bind observations, not native owner authority. All attempts remain visible.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time

if __package__ and "." in __package__:
    from ..ndu_real_materials.evaluator import canonical
    from .trajectory import V2_SCHEMA, is_digest, validate_link
    from .objective import canonical_sha
else:
    from ndu_real_materials.evaluator import canonical
    from ndu_real_runtime.trajectory import V2_SCHEMA, is_digest, validate_link
    from ndu_real_runtime.objective import canonical_sha

DEVELOPMENT_SCHEMA = "ndu.real.development-transition.v1"
ROLES = {"train", "development"}
FIELDS = ("company", "date", "address", "total")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, *, positive=False):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=strict_object)


def episode_diagnostic(case, packet, rows, trajectory, final_delivery=None):
    """Separate actual coverage, selection, stopping and acquisition evidence."""
    role = case["role"]
    require(role in ROLES, "Only train/development observations are admitted")
    require(rows and len(rows) <= 8, "An observed episode needs 1..8 rows")
    require(
        packet["case_id"] == case["id"] and packet["requirements"]["text"] is True,
        "Public text-task identity differs",
    )
    require(len(trajectory["steps"]) == len(rows), "Incomplete trajectory companion")
    first, prior = rows[0], None
    delivered, preparation = packet["initial_delivery"]["text"], []
    field = first["reference_field"]
    require(field in FIELDS, "Unknown frozen reference field")
    expected = canonical(first["expected_text"], field)
    require(expected is not None, "Reference outside the frozen normalizer")
    records, roi, coverage, ids = [], [], [], set()
    for index, (row, step) in enumerate(zip(rows, trajectory["steps"])):
        require(
            row["schema"] == (V2_SCHEMA if role == "train" else DEVELOPMENT_SCHEMA)
            and row["split"] == role
            and row["episode_id"] == case["id"]
            and row["source_group"] == case["source_id"]
            and row["origin_run_id"] == first["origin_run_id"]
            and row["episode_step"] == index,
            "Role, source, episode or original attempt differs",
        )
        validate_link(row)
        require(row["record_id"] not in ids, "Duplicate original record")
        ids.add(row["record_id"])
        require(
            row["reference_field"] == field
            and row["expected_text"] == first["expected_text"]
            and all(
                row[key] == first[key]
                for key in (
                    "source_size",
                    "memory_mode",
                    "utility_profile_sha256",
                    "rubric_sha256",
                    "behavior_control_profile_sha256",
                )
            ),
            "Mixed labels or profiles within an episode",
        )
        if prior is not None:
            require(
                row["previous_record_sha256"] == prior["record_sha256"]
                and row["candidate_features"] == prior["next_candidate_features"]
                and row["public_metadata"] == prior["next_public_metadata"]
                and row["before_score"] == prior["after_score"]
                and row["remaining_seconds"] <= prior["remaining_seconds"]
                and prior.get("terminal_reason") is None,
                "Broken original observation chain",
            )
        meta, candidates = row["public_metadata"], row["candidate_metadata"]
        require(
            len(meta) == 16
            and meta[:4] == [float(field == f) for f in FIELDS]
            and len(candidates) == len(row["candidate_features"])
            and 1 <= len(candidates) <= 128
            and all(
                isinstance(c["text"], str) and len(c["text"]) <= 8192
                for c in candidates
            )
            and number(row["duration_seconds"], positive=True)
            and row["execution_status"] in {"completed", "failed"},
            "Invalid observed candidates, metadata or duration",
        )
        require(
            step["case_id"] == case["id"]
            and step["step"] == index
            and step["action"]["action"] == row["action"]
            and step["candidate_metadata"] == candidates
            and step["candidate_features"] == row["candidate_features"]
            and step["public_metadata"] == meta
            and step["observed_action_seconds"] == row["duration_seconds"],
            "Original trajectory does not bind the diagnostic row",
        )
        correct = [c for c in candidates if canonical(c["text"], field) == expected]
        coverage.append(bool(correct))
        action, selected, decision = row["action"], None, "other_action"
        if row["execution_status"] == "failed":
            decision = "execution_failed"
        elif action == "WRITE_TEXT":
            selected = step["action"]["arguments"]["text"]
            require(
                isinstance(selected, str) and len(selected) <= 8192,
                "Invalid actual text action",
            )
            delivered = selected
            decision = (
                "out_of_candidate_write"
                if not any(selected == c["text"] for c in candidates)
                else "write_correct"
                if canonical(selected, field) == expected
                else "ranking_error"
                if correct
                else "write_without_correct_candidate"
            )
        elif action == "STOP":
            decision = (
                "stop_after_reconstructed_text_success"
                if canonical(delivered, field) == expected
                else "stop_with_unmet_reconstructed_text"
            )
        elif action == "PREPARE_ROI":
            preparation.append(row)
            decision = "prepare_roi"
        elif action == "READ_ROI":
            decision = "read_roi"
            roi.append(
                {
                    "record_id": row["record_id"],
                    "step": index,
                    "preparation_record_ids": [p["record_id"] for p in preparation],
                    "preparation_seconds": sum(
                        p["duration_seconds"] for p in preparation
                    ),
                    "read_seconds": row["duration_seconds"],
                    "cost_scope": "observed actions; already included in attempt envelope",
                }
            )
            preparation = []
        records.append(
            {
                "record_id": row["record_id"],
                "record_sha256": row["record_sha256"],
                "step": index,
                "action": action,
                "execution_status": row["execution_status"],
                "candidate_count": len(candidates),
                "correct_candidate_count": len(correct),
                "correct_candidate_origins": dict(
                    Counter(c["origin"] for c in correct)
                ),
                "candidate_status": "covered"
                if correct
                else "missing_correct_candidate",
                "decision": decision,
                "selected_text_sha256": canonical_sha(selected)
                if selected is not None
                else None,
                "duration_seconds": row["duration_seconds"],
            }
        )
        prior = row
    require(
        prior["next_candidate_features"] is None
        and prior["next_public_metadata"] is None
        and (
            prior.get("terminal_reason") in {"actor_stop", "budget_stop"}
            or prior["execution_status"] == "failed"
        ),
        "No observed terminal boundary",
    )
    for item in roi:
        index = item["step"]
        following = coverage[index + 1] if index + 1 < len(coverage) else None
        item.update(
            before_covered=coverage[index],
            after_covered=following,
            successor_record_sha256=rows[index + 1]["record_sha256"]
            if following is not None
            else None,
            outcome="successor_unobserved"
            if following is None
            else (
                "coverage_retained"
                if following and coverage[index]
                else "coverage_gained"
                if following
                else "coverage_lost"
                if coverage[index]
                else "still_missing"
            ),
        )
    if final_delivery is not None:
        require(
            final_delivery["case_id"] == case["id"], "Final delivery identity differs"
        )
    return {
        "reference_field": field,
        "reference_canonical_sha256": canonical_sha(expected),
        "rows": records,
        "roi_reads": roi,
        "decision_scope": "recorded action arguments and public initial text; final effects are separate",
        "reconstructed_text_correct": canonical(delivered, field) == expected,
        "observed_final_text_correct": None
        if final_delivery is None
        else canonical(final_delivery["text"], field) == expected,
        "final_delivery_matches_reconstruction": None
        if final_delivery is None
        else final_delivery["text"] == delivered,
        "observed_action_seconds": sum(r["duration_seconds"] for r in rows),
        "unconsumed_preparation_seconds": sum(
            r["duration_seconds"] for r in preparation
        ),
    }


class Reader:
    def __init__(self, maximum_bytes):
        require(
            type(maximum_bytes) is int and 1 <= maximum_bytes <= 64 * 1024**2,
            "Invalid read budget",
        )
        self.maximum, self.total, self.bindings = maximum_bytes, 0, []

    def read(self, path, digest=None, *, root):
        path, root = Path(path), Path(root)
        require(
            path.is_absolute()
            and root.is_absolute()
            and path.resolve() == path
            and path.is_relative_to(root)
            and path.is_file(),
            "Input outside declared regular-file root",
        )
        require(path.stat().st_size <= 8 * 1024**2, "Input exceeds file bound")
        with path.open("rb") as stream:
            raw = stream.read(min(8 * 1024**2, self.maximum - self.total) + 1)
        self.total += len(raw)
        require(
            self.total <= self.maximum and len(raw) <= 8 * 1024**2,
            "Diagnostic read budget exhausted",
        )
        observed = hashlib.sha256(raw).hexdigest()
        require(
            digest is None or is_digest(digest) and observed == digest,
            "Input digest differs",
        )
        self.bindings.append({"path": str(path), "sha256": observed, "bytes": len(raw)})
        return raw

    def json(self, path, digest=None, *, root):
        return decode(self.read(path, digest, root=root))


def diagnose(plan):
    """Read pinned original inventories; retain failures and unstarted attempts."""
    require(
        plan["schema"] == "ndu.real.candidate-diagnostic-plan.v1",
        "Unknown diagnostic plan",
    )
    require(
        set(plan["roles"]) <= ROLES and plan["roles"],
        "Only train/development plans are admitted",
    )
    reader = Reader(plan["max_input_bytes"])
    root, materials = Path(plan["collection_root"]), Path(plan["material_root"])
    selected = reader.json(**plan["selected_sources"], root=root)
    cases = {}
    for group in selected["cases"].values():
        for case in group:
            if case["role"] in plan["roles"]:
                require(
                    case["id"] not in cases or cases[case["id"]] == case,
                    "Case role binding differs",
                )
                cases[case["id"]] = case
    attempts, phases, seen_requests = {}, [], set()
    require(1 <= len(plan["phases"]) <= 16, "Invalid phase count")
    for bindings in plan["phases"]:
        inventory = reader.json(**bindings["inventory"], root=root)
        phase = reader.json(**bindings["result"], root=root)
        registrations = inventory["planned"]
        require(
            phase["planned"] == len(registrations)
            and phase["phase"] == inventory["phase"],
            "Phase denominator differs",
        )
        terminals = {}
        for value in phase["attempts"]:
            key = (
                value["attempt"]["original_operation_id"]
                if "attempt" in value
                else Path(value["request"]).stem
            )
            require(key not in terminals, "Duplicate terminal attempt")
            terminals[key] = value
        unstarted = set(phase["not_started_requests"])
        require(
            len(unstarted) == len(phase["not_started_requests"]),
            "Duplicate unstarted attempt",
        )
        registered = set()
        for item in registrations:
            path = item["request"]
            require(path not in seen_requests, "Duplicate registered request")
            seen_requests.add(path)
            request = reader.json(path, item["sha256"], root=root)
            case, profile = request["case"], request["profile"]
            require(
                case["role"] in plan["roles"] and cases.get(case["id"]) == case,
                "Request source/role is not registered train/development",
            )
            operation = profile["original_operation_id"]
            require(
                isinstance(operation, str)
                and Path(operation).name == operation
                and operation not in attempts
                and Path(path).name == operation + ".json",
                "Duplicate or malformed original operation",
            )
            registered.add(operation)
            require(
                (operation in terminals) != (path in unstarted),
                "Missing or repeated original terminal",
            )
            require(
                Path(request["output"]) == root / "episodes" / operation,
                "Episode output binding differs",
            )
            attempts[operation] = {
                "request": request,
                "terminal": terminals.get(operation),
                "request_sha256": item["sha256"],
            }
        require(
            set(terminals) <= registered
            and unstarted <= {r["request"] for r in registrations},
            "Unregistered attempt was appended",
        )
        require(number(phase["elapsed_wall_seconds"]), "Invalid phase elapsed cost")
        phases.append(
            {
                "phase": phase["phase"],
                "planned": len(registrations),
                "elapsed_wall_seconds": phase["elapsed_wall_seconds"],
            }
        )
    require(1 <= len(attempts) <= 128, "Attempt inventory outside diagnostic bound")
    rows, record_ids = defaultdict(list), set()
    raw = reader.read(**plan["records"], root=root)
    for line in raw.splitlines():
        require(
            line and len(line) <= 2 * 1024**2 and len(record_ids) < 1024,
            "Record inventory outside diagnostic bound",
        )
        row = decode(line)
        require(
            row["split"] in plan["roles"] and row["origin_run_id"] in attempts,
            "Unregistered or non-development record",
        )
        require(row["record_id"] not in record_ids, "Duplicate original record")
        record_ids.add(row["record_id"])
        rows[row["origin_run_id"]].append(row)
    output = []
    for operation, registered in attempts.items():
        request, terminal = registered["request"], registered["terminal"]
        case, destination = request["case"], Path(request["output"])
        item = {
            "operation_id": operation,
            "case_id": case["id"],
            "source_group": case["source_id"],
            "role": case["role"],
            "request_sha256": registered["request_sha256"],
            "status": "NotStarted"
            if terminal is None
            else terminal.get("terminal_status", "Unresolved"),
            "wall_seconds": None,
            "cpu_seconds": None,
            "energy_joules": None,
            "provider_charges": None,
            "diagnosis": None,
        }
        result = None
        if terminal is not None and "attempt" in terminal:
            receipt = reader.json(destination / "original-attempt.json", root=root)
            require(
                receipt == terminal["attempt"]
                and receipt["request_sha256"] == item["request_sha256"],
                "Original attempt receipt differs",
            )
            require(
                receipt["original_operation_id"] == operation
                and terminal["output"] == str(destination),
                "Original attempt scope differs",
            )
            for metric in (
                "wall_seconds",
                "cpu_seconds",
                "energy_joules",
                "provider_charges",
            ):
                value = receipt.get(metric)
                require(
                    value is None or number(value), "Invalid original observed cost"
                )
                item[metric] = value
            item.update(
                status=receipt["terminal_status"],
                result_sha256=receipt["result_sha256"],
                retry_of=receipt.get("retry_of"),
            )
            result = reader.json(
                destination / "result.json", receipt["result_sha256"], root=root
            )
            require(
                result["case_id"] == case["id"]
                and result["split"] == case["role"]
                and result["terminal_status"] == item["status"]
                and result["original_operation_id"] == operation,
                "Original result scope differs",
            )
        observed = sorted(rows.get(operation, []), key=lambda r: r["episode_step"])
        if observed:
            require(result is not None, "Observation has no original result receipt")
            require(
                request["config"]["material_root"] == str(materials),
                "Public material root differs",
            )
            packet_binding = case["packet"]
            require(
                packet_binding["path"]
                == f"public/{case['role']}/{case['id']}/case.json",
                "Packet is not a public role-bound observation",
            )
            packet = reader.json(
                materials / packet_binding["path"],
                packet_binding["sha256"],
                root=materials,
            )
            trajectory = reader.json(destination / "trajectory.json", root=root)
            score = result.get("score_components") or {}
            delivery = None
            if score.get("delivery_sha256") is not None:
                delivery = reader.json(
                    destination
                    / f"delivery-{len(trajectory['steps']):02d}"
                    / "delivery.json",
                    score["delivery_sha256"],
                    root=root,
                )
            item["diagnosis"] = episode_diagnostic(
                case, packet, observed, trajectory, delivery
            )
            text_score = score.get("text_quality")
            observed_correct = item["diagnosis"]["observed_final_text_correct"]
            item["text_evaluator_agrees"] = (
                None
                if text_score is None or observed_correct is None
                else text_score == float(observed_correct)
            )
        else:
            item["observation_evidence"] = "unavailable; no quality or ROI inference"
        output.append(item)
    observed = [
        r for item in output if item["diagnosis"] for r in item["diagnosis"]["rows"]
    ]
    reads = [
        r
        for item in output
        if item["diagnosis"]
        for r in item["diagnosis"]["roi_reads"]
    ]
    return {
        "schema": "ndu.real.candidate-diagnostic.v1",
        "diagnostic_id": plan["diagnostic_id"],
        "scientific_admission": "HOLD",
        "scope": "DEVELOPMENT_ONLY_ORIGINAL_OBSERVATIONS",
        "actors_or_ocr_executed": False,
        "training_executed": False,
        "counterfactual_roi_benefit_established": False,
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "full_physical_cost_complete": False,
        "attempts": output,
        "phases": phases,
        "bindings": reader.bindings,
        "summary": {
            "registered_attempts": len(output),
            "observed_rows": len(observed),
            "terminal_status_counts": dict(Counter(i["status"] for i in output)),
            "candidate_status_counts": dict(
                Counter(r["candidate_status"] for r in observed)
            ),
            "decision_counts": dict(Counter(r["decision"] for r in observed)),
            "roi_outcome_counts": dict(Counter(r["outcome"] for r in reads)),
        },
        "costs": {
            "observed_action_seconds": sum(r["duration_seconds"] for r in observed),
            "sum_known_attempt_wall_seconds": sum(
                i["wall_seconds"] for i in output if i["wall_seconds"] is not None
            ),
            "unknown_attempt_wall_count": sum(
                i["wall_seconds"] is None for i in output
            ),
            "energy_joules": None,
            "provider_charges": None,
            "accounting": "Action spans are included in attempt envelopes; phase elapsed wall overlaps both. Never add these levels.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.plan.read_bytes()
    require(
        len(raw) <= 1024**2 and hashlib.sha256(raw).hexdigest() == args.plan_sha256,
        "Diagnostic plan differs",
    )
    plan = decode(raw)
    for bound in plan["source_pins"]:
        require(
            hashlib.sha256(Path(bound["path"]).read_bytes()).hexdigest()
            == bound["sha256"],
            "Frozen diagnostic source changed",
        )
    required_sources = {
        Path(__file__).resolve(),
        Path(sys.modules[canonical.__module__].__file__).resolve(),
        Path(sys.modules[validate_link.__module__].__file__).resolve(),
    }
    require(
        required_sources <= {Path(p["path"]).resolve() for p in plan["source_pins"]},
        "Diagnostic, scorer or chain implementation is not pinned",
    )
    wall, cpu = time.perf_counter(), time.process_time()
    report = diagnose(plan)
    report.update(
        plan_sha256=args.plan_sha256,
        diagnostic_wall_seconds=time.perf_counter() - wall,
        diagnostic_cpu_seconds=time.process_time() - cpu,
        source_pins=plan["source_pins"],
    )
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
