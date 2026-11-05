"""Derive report tables from sealed v4 outputs; never train or change a run."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402
from v4.evidence import verify_run  # noqa: E402


RUN = ROOT / "results/20261026-v4-frozen"
INPUTS = {}


def read(path):
    raw = path.read_bytes()
    INPUTS[str(path.relative_to(ROOT))] = {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return json.loads(raw)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    verification = verify_run(RUN, bootstrap.REPO)
    protocol = read(RUN / "protocol.json")
    manifest = read(RUN / "MANIFEST.json")
    status = read(RUN / "execution_status.json")
    environment = read(RUN / "environment.json")
    outer = read(RUN / "results.json")
    joint = read(RUN / "joint/summary.json")
    transfer = read(RUN / "transfer/transfer-summary.json")
    maintenance = read(RUN / "typed_maintenance/typed-lifecycle-summary.json")
    structure = read(RUN / "structure/structure.json")
    seeds = protocol["seeds"]
    indexes = np.random.default_rng(protocol["statistics"]["bootstrap_seed"]).integers(
        0, len(seeds), (protocol["statistics"]["bootstrap_draws"], len(seeds))
    )

    def stats(values):
        values = np.asarray(values, dtype=float)
        if values.shape != (len(seeds),) or not np.isfinite(values).all():
            raise ValueError("expected one finite value per frozen seed")
        return {
            "values": values.tolist(),
            "mean": float(values.mean()),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "seed_bootstrap_95_percent_interval": np.quantile(
                values[indexes].mean(axis=1), [0.025, 0.975]
            ).tolist(),
        }

    audits = {}
    for name in (
        "transfer",
        "typed-maintenance",
        "structure",
        "joint",
        "selected-replay",
    ):
        value = read(ROOT / f"validation/formal-{name}-audit.json")
        if value.get("passed", value.get("verified")) is not True:
            raise ValueError(f"independent audit did not pass: {name}")
        audits[name] = {
            key: item
            for key, item in value.items()
            if not isinstance(item, (dict, list))
        }
    checks = read(ROOT / "validation/final-python-checks-v2.json")
    formatting = read(ROOT / "validation/final-format-verification.json")
    assert checks["unittest"]["successful"] and checks["ruff"]["successful"]
    assert formatting["all_python_asts_unchanged_from_passing_unittest_source"]

    domains = {}
    for domain in (
        protocol["joint"]["science_domains"] + protocol["joint"]["new_event_views"]
    ):
        rows = [case["domains"][domain] for case in joint["results"]]
        arms = {
            arm: {
                metric: stats([row["arms"][arm][metric] for row in rows])
                for metric in (
                    "exact_answer_rate",
                    "composed_exact_answer_rate",
                    "unsupported_false_accept_rate",
                    "unsupported_any_source_read_rate",
                )
            }
            for arm in rows[0]["arms"]
        }
        domains[domain] = {
            "descriptor": rows[0]["descriptor"],
            "query_denominators": {
                "known": rows[0]["routing"]["known_queries"],
                "unsupported": rows[0]["routing"]["unsupported_queries"],
                "compositional_known_excluding_at": sum(
                    counts["queries"]
                    for intent, counts in rows[0]["arms"]["parameter_actual"][
                        "per_intent"
                    ].items()
                    if intent != "at"
                ),
            },
            "routing": {
                key: stats([row["routing"][key] for row in rows])
                for key in (
                    "known_correct_accepted_rate",
                    "known_coverage",
                    "unsupported_false_accept_rate",
                )
            },
            "gates_passed": {
                name: sum(row["gates"][name] for row in rows)
                for name in rows[0]["gates"]
            },
            "arms": arms,
            "oracle_gap_parameter": stats(
                [row["oracle_gap_parameter"] for row in rows]
            ),
            "parameter_edge_gain_removed": stats(
                [
                    row["arms"]["parameter_actual"]["composed_exact_answer_rate"]
                    - row["arms"]["parameter_removed"]["composed_exact_answer_rate"]
                    for row in rows
                ]
            ),
            "parameter_edge_gain_permuted": stats(
                [
                    row["arms"]["parameter_actual"]["composed_exact_answer_rate"]
                    - row["arms"]["parameter_permuted"]["composed_exact_answer_rate"]
                    for row in rows
                ]
            ),
        }
    gate_counts = {
        gate: sum(value["gates_passed"][gate] for value in domains.values())
        for gate in ("semantic", "parameter_composition", "residual_composition")
    }
    numeric = {}
    for name in protocol["joint"]["science_domains"]:
        rows = [case["numeric_memories"][name] for case in joint["results"]]
        numeric[name] = {
            arm: {
                "artifact_bytes": stats(
                    [row[arm]["artifact"]["bytes"] for row in rows]
                ),
                "deployed_bytes": stats([row[arm]["deployed_bytes"] for row in rows]),
                "all_written_coordinate_exact_fraction": stats(
                    [row[arm]["training"]["written_exact_accuracy"] for row in rows]
                ),
                "all_written_coordinate_mae_scaled_integer_units": stats(
                    [row[arm]["training"]["written_mae"] for row in rows]
                ),
            }
            for arm in ("primary", "rank_control")
        }
        numeric[name]["strong_exact_deployed_bytes"] = stats(
            [row["codecs"]["strong_exact"]["deployed_bytes"] for row in rows]
        )
    deployment = {
        key: stats([row["serialized_deployment"][key] for row in joint["results"]])
        for key, value in joint["results"][0]["serialized_deployment"].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    routing_cost = {
        key: sum(row["routing_training"]["cost"][key] for row in joint["results"])
        for key in (
            "all_candidate_optimizer_steps",
            "all_candidate_actual_example_updates",
            "all_candidate_artifact_bytes",
            "serialized_feature_cache_bytes",
            "research_model_artifact_bytes_including_selected_copy",
            "all_candidate_train_seconds",
        )
    }
    layout_work = {
        key: sum(row["layout_training"][key] for row in joint["results"])
        for key in (
            "all_candidate_calls",
            "candidate_executions",
            "fit_seconds",
            "steps",
            "queries",
        )
    }
    transfer_arms = {}
    for arm in transfer["results"][0]["event_arms"]:
        rows = [case["event_arms"][arm] for case in transfer["results"]]
        transfer_arms[arm] = {
            "parameter_event_bytes": stats(
                [row["write"]["parameter_deployment_bytes"] for row in rows]
            ),
            "residual_event_bytes": stats(
                [row["write"]["exact_deployment_bytes"] for row in rows]
            ),
            "residual_storage_ratio_to_strongest_exact_event": stats(
                [row["exact_storage_ratio_to_best_traditional"] for row in rows]
            ),
            "parameter_event_and_procedure_bytes": stats(
                [row["parameter_event_and_procedure_deployment_bytes"] for row in rows]
            ),
            "residual_event_and_procedure_bytes": stats(
                [row["exact_event_and_procedure_deployment_bytes"] for row in rows]
            ),
            "fields": {
                field: {
                    mode: stats(
                        [
                            row["modes"][mode]["events"]["fields"][field][
                                "exact_fraction"
                            ]
                            for row in rows
                        ]
                    )
                    for mode in ("parameter", "residual_exact")
                }
                for field in rows[0]["modes"]["parameter"]["events"]["fields"]
            },
            "parameter_procedure_tolerance_fraction": stats(
                [
                    row["modes"]["parameter"]["procedures"]["within_absolute_tolerance"]
                    for row in rows
                ]
            ),
            "parameter_chain_tolerance_fraction": stats(
                [
                    row["modes"]["parameter"]["event_procedure_chain"][
                        "within_absolute_tolerance"
                    ]
                    for row in rows
                ]
            ),
        }
    full_read_pass = all(
        row["event_arms"]["full_rank"]["modes"]["parameter"]["events"]["exact_fraction"]
        >= protocol["gates"]["new_type_exact_hidden_reads_min"]
        for row in transfer["results"]
    )
    strong_event = stats(
        [
            row["exact_controls"][row["best_traditional_control"]]["bytes"]
            for row in transfer["results"]
        ]
    )
    maintenance_stats = {
        key: stats([row["storage"][key] for row in maintenance["results"]])
        for key in (
            "minimum_parameter_serving_bytes",
            "minimum_model_residual_serving_bytes",
            "current_model_exact_replay_and_procedure_demo_bytes",
            "retained_store_and_witness_bytes",
        )
    }
    flows = {}
    for name in structure["flows"]:
        rows = [row for row in structure["results"] if row["name"] == name]
        assert [row["seed"] for row in rows] == seeds
        flows[name] = {
            "adaptive_hidden_mse": stats(
                [row["totals"]["adaptive"]["hidden_mse"] for row in rows]
            ),
            "best_fixed_hidden_mse": stats(
                [
                    row["totals"][row["best_fixed_by_whole_flow_selection"]][
                        "hidden_mse"
                    ]
                    for row in rows
                ]
            ),
            "natural_priced_loss_ratio": stats(
                [row["natural_priced_loss_ratio"] for row in rows]
            ),
            "natural_priced_loss_regret": stats(
                [row["priced_loss_regret_vs_best_fixed"] for row in rows]
            ),
            "matched_priced_loss_regret": stats(
                [row["priced_loss_regret_vs_matched"] for row in rows]
            ),
            "normalized_hidden_mse_gain": stats(
                [row["normalized_hidden_mse_gain_vs_best_fixed"] for row in rows]
            ),
            "literal_relative_mse_regret": stats(
                [
                    row["literal_relative_hidden_mse_regret_vs_best_fixed"]
                    for row in rows
                ]
            ),
            "dynamic_passed": sum(row["dynamic_gate"] is True for row in rows),
            "static_diagnostic_passed": sum(
                row["static_bounded_regret_gate"] is True for row in rows
            ),
            "strict_all_flow_diagnostic_passed": sum(
                row["strict_quality_and_both_costs_diagnostic"] for row in rows
            ),
            "cell_schedules": [
                [episode["adaptive"]["cells"] for episode in row["episodes"]]
                for row in rows
            ],
        }
    pairs = [
        {
            "seed": row["seed"],
            "from_cells": row["from_cells"],
            "to_cells": row["to_cells"],
            "before_bytes": row["parent_bytes"],
            "after_bytes": row["selected_bytes"],
            "before_hidden_mse": row["parent_hidden"]["mse"],
            "after_hidden_mse": row["selected_hidden"]["mse"],
            "changed_row_labels": row["migration"]["changed_raw_row_labels"],
            "reload_parity": row["migration"][
                "hidden_coordinate_read_parity_after_reload"
            ],
        }
        for row in structure["pair_merge_mechanisms"]
    ]
    eligibility = {
        "new_event_full_rank_hidden_read": full_read_pass,
        "new_type_maintenance_all_seeds": maintenance["all_maintenance_gates_pass"],
        "dynamic_structure_all_seeds": structure["dynamic_all_seed_gate"],
        "semantic_all_seeds_all_domains": gate_counts["semantic"] == 30,
        "pure_parameter_composition_all_seeds_all_domains": gate_counts[
            "parameter_composition"
        ]
        == 30,
        "new_event_storage_advantage": all(
            value < 1
            for value in transfer_arms["full_rank"][
                "residual_storage_ratio_to_strongest_exact_event"
            ]["values"]
        ),
    }
    summary = {
        "schema": "memory-cell-v4.measured-summary.v1",
        "executed_source_commit": manifest["source_commit"],
        "formal_evidence": verification,
        "environment": environment,
        "seeds": seeds,
        "whole_run_wall_seconds": status["seconds"],
        "stage_wall_seconds": {
            key: value["wall_seconds"] for key, value in outer.items()
        },
        "statistics": protocol["statistics"],
        "all_blockers_closed": all(eligibility.values()),
        "production_admitted": False,
        "qualification": eligibility,
        "joint_gate_cases": 30,
        "joint_gate_pass_counts": gate_counts,
        "domains": domains,
        "numeric_rank_comparison": numeric,
        "serialized_deployment": deployment,
        "routing_candidate_training_totals": routing_cost,
        "layout_training_totals": layout_work,
        "transfer": {
            "source_records": transfer["source_events"],
            "arms": transfer_arms,
            "strong_exact_event_bytes": strong_event,
            "all_work": [row["work"] for row in transfer["results"]],
        },
        "maintenance": {
            "all_seed_gate": maintenance["all_maintenance_gates_pass"],
            "storage": maintenance_stats,
            "per_seed_checks": [row["checks"] for row in maintenance["results"]],
        },
        "structure": {
            "flows": flows,
            "pair_merges": pairs,
            "dynamic_all_seed_gate": structure["dynamic_all_seed_gate"],
            "static_bounded_regret_diagnostic": structure[
                "static_bounded_regret_all_seed_gate"
            ],
            "strict_all_flow_diagnostic": structure[
                "all_flow_strict_improvement_diagnostic"
            ],
        },
        "independent_audits": audits,
        "unittest": checks["unittest"],
        "ruff": checks["ruff"],
        "formatting": {
            key: value for key, value in formatting.items() if key != "final_files"
        },
        "important_limits": protocol["boundaries"] + protocol["not_tested_claims"],
        "report_inputs": dict(sorted(INPUTS.items())),
    }
    write(ROOT / "MEASURED_SUMMARY.json", summary)
    write(
        ROOT / "QUALIFICATION.json",
        {
            "schema": "memory-cell-v4.qualification.v1",
            "executed_source_commit": manifest["source_commit"],
            "formal_manifest_sha256": verification["manifest_sha256"],
            "seeds": seeds,
            "all_blockers_closed": summary["all_blockers_closed"],
            "production_admitted": False,
            "measured_gates": eligibility,
            "joint_gate_pass_counts": gate_counts,
            "all_independent_artifact_audits_passed": True,
            "separate_diagnostics": summary["structure"],
            "open_blockers": [
                "Selected natural-language routers fail 80% correct acceptance; one seed also exceeds 5% unsupported acceptance.",
                "Actual-routing composition edge gain fails two of five seeds across all six domains.",
                "New typed exact parameter-plus-residual state is larger than the strongest ordinary exact codec.",
                "Broad type/task transfer and autonomous type discovery remain unqualified; explicit slots, supplied types and operation catalog are required.",
            ],
            "historical_v3_results_unchanged": True,
            "scope_of_passed_maintenance": "local POSIX single-writer, retained replay/history, clean refit; no physical erasure or distributed guarantee",
            "scope_of_passed_structure": "two predeclared changing numeric flows at 4096B; static bounded-regret is a separate diagnostic",
            "source_native_integration": "V3 historical native integration retained; V4 event/procedure owner not production-admitted",
            "report_input_fingerprints": dict(sorted(INPUTS.items())),
        },
    )
    write(
        ROOT / "analyses/report-inputs.json",
        {
            "schema": "memory-cell-v4.report-inputs.v1",
            "inputs": dict(sorted(INPUTS.items())),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "training_or_model_selection_performed": False,
            "seed_bootstrap_is_conditional_on_fixed_workload_not_language_population": True,
        },
    )
    print(
        json.dumps(
            {
                "all_blockers_closed": summary["all_blockers_closed"],
                "joint_gate_pass_counts": gate_counts,
                "known_correct_mean": domains["co2"]["routing"][
                    "known_correct_accepted_rate"
                ]["mean"],
                "ood_false_accept_mean": domains["co2"]["routing"][
                    "unsupported_false_accept_rate"
                ]["mean"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
