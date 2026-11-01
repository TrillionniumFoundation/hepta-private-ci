"""Owned feature-worker fixture used to exercise real scheduling and IPC.

This worker computes test features. It is neither a real-media encoder nor a
trained scientific candidate. Source availability follows a one-second prefix
schedule; parent-side completion includes receive/deserialization overhead.
"""

import argparse
import json
import math
import subprocess
import sys
import time

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import PrefixObservation
from .execution import ReadResult


class SubprocessService:
    mode = "controlled_fixture_feature_worker; real monotonic release/IPC/completion"

    def __init__(self, object_id):
        self.object_id = object_id
        self.sequence = 0

    def request(self, step, clock):
        self.sequence += 1
        command = [sys.executable, "-m", __name__, "--worker", "--prefix", str(step.prefix_end),
                   "--modality", step.modality.value, "--release-delay",
                   str(max(0, step.prefix_end - clock.now()))]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return Pending(child, self.object_id, f"fixture-{self.sequence}", step)


class Pending:
    def __init__(self, child, object_id, event_id, step):
        self.child = child
        self.object_id = object_id
        self.event_id = event_id
        self.step = step

    def wait_until(self, deadline, clock):
        try:
            stdout, stderr = self.child.communicate(timeout=max(0, deadline - clock.now()))
        except subprocess.TimeoutExpired:
            return None
        now = clock.now()
        if self.child.returncode:
            return ReadResult(error=f"worker exit {self.child.returncode}: {stderr[:256]}")
        if len(stdout.encode()) > 65536:
            return ReadResult(error="worker exceeded response byte bound")
        try:
            payload = json.loads(stdout)
            observation = PrefixObservation(
                event_id=self.event_id, object_id=self.object_id, modality=self.step.modality,
                prefix_end=self.step.prefix_end, available_at=float(self.step.prefix_end),
                completed_at=now, raw=payload["raw"], aligned=payload["aligned"],
                alignment_id="fixture-shared-v1", aligned_window=(0, self.step.prefix_end))
            return ReadResult(observation=observation)
        except (ValueError, KeyError, TypeError) as error:
            return ReadResult(error=f"invalid worker payload: {error}")

    def drain(self, clock):
        try:
            self.child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.communicate(timeout=2)
            raise RuntimeError("owned fixture worker exceeded its drain timeout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--prefix", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--modality", choices=("audio", "video"), required=True)
    parser.add_argument("--release-delay", type=float, required=True)
    args = parser.parse_args()
    if not 0 <= args.release_delay <= 3:
        raise ValueError("fixture release delay outside the bounded schedule")
    time.sleep(args.release_delay)
    # Actual child CPU work, retained in the enclosing worker's process receipt.
    value = sum(math.sin(i * 0.0001) ** 2 for i in range(30000)) / 30000
    shift = 0.1 if args.modality == "audio" else -0.1
    raw = (value + shift, args.prefix / 3)
    print(json.dumps({"raw": raw, "aligned": raw}), flush=True)


if __name__ == "__main__":
    main()
