"""One fresh writer or admitted reader child in the fixed 376-forward probe."""

import argparse
from dataclasses import asdict
import os
from pathlib import Path
import resource
import time

from fitting_common import (
    digest,
    read_json,
    require,
    retain,
    two_cpus,
    validate_protocol,
    verify_pin,
)
from fitting_observation import ForwardLedger
from fitting_probe import observe


def execute(directory, expected, phase):
    started = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = dict(
        schema="hepta.fitting-diagnostic.worker-result.v1",
        phase=phase,
        status="failed",
        pid=os.getpid(),
        charged_forward_reservation=296 if phase == "train" else 80,
        budget_refund=0,
        forward_audit=None,
        source_pin_after=False,
    )
    ledger, lease, service, protocol = None, None, None, None
    try:
        protocol = validate_protocol(directory, expected)
        snapshot, examples = (
            read_json(directory / "snapshot.json"),
            read_json(directory / "examples.json"),
        )
        require(
            digest(snapshot) == protocol["source_snapshot_sha256"]
            and digest(examples) == protocol["examples_sha256"]
            and len(examples) == 40,
            "registered source or token panel changed",
        )
        from memory_service import MemoryService
        from parameter_publication import publish
        from training_backend import seal_candidate, verify_candidate
        from parametric_model import SourceMemoryCell, adapter_digest
        import torch

        result["cpu_affinity"] = two_cpus()
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        service = MemoryService(
            directory / "source-owner",
            protocol["scope"],
            protocol["cell_id"],
            protocol["role"],
        )
        require(
            service.snapshot() == snapshot
            and not set(snapshot["roots"]) & set(protocol["old_roots"]),
            "fresh live synthetic source authority changed",
        )
        quotas = (
            {"training": 256, "memory_teacher": 40}
            if phase == "train"
            else {"reload_teacher": 40, "reload_prefill": 40}
        )
        with (directory / f"{phase}-forward-events.jsonl").open("x") as stream:
            ledger = ForwardLedger(
                examples, quotas, stream, protocol["expected_training_order"]
            )
            if phase == "train":
                lease = service.queue.claim("fitting-diagnostic", lease_seconds=900)
                require(
                    lease is not None
                    and lease.snapshot == snapshot
                    and lease.candidate is None
                    and service.parameter_binding() is None,
                    "fresh writer lease required",
                )
                cell = SourceMemoryCell(protocol["base"], rank=8, seed=24029)
                require(
                    cell.reader.identity == protocol["base_identity"],
                    "writer fixed base differs",
                )
                cell.reset(protocol["scope"])
                require(
                    adapter_digest(cell.reader.model)
                    == protocol["expected_starting_adapter_sha256"],
                    "fresh adapter initialization differs from the controlled reference",
                )
                before = cell.reader.model.register_forward_pre_hook(
                    ledger.before, with_kwargs=True
                )
                after = cell.reader.model.register_forward_hook(
                    ledger.after, with_kwargs=True
                )
                try:
                    ledger.begin("training")
                    receipt = cell.fit_sources(
                        snapshot["facts"],
                        256,
                        0.001,
                        protocol["templates"],
                        objective="completion_ce",
                    )
                    result["training"] = receipt
                    require(
                        receipt["actual_model_forwards"] == 256
                        and receipt["steps"] == 256
                        and receipt["initialization"] == "frozen_base"
                        and receipt["inherited_roots"] == []
                        and receipt["learned_parent_manifest_sha256"] is None
                        and receipt["schedule_indices"]
                        == protocol["expected_training_order"],
                        "actual training method, ancestry or order changed",
                    )
                    require(
                        service.snapshot() == snapshot,
                        "source changed before in-memory observation",
                    )
                    memory, _ = observe(cell, examples, ledger, "memory_teacher")
                    retain(directory / "memory-teacher.json", memory)
                    require(
                        service.snapshot() == snapshot,
                        "source changed during in-memory observation",
                    )
                finally:
                    before.remove()
                    after.remove()
                destination = service.artifacts / "fitting-candidate"
                destination.mkdir(exist_ok=False)
                manifest = cell.save(destination / "checkpoint")
                candidate = seal_candidate(
                    snapshot, destination / "checkpoint", manifest
                )
                verify_candidate(candidate, snapshot, service.artifacts)
                service.queue.stage(lease, candidate)
                publication = publish(service, lease)
                require(
                    publication["status"] == "published"
                    and publication["training"] == receipt,
                    "fresh diagnostic checkpoint was not published",
                )
                result["publication"] = {
                    k: v for k, v in publication.items() if k != "training"
                }
                result["reproduced_reference_adapter_bytes"] = (
                    receipt["adapter_state_sha256"]
                    == protocol["reference_final_adapter_sha256"]
                )
            else:
                binding = service.parameter_binding()
                require(
                    binding is not None
                    and all(
                        service.read(f["entity"], f["relation"]).status.value
                        == "answered"
                        for f in snapshot["facts"]
                    ),
                    "current published key/source binding required",
                )

                def admitted(active):
                    require(
                        active == binding["active"] and service.snapshot() == snapshot,
                        "selected checkpoint or live source changed before dispatch",
                    )
                    cell = SourceMemoryCell(protocol["base"], rank=8, seed=24029)
                    cell.load(
                        active.directory,
                        expected_manifest_sha256=active.manifest_sha256,
                        scope=protocol["scope"],
                        allowed_roots=set(active.roots),
                        revoked=set(snapshot["revoked"]),
                    )
                    trained = read_json(directory / "train-result.json")["training"]
                    require(
                        adapter_digest(cell.reader.model)
                        == trained["adapter_state_sha256"],
                        "reader consumed a different final adapter",
                    )
                    before = cell.reader.model.register_forward_pre_hook(
                        ledger.before, with_kwargs=True
                    )
                    after = cell.reader.model.register_forward_hook(
                        ledger.after, with_kwargs=True
                    )
                    try:
                        teacher, first = observe(
                            cell, examples, ledger, "reload_teacher"
                        )
                        retain(directory / "reload-teacher.json", teacher)
                        prefill, _ = observe(
                            cell, examples, ledger, "reload_prefill", first
                        )
                        retain(directory / "reload-prefill.json", prefill)
                    finally:
                        before.remove()
                        after.remove()
                    return active.manifest_sha256

                result["admitted_manifest_sha256"] = service.owner.invoke(
                    service.store.cell_id,
                    service.store.scope,
                    service.authority_view,
                    admitted,
                )
                require(
                    service.parameter_binding() == binding
                    and service.snapshot() == snapshot,
                    "live binding changed during paired observations",
                )
                revoked = service.revoke("fitting-long_00", 0)
                calls, reads = [], []
                for entity in ("long_00", "long_01"):
                    response = service.invoke_parameter(
                        entity,
                        "color",
                        f"What is the color for {entity}?",
                        lambda *_: calls.append(entity),
                    )
                    reads.append(response)
                probe = dict(
                    receipt=asdict(revoked), reads=reads, decoder_callbacks=len(calls)
                )
                retain(directory / "withdrawal-probe.json", probe)
                require(
                    not calls
                    and [r["status"] for r in reads] == ["revoked", "unavailable"]
                    and service.parameter_binding() is None,
                    "fresh diagnostic revocation allowed stale use",
                )
            require(
                ledger.summary()["completed"] == quotas
                and ledger.pending is None
                and not ledger.rejected,
                "registered worker forward sequence incomplete",
            )
        result["status"] = "complete"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"[:3000]
        if phase == "train" and lease is not None:
            try:
                service.queue.fail(lease, error)
            except Exception as secondary:
                result["lease_failure"] = str(secondary)[:1000]
    finally:
        if ledger is not None:
            result["forward_audit"] = ledger.summary()
        if protocol is not None:
            try:
                verify_pin(directory, protocol)
                result["source_pin_after"] = True
            except Exception as error:
                result["source_pin_error"] = str(error)
                result["status"] = "failed"
        after = resource.getrusage(resource.RUSAGE_SELF)
        result.update(
            wall_seconds=time.perf_counter() - started,
            peak_self_rss_kib=after.ru_maxrss,
            cpu_seconds=after.ru_utime
            + after.ru_stime
            - usage.ru_utime
            - usage.ru_stime,
        )
        retain(directory / f"{phase}-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--phase", choices=("train", "read"), required=True)
    args = parser.parse_args()
    outcome = execute(args.out, args.protocol_sha256, args.phase)
    print(outcome["status"], flush=True)
    raise SystemExit(0 if outcome["status"] == "complete" else 1)
