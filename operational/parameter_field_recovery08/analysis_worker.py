"""Explicit execution08 cost reporting adapter; scientific analysis is unchanged."""

from contextlib import contextmanager
from copy import deepcopy
import importlib
from pathlib import Path

from . import common as c


REPORT = "experiments.parameter_field_fullstudy_20261029.report_results"


def history():
    item = c.descriptor(c.OWN / "HISTORICAL_COSTS.json")
    value = c.bound(item)
    c.need(
        value.get("schema") == "hepta.execution08.historical-cost-projection.1"
        and value.get("scientific_values_decoded") is False
        and value.get("old_completion_claim_created") is False
        and value.get("whole_history_cpu_or_wall_total_known") is False,
        "Wrong historical cost projection",
    )
    rows = value["rows"]
    c.need(
        len(rows) == 7
        and len({r["episode"] for r in rows}) == 7
        and all(
            type(r["gradient_microsteps_lower_bound"]) is int
            and r["gradient_microsteps_lower_bound"] >= 0
            and r["original_receipt_impersonation"] is False
            for r in rows
        )
        and sum(r["gradient_microsteps_lower_bound"] for r in rows)
        == value["gradient_microsteps_known_lower_bound"]
        == 253328,
        "Historical known cost population differs",
    )
    return value, item


def prior_costs(spec):
    value, item = history()
    binding = spec["execution08_historical_costs"]
    c.need(
        binding
        == {
            "schema": "hepta.execution08.cost-adapter-binding.1",
            "projection": item,
            "adapter_source": c.descriptor(Path(__file__).resolve()),
        }
        and spec["integrity"] == value["original_integrity"]
        and spec["engineering_preflights"] == []
        and spec["failed_attempts"] == [],
        "Report does not bind the explicit new historical cost projection",
    )
    prior_item = value["execution07_failure_cost"]
    prior_path = c.SOURCE / prior_item["path"]
    prior = c.bound({**prior_item, "path": str(prior_path)})
    c.need(prior["scientific_values_decoded"] is False
           and prior["full_scientific_closure"] is False
           and prior["outer_wait4"]["exit_code"] == 2
           and prior["outer_wait4"]["cpu_seconds"] > 0,
           "Preserved execution07 failure cost differs")
    preparation_failures = []
    for recorded in value.get("execution08_preworker_failures", []):
        failed = c.bound({**recorded, "path": str(c.SOURCE / recorded["path"])})
        c.need(failed["scientific_values_decoded"] is False
               and failed["scientific_workers_started"] == 0
               and failed["scheduled_training_gradient_microsteps"] == 0
               and failed["outer_wait4"]["exit_code"] == 2
               and failed["outer_wait4"]["cpu_seconds"] > 0,
               "Preserved preworker failure changed")
        preparation_failures.append({"evidence": recorded, "outer_wait4": failed["outer_wait4"],
                                     "cost_scope": failed["cost_scope"], "added_to_current_episode_cpu": False})
    return {
        "execution08_preworker_failures": preparation_failures,
        "engineering_receipts": [],
        "failed_attempts": [],
        "previous_episode_cost_rows": deepcopy(value["rows"]),
        "gradient_microsteps_known_lower_bound": value[
            "gradient_microsteps_known_lower_bound"
        ],
        "unknown_partial_work": True,
        "historical_projection": item,
        "whole_history_cpu_or_wall_total_known": False,
        "execution07_failed_pipeline": {
            "evidence": prior_item,
            "outer_wait4": prior["outer_wait4"],
            "cost_scope": prior["cost_scope"],
            "full_scientific_closure": False,
            "added_to_current_episode_cpu": False,
        },
        "scope": "New, explicitly registered cost-only historical projection. Missing original receipts remain missing; no old completion is fabricated.",
    }


def current_rows(report, complete, operations, endpoint):
    rows = []
    for (phase, seed), record in complete.items():
        ledger = record[
            "work"
            if phase == "C"
            else "reconstruction_work"
            if phase == "R"
            else "costs"
        ]
        rows.append(
            {
                "kind": "training"
                if phase in ("A", "B", "C")
                else "reconstruction"
                if phase == "R"
                else "constructed_witness",
                "phase": phase,
                "seed": seed,
                "gradient_microsteps": report.microsteps(ledger),
                "ledger": ledger,
                "wall_seconds": record.get("wall_seconds", ledger.get("wall_seconds")),
                "cpu_seconds": record.get("cpu_seconds", ledger.get("cpu_seconds")),
                "process_peak_rss_bytes": operations[(phase, seed)].get(
                    "process_peak_rss_bytes"
                ),
            }
        )
    for phase, record in endpoint.items():
        ledger = record["scoring_work" if phase == "C" else "scoring_costs"]
        rows.append(
            {
                "kind": "endpoint_scoring",
                "phase": phase,
                "gradient_microsteps": report.microsteps(ledger),
                "ledger": ledger,
                "wall_seconds": record.get("wall_seconds", ledger.get("wall_seconds")),
                "cpu_seconds": record.get("cpu_seconds", ledger.get("cpu_seconds")),
                "process_peak_rss_bytes": record.get("process_peak_rss_bytes"),
            }
        )
    return rows


@contextmanager
def installed(spec, config):
    report = importlib.import_module(REPORT)
    relative = "experiments/parameter_field_fullstudy_20261029/report_results.py"
    c.need(
        c.descriptor(Path(report.__file__).resolve())["sha256"]
        == config["source_files"][relative],
        "Original report implementation differs",
    )
    c.need(
        not getattr(report, "_execution08_cost_adapter", False), "Nested cost adapter"
    )
    original = report.prior_costs, report.cost_rows, report.render

    def prior(value):
        c.need(value == spec, "Cost reader received another report manifest")
        return prior_costs(value)

    def costs(complete, operations, endpoint, value):
        old = prior(value)
        rows = current_rows(report, complete, operations, endpoint)
        count = sum(r["gradient_microsteps"] for r in rows)
        return {
            "rows": rows,
            "failed_attempts": [],
            "completed_receipt_gradient_microsteps": count,
            "previous_episode_cost_rows": old["previous_episode_cost_rows"],
            "execution07_failed_pipeline": old["execution07_failed_pipeline"],
            "all_attempts_gradient_microsteps_known_lower_bound": count
            + old["gradient_microsteps_known_lower_bound"],
            "unknown_partial_work": True,
            "whole_history_cpu_or_wall_total_known": False,
            "no_quality_cost_exchange_rate_fitted": True,
            "rule": "Current original ledgers counted once. Historical projection is separately disclosed; setup, transport and parent wait4 costs belong to the execution08 operational closure, with nested rows not added twice.",
        }

    def render(result):
        return original[2](result) + (
            "\n\nExecution08 uses an explicit historical cost-only projection. "
            "The prior gradient subtotal is a lower bound; missing original receipts, earlier additional work "
            "and whole-history CPU remain unknown. Operational wait4 and delivery costs are separate.\n"
        )

    prior(spec)
    report.prior_costs, report.cost_rows, report.render = prior, costs, render
    report._execution08_cost_adapter = True
    try:
        yield
    finally:
        report.prior_costs, report.cost_rows, report.render = original
        del report._execution08_cost_adapter


def run(module, original_flags, config):
    c.need(
        module.__name__.endswith("analysis_launch_v2"),
        "Wrong original analysis launcher",
    )
    c.need(
        original_flags.count("--inputs")
        == original_flags.count("--expected-sha256")
        == 1,
        "Missing or duplicate report input identity",
    )
    path = original_flags[original_flags.index("--inputs") + 1]
    digest = original_flags[original_flags.index("--expected-sha256") + 1]
    item = c.descriptor(path)
    c.need(item["sha256"] == digest, "Actual report input pin differs")
    spec = c.bound(item)
    with installed(spec, config):
        return module.main()
