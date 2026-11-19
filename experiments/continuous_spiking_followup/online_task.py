"""Causal paid reads: actual incremental work ends when the task stops."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from .streaming import StreamingClassifier


class EpisodeSource:
    """An in-memory task source with an explicit cursor and terminal guard.

    This counts actual iterator reads and model updates, not physical sensor or
    network I/O. The prepared experimental observations already reside in RAM.
    """

    def __init__(self, x, dt, episode_id):
        self.x, self.dt, self.episode_id = x, dt, str(episode_id)
        self.cursor, self.stopped = 0, False

    def read(self):
        if self.stopped or self.cursor >= len(self.x):
            raise RuntimeError("task source is terminal")
        index = self.cursor
        self.cursor += 1
        return self.x[index : index + 1], self.dt[index : index + 1]

    def stop(self):
        self.stopped = True


@torch.inference_mode()
def execute_episode(
    model,
    policies,
    mode,
    x,
    dt,
    episode_id,
    snr,
    cost,
    native=None,
    capture_resume=False,
):
    source = EpisodeSource(x, dt, episode_id)
    began = time.process_time(), time.perf_counter()
    stream = StreamingClassifier(model).reset(1)
    reset_cpu = time.process_time() - began[0]
    loop = time.process_time(), time.perf_counter()
    trace, snapshot, final_decision, native_recovery = [], None, None, None
    for _ in range(len(x)):
        inputs, duration = source.read()
        logits, aux = stream.step(inputs, duration)
        raw_odds = float(logits[0, 1] - logits[0, 0])
        decision = policies.decide(
            mode, raw_odds, snr, cost, len(x) - source.cursor, len(x)
        )
        native_receipt = None
        if native is not None:
            native_receipt = native.tick(
                decision=decision,
                natural_margin=float(aux["margin"].mean()),
                event_activity=float(aux["event_probability"].mean()),
                episode_id=str(episode_id),
                step=source.cursor,
            )
            actual_stop = native_receipt["stop"]
        else:
            actual_stop = decision["stop"]
        trace.append(
            {
                "step": source.cursor,
                "raw_log_odds": raw_odds,
                "logits": logits[0].tolist(),
                "decision": decision,
                "actual_stop": actual_stop,
                "natural_margin_mean": float(aux["margin"].mean()),
                "event_activity_mean": float(aux["event_probability"].mean()),
                "state_bytes": stream.state_bytes,
                "native": native_receipt,
            }
        )
        if capture_resume and source.cursor == 1 and not actual_stop:
            # Verification-only snapshot; its cost is explicitly retained.
            snap_cpu, snap_wall = time.process_time(), time.perf_counter()
            snapshot = {
                "neural": stream.snapshot(),
                "task_cursor": source.cursor,
                "episode_id": str(episode_id),
                "model_sha256": stream.model_sha256,
                "cpu_seconds": time.process_time() - snap_cpu,
                "wall_seconds": time.perf_counter() - snap_wall,
            }
            if native is not None:
                stream, native_recovery = native.cold_resume(
                    stream, source.cursor, str(episode_id)
                )
                restored_cursor = native_recovery["restored_cursor"]
                if restored_cursor != source.cursor:
                    raise ValueError("restored native task cursor changed")
                source = EpisodeSource(x, dt, episode_id)
                source.cursor = restored_cursor
        if actual_stop:
            source.stop()
            final_decision = decision
            break
    loop_cpu, loop_wall = time.process_time() - loop[0], time.perf_counter() - loop[1]
    if not source.stopped:
        raise RuntimeError("consumer failed to stop at the finite horizon")
    try:
        source.read()
    except RuntimeError:
        post_stop_rejected = True
    else:
        raise AssertionError("post-STOP source read was accepted")
    return {
        "episode_id": str(episode_id),
        "mode": mode,
        "observations": source.cursor,
        "processed_rows": stream.processed_rows,
        "avoided_model_steps": len(x) - stream.processed_rows,
        "predicted_class": int(trace[-1]["raw_log_odds"] >= 0),
        "cost": cost * source.cursor,
        "reset_cpu_seconds": reset_cpu,
        "loop_cpu_seconds": loop_cpu,
        "loop_wall_seconds": loop_wall,
        "total_cpu_seconds": time.process_time() - began[0],
        "total_wall_seconds": time.perf_counter() - began[1],
        "snapshot_cpu_seconds": 0.0 if snapshot is None else snapshot["cpu_seconds"],
        "snapshot_wall_seconds": 0.0 if snapshot is None else snapshot["wall_seconds"],
        "post_stop_read_rejected": post_stop_rejected,
        "final_decision": final_decision,
        "trace": trace,
        "native_recovery": native_recovery,
    }, snapshot


@torch.inference_mode()
def verify_resume(model, policies, mode, x, dt, snr, cost, record, snapshot, directory):
    """Serialize neural state and task cursor, then verify same-order replay.

    This helper restores a fresh adapter in-process. Separate-process neural and
    durable-owner checks are independently recorded by their dedicated tests.
    """
    if snapshot is None:
        return {"status": "already_stopped_after_first_read", "steps_replayed": 0}
    from .stream_state import save_snapshot, load_snapshot

    directory = Path(directory)
    start = time.process_time(), time.perf_counter()
    neural_receipt = save_snapshot(snapshot["neural"], directory / "neural")
    cursor = snapshot["task_cursor"]
    task = {
        "episode_id": snapshot["episode_id"],
        "cursor": cursor,
        "model_sha256": snapshot["model_sha256"],
        "mode": mode,
        "input_sha256": hashlib.sha256(
            x.numpy().tobytes() + dt.numpy().tobytes()
        ).hexdigest(),
        "temperature": policies.temperature,
        "policy_sha256": policies.identity,
        "snr": snr,
        "cost": cost,
        "horizon": len(x),
        "neural_manifest_sha256": neural_receipt["manifest_sha256"],
        "neural_payload_sha256": neural_receipt["payload_sha256"],
    }
    (directory / "task.json").write_text(json.dumps(task, sort_keys=True) + "\n")
    restored_task = json.loads((directory / "task.json").read_text())
    for name, key in (
        ("manifest.json", "neural_manifest_sha256"),
        ("state.npz", "neural_payload_sha256"),
    ):
        if (
            hashlib.sha256((directory / "neural" / name).read_bytes()).hexdigest()
            != restored_task[key]
        ):
            raise ValueError("task-bound neural state changed")
    stream = StreamingClassifier(model).restore(load_snapshot(directory / "neural"))
    if restored_task != task or stream.model_sha256 != task["model_sha256"]:
        raise ValueError("task and neural checkpoint identity disagree")
    maximum = 0.0
    for row in record["trace"][cursor:]:
        index = row["step"] - 1
        logits, _ = stream.step(x[index : index + 1], dt[index : index + 1])
        expected = torch.tensor(row["logits"], dtype=logits.dtype)
        error = float((logits[0] - expected).abs().max())
        maximum = max(maximum, error)
        if not torch.equal(logits[0], expected):
            raise ValueError("same-order serialized stream replay changed logits")
        decision = policies.decide(
            mode,
            float(logits[0, 1] - logits[0, 0]),
            snr,
            cost,
            len(x) - index - 1,
            len(x),
        )
        if decision != row["decision"]:
            raise ValueError("restored task changed stopping decision")
    return {
        "status": "exact_in_process_serialized_replay",
        "max_logit_error": maximum,
        "steps_replayed": len(record["trace"]) - cursor,
        "cpu_seconds": time.process_time() - start[0],
        "wall_seconds": time.perf_counter() - start[1],
        "task_sha256": hashlib.sha256(
            (directory / "task.json").read_bytes()
        ).hexdigest(),
    }


def metrics(records, labels):
    correct = np.array(
        [
            row["predicted_class"] == int(label)
            for row, label in zip(records, labels, strict=True)
        ]
    )
    costs = np.array([row["cost"] for row in records])
    return {
        "episodes": len(records),
        "accuracy": float(correct.mean()),
        "mean_observations": float(np.mean([row["observations"] for row in records])),
        "mean_cost": float(costs.mean()),
        "net_utility": float((correct - costs).mean()),
        "total_processed_rows": sum(row["processed_rows"] for row in records),
        "total_avoided_model_steps": sum(row["avoided_model_steps"] for row in records),
        "loop_cpu_seconds": sum(row["loop_cpu_seconds"] for row in records),
        "loop_wall_seconds": sum(row["loop_wall_seconds"] for row in records),
        "all_post_stop_reads_rejected": all(
            row["post_stop_read_rejected"] for row in records
        ),
    }
