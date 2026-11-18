"""Bounded current-policy sampling, correction, warm-start training and use."""

import copy
from pathlib import Path
import time

from .. import data
from ..coding_sft import write_new
from .onpolicy_contract import SCOPE, require

SCHEMA = "hepta.current-policy-study.v1"


def make_freeze(context, initial, backend, *, operation_id, mode, rounds=2, maximum=2):
    require(mode in {"teacher", "shadow", "controlled"}, "collection mode required")
    require(type(rounds) is int and 1 <= rounds <= 4, "one to four rounds required")
    require(type(maximum) is int and 1 <= maximum <= 4, "one to four attempts required")
    require(
        isinstance(operation_id, str) and 0 < len(operation_id.encode()) <= 180,
        "bounded operation identity required",
    )
    records = context["records"][:6]
    require(
        len(records) == 6 and all(row["split"] == "train" for row in records),
        "all six authored A tasks required",
    )
    return {
        "schema": SCHEMA,
        "operation_id": operation_id,
        "collection_mode": mode,
        "rounds": rounds,
        "maximum_attempts": maximum,
        "context_digest": data.digest(context),
        "A_records_digest": data.digest(records),
        "initial_model_digest": backend.verify_model(initial),
        "source_inventory": backend.sources(),
        "steps_per_round": 64,
        "retention": "latest_round_only",
        "weight_initialization": "previous_candidate_adapter",
        "optimizer_initialization": "fresh_AdamW_each_round",
        "final_evaluation": "same_exposed_A_after_last_update",
        **SCOPE,
    }


def run(context, initial, output, freeze, backend):
    """The backend is explicit so real provider and training can be tested separately."""
    expected = make_freeze(
        context,
        initial,
        backend,
        operation_id=freeze.get("operation_id"),
        mode=freeze.get("collection_mode"),
        rounds=freeze.get("rounds"),
        maximum=freeze.get("maximum_attempts"),
    )
    require(freeze == expected, "study source, data, initialization or budget changed")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "FREEZE.json", freeze)
    records, current = copy.deepcopy(context["records"][:6]), copy.deepcopy(initial)
    rounds, collections, training = [], [], []
    started = time.perf_counter()
    try:
        for number in range(freeze["rounds"]):
            require(
                backend.sources() == freeze["source_inventory"],
                "source changed during study",
            )
            previous = backend.verify_model(current)
            if rounds:
                require(
                    previous == rounds[-1]["candidate_model_digest"],
                    "current policy is not the immediately preceding candidate",
                )
            directory = output / f"round-{number:03d}"
            write_new(
                directory / "INTENT.json",
                {
                    "round_index": number,
                    "current_model_digest": previous,
                    "freeze_digest": data.digest(freeze),
                    "started_at_ns": time.time_ns(),
                    "automatic_retry": False,
                },
            )
            collection = backend.collect(
                records,
                current,
                directory / "collection",
                freeze["collection_mode"],
                freeze["maximum_attempts"],
            )
            require(
                collection["model_digest"] == previous
                and collection["records_digest"] == data.digest(records)
                and collection["reused_observation_count"] == 0
                and collection["complete"] is True,
                "current collection is incomplete or stale",
            )
            if freeze["collection_mode"] != "teacher":
                require(
                    len(collection["rows"]) == len(records)
                    and all(
                        step["output"]["loaded_model_digest"] == previous
                        for row in collection["rows"]
                        for step in row["steps"]
                    ),
                    "a fresh rollout from the current candidate is required",
                )
            collections.append(collection)
            corrected = backend.corrections(
                records,
                collection,
                freeze["collection_mode"],
                number,
                directory / "corrections",
            )
            require(len(corrected) == len(records), "correction coverage changed")
            require(
                all(
                    event.get("trainable") is False
                    for row in corrected
                    for event in row["trajectory"]
                    if event["actor"] == "student"
                ),
                "student actions cannot become supervised targets",
            )
            plan = backend.make_plan(
                corrected,
                current,
                freeze["operation_id"],
                number,
                freeze["collection_mode"],
            )
            require(
                plan["previous_model_digest"] == previous
                and plan["training"]["steps"] == freeze["steps_per_round"],
                "fit does not use current weights and frozen step budget",
            )
            write_new(directory / "RECORDS.json", corrected)
            write_new(directory / "PLAN.json", plan)
            candidate, receipt = backend.fit(
                corrected, current, plan, directory / "model"
            )
            identity = backend.verify_model(candidate)
            require(
                receipt["status"] == "COMPLETE"
                and receipt["candidate_model_digest"] == identity
                and receipt["previous_model_digest"] == previous
                and receipt["steps"] == freeze["steps_per_round"]
                and receipt["warm_start_matched"] is True
                and receipt["optimizer_resume"] is False,
                "training completion or warm-start identity is incomplete",
            )
            if number or plan["previous_training"] is not None:
                require(
                    receipt["warm_start"] is True
                    and receipt["parameter_before"]
                    == plan["previous_training"]["parameter_after"],
                    "updated policy was not initialized from previous tensors",
                )
            training.append(receipt)
            summary = {
                "round_index": number,
                "current_model_digest": previous,
                "collection_digest": data.digest(collection),
                "records_digest": data.digest(corrected),
                "plan_digest": data.digest(plan),
                "candidate_model_digest": identity,
                "training_digest": data.digest(receipt),
                "parameter_before": receipt["parameter_before"],
                "parameter_after": receipt["parameter_after"],
                "parameter_change": receipt["parameter_change"],
            }
            write_new(directory / "RESULT.json", summary)
            rounds.append(summary)
            current = copy.deepcopy(candidate)
        final = backend.evaluate(
            records, current, output / "post-update-A", freeze["maximum_attempts"]
        )
        require(
            final["model_digest"] == data.digest(current)
            and final["records_digest"] == data.digest(records)
            and final["complete"] is True,
            "post-update use does not bind the final actual candidate",
        )
        require(
            backend.sources() == freeze["source_inventory"],
            "source changed during final use",
        )
        all_collections = [*collections, final]
        result = {
            "schema": SCHEMA,
            "status": "COMPLETE",
            "freeze_digest": data.digest(freeze),
            "collection_mode": freeze["collection_mode"],
            "rounds": rounds,
            "final_model_digest": data.digest(current),
            "final_manifest": current,
            "post_update_A_digest": data.digest(final),
            "optimizer_steps": sum(row["steps"] for row in training),
            "model_calls": sum(row["model_calls"] for row in all_collections),
            "student_verifier_calls": sum(
                row["student_verifier_calls"] for row in all_collections
            ),
            "input_tokens": sum(row["input_tokens"] for row in all_collections),
            "output_tokens": sum(row["output_tokens"] for row in all_collections),
            "wall_seconds": time.perf_counter() - started,
            "full_system_cost_complete": False,
            "collection_retention": "all raw observations retained; latest round only enters each fit",
            **SCOPE,
        }
        write_new(output / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(
            output / "FAILED.json",
            {
                "status": "FAILED_PRESERVED",
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_rounds": rounds,
                "wall_seconds": time.perf_counter() - started,
                "call_totals_complete": False,
                "automatic_retry": False,
                **SCOPE,
            },
        )
        raise
