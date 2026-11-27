"""Host-controlled spawn worker. No network service or production authority."""

from dataclasses import replace
import os
import time

import torch

from cell_evolution_snapshot import EvolutionBudgetV1, WithdrawalViewV1, check_sources, digest, load_snapshot
from cell_process_protocol import (MAX_ROWS, MAX_WIRE_BYTES, ProcessInferenceError, ProcessMessageV1,
    exact_keys, probabilities_payload, read_features, sha, snapshot_pins)


def worker_main(connection, counters, worker_index):
    """Counters are host-created shared memory, updated by actual forward hooks.

    They are independent of result payloads, not tamper-proof against a hostile
    worker sharing this trusted host. The worker never executes a Router.
    """
    torch.set_num_threads(1)
    torch.set_default_dtype(torch.float32)
    request = None
    try:
        started = time.process_time_ns()
        request = ProcessMessageV1.decode(connection.recv_bytes(MAX_WIRE_BYTES))
        if request.kind != "load" or request.sequence != 0 or request.worker_index != worker_index:
            raise ProcessInferenceError("first worker request must load pinned artifacts")
        exact_keys(request.payload, ("directory", "budget", "frontier"))
        directory = request.payload["directory"]
        if type(directory) is not str or not 1 <= len(directory) <= 4096:
            raise ProcessInferenceError("invalid local snapshot path")
        view = dict(request.payload["frontier"])
        view["revoked_source_digests"] = tuple(view["revoked_source_digests"])
        frontier = WithdrawalViewV1(**view)
        snapshot = load_snapshot(directory, expected_manifest_sha256=request.pins.snapshot_sha256,
            budget=EvolutionBudgetV1(**request.payload["budget"]), withdrawal_provider=lambda: frontier)
        if snapshot_pins(snapshot, frontier) != request.pins:
            raise ProcessInferenceError("reloaded artifacts differ from owner expectations")
        cells = {c.cell_id: c for c in snapshot.cells}
        def observe(index):
            def hook(module, inputs):
                with counters.get_lock():
                    counters[index * 2] += len(inputs[0])
                    counters[index * 2 + 1] += 1
            return hook
        for index, cell in enumerate(snapshot.cells):
            cell.head._head.register_forward_pre_hook(observe(index))
        if snapshot.router:
            def forbid_router(module, inputs):
                with counters.get_lock():
                    counters[4] += 1
                raise ProcessInferenceError("worker must not run the Router")
            snapshot.router._net.register_forward_pre_hook(forbid_router)
        connection.send_bytes(replace(request, kind="ready", payload={"pid": os.getpid(),
            "resident_tensor_bytes": snapshot.report["resident_tensor_bytes"],
            "cpu_time_ns": time.process_time_ns() - started}).encode())
        previous = request
        while True:
            request = ProcessMessageV1.decode(connection.recv_bytes(MAX_WIRE_BYTES))
            started = time.process_time_ns()
            if (request.kind != "infer" or request.sequence != previous.sequence + 1
                    or request.request_id.rsplit(":", 1)[0] != previous.request_id.rsplit(":", 1)[0]
                    or request.pins != previous.pins or request.worker_index != worker_index):
                raise ProcessInferenceError("stale, reordered or differently pinned request")
            exact_keys(request.payload, ("cell_id", "full_bundle_sha256", "rows", "route_sha256", "features"))
            sha(request.payload["full_bundle_sha256"])
            sha(request.payload["route_sha256"])
            rows = request.payload["rows"]
            if (type(rows) is not list or not rows or rows != sorted(set(rows))
                    or any(type(i) is not int or not 0 <= i < MAX_ROWS for i in rows)
                    or request.payload["cell_id"] not in cells):
                raise ProcessInferenceError("invalid selected Cell or row indices")
            snapshot.require_current(lambda: frontier)
            bundle = read_features(request.payload["features"], snapshot.identity)
            check_sources(bundle.source_record_digests, snapshot.identity, lambda: frontier)
            if len(bundle.source_record_digests) != len(rows):
                raise ProcessInferenceError("selected rows/features differ")
            output = cells[request.payload["cell_id"]].head.predict_task(bundle)
            snapshot.require_current(lambda: frontier)
            payload = {"request_payload_sha256": digest(request.payload),
                "probabilities_f64": probabilities_payload(output["task_probabilities"]),
                "cpu_time_ns": time.process_time_ns() - started}
            connection.send_bytes(replace(request, kind="result", payload=payload).encode())
            previous = request
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        if request is not None:
            try:
                connection.send_bytes(replace(request, kind="error", payload={"reason": "worker rejected request"}).encode())
            except (OSError, ValueError):
                pass
    finally:
        connection.close()
