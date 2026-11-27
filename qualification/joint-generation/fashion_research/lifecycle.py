"""Atomic progress and bounded worker interruption; no data or model imports."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import tempfile


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def planned_stages(seeds):
    return ["shared"] + [f"seed-{seed}/{stage}" for seed in seeds
                         for stage in ("content", "export", "policy")] + ["final_receipt"]


class Progress:
    def __init__(self, output, seeds):
        self.path, self.seeds = Path(output) / "progress.json", list(seeds)
        self.started_seeds, self.started_stages, self.completed_stages = [], [], []
        self.current_stage = None

    def snapshot(self):
        return {"schema": "hepta.fashion-D-progress.v1",
                "started_seeds": self.started_seeds.copy(),
                "unrun_seeds": [s for s in self.seeds if s not in self.started_seeds],
                "started_stages": self.started_stages.copy(),
                "completed_stages": self.completed_stages.copy(),
                "unrun_stages": [s for s in planned_stages(self.seeds) if s not in self.started_stages],
                "current_stage": self.current_stage}

    def start_stage(self, stage, seed=None):
        key = stage if seed is None else f"seed-{seed}/{stage}"
        if key not in planned_stages(self.seeds) or key in self.started_stages:
            raise ValueError("unknown or already started stage")
        if self.current_stage is not None:
            raise ValueError("complete the current stage before starting another")
        if seed is not None and seed not in self.started_seeds:
            self.started_seeds.append(seed)
        self.started_stages.append(key)
        self.current_stage = key
        atomic_json(self.path, self.snapshot())

    def complete_stage(self, stage, seed=None):
        key = stage if seed is None else f"seed-{seed}/{stage}"
        if self.current_stage != key:
            raise ValueError("stage is not active")
        self.completed_stages.append(key)
        self.current_stage = None
        atomic_json(self.path, self.snapshot())

    def interrupt_for_receipt(self):
        # Leave the interrupted stage started but incomplete, then record the
        # receipt stage. Never pretend the interrupted operation completed.
        self.current_stage = None
        self.start_stage("final_receipt")


def read_progress(output, seeds=(11, 23, 47)):
    try:
        value = json.loads((Path(output) / "progress.json").read_text())
        required = {"started_seeds", "unrun_seeds", "started_stages", "completed_stages",
                    "unrun_stages", "current_stage"}
        if not isinstance(value, dict) or not required <= set(value):
            raise ValueError("incomplete progress checkpoint")
        return value
    except (OSError, ValueError) as error:
        value = Progress(output, seeds).snapshot()
        value["progress_read_error"] = type(error).__name__ + ": " + str(error)
        return value


class WorkerInterrupted(RuntimeError):
    pass


@contextmanager
def worker_signals():
    def interrupt(signum, frame):
        raise WorkerInterrupted("worker interrupted by " + signal.Signals(signum).name)
    previous = {s: signal.signal(s, interrupt) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
