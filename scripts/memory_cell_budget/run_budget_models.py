"""Serial bounded memory comparison; execution requires explicit model-lane flag."""

import argparse
from collections import Counter
from contextlib import contextmanager
import json
import math
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

from budget_ledger import BudgetExceeded, digest
from cohort_contract import file_sha, retain, validate_seal
from model_budget import allocate_parent, inventory, ledger_for, model_call
from model_load import continued_load
from retrieval_index import tokens
from workflow_records import FINAL_TEMPLATE, SCOPE, TRAIN_TEMPLATES


ARMS = ("single", "expanded", "data_split", "random_split")


@contextmanager
def hard_deadline(seconds):
    """Main-thread Linux timer covers host work as well as all model children."""

    def expired(signum, frame):
        raise TimeoutError("per-arm end-to-end wall budget elapsed")

    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def questions(shared, study):
    records = json.loads((shared / "admitted-source-records.json").read_text())
    known = [
        dict(
            id=r["record_id"],
            kind="known_source_heldout_wording",
            question=FINAL_TEMPLATE.format(**r),
        )
        for r in records[:16]
    ]
    natural = [
        dict(
            id=r["task_id"],
            kind="natural_time_holdout",
            question="Return one short shell command for this original failure:\n"
            + r["text"],
        )
        for r in json.loads((study / "requests.json").read_text())
    ]
    return records, known + natural


def freeze_routes(arm, records, versions, partition, queries):
    if len(versions) == 1:
        return [dict(query_id=q["id"], slot=0, scores=[1.0]) for q in queries]
    vectors = []
    for slot in range(2):
        counts = Counter()
        for row, assigned in zip(records, partition["slots"]):
            if assigned == slot:
                for template in TRAIN_TEMPLATES:
                    counts.update(tokens(template.format(**row)))
        norm = math.sqrt(sum(v * v for v in counts.values()))
        vectors.append({k: v / norm for k, v in counts.items()})
    routes = []
    for query in queries:
        counts = Counter(tokens(query["question"]))
        norm = math.sqrt(sum(v * v for v in counts.values()))
        scores = [
            sum(v * counts.get(k, 0) / max(norm, 1) for k, v in vector.items())
            for vector in vectors
        ]
        routes.append(
            dict(
                query_id=query["id"],
                slot=max(range(2), key=lambda i: (scores[i], -i)),
                scores=scores,
            )
        )
    return routes


def execute_reads(arm, versions, queries, routes, records, ledger, args, directory):
    results = []
    allowed = [r["source_digest"] for r in records]
    route_by_id = {r["query_id"]: r["slot"] for r in routes}
    controls = {
        "adapter": queries,
        "base": queries[:4] + queries[16:],
        "shuffled": queries[:4] + queries[16:],
    }
    for control, selected in controls.items():
        for slot, version in enumerate(versions):
            assigned = [q for q in selected if route_by_id[q["id"]] == slot]
            if not assigned:
                continue
            event = f"{control}-{slot}"
            request = dict(
                phase="read",
                model=str(args.model),
                version=version,
                allowed_roots=allowed,
                questions=[q["question"] for q in assigned],
                control=control,
            )
            measurement = model_call(
                ledger,
                event,
                request,
                implementation=args.implementation,
                directory=directory / event,
            )
            raw = measurement["output"]
            rows = {
                index: row for index, row in zip(raw["indices"], raw["journal"]["rows"])
            }
            rejected = {r["index"]: r for r in raw["rejected"]}
            for index, query in enumerate(assigned):
                results.append(
                    dict(
                        query_id=query["id"],
                        kind=query["kind"],
                        control=control,
                        slot=slot,
                        raw=rows.get(index),
                        rejection=rejected.get(index),
                        measurement_sha256=digest(measurement),
                        read_started_after_route_freeze=True,
                    )
                )
    retain(directory / "raw-results.json", results)
    return results


def score_known(records, versions, rows):
    lookup = {r["record_id"]: r for r in records[:16]}
    report = {}
    for control in ("adapter", "base", "shuffled"):
        selected = [
            r
            for r in rows
            if r["control"] == control and r["kind"] == "known_source_heldout_wording"
        ]
        correct = supported = 0
        for row in selected:
            truth = lookup[row["query_id"]]
            match = row["raw"] is not None and row["raw"]["text"] == truth["value"]
            correct += match
            supported += (
                match and truth["source_digest"] in versions[row["slot"]]["roots"]
            )
        report[control] = dict(
            correct=int(correct),
            supported_correct=int(supported),
            denominator=len(selected),
            interpretation="known source facts under a new wording; not natural-task repair or independent future tasks",
        )
    return report


def arm_run(arm, args, protocol, shared, parent_measurement):
    try:
        seconds = (
            protocol["common_budget"]["limits"]["wall_ns"] / 10**9
            - parent_measurement["actual"]["wall_ns"] / 10**9
        )
        with hard_deadline(seconds):
            return _arm_run(arm, args, protocol, shared, parent_measurement)
    except Exception as error:
        return failed_arm(arm, args, protocol, error, unexecuted=False)


def abandon_pending(ledger, reason):
    for row in ledger.snapshot()["events"]:
        if row["state"] == "reserved":
            ledger.abandon(row["event"], reason=reason)


def failed_arm(arm, args, protocol, error, *, unexecuted):
    """Outside the timer: preserve partial files, charge unknown work, no retry."""
    result = dict(
        arm=arm,
        status="unexecuted_shared_dependency_failure"
        if unexecuted
        else "outer_arm_failure",
        error_type=type(error).__name__,
        error=str(error),
        model_arm_attempted=not unexecuted,
        natural_task_successes=0,
        natural_task_denominator=4,
        known_source_denominator=16,
        no_automatic_retry=True,
        unknown_reservations_are_not_refunded=True,
    )
    try:
        path = args.output / arm / "budget.sqlite3"
        if path.exists():
            ledger = ledger_for(
                path, arm, protocol, file_sha(args.study / "protocol.json")
            )
            abandon_pending(ledger, "outer arm failure with incomplete operation")
            result["budget"] = ledger.snapshot()
        else:
            result["budget"] = None
        destination = args.output / (arm + ".outer-failure.json")
        retain(destination, result)
        result["outer_failure_receipt_path"] = str(destination)
    except Exception as persistence_error:
        result["failure_receipt_persisted"] = False
        result["persistence_error"] = str(persistence_error)
        print(
            json.dumps(
                dict(
                    schema="hepta.budget.failure-receipt-unavailable.v1", failure=result
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
    return result


def shared_identity(shared):
    return {
        str(p.relative_to(shared)): file_sha(p)
        for p in sorted(shared.rglob("*"))
        if p.is_file()
    }


def _arm_run(arm, args, protocol, shared, parent_measurement):
    destination = args.output / arm
    destination.mkdir()
    ledger = ledger_for(
        destination / "budget.sqlite3",
        arm,
        protocol,
        file_sha(args.study / "protocol.json"),
    )
    allocate_parent(ledger, parent_measurement)
    try:
        request = dict(
            phase="arm",
            arm=arm,
            model=str(args.model),
            study=str(args.study),
            shared=str(shared),
            output=str(destination / "training"),
            parent_result_sha256=file_sha(shared / "result.json"),
        )
        trained = model_call(
            ledger,
            "train",
            request,
            implementation=args.implementation,
            directory=destination / "training-process",
            expected_updates=96,
        )
        versions = trained["output"]["versions"]
        records, queries = questions(shared, args.study)
        started = time.perf_counter_ns()
        cpu = time.process_time_ns()
        ledger.reserve(
            "routes",
            "feature",
            dict(wall_ns=10**9, cpu_ns=10**9, write_bytes=1024**2),
            request_sha256=digest(queries),
        )
        routes = freeze_routes(
            arm, records, versions, trained["output"]["partition"], queries
        )
        route_receipt = dict(
            arm=arm,
            routes=routes,
            queries_sha256=digest(queries),
            frozen_at_ns=time.time_ns(),
            versions=versions,
            source_records_sha256=file_sha(shared / "admitted-source-records.json"),
            final_decoder_calls_so_far=0,
            policy="source-only fixed lexical-centroid; no trained edges",
        )
        retain(destination / "routes.json", route_receipt)
        retain(destination / "queries.json", queries)
        ledger.settle(
            "routes",
            dict(
                wall_ns=time.perf_counter_ns() - started,
                cpu_ns=time.process_time_ns() - cpu,
                write_bytes=(destination / "routes.json").stat().st_size
                + (destination / "queries.json").stat().st_size,
            ),
            receipt_sha256=digest(route_receipt),
        )
        raw = execute_reads(
            arm, versions, queries, routes, records, ledger, args, destination
        )
        # Predictions are durably retained before consulting known source values.
        retain(
            destination / "outputs-frozen.json",
            dict(
                sha256=file_sha(destination / "raw-results.json"),
                frozen_at_ns=time.time_ns(),
            ),
        )
        scores = score_known(records, versions, raw)
        natural = [
            r
            for r in raw
            if r["control"] == "adapter" and r["kind"] == "natural_time_holdout"
        ]
        load = continued_load(
            versions, queries, routes, records, ledger, args, destination
        )
        components = [
            dict(name="base", path=str(args.model), kind="base", private=False),
            dict(name="source", path=str(args.study), kind="source", private=False),
            dict(
                name="shared-parent",
                path=str(shared.parent),
                kind="recovery",
                private=False,
            ),
            dict(name="arm", path=str(destination), kind="adapter", private=True),
        ]
        if args.runtime_component:
            components.append(
                dict(
                    name="runtime",
                    path=str(args.runtime_component),
                    kind="runtime",
                    private=False,
                )
            )
        full = inventory(
            ledger,
            components,
            args.output / (arm + ".inventory.json"),
            peak_rss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
        )
        result = dict(
            arm=arm,
            status="executed",
            known_source_scores=scores,
            natural_outputs=natural,
            continuous_load=load,
            standalone_end_to_end_wall_ceiling_seconds=600,
            active_capacity_values=sum(
                r["trainable_parameters"] for r in trained["output"]["receipts"]
            ),
            natural_task_successes=0,
            natural_task_denominator=4,
            natural_execution_status="original command gate must be executed separately; no labels count as success",
            inventory_sha256=full["inventory_sha256"],
            complete_retained_declared_component_bytes=full["logical_bytes"],
            runtime_component_declared=args.runtime_component is not None,
            OS_dependency_closure_complete=False,
            actual_equal_cost_matched=False,
            budget=ledger.snapshot(),
        )
    except Exception as error:
        abandon_pending(ledger, "arm ended before a complete operation receipt")
        result = dict(
            arm=arm,
            status="budget_exhausted_or_infrastructure_failure",
            error=str(error),
            error_type=type(error).__name__,
            natural_task_successes=0,
            natural_task_denominator=4,
            known_source_scored_correct=0,
            known_source_denominator=16,
            uncompleted_queries_not_dropped=True,
            budget=ledger.snapshot(),
        )
    retain(args.output / (arm + ".result.json"), result)
    return result


def run(args):
    if not args.model_lane_authorized:
        raise ValueError(
            "root must explicitly allocate the single pretrained execution lane"
        )
    validate_seal(args.study)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.implementation, text=True
    ).strip()
    protocol = json.loads((args.study / "protocol.json").read_text())
    if head != protocol["implementation_base"]:
        raise ValueError("implementation HEAD differs from registered source")
    args.output.mkdir(parents=True, exist_ok=False)
    retain(
        args.output / "execution-start.json",
        dict(
            protocol_sha256=file_sha(args.study / "protocol.json"),
            source_head=head,
            started_at_ns=time.time_ns(),
            arm_order=ARMS,
            model_path=str(args.model),
        ),
    )
    shared = args.output / "shared" / "state"
    ledger = ledger_for(
        args.output / "shared" / "budget.sqlite3",
        "shared-parent",
        protocol,
        file_sha(args.study / "protocol.json"),
    )
    parent, results, parent_pin = None, [], None
    try:
        parent = model_call(
            ledger,
            "parent",
            dict(
                phase="parent",
                model=str(args.model),
                study=str(args.study),
                output=str(shared),
            ),
            implementation=args.implementation,
            directory=args.output / "shared" / "process",
            expected_updates=32,
        )
        parent_pin = shared_identity(shared)
    except Exception as error:
        abandon_pending(ledger, "shared parent operation incomplete")
        results = [
            failed_arm(arm, args, protocol, error, unexecuted=True) for arm in ARMS
        ]
    if parent is not None and parent_pin is not None:
        for index, arm in enumerate(ARMS):
            try:
                validate_seal(args.study)
                if shared_identity(shared) != parent_pin:
                    raise ValueError("shared parent/source files changed between arms")
            except Exception as error:
                results.extend(
                    failed_arm(name, args, protocol, error, unexecuted=True)
                    for name in ARMS[index:]
                )
                break
            results.append(arm_run(arm, args, protocol, shared, parent))
    final_integrity, error_text = True, None
    try:
        validate_seal(args.study)
        if parent_pin is not None and shared_identity(shared) != parent_pin:
            raise ValueError("shared parent/source final identity mismatch")
    except Exception as error:
        final_integrity, error_text = False, str(error)
    result = dict(
        schema="hepta.memory-budget.models.v1",
        shared_parent_measurement_sha256=digest(parent) if parent else None,
        shared_physical_budget=ledger.snapshot(),
        arms=results,
        actual_equal_total_cost=False,
        final_shared_and_source_integrity=final_integrity,
        final_integrity_error=error_text,
        shared_parent_file_pin=parent_pin,
        prospective_task_results=0,
        admitted_corpus_scope="source-only workflow short-command memory",
        scientific_future_or_compression_qualification=False,
    )
    retain(args.output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("study", "model", "implementation", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--runtime-component", type=Path)
    parser.add_argument("--model-lane-authorized", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))
