"""Fail-closed same-host process inference over actual immutable E1 artifacts.

The owner holds current generation and withdrawal history. Workers are trusted
host children, not authenticated remote nodes. Failed pools cannot be reused.
"""

from dataclasses import asdict
import math
import multiprocessing
import threading
import time
import uuid

import torch

from cell_evolution_snapshot import (EvolutionError, OfflineEvolutionOwnerV1, check_sources, digest)
from cell_process_protocol import (MAX_ROWS, MAX_WIRE_BYTES, ProcessInferenceError, ProcessMessageV1,
    exact_keys, feature_payload, match_response, read_probabilities, snapshot_pins)
from cell_process_worker import worker_main
from cell_router_training import _choose, _subset
from feature_bundle import FeatureBundleV1


class SnapshotProcessOwnerV1:
    """Retains the latest observed source frontier, including rejected requests."""
    def __init__(self, snapshot, withdrawal_provider):
        self._owner = OfflineEvolutionOwnerV1(snapshot, withdrawal_provider)
        self._frontier = asdict(snapshot.require_current(withdrawal_provider))

    @property
    def current(self):
        return self._owner.current

    def _observe(self, identity):
        view = check_sources((), identity, self._owner._provider, self._frontier)
        self._frontier = asdict(view)
        return view

    def capture(self):
        with self._owner._lock:
            snapshot = self.current
            view = self._observe(snapshot.identity)
            snapshot.require_current(lambda: view)
            return snapshot, view

    def commit(self, candidate, *, expected_parent_manifest_sha256):
        with self._owner._lock:
            view = self._observe(candidate.identity)
            candidate.require_current(lambda: view)
            predecessor = self._owner.current
            self._owner.commit(candidate, expected_parent_manifest_sha256=expected_parent_manifest_sha256)
            try:
                # Recheck the external frontier after the in-memory CAS. A
                # withdrawn ancestor discovered here must not leave a rejected
                # successor selected. This is only an in-process shadow owner,
                # not a substitute for a durable production transaction.
                candidate.require_current(lambda: self._observe(candidate.identity))
            except Exception:
                self._owner._current = predecessor
                # Preserve the observed withdrawal frontier: restoring the old
                # pointer is not authorization to use a now-revoked ancestor.
                raise


def _route(snapshot, bundle, budget_units):
    cells = snapshot.cells
    router = snapshot.router
    report = router.report if router else cells[0].head.report
    cap = snapshot.budget.inference_cost_units_per_row
    if router:
        cap = min(cap, report["config"]["budget_units"])
    budget = cap if budget_units is None else budget_units
    if type(budget) not in (float, int) or not math.isfinite(budget) or not 0 < budget <= cap:
        raise ProcessInferenceError("runtime inference budget exceeds owner cap")
    top_k = report["config"]["top_k"] if router else 1
    ids = [cell.cell_id for cell in cells]
    scores = [[None] * len(cells) for _ in bundle.source_record_digests]
    if router:
        with torch.inference_mode():
            values = router._net(bundle.read_global().float())
        if values.shape != (len(scores), len(cells)) or not torch.isfinite(values).all():
            raise ProcessInferenceError("invalid Router output")
        scores = values.tolist()
    ledger = []
    for row, values in enumerate(scores):
        rank = sorted(range(len(cells)), key=lambda i: (values[i], ids[i])) if router else [0]
        selected = _choose(rank, cells, ids, top_k, budget)
        ledger.append({"source_record_digest": bundle.source_record_digests[row],
            "candidates": [{"cell_id": c.cell_id, "predicted_loss_cost": values[i],
                "declared_cost_units": float(c.cost_units), "legal": c.cost_units <= budget}
                for i, c in enumerate(cells)], "selected": [ids[i] for i in selected],
            "actual_calls": [], "actual_cost_units": 0.0, "budget_units": float(budget),
            "route_mode": "learned" if router else "single_cell"})
    return ledger


class SnapshotWorkerPoolV1:
    """One immutable generation per pool; create a new pool after owner changes."""
    def __init__(self, owner, *, worker_count=1, timeout_seconds=30.0,
                 max_requests_per_worker=1024):
        if (type(owner) is not SnapshotProcessOwnerV1 or type(worker_count) is not int
                or not 1 <= worker_count <= 2 or type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or not 0.05 <= timeout_seconds <= 60
                or type(max_requests_per_worker) is not int
                or not 1 <= max_requests_per_worker <= 1024):
            raise ProcessInferenceError("invalid bounded process pool")
        self._owner, self._timeout = owner, timeout_seconds
        self._request_limit = max_requests_per_worker
        self._snapshot, self._frontier = owner.capture()
        self._pins = snapshot_pins(self._snapshot, self._frontier)
        self._session = uuid.uuid4().hex
        self._workers, self._sequences = [], [0] * worker_count
        self._closed = False
        self._serial = threading.Lock()
        self._stats_lock = threading.Lock()
        self._events = []
        self._stats = {"sent_payload_bytes": 0, "received_payload_bytes": 0,
            "sent_frames": 0, "received_frames": 0}
        context = multiprocessing.get_context("spawn")
        started = time.perf_counter_ns()
        try:
            for index in range(worker_count):
                parent, child = context.Pipe(duplex=True)
                counters = context.Array("q", 5, lock=True)
                process = context.Process(target=worker_main, args=(child, counters, index), daemon=True)
                process.start()
                child.close()
                self._workers.append((process, parent, counters))
            requests = {i: [self._message(i, "load", {"directory": str(self._snapshot.directory.resolve()),
                "budget": asdict(self._snapshot.budget), "frontier": asdict(self._frontier)})]
                for i in range(worker_count)}
            responses = self._exchange(requests)
            for i, values in responses.items():
                response = values[0]
                match_response(response, requests[i][0], "ready")
                exact_keys(response.payload, ("pid", "resident_tensor_bytes", "cpu_time_ns"))
                if (type(response.payload["cpu_time_ns"]) is not int
                        or not 0 <= response.payload["cpu_time_ns"] < 2**63
                        or response.payload["pid"] != self._workers[i][0].pid
                        or response.payload["resident_tensor_bytes"] != self._snapshot.report["resident_tensor_bytes"]):
                    raise ProcessInferenceError("worker load receipt mismatch")
            self._guard()
            self.startup_ns = time.perf_counter_ns() - started
        except Exception:
            self.close()
            raise

    def _message(self, index, kind, payload):
        sequence = self._sequences[index]
        if sequence >= self._request_limit:
            raise ProcessInferenceError("worker lifetime request limit exhausted")
        self._sequences[index] += 1
        return ProcessMessageV1(kind, f"{self._session}:{index}:{sequence}", sequence, index,
                                self._pins.graph_generation, self._pins, payload)

    def _guard(self):
        if self._closed:
            raise ProcessInferenceError("failed or closed pool cannot be reused")
        if any(not process.is_alive() for process, _, _ in self._workers):
            raise ProcessInferenceError("worker is unavailable; discard result")
        snapshot, frontier = self._owner.capture()
        if snapshot_pins(snapshot, frontier) != self._pins:
            raise ProcessInferenceError("owner generation or source frontier changed; discard result")

    def _exchange(self, groups):
        # Serialize before starting I/O so oversized requests execute no Heads.
        encoded = {i: [(message, message.encode()) for message in messages] for i, messages in groups.items()}
        responses, failures = {}, []
        def run(index, messages):
            process, connection, _ = self._workers[index]
            values = []
            try:
                for message, data in messages:
                    if not process.is_alive():
                        raise ProcessInferenceError("worker crashed")
                    connection.send_bytes(data)
                    with self._stats_lock:
                        self._stats["sent_payload_bytes"] += len(data)
                        self._stats["sent_frames"] += 1
                    raw = connection.recv_bytes(MAX_WIRE_BYTES)
                    with self._stats_lock:
                        self._stats["received_payload_bytes"] += len(raw)
                        self._stats["received_frames"] += 1
                    response = ProcessMessageV1.decode(raw)
                    match_response(response, message, "ready" if message.kind == "load" else "result")
                    values.append(response)
                    with self._stats_lock:
                        self._events.append({"request_id": message.request_id, "kind": message.kind,
                            "worker_index": index, "generation": message.generation,
                            "snapshot_sha256": message.pins.snapshot_sha256,
                            "cell_id": message.payload.get("cell_id"), "rows": message.payload.get("rows", []),
                            "full_bundle_sha256": message.payload.get("full_bundle_sha256"),
                            "feature_bundle_sha256": message.payload.get("features", {}).get("bundle_sha256"),
                            "route_sha256": message.payload.get("route_sha256"),
                            "request_payload_sha256": digest(message.payload),
                            "response_payload_sha256": digest(response.payload),
                            "sent_bytes": len(data), "received_bytes": len(raw)})
                responses[index] = values
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=run, args=(i, messages), daemon=True) for i, messages in encoded.items()]
        deadline = time.monotonic() + self._timeout
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if failures or any(t.is_alive() for t in threads):
            self.close()
            raise ProcessInferenceError("worker failure, invalid response or deadline exceeded") from (failures[0] if failures else None)
        return responses

    def counts(self):
        result = []
        for process, _, counters in self._workers:
            lock = counters.get_lock()
            if not lock.acquire(timeout=min(self._timeout, 0.5)):
                raise ProcessInferenceError("worker counter lock unavailable")
            try:
                values = list(counters)
            finally:
                lock.release()
            result.append({"pid": process.pid, "heads": {cell.cell_id: {
                "example_calls": values[2 * i], "module_forwards": values[2 * i + 1]}
                for i, cell in enumerate(self._snapshot.cells)}, "router_forwards": values[4]})
        return result

    def transport_receipt(self):
        with self._stats_lock:
            return {**self._stats, "events": list(self._events),
                "request_limit_per_worker_including_load": self._request_limit,
                "requests_issued_per_worker": list(self._sequences),
                "framing_bytes": 4 * (self._stats["sent_frames"] + self._stats["received_frames"])}

    def predict_task(self, bundle, *, budget_units=None):
        with self._serial:
            try:
                return self._predict(bundle, budget_units)
            except Exception:
                self.close()
                raise

    def _predict(self, bundle, budget_units):
        started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
        self._guard()
        # Reserve the worst-case selected Cell batches before executing the Router.
        # This may close a pool with spare messages, but never evaluates a route
        # that cannot fit its full dispatch. Load requests consume the same limit.
        capacity = [0] * len(self._workers)
        for index in range(len(self._snapshot.cells)):
            capacity[index % len(self._workers)] += 1
        if any(issued + required > self._request_limit
               for issued, required in zip(self._sequences, capacity, strict=True)):
            raise ProcessInferenceError("worker lifetime request limit exhausted before routing")
        if type(bundle) is not FeatureBundleV1:
            raise ProcessInferenceError("typed features required")
        bundle.require_identity(self._snapshot.identity)
        check_sources(bundle.source_record_digests, bundle.identity, lambda: self._frontier)
        feature_payload(bundle)  # Reject unsupported views/row counts before routing.
        before, transport_before = self.counts(), self.transport_receipt()
        router_count = [0]
        handle = None
        if self._snapshot.router:
            def observe(module, inputs):
                router_count[0] += 1
            handle = self._snapshot.router._net.register_forward_pre_hook(observe)
        try:
            routes = _route(self._snapshot, bundle, budget_units)
        finally:
            if handle:
                handle.remove()
        groups, requested = {}, []
        for index, cell in enumerate(self._snapshot.cells):
            rows = [i for i, row in enumerate(routes) if cell.cell_id in row["selected"]]
            if not rows:
                continue
            worker = index % len(self._workers)
            request = self._message(worker, "infer", {"cell_id": cell.cell_id,
                "full_bundle_sha256": bundle.bundle_digest, "rows": rows,
                "route_sha256": digest(routes), "features": feature_payload(_subset(bundle, rows))})
            groups.setdefault(worker, []).append(request)
            requested.append((cell, worker, request))
        self._guard()
        results = self._exchange(groups)
        by_id = {result.request_id: result for values in results.values() for result in values}
        classes = self._snapshot.cells[0].head.report["config"]["task_count"]
        probabilities = torch.zeros((len(routes), classes), dtype=torch.float64)
        worker_cpu_ns = 0
        for cell, worker, request in requested:
            result = by_id[request.request_id]
            exact_keys(result.payload, ("request_payload_sha256", "probabilities_f64", "cpu_time_ns"))
            if (result.payload["request_payload_sha256"] != digest(request.payload)
                    or type(result.payload["cpu_time_ns"]) is not int
                    or not 0 <= result.payload["cpu_time_ns"] < 2**63):
                raise ProcessInferenceError("result does not match owner feature/selection pins")
            rows = request.payload["rows"]
            values = read_probabilities(result.payload["probabilities_f64"], len(rows), classes)
            worker_cpu_ns += result.payload["cpu_time_ns"]
            for position, row in enumerate(rows):
                probabilities[row] += values[position] / len(routes[row]["selected"])
                routes[row]["actual_calls"].append(cell.cell_id)
                routes[row]["actual_cost_units"] += float(cell.cost_units)
        after = self.counts()
        measured = []
        for worker in range(len(self._workers)):
            for cell in self._snapshot.cells:
                previous, current = before[worker]["heads"][cell.cell_id], after[worker]["heads"][cell.cell_id]
                calls = {k: current[k] - previous[k] for k in current}
                rows = sum(len(r.payload["rows"]) for c, w, r in requested if w == worker and c == cell)
                if calls != {"example_calls": rows, "module_forwards": int(rows > 0)}:
                    raise ProcessInferenceError("independent controller observed unexpected Head calls")
                measured.append({"worker_index": worker, "cell_id": cell.cell_id, **calls})
            if after[worker]["router_forwards"] != before[worker]["router_forwards"]:
                raise ProcessInferenceError("worker executed an unrequested Router")
        router = self._snapshot.router
        temperature = router.report["temperature"] if router else 1.0
        if router:
            probabilities = (probabilities.clamp_min(1e-12).log() / temperature).softmax(-1)
        else:
            probabilities = probabilities.float()
        config = router.report["config"] if router else self._snapshot.cells[0].head.report["config"]
        transport_after = self.transport_receipt()
        # Linearization point: hold the same lock as owner commits through final validation.
        with self._owner._owner._lock:
            self._guard()
            bundle.require_identity(self._snapshot.identity)
            return {"task_probabilities": probabilities,
                "accepted": probabilities.max(-1).values >= config["confidence_threshold"],
                "routes": routes, "snapshot_sha256": self._pins.snapshot_sha256,
                "graph_generation": self._pins.graph_generation, "feature_bundle_sha256": bundle.bundle_digest,
                "source_frontier_sha256": self._pins.frontier_sha256, "controller_head_counts": measured,
                "router_forward_calls": router_count[0],
                "head_example_calls": sum(c["example_calls"] for c in measured),
                "actual_cost_units": sum(r["actual_cost_units"] for r in routes),
                "elapsed_ns": time.perf_counter_ns() - started,
                "owner_cpu_ns": time.process_time_ns() - cpu_started, "worker_cpu_ns": worker_cpu_ns,
                "ipc": {k: transport_after[k] - transport_before[k] for k in self._stats},
                "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}

    def close(self):
        self._closed = True
        for process, connection, _ in self._workers:
            connection.close()
            if process.is_alive():
                process.terminate()
            process.join(0.2)
            if process.is_alive():
                process.kill()
                process.join(2)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
