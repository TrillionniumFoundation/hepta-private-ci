"""Source-pinned prediction diagnostics on actual adjacent action/STOP macros.

This driver replays the original frozen collector. It neither trains a new
generator nor creates counterfactual outcomes, policy-benefit estimates or
independent training repetitions. Missing support and failed attempts survive.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

from .conditional_particles import ConditionalResidualBank, UnsupportedCondition
from .controllers import ControlPlan, PublicState
from .objective import edge_value
from .stopped_control import StoppedController
from .stopped_diagnostics import (
    REGISTRATION_SCHEMA as REGISTRATION_SCHEMA,
    ROLES,
    Budget,
    _aggregate,
    _json,
    _number,
    _pinned_json,
    _records,
    _write,
    validate_registration as validate_registration,
    weighted_crps as weighted_crps,
)
from .stopped_torch import FrozenMacroPredictor, select_stopped_macros, source_identity
from .trajectory import V2_SCHEMA


def _public_state(macro, features, metadata):
    row = macro.start_row
    if row["schema"] == V2_SCHEMA:
        return PublicState(
            features,
            row["remaining_seconds"],
            row["episode_step"],
            tuple(row["legal_actions"]),
        )
    budget = _number(metadata.get("episode_wall_seconds"))
    if not 0 < budget <= 3600:
        raise ValueError(
            "Legacy public remaining time needs the original episode budget"
        )
    legal = ("STOP",) if row["action"] == "STOP" else (row["action"], "STOP")
    return PublicState(
        features,
        row["public_metadata"][14] * budget,
        int(row["record_id"].rsplit("/", 1)[1]),
        legal,
    )


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(args.max_wall_seconds)
    report = {
        "schema": "ndu.stopped.calibration-result.v1",
        "status": "started",
        "hold": True,
        "net_benefit_established": False,
        "counterfactual_outcomes_created": False,
        "policy_evaluation_performed": False,
        "independent_training_repeats": 0,
        "source_group_disjointness": "declared_frozen_rosters_checked; complete_prior_training_exposure_not_authenticated",
        "requested_device": args.device,
        "gpu_used": False,
        "runtime": None,
        "input_pins": {
            "records_sha256": args.expected_records_sha256,
            "weights_sha256": args.expected_weights_sha256,
            "registration_sha256": args.expected_registration_sha256,
            "behavior_metadata_sha256": args.expected_behavior_metadata_sha256,
            "source_sha256": args.expected_source_sha256,
            "parent_records_sha256": args.expected_parent_records_sha256,
        },
        "diagnostic_macros_attempted": 0,
        "diagnostic_macros_recorded": 0,
        "deadline_enforcement": "cooperative_stage_and_row_checks; outer_owner_needed_for_hard_kill",
        "cost_scope": "driver_run_interval_excludes_interpreter_imports_and_final_receipt_serialization; outer_owner_required; prior_collection_recorded_once; transport_money_energy_unknown",
    }
    _write(output / "started.json", report)
    predictor, diagnostic_rows = None, []
    try:
        with budget.stage("admission"):
            registration = validate_registration(
                _pinned_json(args.registration, args.expected_registration_sha256)
            )
            metadata = _pinned_json(
                args.behavior_metadata, args.expected_behavior_metadata_sha256
            )
            if (
                not isinstance(metadata, dict)
                or metadata.get("core") != registration["core"]
                or metadata.get("weights_sha256") != args.expected_weights_sha256
            ):
                raise ValueError(
                    "Original behavior metadata differs from the selected core or checkpoint"
                )
            rows, manifest = _records(
                args.records, args.expected_records_sha256, budget
            )
            if bool(args.parent_records) != bool(args.expected_parent_records_sha256):
                raise ValueError("Parent records require their exact original SHA256")
            if args.parent_records:
                _, parent = _records(
                    args.parent_records,
                    args.expected_parent_records_sha256,
                    budget,
                    selected_weights=args.expected_weights_sha256,
                )
                if parent["selected_raw_lines_sha256"] != manifest["sha256"] or parent[
                    "selected_records"
                ] != len(rows):
                    raise ValueError(
                        "Behavior subset is not the exact selected original parent lines"
                    )
                manifest["parent_selection"] = parent
            roles = {
                group: role
                for role in ROLES
                for group in registration[role + "_source_groups"]
            }
            if any(row.get("source_group") not in roles for row in rows):
                raise ValueError(
                    "An original source group has no frozen registered role"
                )
            report["registration"] = registration
            report["input_role_counts"] = dict(
                Counter(roles[row["source_group"]] for row in rows)
            )
            report["source_manifest"] = {
                "records": manifest,
                "registration_sha256": args.expected_registration_sha256,
                "behavior_metadata_sha256": args.expected_behavior_metadata_sha256,
                "weights_sha256": args.expected_weights_sha256,
                "expected_source_sha256": args.expected_source_sha256,
                "actual_source_sha256": source_identity(),
                "driver_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            }
            _write(output / "source-manifest.json", report["source_manifest"])
            if (
                report["source_manifest"]["actual_source_sha256"]
                != args.expected_source_sha256
            ):
                raise ValueError(
                    "Actual diagnostic dependency source differs from the frozen pin"
                )
            unfitted = metadata.get("status") == "BOOTSTRAP_READY_NOT_A_FIT"
            if registration["behavior_was_unfitted_collector"] != unfitted:
                raise ValueError(
                    "Registered collector disposition differs from its original receipt"
                )
            prior_records = metadata.get("records") or {}
            if not isinstance(prior_records, dict):
                raise ValueError("Original receipt record inventory is malformed")
            prior_group_count = prior_records.get("source_groups")
            report["original_receipt_training_source_groups"] = prior_group_count
            if (
                not unfitted
                and type(prior_group_count) is int
                and prior_group_count != len(registration["fit_source_groups"])
            ):
                raise ValueError(
                    "Registered fit roster count differs from the original training receipt"
                )
            if not registration["fit_source_groups"]:
                raise ValueError(
                    "Known unfitted collector admitted by receipt but empty-fit residual banks are not yet supported"
                )
        with budget.stage("extract_actual_terminal_macros"):
            macros, report["selection"] = select_stopped_macros(
                rows, expected_behavior_weights_sha256=args.expected_weights_sha256
            )
            legacy = any(row["schema"] != V2_SCHEMA for row in rows)
            report["legacy_memory_source_established"] = False if legacy else None
            report["memory_semantics"] = (
                "pinned_metadata_declaration_does_not_prove_original_legacy_memory_source"
                if legacy
                else "recorded_v2_memory_mode_checked"
            )
            if legacy and metadata.get("memory_mode") != registration["memory_mode"]:
                raise ValueError(
                    "Legacy records need an explicit original metadata memory mode; no reset default is inferred"
                )
            if any(
                row["schema"] == V2_SCHEMA
                and row["memory_mode"] != registration["memory_mode"]
                for row in rows
            ):
                raise ValueError("Original collection and replay memory modes differ")
            selected = [
                m for m in macros if roles[m.start_row["source_group"]] != "fit"
            ]
            report["macro_role_counts"] = dict(
                Counter(roles[m.start_row["source_group"]] for m in macros)
            )
            if not any(
                roles[m.start_row["source_group"]] == "calibration" for m in selected
            ):
                raise ValueError(
                    "No admitted actual terminal macros in the registered calibration sources"
                )
        with budget.stage("load_frozen_behavior_checkpoint"):
            import torch

            if args.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError(
                    "Requested CUDA diagnostic has no actual CUDA device"
                )
            torch.manual_seed(registration["seed"])
            predictor = FrozenMacroPredictor(
                args.weights,
                expected_weights_sha256=args.expected_weights_sha256,
                expected_source_sha256=args.expected_source_sha256,
                core=registration["core"],
                memory_mode=registration["memory_mode"],
                device=args.device,
            )
            report["runtime"] = {
                "python": sys.version,
                "torch": str(torch.__version__),
                "cuda_available": bool(torch.cuda.is_available()),
                "cuda_device_count": torch.cuda.device_count(),
                "actual_model_device": str(next(predictor.model.parameters()).device),
                "cuda_device_name": torch.cuda.get_device_name(0)
                if args.device == "cuda"
                else None,
            }
            report["gpu_used"] = args.device == "cuda"
        with budget.stage("replay_original_behavior_states"):
            encoded = {}
            anchor = next(predictor.model.parameters())
            for macro in selected:
                budget.check()
                if macro.records_sha256 in encoded:
                    continue
                memory, states = None, {}
                for row in macro.prefix_rows:
                    budget.check()
                    with torch.inference_mode():
                        feature, _, _, memory = predictor.model.public_state_step(
                            torch.tensor(
                                row["candidate_features"],
                                dtype=anchor.dtype,
                                device=anchor.device,
                            ),
                            row["public_metadata"],
                            memory=memory,
                            memory_mode=registration["memory_mode"],
                        )
                    states[row["record_id"]] = tuple(feature.detach().cpu().tolist())
                encoded[macro.records_sha256] = states
            predictor.assert_unchanged()
        with budget.stage("fit_source_disjoint_residual_bank"):
            calibration = []
            for macro in selected:
                budget.check()
                if roles[macro.start_row["source_group"]] != "calibration":
                    continue
                states = encoded[macro.records_sha256]
                state = _public_state(
                    macro, states[macro.start_row["record_id"]], metadata
                )
                center = predictor.center(state, macro.start_row["action"])
                calibration.append(
                    {
                        "public_features": list(state.features),
                        "action": macro.start_row["action"],
                        "predicted_next_features": list(center.next_features),
                        "observed_next_features": list(
                            states[macro.stop_row["record_id"]]
                        ),
                        "predicted_duration_seconds": center.duration_seconds,
                        "observed_duration_seconds": macro.duration_seconds,
                        "predicted_utility": center.utility,
                        "observed_utility": macro.terminal_utility,
                        "source_group": macro.start_row["source_group"],
                        "split": "calibration",
                    }
                )
            bank = ConditionalResidualBank.fit(
                calibration,
                binding=dict(predictor.binding),
                fit_source_groups=registration["fit_source_groups"],
                feature_scale=registration["feature_scales"],
                neighbor_groups=registration["neighbor_groups"],
                max_per_group=registration["max_per_group"],
                max_distance=registration["max_distance"],
            )
            _write(output / "conditional-bank.json", bank.to_dict())
            bank = ConditionalResidualBank.from_dict(
                _json((output / "conditional-bank.json").read_bytes()),
                expected_sha256=bank.sha256,
                expected_binding=dict(predictor.binding),
            )
            report["bank"] = {
                "canonical_sha256": bank.sha256,
                "calibration_macros": len(calibration),
                "calibration_source_groups": len(
                    {r["source_group"] for r in calibration}
                ),
                "cold_load_verified": True,
                "conditional_coverage_established": False,
            }
        plans = [
            ControlPlan(
                risk=risk,
                horizon=1,
                particles=registration["particles"],
                memory_mode=registration["memory_mode"],
                latency_weight=registration["latency_weight"],
                discount_per_second=registration["discount_per_second"],
            )
            for risk in registration["risk_settings"]
        ]
        policies = [
            StoppedController(
                predictor,
                bank,
                plan,
                practical_margin=registration["practical_margin"],
                seed=registration["seed"],
            )
            for plan in plans
        ]
        with (
            budget.stage("diagnose_held_out_source_predictions"),
            (output / "diagnostics.jsonl").open("x", encoding="utf-8") as stream,
        ):
            for macro in selected:
                if roles[macro.start_row["source_group"]] != "diagnostic":
                    continue
                budget.check()
                report["diagnostic_macros_attempted"] += 1
                state = _public_state(
                    macro,
                    encoded[macro.records_sha256][macro.start_row["record_id"]],
                    metadata,
                )
                action = macro.start_row["action"]
                center = predictor.center(state, action)
                item = {
                    "record_id": macro.start_row["record_id"],
                    "source_group": macro.start_row["source_group"],
                    "action": action,
                    "schema": macro.start_row["schema"],
                    "status": "unsupported",
                    "sensitivity_action_support": "recorded_v2_legal_actions"
                    if macro.start_row["schema"] == V2_SCHEMA
                    else "observed_action_plus_STOP_only; full_legal_space_not_reconstructed",
                    "actual_terminal_utility": macro.terminal_utility,
                    "actual_recorded_macro_seconds": macro.duration_seconds,
                    "center_point": {
                        "utility": center.utility,
                        "duration_seconds": center.duration_seconds,
                    },
                    "center_crps_all_observed": {
                        "quality": abs(center.utility - macro.terminal_utility),
                        "duration": abs(
                            center.duration_seconds - macro.duration_seconds
                        ),
                        "net": abs(
                            edge_value(
                                center.duration_seconds, center.utility, plans[0]
                            )
                            - edge_value(
                                macro.duration_seconds, macro.terminal_utility, plans[0]
                            )
                        ),
                    },
                    "prediction_sensitivity": [],
                    "counterfactual_outcomes_created": False,
                }
                try:
                    scenarios, item["support"] = policies[0].scenarios(state, action)
                    values = {
                        "quality_crps": [x[0] for x in scenarios],
                        "duration_crps": [x[1] for x in scenarios],
                        "net_crps": [
                            edge_value(x[1], x[0], plans[0]) for x in scenarios
                        ],
                    }
                    observed = (
                        macro.terminal_utility,
                        macro.duration_seconds,
                        edge_value(
                            macro.duration_seconds, macro.terminal_utility, plans[0]
                        ),
                    )
                    means = (
                        center.utility,
                        center.duration_seconds,
                        edge_value(center.duration_seconds, center.utility, plans[0]),
                    )
                    item["metrics"] = {
                        name: {
                            "center": abs(point - actual),
                            "joint": weighted_crps(
                                values[name], [x[2] for x in scenarios], actual
                            ),
                        }
                        for name, point, actual in zip(values, means, observed)
                    }
                    item["status"] = "supported"
                except UnsupportedCondition as error:
                    item["unsupported_reason"] = str(error)
                for plan, policy in zip(plans, policies):
                    budget.check()
                    try:
                        chosen, receipt = policy.choose(state)
                        item["prediction_sensitivity"].append(
                            {
                                "risk": plan.risk,
                                "predicted_action": chosen,
                                "receipt": receipt,
                                "actual_outcome_for_choice": None,
                            }
                        )
                    except UnsupportedCondition as error:
                        item["prediction_sensitivity"].append(
                            {
                                "risk": plan.risk,
                                "status": "unsupported",
                                "reason": str(error),
                            }
                        )
                stream.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                diagnostic_rows.append(item)
                report["diagnostic_macros_recorded"] += 1
            predictor.assert_unchanged()
            if args.device == "cuda":
                torch.cuda.synchronize()
        report["diagnostic_status_counts"] = dict(
            Counter(row["status"] for row in diagnostic_rows)
        )
        report["prediction_metrics"] = _aggregate(diagnostic_rows)
        report["status"] = (
            "completed"
            if report["diagnostic_status_counts"].get("supported")
            else "completed_without_supported_diagnostics"
        )
    except BaseException as error:
        report.update(
            status="failed", error={"type": type(error).__name__, "message": str(error)}
        )
        with (output / "traceback.txt").open("x", encoding="utf-8") as stream:
            stream.write(traceback.format_exc())
    finally:
        report["wall_seconds"] = time.perf_counter() - budget.started
        report["process_cpu_seconds"] = time.process_time() - budget.cpu_started
        report["stages"] = budget.stages
        report["cost_accounting"] = (
            "stages are inside the measured run interval; overlapping macro observations and original collection are not summed again"
        )
        _write(output / "receipt.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(output),
                "hold": True,
                "net_benefit_established": False,
            },
            sort_keys=True,
        )
    )
    return (
        0
        if report["status"] == "completed"
        else 2
        if report["status"].startswith("completed_")
        else 1
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("records", "weights", "registration", "behavior-metadata", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("records", "weights", "registration", "behavior-metadata", "source"):
        parser.add_argument("--expected-" + name + "-sha256", required=True)
    parser.add_argument("--parent-records", type=Path)
    parser.add_argument("--expected-parent-records-sha256")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--max-wall-seconds", type=float, default=1800)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
