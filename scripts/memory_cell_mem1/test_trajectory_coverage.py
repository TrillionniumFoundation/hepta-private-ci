"""Harness regressions using an order-sensitive protocol double, not Rust."""

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from environment import Experience, Owner
import run
from run_trajectory_coverage import (
    MatchedTrajectory,
    PriorityReference,
    align_pool,
    readback_trajectory,
    run_campaign,
)


class ProtocolDouble:
    def __init__(self, binary, state, generation, width=16, outputs=8, eta=0.5):
        self.binary, self.state, self.generation = str(binary), state, generation
        self.width, self.outputs, self.eta = width, outputs, eta
        self.multiplications = self.wall_ns = 0
        self.calls, self.state_bytes = 1, 512
        self.digest = hashlib.sha256(state.encode()).hexdigest()

    def command(self, text):
        self.calls += 1
        self.wall_ns += 1

    def predict(self, key):
        self.command("predict")
        self.multiplications += self.width * self.outputs
        chosen = int(self.digest[:4], 16) % self.outputs
        return [float(i == chosen) for i in range(self.outputs)]

    def update(self, key, target, support):
        self.command(
            f"update {self.generation} {support} "
            + ",".join(map(repr, key))
            + " "
            + ",".join(map(repr, target))
        )
        self.digest = hashlib.sha256(
            (self.digest + repr((key, target))).encode()
        ).hexdigest()
        self.multiplications += (
            3 * self.width * self.outputs + self.width + 2 * self.outputs
        )
        return {"sequence": self.calls, "loss": 0.0}

    def checkpoint(self):
        self.command("checkpoint")
        data = json.dumps([self.state, self.generation, self.digest]).encode()
        return hashlib.sha256(data).hexdigest(), data.hex()

    def restore(self, checkpoint):
        self.command("restore")
        state, generation, digest = json.loads(bytes.fromhex(checkpoint[1]))
        if state != self.state or generation != self.generation:
            raise ValueError("owner mismatch")
        self.digest = digest

    def reset(self, generation, suffix):
        self.command("reset")
        self.state += ":" + suffix
        self.generation = generation
        self.digest = hashlib.sha256(self.state.encode()).hexdigest()

    def clone(self):
        new = ProtocolDouble(self.binary, self.state, self.generation)
        new.restore(self.checkpoint())
        return new

    def restart(self, directory):
        checkpoint = self.checkpoint()
        directory.mkdir()
        (directory / "state.bin").write_bytes(bytes.fromhex(checkpoint[1]))
        new = ProtocolDouble(self.binary, self.state, self.generation)
        new.restore(checkpoint)
        return new

    def close(self):
        pass


class TrajectoryTests(unittest.TestCase):
    def test_readback_rejects_ledger_and_provenance_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "protocol-double"
            binary.write_text("not a native executable")
            with patch.object(run, "NativeMemory", ProtocolDouble):
                result = run_campaign(binary, root / "campaign", [0], "a" * 40)
            self.assertNotIn("failures", result)
            directory = root / "campaign/stationary-0-coverage_uniform"
            reference = root / "campaign/stationary-0-reference"
            kwargs = dict(seed=0, profile="coverage_uniform", owner_change=False)
            ledger_path = directory / "matching-B.json"
            original = ledger_path.read_text()
            altered = json.loads(original)
            altered["replay_request_bytes"] += 1
            ledger_path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "ledger"):
                readback_trajectory(directory, reference, **kwargs)
            ledger_path.write_text(original)
            event_path = directory / "events.jsonl"
            events = [json.loads(line) for line in event_path.read_text().splitlines()]
            next(e for e in events if e["event"] == "update" and e["kind"] == "sleep")[
                "support"
            ] = "0" * 64
            event_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
            with self.assertRaisesRegex(ValueError, "provenance"):
                readback_trajectory(directory, reference, **kwargs)

    def test_failed_native_admission_closes_open_event_stream(self):
        raw = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(Path, "open", return_value=raw),
                patch.object(
                    run,
                    "NativeMemory",
                    side_effect=RuntimeError("native admission failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "native admission"):
                    PriorityReference("unused", Path(temporary) / "trial", "fast", 0)
        self.assertTrue(raw.closed)

    def test_complete_trajectories_carry_order_with_matched_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "protocol-double"
            binary.write_text("not a native executable")
            with patch.object(run, "NativeMemory", ProtocolDouble):
                result = run_campaign(binary, root / "campaign", [0, 1], "a" * 40)
            self.assertNotIn("failures", result)
            self.assertEqual(
                [r["status"] for r in result["roster"]], ["completed"] * 12
            )
            self.assertEqual(len(result["pairs"]), 4)
            left = root / "campaign/stationary-0-coverage_uniform"
            right = root / "campaign/stationary-0-coverage_structured"
            a = json.loads((left / "plan-A1.json").read_text())
            b = json.loads((right / "plan-A1.json").read_text())
            self.assertEqual(a["pre_state"], b["pre_state"])
            self.assertEqual(a["pool"], b["pool"])
            self.assertNotEqual(a["order"], b["order"])
            a = json.loads((left / "plan-B.json").read_text())
            b = json.loads((right / "plan-B.json").read_text())
            self.assertNotEqual(a["pre_state"], b["pre_state"])
            self.assertEqual(a["pool"], b["pool"])
            for i in range(0, len(result["roster"]), 3):
                x, y = result["roster"][i + 1 : i + 3]
                self.assertEqual(x["teacher_cost"], y["teacher_cost"])
                self.assertGreater(x["teacher_cost"]["native_calls"], 0)

    def test_pool_alignment_permits_priority_only(self):
        owner = Owner(0)
        row = Experience(
            "A:0", 1, owner.features["A:0"], owner.facts["A:0"].label, 3, 0.8, "A"
        )
        reference = [row]
        self.assertEqual(align_pool([replace(row, surprise=0.1)], reference), reference)
        for changed in (
            replace(row, version=2),
            replace(row, step=4),
            replace(row, label=7 - row.label),
        ):
            with self.assertRaisesRegex(ValueError, "exposure"):
                align_pool([changed], reference)
        aligned = align_pool(reference, reference)
        aligned.clear()
        self.assertEqual(reference, [row])

    def test_late_failure_preserves_completed_runs_and_roster(self):
        original = MatchedTrajectory.sleep

        def fail_at_b(trial, phase):
            if phase == "B" and trial.profile == "coverage_structured":
                raise RuntimeError("injected late replay failure")
            original(trial, phase)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "protocol-double"
            binary.write_text("not a native executable")
            with (
                patch.object(run, "NativeMemory", ProtocolDouble),
                patch.object(MatchedTrajectory, "sleep", fail_at_b),
            ):
                result = run_campaign(binary, root / "campaign", [0], "a" * 40)
            self.assertEqual(
                [r["status"] for r in result["roster"]],
                ["completed", "completed", "failed"] * 2,
            )
            self.assertEqual(result["pairs"], [])
            self.assertEqual(len(result["failures"]), 2)
            self.assertTrue(
                (
                    root / "campaign/dynamic-0-coverage_structured/matching-A1.json"
                ).is_file()
            )
            self.assertEqual(
                result, json.loads((root / "campaign/results.json").read_text())
            )


if __name__ == "__main__":
    unittest.main()
