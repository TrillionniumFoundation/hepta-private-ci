"""JSONL subprocess boundary and actual artifact IO for the finite evidence task.

The policy receives public responses only. This is an interface separation, not
an OS sandbox against arbitrary code capable of opening the artifact directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .task import TaskParameters, generate_episode, initial_state, legal_actions, step


SOURCE_BYTES = 256


def _encoded_source(source_id, vote, reliability):
    body = json.dumps({"source_id": source_id, "vote": vote, "reliability": reliability},
                      sort_keys=True, separators=(",", ":")).encode()
    if len(body) > SOURCE_BYTES:
        raise ValueError("source exceeds its fixed storage bound")
    return body.ljust(SOURCE_BYTES, b" ")


class ArtifactWorker:
    """Own private fixtures and expose only explicitly permitted operations."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.episode = None
        self.state = None
        self.session = None
        self.folder = None
        self.failed = False

    def handle(self, request):
        start = time.perf_counter()
        operation = request.get("op")
        if operation == "start":
            result = self._start(request)
        elif operation == "step":
            result = self._step(request)
        elif operation == "close":
            result = {"ok": True, "closed": True}
        else:
            raise ValueError("unsupported broker operation")
        result["worker_seconds"] = time.perf_counter() - start
        return result

    def _start(self, request):
        if self.state is not None and not self.state.terminated and not self.failed:
            raise ValueError("finish the active task before starting another")
        p = TaskParameters(**request.get("parameters", {}))
        episode = generate_episode(request["seed"], p)
        session = "session_" + uuid.uuid4().hex
        folder = self.root / session
        folder.mkdir()
        for index, vote in enumerate(episode.ordinary_votes):
            (folder / f"ordinary_{index}.json").write_bytes(
                _encoded_source(f"ordinary/{index}", vote, p.ordinary_reliability))
        delayed = (_encoded_source("delayed/0", episode.delayed_vote, p.delayed_reliability)
                   if not episode.delayed_corrupt else b'{"unreadable":'.ljust(SOURCE_BYTES, b" "))
        (folder / "delayed_0.json").write_bytes(delayed)
        self.episode, self.state, self.session, self.folder = episode, initial_state(episode), session, folder
        self.failed = False
        # No unread digest, varying payload length, private source, or damage flag.
        return {"ok": True, "session": session, "state": self.state.to_dict(),
                "legal_actions": list(legal_actions(self.state)),
                "setup_source_files": p.ordinary_count + 1,
                "setup_source_bytes": SOURCE_BYTES * (p.ordinary_count + 1)}

    def _step(self, request):
        if self.state is None or self.state.terminated or self.failed:
            raise ValueError("no active task")
        previous = self.state
        result = step(previous, request["action"], self.episode)
        io_start = time.perf_counter()
        reads = []
        written = 0
        read_bytes = 0
        phase = "source_readback"
        try:
            if result.info["executed_action"] == "REPAIR":
                phase = "repair_write"
                payload = _encoded_source("delayed/0", self.episode.delayed_vote,
                                          self.episode.parameters.delayed_reliability)
                written += (self.folder / "delayed_0.json").write_bytes(payload)
            for observation in result.info["new_observations"]:
                phase = "source_readback"
                source_id = observation["source_id"]
                filename = source_id.replace("/", "_") + ".json"
                payload = (self.folder / filename).read_bytes()
                read_bytes += len(payload)
                parsed = json.loads(payload)
                expected = {key: observation[key] for key in ("source_id", "vote", "reliability")}
                if parsed != expected:
                    raise ValueError("source readback does not match the task fixture")
                reads.append({"source_id": source_id, "bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest(), "verified": True})
        except (OSError, ValueError) as error:
            return self._failure(result, error, phase, io_start, read_bytes, written)
        self.state = result.state
        response = {"ok": True, "session": self.session, **result.to_dict()}
        response["info"]["broker_io"] = {
            "source_reads": reads, "source_bytes_read": read_bytes,
            "source_bytes_written": written, "source_io_seconds": time.perf_counter() - io_start,
        }
        if result.done:
            output = {
                "schema": "hepta.round7.artifact-output.v1", "answer": result.state.answer,
                "posterior_at_commit": previous.posterior, "tick": result.state.tick,
                "remaining_budget": result.state.remaining_budget,
                "observed_source_ids": list(result.state.observed_source_ids),
                "terminal_quality": result.info["terminal_quality"],
                "total_modeled_cost": result.state.total_cost,
                "utility": result.info["terminal_quality"] - result.state.total_cost,
                "terminal_state_digest": result.state.digest(),
            }
            payload = (json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n").encode()
            temporary = self.folder / "output.json.tmp"
            destination = self.folder / "output.json"
            artifact_written = 0
            artifact_read = 0
            artifact_start = time.perf_counter()
            phase = "terminal_write"
            try:
                artifact_written = temporary.write_bytes(payload)
                phase = "terminal_commit"
                temporary.replace(destination)
                phase = "terminal_readback"
                readback = destination.read_bytes()
                artifact_read = len(readback)
                if readback != payload or json.loads(readback) != output:
                    raise ValueError("terminal artifact readback failed")
            except (OSError, ValueError) as error:
                failure = self._failure(result, error, phase, io_start, read_bytes, written)
                failure.update(incurred_artifact_bytes_written=artifact_written,
                               incurred_artifact_bytes_read=artifact_read)
                return failure
            response["artifact"] = {"path": str(destination), "bytes": len(readback),
                                    "sha256": hashlib.sha256(readback).hexdigest(),
                                    "server_readback_verified": True, "output": output,
                                    "artifact_io_seconds": time.perf_counter() - artifact_start}
        return response

    def _failure(self, result, error, phase, started, read_bytes, written_bytes):
        # Work was incurred before the error. Invalidate the entire session.
        self.state = result.state
        self.failed = True
        return {"ok": False, "error": type(error).__name__ + ": artifact IO failed",
                "operational_failure": True, "failed_phase": phase,
                "incurred_modeled_cost": result.cost,
                "incurred_budget_debit": result.info["costs"]["budget_debit"],
                "incurred_source_bytes_read": read_bytes,
                "incurred_source_bytes_written": written_bytes,
                "incurred_io_seconds": time.perf_counter() - started,
                "byte_counts_are_acknowledged_only": True,
                "partial_failed_write_bytes_unknown": isinstance(error, OSError) and "write" in phase,
                "retry_allowed": False, "session": self.session}


class BrokerClient:
    """Synchronous JSONL client; policies must only receive its public state fields."""

    def __init__(self, artifact_root):
        self.root = Path(artifact_root).resolve()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "experiments.analytic_event_neuron.round7.broker",
             "--worker", "--root", str(self.root)],
            cwd=str(Path(__file__).resolve().parents[3]), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

    def request(self, record):
        started = time.perf_counter()
        encoded = json.dumps(record, allow_nan=False) + "\n"
        self.process.stdin.write(encoded)
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("broker exited without a JSONL response")
        response = json.loads(line)
        response["transport_bytes"] = {"request_utf8": len(encoded.encode("utf-8")),
                                       "response_utf8": len(line.encode("utf-8"))}
        if response.get("artifact") is not None:
            artifact = response["artifact"]
            path = Path(artifact["path"]).resolve()
            if self.root not in path.parents or path.name != "output.json":
                raise ValueError("artifact is outside the declared broker scope")
            payload = path.read_bytes()
            valid = (len(payload) == artifact["bytes"] and
                     hashlib.sha256(payload).hexdigest() == artifact["sha256"] and
                     json.loads(payload) == artifact["output"])
            if not valid:
                raise ValueError("independent client readback failed")
            artifact["client_readback_verified"] = True
        response["client_roundtrip_seconds"] = time.perf_counter() - started
        return response

    def start(self, seed, parameters=None):
        p = parameters or TaskParameters()
        return self.request({"op": "start", "seed": int(seed),
                             "parameters": p.to_dict() if isinstance(p, TaskParameters) else p})

    def step(self, action):
        return self.request({"op": "step", "action": action})

    def close(self):
        if self.process.poll() is None:
            self.request({"op": "close"})
        self.process.wait(timeout=10)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    worker = ArtifactWorker(args.root)
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            response = worker.handle(request)
        except Exception as error:
            response = {"ok": False, "error": type(error).__name__ + ": " + str(error)}
        print(json.dumps(response, sort_keys=True, allow_nan=False), flush=True)
        if request is not None and request.get("op") == "close":
            break


if __name__ == "__main__":
    main()
