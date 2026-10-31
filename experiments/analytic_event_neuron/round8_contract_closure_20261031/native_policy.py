"""Public-State client for the real Rust model port and acknowledged native owner.

The unchanged R7 BrokerClient executes the returned action. This adapter does
not read private evidence, compute a transition, run a Q head or choose actions.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import time

from ..round7.task import ACTIONS, features, legal_actions


class NativePolicy:
    def __init__(self, model_path, *, binary, owner_dir, seed=0, head=1,
                 deployment="hard", ack=None, timeout=30.0):
        self.model_path, self.binary = Path(model_path).resolve(), Path(binary).resolve()
        self.owner_dir = Path(owner_dir).resolve()
        self.owner_dir.mkdir(parents=True, exist_ok=True)
        self.seed, self.head, self.deployment = int(seed), int(head), deployment
        self.timeout = timeout
        self.closed = False
        self.child_cpu_seconds = None
        self.peak_rss_kib = None
        self.roundtrip_nanos = 0
        self.ack = ack or "0" * 64
        start = time.perf_counter_ns()
        self.process = subprocess.Popen([str(self.binary), str(self.model_path), str(self.owner_dir),
            str(self.seed), str(self.head), deployment, self.ack], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        try:
            self.ready = self._read()
            if not self.ready.get("ok") or not self.ready.get("ready"):
                raise RuntimeError(self.ready)
            self._state = self.ready["pair"]["state"]
            self.ack = self.ready["pair_after"]
            self.startup_roundtrip_nanos = time.perf_counter_ns() - start
        except BaseException:
            self.close()
            raise

    def _read(self):
        if not select.select([self.process.stdout], [], [], self.timeout)[0]:
            raise TimeoutError("native response deadline")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("native process ended without a response")
        return json.loads(line)

    def request(self, record):
        start = time.perf_counter_ns()
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        self.process.stdin.write(encoded)
        self.process.stdin.flush()
        result = self._read()
        elapsed = time.perf_counter_ns() - start
        self.roundtrip_nanos += elapsed
        result["roundtrip_nanos"] = elapsed
        result["transport_bytes"] = len(encoded.encode())
        return result

    def act(self, state):
        if state.terminated:
            raise ValueError("cannot act on a terminal public state")
        allowed = legal_actions(state)
        request = dict(pair_before=self.ack, sequence=self._state["calls"] + 1,
            features=features(state).tolist(), legal=[a in allowed for a in ACTIONS],
            public_state_sha256=state.digest())
        response = self.request(request)
        if not response.get("ok"):
            raise RuntimeError(response)
        receipt = response["receipt"]
        prediction = receipt["prediction"]
        action = prediction["action"]
        if action not in allowed or receipt["signals_q24"] != [int(a == action) * (1 << 24) for a in ACTIONS] + [0]:
            raise AssertionError("native action/signal/public legality mismatch")
        self._state = dict(calls=request["sequence"], mass=prediction["mass"])
        self.ack = receipt["pair_after"]
        packet = struct.pack("<I5d", self._state["calls"], *prediction["moments"], prediction["event_count"]) + action.encode()
        prediction.update(native_receipt={k: v for k, v in receipt.items() if k != "prediction"},
            kernel_ns=sum(prediction["costs"][key] for key in ("encode_nanos", "cdf_transition_nanos", "ctmc_transition_nanos", "propagate_nanos")),
            prediction_ns=response["roundtrip_nanos"], wire_bytes=len(packet), wire_hex=packet.hex(),
            state_bytes=len(json.dumps(self.snapshot(), sort_keys=True).encode()),
            transport_request_bytes=response["transport_bytes"],
            event_semantics="sampled finite-law model events" if self.deployment == "hard" else "expected finite-law model events",
            wire_semantics="same R7 serialized public packet, local adapter measurement")
        return action, prediction

    def snapshot(self):
        return dict(schema="hepta.r7-native-client.v1", source_digest=self.ready["source_digest"],
            identity=self.ready["pair"]["identity"], calls=self._state["calls"], mass=self._state["mass"],
            acknowledged_pair_sha256=self.ack)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        _, status, usage = os.wait4(self.process.pid, 0)
        self.process.returncode = os.waitstatus_to_exitcode(status)
        self.child_cpu_seconds = usage.ru_utime + usage.ru_stime
        self.peak_rss_kib = usage.ru_maxrss
        self.stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
