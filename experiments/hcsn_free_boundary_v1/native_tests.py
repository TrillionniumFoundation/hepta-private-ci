"""Meaningful failures/quantization checks against the real archived Rust host."""

import json
from pathlib import Path
import tempfile
import unittest

import torch

from .model import HCSNClassifier
from .native_bridge import NativeSession, Signals, UPSTREAM, restored_binary
from .run_native_live import run_live


class NativeCausalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = restored_binary()

    def make_session(self, directory, case="probe"):
        return NativeSession(directory, binary=self.binary, policy="causal_maxout",
                             model_digest=UPSTREAM.digest("native-development-fixture"),
                             case=case, seed=13)

    def test_invalid_feature_and_stale_checkpoint_do_not_advance_owner(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-native-invalid-") as directory:
            session = self.make_session(directory)
            try:
                session.tick(Signals(0.8, 0.1, 0.1, 0.1))
                before = session.bridge.rpc({"command": "Status"})
                with self.assertRaises(ValueError):
                    session.tick(Signals(0.1, 0.1, 1.1, 0.1))
                self.assertEqual(before, session.bridge.rpc({"command": "Status"}))
                request = {"command": "Tick", "observation": {
                    "event_id": "stale", "step": 2, "checkpoint": "0" * 64,
                    "features": Signals(0.8, 0.1, 0.1, 0.1).packet(),
                    "evidence_digest": UPSTREAM.digest("stale-development-probe")}}
                rejection = session.bridge.rpc(request, allow_error=True)
                self.assertFalse(rejection["ok"])
                self.assertEqual(before, session.bridge.rpc({"command": "Status"}))
            finally:
                session.close()

    def test_q24_tie_selects_stop_and_positive_ulp_keeps(self):
        actions = []
        for offset in (0, 2 / (1 << 24)):
            with tempfile.TemporaryDirectory(prefix="hcsn-native-rounding-") as directory:
                session = self.make_session(directory)
                try:
                    row = session.tick(Signals(0.05 + offset, -0.5, 0.1, 0.1))
                    actions.append(row["native"]["effective_action"])
                    session.verify_retry()
                    if session.terminal:
                        session.verify_terminal()
                finally:
                    session.close()
        self.assertEqual(actions, ["stop", "keep"])

    def test_live_model_updates_equal_actual_owner_ticks(self):
        torch.set_num_threads(1)
        model = HCSNClassifier(3, 2, width=2, depth=1, seed=144)
        generator = torch.Generator().manual_seed(147)
        x = torch.randn(2, 4, 3, generator=generator)
        dt, labels = torch.ones(2, 4), torch.tensor([0, 1])
        with tempfile.TemporaryDirectory(prefix="hcsn-native-live-") as directory:
            output = Path(directory) / "run"
            result = run_live(model, x, dt, labels, 0.02, output,
                              binary=self.binary, provenance={"kind": "untrained API fixture"})
            for policy, summary in result["summary"].items():
                paths = sorted((output / policy).glob("*/RESULT.json"))
                records = [json.loads(p.read_text()) for p in paths]
                ticks = sum(c["counters"]["owner_ticks"] for r in records
                            for c in r["native_process_costs"])
                self.assertEqual(ticks, summary["actual_reads"])
                self.assertEqual(summary["actual_reads"] + summary["avoided_model_updates"], 8)


if __name__ == "__main__":
    unittest.main()
