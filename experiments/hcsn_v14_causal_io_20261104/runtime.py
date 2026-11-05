"""Durable single-session READ/RESET with bounded exact content retrieval.

SQLite serializes writers. The pure core transition and its accepted content
commit together. External read transport must reuse read_id after recovery;
this is not a claim of exactly-once external I/O or cross-machine failover.
"""

from contextlib import contextmanager
import json
import sqlite3

from .boundary import BoundaryError, MODALITIES, canonical, digest, identity, integer, sha256


class Session:
    def __init__(self, path, frozen, core, session_id, source_clock_id,
                 memory_bytes=65536, max_operations=4096):
        identity(session_id); identity(source_clock_id); sha256(core.model_id)
        integer(memory_bytes, 1); integer(max_operations, 1)
        if not any(s["session_id"] == session_id and s["clock_id"] == source_clock_id
                   for s in frozen.sources.values()):
            raise BoundaryError("Session/clock absent from input freeze")
        self.frozen, self.core = frozen, core
        self._identity = {"schema": "hcsn-v14-session.v1", "input": frozen.sha256,
                         "model": core.model_id, "execution": getattr(core, "execution_id", core.model_id),
                         "session": session_id, "source_clock": source_clock_id,
                         "arrival_clock": frozen.arrival_clock_id, "memory_bytes": memory_bytes,
                         "max_operations": max_operations}
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT, sha TEXT)")
        try:
            with self.transaction() as state:
                if not state:
                    state.update(identity=self.identity, epoch=0, last_ns=0, frontier_ns=0, charge_units=0,
                                 operations={}, content={}, content_bytes=0, watermarks={}, core=core.initial())
                if state["identity"] != self.identity:
                    raise BoundaryError("Restart requires identical input/model/session/clock/budget identity")
                core.output(state["core"])
        except BaseException:
            self.db.close()
            raise

    @property
    def identity(self):
        return json.loads(canonical(self._identity))

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT body,sha FROM snapshot WHERE id=1").fetchone()
            state = {} if row is None else json.loads(row[0])
            if row is not None and digest(state) != row[1]:
                raise BoundaryError("Persisted snapshot integrity mismatch")
            if state and state["identity"] != self._identity:
                raise BoundaryError("Persisted session identity changed")
            yield state
            body = canonical(state).decode("utf-8")
            self.db.execute("INSERT OR REPLACE INTO snapshot VALUES(1,?,?)", (body, digest(state)))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _clock(self, state, now_ns):
        integer(now_ns)
        if now_ns < state["last_ns"]:
            raise BoundaryError("Arrival clock regressed")
        state["last_ns"] = now_ns

    def _room(self, state):
        if len(state["operations"]) >= self.identity["max_operations"]:
            raise BoundaryError("Durable operation budget exhausted; roll to a new session explicitly")

    def issue(self, read_id, source_id, modality, start_ns, end_ns, now_ns, cost_units=1):
        identity(read_id); integer(start_ns); integer(end_ns); integer(now_ns); integer(cost_units)
        source = self.frozen.sources.get(source_id)
        if (source is None or source["session_id"] != self.identity["session"]
                or source["clock_id"] != self.identity["source_clock"]
                or modality not in MODALITIES or modality not in source["encoders"]
                or not start_ns < end_ns <= source["max_end_ns"]):
            raise BoundaryError("READ outside frozen source/session/encoder/window")
        request = {"kind": "READ", "source_id": source_id, "modality": modality,
                   "start_ns": start_ns, "end_ns": end_ns, "cost_units": cost_units}
        with self.transaction() as state:
            previous = state["operations"].get(read_id)
            if previous is not None:
                if previous["request"] != request:
                    raise BoundaryError("Idempotency key reused with different operation")
                return json.loads(canonical(previous))
            self._clock(state, now_ns); self._room(state)
            key = source_id+":"+modality
            if start_ns < state["watermarks"].get(key, 0):
                raise BoundaryError("READ overlaps previously accepted interval")
            if any(op["request"]["kind"] == "READ" and op["state"] == "pending"
                   and op["request"]["source_id"] == source_id and op["request"]["modality"] == modality
                   for op in state["operations"].values()):
                raise BoundaryError("One pending read per source modality")
            op = {"request": request, "epoch": state["epoch"], "issued_ns": now_ns, "state": "pending"}
            state["operations"][read_id] = op
            state["charge_units"] += cost_units
            return json.loads(canonical(op))

    def complete(self, read_id, packet, now_ns):
        integer(now_ns)
        source = self.frozen.verify(packet)
        payload = packet.document()
        fingerprint = digest(payload)
        with self.transaction() as state:
            op = state["operations"].get(read_id)
            if op is None or op["request"]["kind"] != "READ":
                raise BoundaryError("Completion has no issued READ")
            if op["state"] == "done":
                if op["packet_sha256"] != fingerprint:
                    raise BoundaryError("Same READ completed with different bytes")
                return json.loads(canonical(op["receipt"]))
            if op["state"] != "pending" or op["epoch"] != state["epoch"]:
                raise BoundaryError("Late completion belongs to a previous RESET epoch")
            request = op["request"]
            if any(payload[k] != request[k] for k in ("source_id", "modality", "start_ns", "end_ns")):
                raise BoundaryError("Completion differs from requested source or window")
            self._clock(state, now_ns)
            if now_ns < op["issued_ns"]:
                raise BoundaryError("Completion precedes issue")
            release = source["release_offset_ns"]+packet.end_ns+source["sync_uncertainty_ns"]
            if packet.status == "ok" and now_ns < release:
                raise BoundaryError("Source samples have not conservatively reached the arrival clock")
            address = None
            if packet.status == "ok":
                key = packet.source_id+":"+packet.modality
                if packet.start_ns < state["watermarks"].get(key, 0):
                    raise BoundaryError("Completion overlaps accepted source time")
                next_frontier = max(state["frontier_ns"], packet.end_ns)
                next_core = self.core.step(state["core"], packet, next_frontier-state["frontier_ns"])
                canonical(next_core)
                address = digest({"packet": fingerprint, "epoch": state["epoch"], "read_id": read_id})
                stored = {"packet": payload, "packet_sha256": fingerprint, "epoch": state["epoch"],
                          "read_id": read_id, "accepted_ns": now_ns}
                size = len(canonical(stored))
                if state["content_bytes"]+size > self.identity["memory_bytes"]:
                    raise BoundaryError("Addressable content capacity exceeded")
                state["content"][address] = stored
                state["content_bytes"] += size
                state["core"] = next_core
                state["frontier_ns"] = next_frontier
                state["watermarks"][key] = packet.end_ns
            receipt = {"status": packet.status, "address": address, "read_id": read_id,
                       "epoch": state["epoch"], "packet_sha256": fingerprint}
            op.update(state="done", packet_sha256=fingerprint, receipt=receipt)
            return json.loads(canonical(receipt))

    def reset(self, action_id, now_ns, cost_units=1):
        identity(action_id); integer(now_ns); integer(cost_units)
        request = {"kind": "RESET", "cost_units": cost_units}
        with self.transaction() as state:
            previous = state["operations"].get(action_id)
            if previous is not None:
                if previous["request"] != request:
                    raise BoundaryError("Idempotency key reused with different RESET")
                return json.loads(canonical(previous))
            self._clock(state, now_ns); self._room(state)
            state["epoch"] += 1
            state["core"] = self.core.initial()
            state["charge_units"] += cost_units
            for op in state["operations"].values():
                if op["state"] == "pending":
                    op["state"] = "cancelled_by_reset"
            result = {"request": request, "epoch": state["epoch"], "state": "done", "issued_ns": now_ns}
            state["operations"][action_id] = result
            return json.loads(canonical(result))

    def query(self, address):
        sha256(address)
        with self.transaction() as state:
            item = state["content"].get(address)
            if item is None:
                return {"status": "unknown", "text": None, "citation": None}
            if digest(item["packet"]) != item["packet_sha256"]:
                raise BoundaryError("Stored content differs from accepted bytes")
            packet = item["packet"]
            return {"status": "ok", "text": packet["content"], "citation": {
                "address": address, "source_id": packet["source_id"], "source_sha256": packet["source_sha256"],
                "encoder_sha256": packet["encoder_sha256"], "clock_id": packet["clock_id"],
                "start_ns": packet["start_ns"], "end_ns": packet["end_ns"],
                "epoch": item["epoch"], "read_id": item["read_id"], "packet_sha256": item["packet_sha256"]}}

    def output(self):
        with self.transaction() as state:
            return json.loads(canonical(self.core.output(state["core"])))

    def receipt(self):
        with self.transaction() as state:
            return {"identity": self.identity, "epoch": state["epoch"], "charge_units": state["charge_units"],
                    "operations": len(state["operations"]), "content_items": len(state["content"]),
                    "content_bytes": state["content_bytes"], "frontier_ns": state["frontier_ns"],
                    "state_sha256": digest(state), "pending_read_ids": sorted(
                        k for k, op in state["operations"].items() if op["state"] == "pending"),
                    **self.frozen.claims()}

    def close(self):
        self.db.close()
