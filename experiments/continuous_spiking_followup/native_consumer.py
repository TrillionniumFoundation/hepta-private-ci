"""A paid-read task consumes actual original-owner actions and cold frontiers."""

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import tarfile
import time

from .bridge import NativeClient, _digest, _identity, signals


def _save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _archive(directory):
    """Preserve each original owner/task file; never regenerate trajectories."""
    paths = sorted(path for path in directory.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in directory.rglob("*")):
        raise ValueError("native evidence may not contain symbolic links")
    records = {
        str(path.relative_to(directory)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in paths
    }
    destination = directory.with_name(directory.name + ".tar.gz")
    with destination.open("xb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in paths:
                    info = archive.gettarinfo(
                        str(path), arcname=str(path.relative_to(directory))
                    )
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as source:
                        archive.addfile(info, source)
    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "uncompressed_file_bytes": sum(row["bytes"] for row in records.values()),
        "files": records,
    }


class NativeEpisodeConsumer:
    """One episode's real durable owner; tensor state belongs to the caller.

    Risk/activity/natural margin enter the native temporal state. The original
    sparse head and NDU act on the declared decision score. This compilation
    does not test a learned native sparse-head advantage or grant authority.
    """

    def __init__(
        self,
        binary,
        directory,
        *,
        model_sha256,
        objective_sha256,
        policy_id,
        episode_id,
        seed,
        maximum_steps,
        task_binding,
    ):
        if policy_id not in {"fixed", "direct", "value"}:
            raise ValueError("native task supports fixed/direct/value policies")
        required = {"input_sha256", "policy_sha256", "snr", "cost", "horizon"}
        if set(task_binding) != required or task_binding["horizon"] != maximum_steps:
            raise ValueError("complete immutable task binding is required")
        for key in ("input_sha256", "policy_sha256"):
            _identity(task_binding[key], key)
        if (
            not math.isfinite(float(task_binding["snr"]))
            or task_binding["snr"] <= 0
            or not math.isfinite(float(task_binding["cost"]))
            or task_binding["cost"] < 0
        ):
            raise ValueError("invalid task SNR/cost")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.binary = str(binary)
        self.episode_id, self.policy_id, self.seed = str(episode_id), policy_id, seed
        self.task_binding = json.loads(json.dumps(task_binding, allow_nan=False))
        self.maximum_steps, self.model_sha256 = maximum_steps, model_sha256
        self.case_id = "hcsn." + _digest(
            {"episode": self.episode_id, "policy": policy_id}
        )
        self.score_kind = (
            "value_model_advantage"
            if policy_id == "value"
            else "threshold_confidence_advantage"
        )
        self.arguments = {
            "model_sha256": model_sha256,
            "objective_sha256": objective_sha256,
            "arm_id": "hcsn." + policy_id,
            "score_kind": self.score_kind,
            "maximum_ticks": maximum_steps,
            "policy_sha256": task_binding["policy_sha256"],
        }
        self.started = time.process_time(), time.perf_counter()
        self.client = NativeClient(
            self.binary, self.directory / "owner", **self.arguments
        )
        self.open_receipt = self.client.open(self.case_id, seed)
        self.steps, self.terminal, self.disagreements = 0, False, 0
        self.process_costs, self.recoveries = [], []
        self.stop_probe, self.final_receipt = None, None
        _save(
            self.directory / "CONTRACT.json",
            {
                "schema": "hcsn-native-task-contract-v1",
                "episode_id": self.episode_id,
                "case_id": self.case_id,
                "seed": seed,
                "policy_id": policy_id,
                "task_binding": self.task_binding,
                "client_arguments": self.arguments,
                "native_identity": self.client.native.identity,
                "margin_normalization": "raw / (1 + abs(raw)); raw retained",
            },
        )

    def tick(self, *, decision, natural_margin, event_activity, episode_id, step):
        if (
            str(episode_id) != self.episode_id
            or type(step) is not int
            or step != self.steps + 1
            or step > self.maximum_steps
        ):
            raise ValueError("task cursor or episode identity mismatch")
        if self.terminal:
            raise RuntimeError(
                "task already stopped; no further model observation permitted"
            )
        raw_margin = float(natural_margin)
        if not math.isfinite(raw_margin):
            raise ValueError("natural margin must be finite")
        packet = signals(
            decision["continue_score"],
            score_kind=decision["score_kind"],
            natural_margin=raw_margin / (1 + abs(raw_margin)),
            task_risk=decision["predicted_error_probability"],
            activity=event_activity,
            continuation_value=decision["continuation_value"],
            stopping_value=decision["stopping_value"],
            forced_terminal=decision["forced_terminal"],
        )
        causal_digest = _digest(
            {
                "episode_id": self.episode_id,
                "step": step,
                "task_binding": self.task_binding,
                "decision": decision,
                "natural_margin_raw": raw_margin,
                "interval_event_probability": float(event_activity),
            }
        )
        raw = self.client.tick(packet, evidence_digest=causal_digest)
        action = raw["effective_action"]
        if action not in {"keep", "stop"}:
            raise RuntimeError("unexpected native task action")
        self.steps, self.terminal = step, action == "stop"
        disagreement = self.terminal != bool(decision["stop"])
        self.disagreements += int(disagreement)
        if self.terminal:
            before = self.client.status()
            probe = {
                "command": "Tick",
                "observation": {
                    "event_id": self.case_id + ".forbidden-after-stop",
                    "step": step + 1,
                    "checkpoint": before["checkpoint"],
                    "features": packet["features"],
                    "evidence_digest": _digest(
                        {"episode": self.episode_id, "probe": "post-stop"}
                    ),
                },
            }
            rejected = self.client.native.rpc(probe, allow_error=True)
            after = self.client.status()
            if (
                rejected.get("ok", True)
                or "Terminal episode" not in rejected.get("error", "")
                or before != after
            ):
                raise RuntimeError("actual native post-STOP guard failed")
            self.stop_probe = {"before": before, "rejection": rejected, "after": after}
        receipt = {
            "stop": self.terminal,
            "action": action,
            "raw": raw,
            "policy_disagreement": disagreement,
            "signal_packet": packet,
            "natural_margin_raw": raw_margin,
            "causal_source_digest": causal_digest,
            "bound_native_evidence_digest": self.client.last_request["observation"][
                "evidence_digest"
            ],
            "post_stop_probe": self.stop_probe,
        }
        _save(self.directory / f"TICK_{step:03d}.json", receipt)
        return receipt

    def cold_resume(self, stream, cursor, episode_id):
        if (
            self.terminal
            or str(episode_id) != self.episode_id
            or cursor != self.steps
            or stream.steps != cursor
            or stream.batch_size != 1
            or stream.model_sha256 != self.model_sha256
        ):
            raise ValueError(
                "cannot checkpoint mismatched task/neural/native frontiers"
            )
        from .streaming import StreamingClassifier

        began = time.process_time(), time.perf_counter()
        directory = self.directory / f"recovery_{len(self.recoveries):02d}"
        directory.mkdir()
        state_receipt = stream.save_state(directory / "stream")
        payload = {
            "schema": "hcsn-native-complete-prefix-v1",
            "episode_id": self.episode_id,
            "cursor": cursor,
            "model_sha256": self.model_sha256,
            "task_binding": self.task_binding,
            "policy_id": self.policy_id,
            "seed": self.seed,
            "native_binding": self.client.binding(),
            "stream_manifest_sha256": state_receipt["manifest_sha256"],
            "stream_payload_sha256": state_receipt["payload_sha256"],
        }
        digest = _save(directory / "TASK.json", payload)
        old_pid = self.client.process_id
        self.process_costs.append(self.client.close())
        raw = (directory / "TASK.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or json.loads(raw) != payload:
            raise ValueError("task checkpoint identity changed")
        for name, key in (
            ("manifest.json", "stream_manifest_sha256"),
            ("state.npz", "stream_payload_sha256"),
        ):
            if (
                hashlib.sha256((directory / "stream" / name).read_bytes()).hexdigest()
                != payload[key]
            ):
                raise ValueError("bound neural state changed")
        restored = StreamingClassifier(stream.model).load_state(directory / "stream")
        if (
            restored.steps != payload["cursor"]
            or restored.model_sha256 != payload["model_sha256"]
        ):
            raise ValueError("restored neural and task cursor disagree")
        self.client = NativeClient(
            self.binary, self.directory / "owner", **self.arguments
        )
        native_resume = self.client.open(self.case_id, self.seed, resume=True)
        self.client.verify_binding(payload["native_binding"])
        if self.client.process_id == old_pid:
            raise RuntimeError("native cold resume did not create a new process")
        receipt = {
            "status": "new_native_process_and_serialized_neural_state_restored",
            "old_pid": old_pid,
            "new_pid": self.client.process_id,
            "task_sha256": digest,
            "restored_cursor": payload["cursor"],
            "native_resume": native_resume,
            "stream": state_receipt,
            "cpu_seconds": time.process_time() - began[0],
            "wall_seconds": time.perf_counter() - began[1],
            "python_process_restarted": False,
        }
        self.recoveries.append(receipt)
        _save(directory / "RECEIPT.json", receipt)
        return restored, receipt

    def finish(self):
        if self.final_receipt is not None:
            return self.final_receipt
        self.process_costs.append(self.client.close())
        if any(row["exit_code"] != 0 for row in self.process_costs):
            raise RuntimeError("native child exited unsuccessfully")
        receipt = {
            "schema": "hcsn-native-episode-receipt-v1",
            "episode_id": self.episode_id,
            "policy_id": self.policy_id,
            "steps": self.steps,
            "terminal": self.terminal,
            "policy_disagreements": self.disagreements,
            "recoveries": self.recoveries,
            "post_stop_native_rejected": self.stop_probe is not None,
            "native_processes": self.process_costs,
            "native_child_cpu_seconds": sum(
                row["child_cpu_seconds"] for row in self.process_costs
            ),
            "parent_lifetime_cpu_seconds": time.process_time() - self.started[0],
            "parent_lifetime_wall_seconds": time.perf_counter() - self.started[1],
            "timing_scope": "parent lifetime includes caller model/policy work; nested with episode timing, not additive",
        }
        _save(self.directory / "RECEIPT.json", receipt)
        began = time.process_time(), time.perf_counter()
        receipt["archive"] = _archive(self.directory)
        receipt["archive_cpu_seconds"] = time.process_time() - began[0]
        receipt["archive_wall_seconds"] = time.perf_counter() - began[1]
        self.final_receipt = receipt
        return receipt

    def close(self):
        return self.finish()
