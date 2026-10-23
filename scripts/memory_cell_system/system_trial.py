"""Execute a bounded pretrained typed-cell lifecycle across real TCP workers.

Synthetic facts exercise mechanics and parameter controls. Natural CI experience
is evaluated separately by memory_cell_domain; neither trial proves general memory.
"""

# Standalone CLI resolves the existing sibling research modules before imports.
# ruff: noqa: E402

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import traceback

SCRIPTS = Path(__file__).resolve().parents[1]
for dependency in (
    "memory_cell",
    "memory_cell_catalog",
    "memory_cell_service",
    "memory_cell_network",
):
    sys.path.insert(0, str(SCRIPTS / dependency))

from memory_service import MemoryService
from prepare_parametric import prepare
from system_common import (
    exact,
    plain,
    raw_signature,
    retain,
    source_identity,
    wait_for_claim,
)
from system_network import NetworkSession
from system_runtime import read_worker, train_once

SCOPE = "memory-service-network-development"
TEMPLATE = (
    "According to the retained record, state the {relation} associated with {entity}."
)
COLORS = ("red", "blue", "green", "yellow", "black", "white", "orange", "purple")


def train(service, model, output, label, steps=256):
    print(json.dumps({"stage": label, "steps": steps}), flush=True)
    result = train_once(service, model, output, label, steps)
    retain(output / f"{label}.json", result)
    if result["status"] != "published":
        raise AssertionError(
            f"current complete replay was not published: {result['status']}"
        )
    return service.parameter_binding()["active"]


def blocked(service, entity, relation):
    callbacks = []

    def forbidden(*args):
        callbacks.append(True)
        raise AssertionError("unsupported source reached decoder")

    result = service.invoke_parameter(
        entity, relation, "Return its stored value.", forbidden
    )
    return {"read": result, "model_callbacks": len(callbacks)}


def run(model, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    identity = source_identity()
    retain(output / "source-identity.json", identity)
    retain(
        output / "protocol.json",
        {
            "schema": "hepta.memory-system.pretrained-mechanism.v1",
            "scope": SCOPE,
            "phase": "finite_development",
            "synthetic_initial_sources": 8,
            "new_source_during_training": 1,
            "background_updates": 32,
            "updates_per_clean_publication": 256,
            "rank": 8,
            "seed": 2718,
            "learning_rate": 0.001,
            "control_question": TEMPLATE,
            "minimum_parameter_accuracy": 0.75,
            "minimum_control_advantage": 0.5,
            "correction_and_retained_accuracy_required": True,
            "corrected_source_exact_value_required": True,
            "source_overlay_excluded_from_parameter_metrics": True,
            "physical_hosts": 1,
            "training_and_decoder_execution": "bounded_child_processes",
            "production_accepted": False,
        },
    )
    acquisition = prepare(model)
    retain(output / "base-acquisition.json", acquisition)
    service_root = output / "source-owner"
    service = MemoryService(service_root, SCOPE, role="semantic")
    writes = [
        service.write(f"trial/source_{i:02d}", f"case_{i:02d}", "color", value)
        for i, value in enumerate(COLORS)
    ]
    overlay = [service.read(f"case_{i:02d}", "color") for i in range(8)]
    retain(
        output / "initial-writes-and-overlay.json", {"writes": writes, "reads": overlay}
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            train_once, service, model, output, "background-worker", 32
        )
        claim = wait_for_claim(service.queue, writes[-1].training_job_id, future)
        deadline = time.monotonic() + 60
        while not list(service.artifacts.glob("job-*/")):
            if future.done() or time.monotonic() >= deadline:
                raise RuntimeError(
                    "background trainer did not create its attempt directory"
                )
            time.sleep(0.02)
        arrived = service.write("trial/source_08", "case_08", "color", "green")
        immediate = service.read("case_08", "color")
        stale = future.result(timeout=600)
    retain(
        output / "background-new-event.json",
        {
            "observed_claim": claim,
            "new_write": arrived,
            "immediate_read": immediate,
            "old_training_result": stale,
            "stale_parameters_not_published": service.parameter_binding() is None,
        },
    )
    first = train(service, model, output, "first-publication")
    initial = service.snapshot()
    retain(output / "first-source-snapshot.json", initial)
    facts = initial["facts"]
    questions = [TEMPLATE.format(**fact) for fact in facts]
    cold = output / "fresh-controls"
    cold.mkdir()
    (cold / "reader-cwd").mkdir()
    controls = {
        control: read_worker(
            model,
            first.directory,
            first.manifest_sha256,
            SCOPE,
            first.roots,
            questions,
            cold,
            control,
            control=control,
        )
        for control in ("adapter", "base", "shuffled")
    }
    metrics = {name: exact(journal, facts) for name, journal in controls.items()}
    retain(output / "parameter-controls.json", metrics)
    unknown = blocked(service, "missing_case", "color")
    network = NetworkSession(output / "network", model, service_root, SCOPE)
    try:
        migration = network.migration(first, questions, controls["adapter"])
        routed = service.invoke_parameter(
            "case_00", "color", questions[0], network.client.service_reader
        )
        retain(output / "typed-network-parameter-read.json", routed)
        conflict_write = service.write(
            "trial/conflicting_report", "case_00", "color", "blue"
        )
        conflict = blocked(service, "case_00", "color")
        service.revoke("trial/conflicting_report", conflict_write.revision)
        correction = service.correct("trial/source_00", "white", expected_revision=0)
        immediate_correction = service.read("case_00", "color")
        stale_parameter = blocked(service, "case_00", "color")
        correction_denials = {
            node: network.refused(node, questions[:1]) for node in ("A", "B")
        }
        correction_frontier = plain(service.authority_view())
        retain(
            output / "typed-source-mutations.json",
            {
                "unknown": unknown,
                "conflict": conflict,
                "correction": correction,
                "immediate_correction": immediate_correction,
                "stale_parameter": stale_parameter,
                "network_denials_without_manual_frontier_sync": correction_denials,
            },
        )
        corrected = train(service, model, output, "corrected-publication")
        corrected_publication = network.publish(
            corrected, migration["migration"]["placement"], "B"
        )
        corrected_facts = service.snapshot()["facts"]
        corrected_questions = [TEMPLATE.format(**fact) for fact in corrected_facts]
        corrected_read = network.client.read(SCOPE, "memory", corrected_questions)
        retain(output / "corrected-network-read.json", corrected_read)
        withdrawal = service.revoke("trial/source_01", expected_revision=0)
        withdrawn = blocked(service, "case_01", "color")
        withdrawal_denials = {
            node: network.refused(node, questions[:1]) for node in ("A", "B")
        }
        withdrawal_frontier = plain(service.authority_view())
        retain(
            output / "withdrawal.json",
            {
                "receipt": withdrawal,
                "typed_read": withdrawn,
                "nodes_without_manual_frontier_sync": withdrawal_denials,
            },
        )
        rebuilt = train(service, model, output, "withdrawal-clean-publication")
        rebuilt_publication = network.publish(
            rebuilt, corrected_publication["placement"], "B"
        )
        retained = service.snapshot()
        retained_questions = [TEMPLATE.format(**fact) for fact in retained["facts"]]
        rebuilt_read = network.client.read(SCOPE, "memory", retained_questions)
        old_pid = network.nodes["B"].process.pid
        network.nodes["B"].stop()
        network.nodes["B"].start()
        restarted_read = network.client.read(SCOPE, "memory", retained_questions)
        network.authority.stop()
        outage = network.refused("B", retained_questions[:1])
        network.authority.start()
        recovered_read = network.client.read(SCOPE, "memory", retained_questions)
        retain(
            output / "restart-and-outage.json",
            {
                "old_pid": old_pid,
                "restarted": restarted_read,
                "outage": outage,
                "recovered": recovered_read,
                "rebuilt": rebuilt_read,
                "publication": rebuilt_publication,
            },
        )
        lifecycle_gates = {
            "unknown_zero_callback": unknown["read"]["status"] == "unknown"
            and unknown["model_callbacks"] == 0,
            "conflict_zero_callback": conflict["read"]["status"] == "conflict"
            and conflict["model_callbacks"] == 0,
            "withdrawn_zero_callback": withdrawn["read"]["status"] == "revoked"
            and withdrawn["model_callbacks"] == 0,
            "corrected_overlay_immediate": immediate_correction.answer == "white",
            "stale_parameter_epoch_unavailable": stale_parameter["read"]["status"]
            == "unavailable",
            "live_source_withdrawal_reaches_both_nodes": all(
                row["before"] == row["after"] and row["observed_frontier"] == frontier
                for denials, frontier in (
                    (correction_denials, correction_frontier),
                    (withdrawal_denials, withdrawal_frontier),
                )
                for row in denials.values()
            ),
            "replayed_roots_exclude_withdrawals": not set(rebuilt.roots)
            & set(retained["revoked"]),
            "worker_restart_preserves_raw_output": old_pid != restarted_read["pid"]
            and raw_signature(rebuilt_read["journal"])
            == raw_signature(restarted_read["journal"]),
            "authority_outage_zero_callback": outage["before"] == outage["after"],
            "authority_recovery_preserves_raw_output": raw_signature(
                recovered_read["journal"]
            )
            == raw_signature(rebuilt_read["journal"]),
            "typed_service_uses_network_parameters": routed["status"] == "generated"
            and routed["origin"] == "parameters",
        }
        metrics["corrected"] = exact(corrected_read["journal"], corrected_facts)
        metrics["after_withdrawal"] = exact(rebuilt_read["journal"], retained["facts"])
        corrected_index = next(
            i
            for i, fact in enumerate(corrected_facts)
            if fact["entity"] == "case_00" and fact["relation"] == "color"
        )
        correction_exact = metrics["corrected"]["per_source"][corrected_index]
    finally:
        network.close()
    writes = [
        json.loads(path.read_text())["training"]
        for path in sorted(service.artifacts.glob("job-*/checkpoint/lineage.json"))
    ]
    retain(output / "all-training-receipts.json", writes)
    after_identity = source_identity()
    retain(output / "source-identity-after.json", after_identity)
    accuracy = metrics["adapter"]["accuracy"]
    result = {
        "schema": "hepta.memory-system.pretrained-result.v1",
        "metrics": metrics,
        "engineering_gates": {
            "new_event_read_while_background_training": immediate.answer == "green",
            "stale_background_attempt_not_published": stale["status"] == "superseded",
            "source_identity_unchanged": identity == after_identity,
            **migration["gates"],
            **lifecycle_gates,
        },
        "parameter_control_gates": {
            "accuracy": accuracy >= 0.75,
            "adapter_over_base": accuracy - metrics["base"]["accuracy"] >= 0.5,
            "adapter_over_shuffled": accuracy - metrics["shuffled"]["accuracy"] >= 0.5,
            "corrected_parameter_accuracy": metrics["corrected"]["accuracy"] >= 0.75,
            "corrected_source_exact_value": correction_exact,
            "retained_after_withdrawal_accuracy": metrics["after_withdrawal"][
                "accuracy"
            ]
            >= 0.75,
        },
        "costs": {
            "all_training_updates": sum(row["steps"] for row in writes),
            "all_training_input_tokens": sum(row["input_tokens"] for row in writes),
            "all_training_seconds": sum(row["seconds"] for row in writes),
            "shared_base_disk_bytes": acquisition["total_bytes"],
            "all_retained_trial_bytes_before_result": sum(
                path.stat().st_size for path in output.rglob("*") if path.is_file()
            ),
            "wall_seconds": time.perf_counter() - started,
            "runtime_libraries_not_counted": True,
        },
        "future_task_advantage_proven": False,
        "net_compression_proven": False,
        "multi_host_qualification": False,
        "production_accepted": False,
    }
    result["engineering_status"] = (
        "passed" if all(result["engineering_gates"].values()) else "failed"
    )
    result["parameter_control_status"] = (
        "passed" if all(result["parameter_control_gates"].values()) else "failed"
    )
    result["research_target_status"] = "not_established_by_this_mechanism_trial"
    retain(output / "result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    absent = not args.output.exists()
    try:
        outcome = run(args.model.resolve(), args.output.resolve())
    except Exception:
        if absent and args.output.is_dir():
            retain(
                args.output / "execution-failure.json",
                {"traceback": traceback.format_exc()},
            )
        raise
    raise SystemExit(
        0
        if outcome["engineering_status"]
        == outcome["parameter_control_status"]
        == "passed"
        else 1
    )
