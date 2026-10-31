"""Actual executable transport; task outcomes checked against public Python contract."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "value"))
from task import Config, Packet, State, execute, initial, legal, posterior
from oracle import choose

ZERO = "0" * 64
PARAMETERS = [.2, -.3, .4, -.1, .5, .2, .4, -.2, .3, .5, -.1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n")


def config_from_dict(value):
    return Config(**{**value, "packets": tuple(Packet(**p) for p in value["packets"])})


def policy_from_entries(entries):
    return lambda c, s: choose(entries[s.key], legal(c, s))


class Client:
    def __init__(self, binary, model, root, acknowledgement):
        self.proc = subprocess.Popen([str(binary), str(model), str(root), acknowledgement],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1)

    def request(self, data):
        self.proc.stdin.write(json.dumps(data) + "\n")
        self.proc.stdin.flush()
        ready, _, _ = select.select([self.proc.stdout], [], [], 30)
        if not ready:
            self.proc.terminate()
            raise TimeoutError("native request exceeded 30 seconds")
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(self.proc.stderr.read())
        return json.loads(line)

    def close(self):
        self.proc.stdin.close()
        _, status, usage = os.wait4(self.proc.pid, 0)
        self.proc.returncode = os.waitstatus_to_exitcode(status)
        error = self.proc.stderr.read()
        self.proc.stdout.close()
        self.proc.stderr.close()
        if self.proc.returncode:
            raise RuntimeError((self.proc.returncode, error))
        return {"child_cpu_seconds": usage.ru_utime + usage.ru_stime,
                "peak_rss_kib": usage.ru_maxrss}


def model_config(task, payloads, entries, family, weights, seed):
    return {"parameters": PARAMETERS, "family": family, "seed_hex": f"{seed:016x}",
            "content_model": str(weights), "content_model_sha256": sha(weights),
            "tick_micros": 50_000, "task": task.to_dict(), "payloads": payloads,
            "policy": {"kind": "q_table", "entries": entries}}


def check_public(expected, actual):
    left, right = asdict(expected), dict(actual)
    error = abs(left.pop("paid_cost") - right.pop("paid_cost"))
    if left != right or error > 2e-12:
        raise AssertionError({"expected": asdict(expected), "actual": actual, "cost_error": error})
    return error


def run_owner(binary, model_path, root, task, world, policy, *, restart=False,
              forced_first=None, start=None, acknowledgement=ZERO, only_steps=None):
    root.mkdir(parents=True, exist_ok=True)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    client = Client(binary, model_path, root, acknowledgement)
    state = initial(task) if start is None else start
    prefix_cost = state.paid_cost
    trace, children = [], []
    try:
        snapshot = client.request({"operation": "snapshot"})
        if not snapshot.get("ok"):
            raise AssertionError(snapshot)
        check_public(state, snapshot["state"])
        for step in range(task.deadline + 2):
            requested = forced_first if step == 0 and forced_first is not None else policy(task, state)
            command = {"operation": "decide", "task_before": acknowledgement}
            if step == 0 and forced_first is not None:
                command["requested"] = forced_first
            response = client.request(command)
            if not response.get("ok"):
                raise AssertionError(response)
            receipt = response["receipt"]
            state, expected = execute(task, state, world, requested)
            check_public(state, receipt["state"])
            for key in ("requested", "actual", "read_attempted", "observation", "cost"):
                if key == "cost":
                    assert abs(expected[key] - receipt[key]) < 2e-12
                else:
                    assert expected[key] == receipt[key], (expected, receipt)
            assert abs(posterior(task, state) - receipt["posterior"]) < 2e-14
            if receipt["actual"] == "STOP":
                assert receipt["inner"] is None
            else:
                assert receipt["inner"]["cell"]["sequence"] == state.clock
                assert receipt["inner"]["native_physics_executed"]
            acknowledgement = receipt["task_after"]
            trace.append(receipt)
            if state.terminated or (only_steps and len(trace) >= only_steps):
                break
            if restart and step == 0:
                children.append(client.close())
                client = Client(binary, model_path, root, acknowledgement)
    finally:
        children.append(client.close())
    quality = int(state.answer == world.truth) if state.terminated else None
    return {"state": asdict(state), "quality": quality,
            "utility": quality - (state.paid_cost-prefix_cost) if quality is not None else None,
            "task_cost": state.paid_cost-prefix_cost, "clock": state.clock,
            "reads": state.next_packet, "trace": trace, "task_after": acknowledgement,
            "cpu_seconds": time.process_time()-start_cpu + sum(c["child_cpu_seconds"] for c in children),
            "wall_seconds": time.perf_counter()-start_wall,
            "peak_child_rss_kib": max(c["peak_rss_kib"] for c in children),
            "processes": len(children)}
