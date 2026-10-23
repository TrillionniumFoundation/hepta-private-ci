"""Prepare, then explicitly execute one fixed-weight three-seed development diagnosis."""

import argparse
import json
import os
from pathlib import Path
import time
import traceback

from diagnosis_common import (
    SEEDS,
    configure,
    digest,
    file_sha,
    identity,
    inputs,
    panels,
    protocol,
    retain,
    verify_base,
)


def output_path(path):
    path = Path(path).resolve()
    diagnosis_root = Path(__file__).resolve().parent
    if path == diagnosis_root or diagnosis_root not in path.parents:
        raise ValueError(
            "all new diagnosis evidence must remain in routing-diagnosis-work"
        )
    return path


def prepare(args):
    configure(args.repo)
    output = output_path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    registered = protocol(args.repo, args.historical, args.model)
    pins = inputs(args.historical)
    source = identity(args.repo)
    if not source["tracked_worktree_clean"] or source["untracked_repository_sources"]:
        raise ValueError("preparation requires committed unchanged repository source")
    cohort = {}
    for seed in SEEDS:
        data, source_rows, balanced, final = panels(seed)
        historical = json.loads(
            (Path(args.historical) / f"seed-{seed}/dataset.json").read_text()
        )
        if data != historical:
            raise ValueError(
                "fixed dataset generator differs from retained historical dataset"
            )
        source_questions = [row["question"] for row in source_rows]
        final_questions = [row["question"] for row in final]
        normalize = lambda value: " ".join(value.casefold().split())
        for values in (source_questions, final_questions):
            if len({normalize(q) for q in values}) != len(values):
                raise ValueError("duplicate source or final wording")
        if set(map(normalize, source_questions)) & set(map(normalize, final_questions)):
            raise ValueError("source and final question overlap")
        cohort[str(seed)] = {
            "dataset_sha256": digest(data),
            "sources_sha256": data["sources_sha256"],
            "source_panel_sha256": digest(source_rows),
            "final_panel_sha256": digest(final),
            "balanced_indices": balanced,
            "balanced_indices_sha256": digest(balanced),
        }
    retain(output / "protocol.json", registered)
    retain(output / "input-pins.json", pins)
    retain(output / "source-identity.json", source)
    retain(output / "cohort-pins.json", cohort)
    copies = output / "diagnosis-source"
    copies.mkdir()
    for name, expected in source["diagnosis_sources"].items():
        payload = (Path(__file__).parent / name).read_bytes()
        with (copies / name).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if file_sha(copies / name) != expected:
            raise ValueError("diagnosis source changed while retaining its snapshot")
    receipt = {
        "protocol_sha256": file_sha(output / "protocol.json"),
        "input_pins_sha256": file_sha(output / "input-pins.json"),
        "source_identity_sha256": file_sha(output / "source-identity.json"),
        "cohort_pins_sha256": file_sha(output / "cohort-pins.json"),
        "prepared_unix_ns": time.time_ns(),
        "model_calls": 0,
        "decoder_queries_authorized_but_not_started": 2904,
        "parent_feature_forwards_authorized_but_not_started": 1272,
    }
    retain(output / "prepared.json", receipt)
    print(
        json.dumps(
            {"stage": "prepared", "output": str(output), **receipt}, sort_keys=True
        ),
        flush=True,
    )


def validate_prepared(output):
    receipt = json.loads((output / "prepared.json").read_text())
    names = {
        "protocol": "protocol_sha256",
        "input-pins": "input_pins_sha256",
        "source-identity": "source_identity_sha256",
        "cohort-pins": "cohort_pins_sha256",
    }
    loaded = {}
    for name, key in names.items():
        path = output / f"{name}.json"
        if file_sha(path) != receipt[key]:
            raise ValueError("prepared evidence pin changed")
        loaded[name] = json.loads(path.read_text())
    registered = loaded["protocol"]
    configure(registered["repo"])
    if registered != protocol(
        registered["repo"], registered["historical"], registered["model"]
    ):
        raise ValueError("registered protocol changed")
    if (
        identity(registered["repo"]) != loaded["source-identity"]
        or inputs(registered["historical"]) != loaded["input-pins"]
    ):
        raise ValueError(
            "source code, historical reports, router or checkpoint bytes changed"
        )
    if any(
        file_sha(output / "diagnosis-source" / name) != expected
        for name, expected in loaded["source-identity"]["diagnosis_sources"].items()
    ):
        raise ValueError("retained diagnosis source snapshot changed")
    return loaded


def run_seed(registered, seed, pin, cohort_pin, output):
    from diagnosis_execution import cpu_delta, cpu_snapshot, fresh_rows, parent_features
    from diagnosis_routing import fit_and_freeze, observations
    from diagnosis_scoring import added_costs, score_final, score_source
    from population_scoring import source_capabilities

    output.mkdir(exist_ok=False)
    started, before = time.perf_counter(), cpu_snapshot()
    data, source_rows, balanced, final = panels(seed)
    if (
        digest(data) != cohort_pin["dataset_sha256"]
        or digest(source_rows) != cohort_pin["source_panel_sha256"]
        or digest(final) != cohort_pin["final_panel_sha256"]
        or balanced != cohort_pin["balanced_indices"]
    ):
        raise ValueError("prepared dataset or diagnosis panel changed")
    retain(output / "dataset.json", data)
    retain(output / "source-panel.json", source_rows)
    retain(output / "final-panel.json", final)
    capabilities, versions = source_capabilities(data["sources"]), pin["versions"]
    source_raw, read_receipts = [], []
    for slot, version in enumerate(versions["split"]):
        rows, receipt = fresh_rows(
            registered["model"],
            version,
            [p["question"] for p in source_rows],
            output / f"source-expert-{slot}",
            f"source-{slot}",
            data["scope"],
            context={"source_panel_sha256": cohort_pin["source_panel_sha256"]},
        )
        source_raw.append(rows)
        read_receipts.append(receipt)
    measured, evidence = observations(
        source_rows, source_raw, versions["split"], capabilities
    )
    retain(
        output / "source-observations.json",
        {"observations": measured, "evidence": evidence},
    )
    source_provenance = {
        "source_panel_sha256": cohort_pin["source_panel_sha256"],
        "source_ledger_sha256": data["sources_sha256"],
        "expert_manifests": [v["manifest_sha256"] for v in versions["split"]],
        "raw_generation_receipts": read_receipts,
        "observations_sha256": digest(measured),
        "labels_from_fresh_expert_generations": True,
        "labels_copied_from_historical_reports": False,
    }
    print(
        json.dumps(
            {"stage": "source-utilities-read", "seed": seed, "decoder_queries": 608}
        ),
        flush=True,
    )
    vectors, feature_receipt = parent_features(
        registered["repo"],
        registered["model"],
        versions["parent"][0],
        [p["question"] for p in source_rows + final],
        output / "parent-features",
        data["scope"],
    )
    source_provenance["parent_features_sha256"] = feature_receipt["sha256"]
    metadata = [
        {
            key: probe[key]
            for key in ("probe_id", "question", "family", "operation", "source_roots")
        }
        for probe in final
    ]
    frozen, routing_costs, source_routes = fit_and_freeze(
        pin,
        source_rows,
        balanced,
        measured,
        source_provenance,
        vectors,
        metadata,
        versions,
        capabilities,
        output / "routing",
    )
    plan_path = output / "routing/route-plan.json"
    context = {
        "route_plan_sha256": file_sha(plan_path),
        "route_plan_frozen_unix_ns": frozen["frozen_unix_ns"],
    }
    retain(output / "route-plan-commit.json", context)
    print(json.dumps({"stage": "routes-frozen", "seed": seed, **context}), flush=True)
    final_raw = []
    for slot, version in enumerate(versions["split"] + versions["single"]):
        rows, receipt = fresh_rows(
            registered["model"],
            version,
            [p["question"] for p in final],
            output / f"final-model-{slot}",
            f"final-{slot}",
            data["scope"],
            context=context,
        )
        final_raw.append(rows)
        read_receipts.append(receipt)
    if file_sha(plan_path) != context["route_plan_sha256"]:
        raise ValueError("route plan changed during final generation")
    scored = score_final(
        final, final_raw[:2], final_raw[2], versions, capabilities, frozen
    )
    retain(output / "final-assessments.json", scored)
    retain(
        output / "source-assessments.json",
        score_source(
            source_rows, source_raw, versions["split"], capabilities, source_routes
        ),
    )
    cost = added_costs(
        read_receipts,
        feature_receipt,
        routing_costs,
        time.perf_counter() - started,
        cpu_delta(before),
    )
    if (
        cost["decoder_reads"]["queries"],
        cost["parent_features"]["model_forwards"],
        cost["router_fit_optimizer_updates"],
    ) != (968, 424, 800):
        raise ValueError("registered additional model work counts differ")
    if cost["decoder_reads"]["fresh_processes"] != 9:
        raise ValueError("unexpected decoder fresh process count")
    result = {
        "seed": seed,
        "metrics": {
            name: value["metrics"] for name, value in scored["policies"].items()
        },
        "comparable_policy_cohorts": scored["comparable_policy_cohorts"],
        "all_denominators": scored["all_denominators"],
        "routing": {
            name: value["routing"]
            for name, value in scored["policies"].items()
            if "routing" in value
        },
        "costs": cost,
        "historical_sunk_training_costs": pin["historical_training_costs"],
        "historical_sunk_source_selection_work": pin["historical_selection_work"],
        "historical_sunk_final_work": pin["historical_final_work"],
        "historical_sunk_router_fit_updates": pin["original_router_receipt"][
            "training"
        ]["optimizer_updates"],
        "decoder_hash_check": "whole-trial check pending; immutable versions pinned in input-pins.json",
        "route_plan_sha256": context["route_plan_sha256"],
        "final_assessments_sha256": file_sha(output / "final-assessments.json"),
        "confirmation": False,
        "scientific_phase3_closed": False,
        "equal_total_budget": False,
        "capacity_advantage_established": False,
        "production_accepted": False,
    }
    retain(output / "result.json", result)
    print(
        json.dumps(
            {
                "stage": "seed-complete",
                "seed": seed,
                "retention": {
                    name: value["retention"]["accuracy"]
                    for name, value in result["metrics"].items()
                },
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def execute(args):
    output = output_path(args.output)
    prepared = validate_prepared(output)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = "2"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from diagnosis_execution import cpu_delta, cpu_snapshot, partial_work, runtime

    started, before = time.perf_counter(), cpu_snapshot()
    retain(
        output / "execution-start.json",
        {
            "started_unix_ns": time.time_ns(),
            "runtime": runtime(),
            "prepared_sha256": file_sha(output / "prepared.json"),
            "operator_start_explicit": True,
        },
    )
    registered = prepared["protocol"]
    try:
        acquisition = verify_base(registered["model"])
        retain(output / "base-acquisition.json", acquisition)
        results = [
            run_seed(
                registered,
                seed,
                prepared["input-pins"][str(seed)],
                prepared["cohort-pins"][str(seed)],
                output / f"seed-{seed}",
            )
            for seed in SEEDS
        ]
        if (
            identity(registered["repo"]) != prepared["source-identity"]
            or inputs(registered["historical"]) != prepared["input-pins"]
            or verify_base(registered["model"]) != acquisition
        ):
            raise ValueError(
                "code, old reports, original router, base or decoder checkpoint bytes changed"
            )
        totals = {
            "decoder_queries": sum(
                r["costs"]["decoder_reads"]["queries"] for r in results
            ),
            "parent_feature_forwards": sum(
                r["costs"]["parent_features"]["model_forwards"] for r in results
            ),
            "new_router_optimizer_updates": sum(
                r["costs"]["router_fit_optimizer_updates"] for r in results
            ),
            "new_decoder_optimizer_updates": 0,
            "new_gradient_probes": 0,
            "fresh_decoder_processes": sum(
                r["costs"]["decoder_reads"]["fresh_processes"] for r in results
            ),
            "fresh_parent_feature_processes": 3,
            "decoder_input_tokens": sum(
                r["costs"]["decoder_reads"]["input_tokens"] for r in results
            ),
            "decoder_generated_tokens": sum(
                r["costs"]["decoder_reads"]["generated_tokens"] for r in results
            ),
            "parent_feature_input_tokens": sum(
                r["costs"]["parent_features"]["input_tokens"] for r in results
            ),
            "actual_event_artifact_bytes_before_result": sum(
                p.stat().st_size for p in output.rglob("*") if p.is_file()
            ),
            "shared_base_disk_bytes_reused_count_once": acquisition["total_bytes"],
            "whole_event_wall_seconds": time.perf_counter() - started,
            "whole_event_cpu": cpu_delta(before),
        }
        result = {
            "schema": "hepta.routing-diagnosis.result.v1",
            "seeds": results,
            "additional_event_costs": totals,
            "original_inputs_and_old_reports_unchanged": True,
            "base_publisher_bytes_unchanged": True,
            "engineering_integrity_passed": True,
            "confirmation": False,
            "sunk_cost_scope": "historical parent and candidate decoder training, gradients, original router, source selection and final reads retained separately per seed; prior codec evaluations are outside this routing diagnosis cost scope",
            "historical_total_decoder_updates": sum(
                r["historical_sunk_training_costs"]["total_optimizer_updates"]
                for r in results
            ),
            "historical_total_gradient_forwards_backwards": sum(
                r["historical_sunk_training_costs"]["gradient_probe_forwards_backwards"]
                for r in results
            ),
            "historical_total_original_router_updates": sum(
                r["historical_sunk_router_fit_updates"] for r in results
            ),
            "equal_total_budget": False,
            "scientific_phase3_closed": False,
            "capacity_advantage_established": False,
            "general_memory_proven": False,
            "production_accepted": False,
            "live_dispatch_executed": False,
        }
        retain(output / "result.json", result)
        print(
            json.dumps(
                {
                    "stage": "complete",
                    **totals,
                    "engineering_integrity_passed": True,
                    "scientific_phase3_closed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    except BaseException as error:
        original_traceback = traceback.format_exc()
        try:
            partial = partial_work(output)
        except Exception as accounting_error:
            partial = {
                "reconstruction_error": repr(accounting_error),
                "exact_total_model_work_known_after_failure": False,
            }
        retain(
            output / "failure.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": original_traceback,
                "wall_seconds": time.perf_counter() - started,
                "cpu": cpu_delta(before),
                "partial_evidence_preserved": True,
                "automatic_retry": False,
                "partial_model_work": partial,
                "confirmation": False,
                "scientific_phase3_closed": False,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    preparation = commands.add_parser(
        "prepare", help="pin explicitly supplied source, model and historical artifacts"
    )
    preparation.add_argument("--output", required=True, type=Path)
    preparation.add_argument("--repo", required=True, type=Path)
    preparation.add_argument("--historical", required=True, type=Path)
    preparation.add_argument("--model", required=True, type=Path)
    execution = commands.add_parser(
        "execute", help="execute the unchanged prepared paths and protocol"
    )
    execution.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    prepare(arguments) if arguments.action == "prepare" else execute(arguments)
