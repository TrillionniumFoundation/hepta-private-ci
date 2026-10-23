"""Strict MP1 client; Rust owns selection, budget, execution ACKs and sealing.

The caller owns the gzip text transcript stream. RPC timings exclude neural work;
child CPU comes from wait4 for this PID, while lifetime includes waiting on Python.
This is a research execution bridge, not authentication of remote model execution.
"""

import hashlib
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import time

import numpy as np

from allocation_model import ACTIONS, BUDGET, DECODER_COSTS, EMIT_COST, INIT_COST, REFINE_COST, joint_hash
from model import MODALITIES


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def digests(values):
    if isinstance(values, dict):
        require(tuple(values) == MODALITIES, "ordered four modality labels required")
        values = list(values.values())
    require(len(values) == 4 and all(isinstance(h, str) and re.fullmatch("[0-9a-f]{64}", h)
                                   and h != "0" * 64 for h in values), "four canonical nonzero hashes required")
    return list(values)


class NativeBridge:
    def __init__(self, binary, transcript_stream):
        binary = Path(binary).resolve(strict=True)
        self.binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.binary_path, self.stream = str(binary), transcript_stream
        self.digest, self.sessions, self.completed, self.requests = hashlib.sha256(), 0, 0, 0
        self.rpc_wall, self.rpc_cpu, self.started = 0., 0., time.perf_counter()
        self.current, self.receipt, self.failure = None, None, None
        self.labels, self.stderr = set(), tempfile.TemporaryFile()
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, bufsize=0)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.failure = repr(error)
        try:
            self.close()
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note("Native cleanup: " + str(cleanup))
        return False

    def _log(self, prefix, line):
        text = prefix + line + "\n"
        self.stream.write(text)
        self.stream.flush()
        self.digest.update(text.encode("ascii"))

    def _exchange(self, fields, expected, extras=()):
        require(self.receipt is None, "native process is closed")
        command = "\t".join(map(str, fields))
        payload = (command + "\n").encode("ascii")
        require(len(payload) <= 4096 and "\n" not in command and "\r" not in command, "bounded single request required")
        started, cpu = time.perf_counter(), time.process_time()
        try:
            self._log("> ", command)
            self.requests += 1
            self.process.stdin.write(payload)
            self.process.stdin.flush()
            data, deadline = b"", time.monotonic() + 10
            while not data.endswith(b"\n"):
                timeout = deadline - time.monotonic()
                if timeout <= 0 or not select.select([self.process.stdout], [], [], timeout)[0]:
                    raise TimeoutError("native MP1 response exceeded 10 seconds")
                chunk = os.read(self.process.stdout.fileno(), 4097 - len(data))
                if not chunk:
                    raise RuntimeError("native MP1 closed before its response")
                data += chunk
                require(len(data) <= 4096, "native response exceeds line bound")
            require(data.count(b"\n") == 1 and b"\r" not in data, "one canonical response required")
            line = data[:-1].decode("ascii")
            self._log("< ", line)
            response = line.split("\t")
            prefix = ["MP1", "OK", fields[1], str(expected["wire_session_id"]), str(expected["version"]),
                      str(expected["remaining"]), str(expected["total_refinements"]),
                      *map(str, expected["refinement_counts"]), expected["phase"], expected["joint_hash"]]
            require(len(response) == 13 + len(extras) and response[:13] == prefix,
                    "native response/state mismatch: " + line)
            for actual, wanted in zip(response[13:], extras):
                require(float(actual) == wanted if isinstance(wanted, float) else actual == wanted,
                        "native returned a different action/value/output binding")
            self.current = expected
            return dict(expected, refinement_counts=list(expected["refinement_counts"]))
        finally:
            self.rpc_wall += time.perf_counter() - started
            self.rpc_cpu += time.process_time() - cpu

    @staticmethod
    def _feedback(feedback):
        q, latents = np.asarray(feedback["q"]), np.asarray(feedback["latents"])
        require(q.dtype == np.dtype("<f4") and latents.dtype == np.dtype("<f4")
                and q.shape == (1, 8) and latents.shape == (1, 4, 64)
                and np.isfinite(q).all() and np.isfinite(latents).all(), "finite registered float32 feedback required")
        condition, counts = feedback["condition"], feedback["refinement_counts"]
        require(type(condition) is int and 0 <= condition < 8
                and np.array_equal(q, np.eye(8, dtype=np.float32)[[condition]]), "condition must bind one-hot q")
        hashes = digests(feedback["latent_hashes"])
        require(hashes == [hashlib.sha256(latents[:, m].tobytes()).hexdigest() for m in range(4)]
                and feedback["q_hash"] == hashlib.sha256(q.tobytes()).hexdigest()
                and feedback["joint_hash"] == joint_hash(hashes), "feedback hashes differ from actual tensors")
        require(len(counts) == 4 and all(type(n) is int and 0 <= n <= 2 for n in counts)
                and sum(counts) <= 2 and feedback["sealed"] is False, "unsealed registered counts required")
        depth = sum(counts)
        expected = {"depth": depth, "version": depth, "budget_macs": BUDGET,
                    "spent_macs": INIT_COST + depth * REFINE_COST,
                    "remaining_macs": BUDGET - INIT_COST - depth * REFINE_COST}
        require(all(type(feedback[k]) is int and feedback[k] == v for k, v in expected.items()),
                "feedback budget/version/depth mismatch")
        return hashes

    def _bound(self, sid, feedback, phase, before_emission=False):
        hashes = self._feedback(feedback)
        state = self.current
        require(state is not None and state["session_id"] == sid and state["phase"] == phase,
                "wrong session or execution phase")
        require(feedback["condition"] == self.condition and feedback["q_hash"] == self.q_hash,
                "semantic condition changed during generation")
        offset = int(before_emission)
        require(feedback["version"] + offset == state["version"]
                and feedback["remaining_macs"] - offset * EMIT_COST == state["remaining"]
                and feedback["refinement_counts"] == state["refinement_counts"], "stale feedback ledger")
        return hashes

    def begin(self, sid, feedback, policy_mode, plan=None):
        hashes = self._feedback(feedback)
        plan = () if plan is None else tuple(plan)
        require(isinstance(sid, str) and sid and sid not in self.labels, "unique external session label required")
        require(self.current is None or self.current["phase"] == "sealed", "previous stream is unfinished")
        require(feedback["version"] == 0 and policy_mode in ("ADAPTIVE", "COMMITTED", "CLEAN")
                and len(plan) <= 2 and all(type(m) is int and 0 <= m < 4 for m in plan)
                and (policy_mode == "COMMITTED" or not plan), "registered initial mode/plan required")
        wire = self.sessions + 1
        state = {"session_id": sid, "wire_session_id": wire, "native_session_id": wire, "version": 0,
                 "remaining": BUDGET - INIT_COST, "total_refinements": 0, "refinement_counts": [0] * 4,
                 "phase": "ready", "joint_hash": joint_hash(hashes)}
        token = ",".join(ACTIONS[m + 1] for m in plan) or "-"
        result = self._exchange(["MP1", "INIT", wire, feedback["condition"], feedback["q_hash"], BUDGET,
                                 INIT_COST, 2, *DECODER_COSTS, *([REFINE_COST] * 4), *hashes, policy_mode, token], state)
        self.sessions += 1
        self.labels.add(sid)
        self.hashes, self.condition, self.q_hash = hashes, feedback["condition"], feedback["q_hash"]
        self.mode, self.plan = policy_mode, plan
        return result

    def choose(self, sid, feedback, decision):
        hashes = self._bound(sid, feedback, "ready")
        require(hashes == self.hashes and feedback["joint_hash"] == self.current["joint_hash"], "stale latent snapshot")
        depth = self.current["total_refinements"]
        eligible = np.array([True, *([depth < 2 and self.current["remaining"] >= REFINE_COST + EMIT_COST] * 4)])
        if self.mode != "ADAPTIVE":
            eligible[:] = False
            eligible[self.plan[depth] + 1 if self.mode == "COMMITTED" and depth < len(self.plan) else 0] = True
        scores, declared = np.asarray(decision["scores"]), np.asarray(decision["eligible"])
        require(scores.dtype == np.float64 and scores.shape == (5,) and np.isfinite(scores).all()
                and declared.dtype == np.bool_ and np.array_equal(declared, eligible)
                and np.all(scores[~eligible] == 0), "complete finite utility table with exact eligibility required")
        selected = int(np.flatnonzero(eligible)[0])
        for action in range(5):
            if eligible[action] and scores[action] > scores[selected] + 1e-12:
                selected = action
        require(type(decision["action"]) is int and decision["action"] == selected, "Python action differs from canonical utility choice")
        costs = [EMIT_COST, *([REFINE_COST] * 4)]
        expected = dict(self.current, refinement_counts=list(self.current["refinement_counts"]))
        expected.update(version=expected["version"] + 1, remaining=expected["remaining"] - costs[selected],
                        phase="await_outputs" if selected == 0 else "await_refinement")
        if selected:
            expected["refinement_counts"][selected - 1] += 1
            expected["total_refinements"] += 1
        entries = [item for a in range(5) for item in (ACTIONS[a], repr(float(scores[a])), costs[a])]
        result = self._exchange(["MP1", "CHOOSE", expected["wire_session_id"], feedback["version"],
                                 feedback["joint_hash"], *entries], expected, (ACTIONS[selected], float(scores[selected])))
        self.selected = selected
        return dict(result, action=selected, action_name=ACTIONS[selected], value=float(scores[selected]))

    def refined(self, sid, feedback):
        hashes = self._bound(sid, feedback, "await_refinement")
        require(all(hashes[m] == self.hashes[m] for m in range(4) if m != self.selected - 1),
                "unselected modality changed during execution")
        expected = dict(self.current, phase="ready", joint_hash=joint_hash(hashes))
        result = self._exchange(["MP1", "REFINED", expected["wire_session_id"], expected["version"],
                                 ACTIONS[self.selected], *hashes], expected)
        self.hashes = hashes
        return result

    def emitted(self, sid, feedback, output_hashes):
        hashes = self._bound(sid, feedback, "await_outputs", before_emission=True)
        require(hashes == self.hashes and feedback["joint_hash"] == self.current["joint_hash"], "emitted latent snapshot changed")
        outputs = digests(output_hashes)
        fields = [item for name, value in zip(MODALITIES, outputs) for item in (name, value)]
        expected = dict(self.current, phase="sealed")
        result = self._exchange(["MP1", "EMITTED", expected["wire_session_id"], expected["version"],
                                 expected["joint_hash"], *fields], expected, (*fields, joint_hash(outputs, "outputs")))
        self.completed += 1
        return dict(result, output_hashes=dict(zip(MODALITIES, outputs)), output_joint_hash=joint_hash(outputs, "outputs"))

    def close(self):
        if self.receipt is not None:
            return self.receipt
        self.process.stdin.close()
        deadline, terminated = time.monotonic() + 10, False
        while True:
            pid, status, usage = os.wait4(self.process.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() > deadline:
                self.process.kill()
                pid, status, usage = os.wait4(self.process.pid, 0)
                terminated = True
                break
            time.sleep(.01)
        self.process.returncode = os.waitstatus_to_exitcode(status)
        self.process.stdout.close()
        self.stderr.seek(0)
        stderr = self.stderr.read().decode("utf-8", errors="replace")
        self.stderr.close()
        self.stream.flush()
        self.receipt = {"sessions": self.sessions, "completed_sessions": self.completed, "requests": self.requests,
                        "transcript_sha256": self.digest.hexdigest(), "binary_path": self.binary_path,
                        "binary_sha256": self.binary_sha256, "rpc_wall_seconds": self.rpc_wall,
                        "rpc_python_cpu_seconds": self.rpc_cpu, "native_user_cpu_seconds": usage.ru_utime,
                        "native_system_cpu_seconds": usage.ru_stime, "native_lifetime_wall_seconds": time.perf_counter() - self.started,
                        "exit_code": self.process.returncode, "stderr": stderr, "terminated_after_timeout": terminated,
                        "caller_failure": self.failure, "timing_scope": "lifetime includes caller work; RPC excludes neural kernels; CPU is this native PID only"}
        require(not terminated and self.process.returncode == 0 and self.sessions == self.completed,
                "native process did not finish sealed sessions: " + stderr)
        return self.receipt
