"""A subprocess owns private data and releases only actually acquired readbacks."""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from ..round4.runtime_evidence import acquire, acquire_wait, transport
from ..round4.runtime_owner import validate_public


SCHEMA = "hepta.acquired-feedback-broker.v6"
LIMIT = 65536
LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def durable_readback(delivery, start):
    """Add explicit durability and byte reread after inherited transport decode."""
    records = delivery.receipts[start:]
    directories = {delivery.root, *list(delivery.root.parents)[:3]}
    for record in records:
        pairs = (("path", "sha256"),) if record["kind"] == "observation" else (
            ("text_path", "text_sha256"), ("image_path", "image_sha256"))
        for key, expected in pairs:
            path = delivery.root / record[key]
            if path.is_symlink() or not path.resolve().is_relative_to(delivery.root.resolve()):
                raise ValueError("Unsafe transport artifact")
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
                if hashlib.sha256(stream.read()).hexdigest() != record[expected]:
                    raise ValueError("Transport artifact changed before durable readback")
            directories.add(path.parent)
    for directory in sorted(directories):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return records, time.perf_counter_ns()


class Rejected(ValueError):
    """A protocol/domain refusal before task state or transport mutation."""


class Environment:
    """Lives only in the broker subprocess; no private value enters responses."""
    def __init__(self, data_path, root, scope):
        import numpy as np
        original = data_path.read_bytes()
        with np.load(io.BytesIO(original), allow_pickle=False) as source:
            self.data = {key: source[key].copy() for key in source.files}
        required = {"initial_output", "self_evaluation", "wait_evaluation", "sensor_variance",
                    "wait_variance", "repair_cost", "wait_cost", "target", "ids"}
        if not required.issubset(self.data) or not LABEL.fullmatch(scope):
            raise ValueError("Missing environment data or invalid scope")
        n = len(self.data["ids"])
        if not 1 <= n <= 1000000 or any(self.data[k].shape != (n,) for k in required):
            raise ValueError("Invalid environment row shape")
        if any(not np.isfinite(self.data[k]).all() for k in required - {"ids"}):
            raise ValueError("Nonfinite environment values")
        if any(np.any(self.data[k] <= 0) for k in ("sensor_variance", "wait_variance", "repair_cost", "wait_cost")):
            raise ValueError("Environment costs and variances must be positive")
        self.data["ids"] = np.asarray(["broker6:" + digest([scope, i])[:24] for i in range(n)])
        self.root, self.scope, self.state, self.delivery = root, scope, None, None
        self.used, self.finished, self.failed, self.previous = set(), 0, False, "0" * 64
        self.transcript = root / "BROKER_TRANSCRIPT.jsonl"
        self.transcript.touch(exist_ok=False)
        append(root / "BROKER_START.jsonl", {"schema": SCHEMA, "pid": os.getpid(), "rows": n,
            "data_sha256": hashlib.sha256(original).hexdigest(),
            "same_uid_hostile_isolation_claimed": False, "private_targets_returned": False})

    def handle(self, request):
        op = request.get("op")
        fields = {"start": {"id", "op", "index", "arm"}, "wait": {"id", "op"},
                  "finish": {"id", "op", "choice", "repair_amount"}, "close": {"id", "op"}}
        if not isinstance(op, str) or op not in fields or set(request) != fields[op]:
            raise Rejected("Exact operation fields required")
        if op == "close":
            return {"complete": not self.failed and (self.state is None or self.state["phase"] == "terminal"),
                    "finished_cases": self.finished}, []
        if self.failed:
            raise Rejected("Broker failed; retained partial evidence requires separate recovery")
        if op == "start":
            i, arm = request["index"], request["arm"]
            if (type(i) is not int or not 0 <= i < len(self.data["ids"])
                    or not isinstance(arm, str) or not LABEL.fullmatch(arm)
                    or (i, arm) in self.used or (self.state is not None and self.state["phase"] != "terminal")):
                raise Rejected("Invalid, duplicate, or unfinished case")
            case_dir = self.root / "cases" / digest([self.scope, i, arm])[:32]
            case_dir.mkdir(parents=True, exist_ok=False)
            self.delivery = transport(case_dir, self.scope)
            public = acquire(self.data, i, arm, self.delivery)
            validate_public(public)
            records, timestamp = durable_readback(self.delivery, 0)
            self.state = {"index": i, "arm": arm, "case_id": str(self.data["ids"][i]),
                          "case_dir": str(case_dir), "phase": "observed", "public": public,
                          "cost": 0.0, "durable_readback_ns": timestamp}
            self.used.add((i, arm))
            return {"public": public, "case_id": self.state["case_id"], "case_dir": str(case_dir)}, records
        if self.state is None or self.state["phase"] == "terminal":
            raise Rejected("An active nonterminal case is required")
        s, start = self.state, len(self.delivery.receipts)
        if op == "wait":
            if s["phase"] != "observed":
                raise Rejected("Paid wait is available exactly once")
            public = acquire_wait(self.data, s["index"], s["arm"], self.delivery, s["public"])
            validate_public(public)
            records, timestamp = durable_readback(self.delivery, start)
            s.update(public=public, cost=s["cost"] + public["wait_cost"], phase="waited", durable_readback_ns=timestamp)
            return {"public": public}, records
        choice, amount = request["choice"], request["repair_amount"]
        if (choice not in ("stop", "repair") or type(amount) not in (int, float)
                or not math.isfinite(amount) or abs(amount) > 8 or (choice == "stop" and amount != 0)):
            raise Rejected("A terminal choice and finite repair amount within [-8,8] are required")
        value = s["public"]["initial"] + amount
        if not math.isfinite(value):
            raise Rejected("Final output must be finite")
        delivered = self.delivery.deliver(s["case_id"], s["arm"], "final", value, choice)
        records, timestamp = durable_readback(self.delivery, start)
        cost = s["cost"] + (s["public"]["repair_cost"] if choice == "repair" else 0)
        cost_receipt = self.delivery.save_receipts()
        with Path(cost_receipt["receipt_path"]).open("rb") as stream:
            os.fsync(stream.fileno())
            if hashlib.sha256(stream.read()).hexdigest() != cost_receipt["receipt_sha256"]:
                raise ValueError("Final transport receipt changed")
        result = {"delivered": delivered, "cost": cost, "transport": cost_receipt,
                  "final_readback_ns": timestamp}
        s.update(phase="terminal", cost=cost, choice=choice, repair_amount=amount,
                 result=result, durable_readback_ns=timestamp)
        self.finished += 1
        return result, records

    def dispatch(self, request):
        before, records = digest(self.state), []
        try:
            result, records = self.handle(request)
            response = {"id": request["id"], "ok": True, "result": result}
        except Rejected as error:
            response = {"id": request.get("id"), "ok": False, "error": str(error), "fatal": False}
        except Exception:
            self.failed = True
            response = {"id": request.get("id"), "ok": False, "error": "Broker I/O or environment failure; partial evidence retained", "fatal": True}
        response["state_sha256"] = digest(self.state)
        valid = response["ok"]
        record = {"schema": SCHEMA, "request_id": request.get("id"), "operation": request.get("op"),
                  "request": request if valid else {"sha256": digest(request), "keys": sorted(request)},
                  "response": response, "state_before_sha256": before, "state_after_sha256": digest(self.state),
                  "state": self.state, "transport_records": records, "previous_sha256": self.previous,
                  "recorded_ns": time.perf_counter_ns()}
        record["sha256"] = digest(record)
        append(self.transcript, record)
        if valid and self.state is not None and request["op"] != "close":
            append(Path(self.state["case_dir"]) / "PUBLIC_TRANSITIONS.jsonl", record)
        self.previous = record["sha256"]
        return response


class Broker:
    """Policy-side protocol client: it never opens or loads the data file."""
    def __init__(self, data_path, work_root, scope):
        self.root = Path(work_root).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.stderr = (self.root / "BROKER.stderr.log").open("xb")
        self.sequence, self.closed, self.case_dir, self.case_id = 0, False, None, None
        self.process = subprocess.Popen([sys.executable, "-m", __name__, "--data", str(Path(data_path).resolve()),
            "--root", str(self.root), "--scope", scope], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.stderr, text=True, bufsize=1)
        ready = self.process.stdout.readline(LIMIT)
        if not ready or json.loads(ready) != {"schema": SCHEMA, "pid": self.process.pid, "ready": True}:
            self.process.wait(timeout=10)
            self.stderr.close()
            raise RuntimeError("Broker startup failed; stderr retained")

    def request(self, operation, **fields):
        if self.closed:
            raise RuntimeError("Broker client is closed")
        if {"id", "op"}.intersection(fields):
            raise ValueError("Protocol identifiers are client-owned")
        next_sequence = self.sequence + 1
        payload = json.dumps({"id": next_sequence, "op": operation, **fields}, allow_nan=False) + "\n"
        if len(payload.encode()) > LIMIT:
            raise ValueError("Broker request exceeds protocol bound")
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        self.sequence = next_sequence
        line = self.process.stdout.readline(LIMIT)
        if not line or not line.endswith("\n"):
            raise RuntimeError("Broker response incomplete; evidence retained")
        response = json.loads(line)
        if response.get("id") != self.sequence:
            raise RuntimeError("Broker response sequence mismatch")
        self.last_response = response
        if not response["ok"]:
            raise Rejected(response["error"])
        return response["result"]

    def start(self, index, arm):
        result = self.request("start", index=index, arm=arm)
        self.case_dir, self.case_id = Path(result["case_dir"]), result["case_id"]
        validate_public(result["public"])
        return result["public"]

    def wait(self):
        result = self.request("wait")["public"]
        validate_public(result)
        return result

    def finish(self, choice, repair_amount=0.0):
        return self.request("finish", choice=choice, repair_amount=repair_amount)

    def close(self):
        if self.closed:
            return self.close_receipt
        self.close_receipt = self.request("close")
        self.process.stdin.close()
        code = self.process.wait(timeout=10)
        self.process.stdout.close()
        self.stderr.close()
        self.closed = True
        if code:
            raise RuntimeError("Broker process failed")
        return self.close_receipt

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def serve(data_path, root, scope):
    environment = Environment(Path(data_path), Path(root), scope)
    print(json.dumps({"schema": SCHEMA, "pid": os.getpid(), "ready": True}), flush=True)
    expected = 1
    while line := sys.stdin.readline(LIMIT + 1):
        if len(line.encode()) > LIMIT or not line.endswith("\n"):
            raise ValueError("Bounded complete broker requests required")
        request = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        if not isinstance(request, dict) or type(request.get("id")) is not int or request["id"] != expected:
            raise ValueError("Monotone broker request identity required")
        expected += 1
        response = environment.dispatch(request)
        print(json.dumps(response, allow_nan=False), flush=True)
        if request.get("op") == "close" and response["ok"]:
            return
    raise RuntimeError("Broker input ended without explicit close")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--scope", required=True)
    arguments = parser.parse_args()
    serve(arguments.data, arguments.root, arguments.scope)
