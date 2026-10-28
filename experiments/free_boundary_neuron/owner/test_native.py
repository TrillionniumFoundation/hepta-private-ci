"""Behavioral integration fixtures against the original native owner binary."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from experiments.free_boundary_neuron.math.finite_horizon import build_readout
from .common import Native, digest, encoder_proof, open_request, permit, sha, write
from .audit import reconstruct
from .run import episode


class NativeOwnerTests(unittest.TestCase):
    def setUp(self):
        self.binary = Path(os.environ["FREE_BOUNDARY_NATIVE_BINARY"]).resolve()
        base = Path(__file__).parent / "runs"
        base.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base, prefix="test-native-")
        self.root = Path(self.temporary.name).resolve()
        permit(self.root)
        self.model = build_readout(
            {
                "state_min": -2.0,
                "state_max": 2.0,
                "state_count": 11,
                "horizon_steps": 4,
                "dt": 0.1,
                "mu": 0.15,
                "sigma": 0.65,
                "rho": 0.15,
                "killing_rate": 0.05,
                "payoff_cost": 0.25,
                "running_cost": 0.02,
            }
        )
        self.model_path = self.root / "MODEL.json"
        write(self.model_path, self.model)
        self.calibration = self.root / "CALIBRATION.json"
        encoder_proof(self.model_path, self.calibration)
        self.native = None

    def tearDown(self):
        if self.native is not None:
            self.native.close()
        self.temporary.cleanup()

    def start(self, case="fixture", expires=64, policy=None):
        self.request = open_request(
            case,
            self.model_path,
            self.calibration,
            policy or {"kind": "free_boundary"},
            expires,
        )
        self.native = Native(self.binary, self.root)
        return self.native.call({"command": "Open", "request": self.request})

    def event(self, state, remaining=4, identity="event.0"):
        return {
            "event_id": identity,
            "state": state,
            "remaining": remaining,
            "evidence_digest": digest(
                ["engineering-fixture", identity, state, remaining]
            ),
        }

    def continue_state(self):
        return self.model["action"][4].index("continue")

    def cold(self):
        old = self.native.call({"command": "Close"})
        self.native.close()
        self.native = Native(self.binary, self.root)
        restored = self.native.call({"command": "Resume", "request": self.request})
        self.assertEqual(old, restored["status"])
        return restored

    def test_stop_cancels_future_native_ticks_and_exact_retry(self):
        self.start()
        observation = self.event(10)
        result = self.native.call({"command": "Observe", "observation": observation})
        self.assertEqual(
            (
                result["readout"]["action"],
                result["terminal"],
                result["owner_authority"],
            ),
            ("stop", True, "DENY_ALL"),
        )
        retry = self.native.call({"command": "Observe", "observation": observation})
        self.assertEqual(
            (
                retry["native_transition_executed"],
                retry["actual_model_calls"],
                retry["checkpoint_after"],
            ),
            (False, 0, result["checkpoint_after"]),
        )
        before = self.native.call({"command": "Status"})
        self.native.call(
            {"command": "Observe", "observation": self.event(9, 3, "event.1")},
            expect_error=True,
        )
        self.assertEqual(before, self.native.call({"command": "Status"}))

    def test_cold_recovery_conflicting_retry_and_real_successor(self):
        self.start(policy={"kind": "exact_dp"})
        observation = self.event(self.continue_state())
        first = self.native.call({"command": "Observe", "observation": observation})
        before = self.native.call({"command": "Status"})
        self.native.call(
            {"command": "Observe", "observation": dict(observation, state=10)},
            expect_error=True,
        )
        self.assertEqual(before, self.native.call({"command": "Status"}))
        restored = self.cold()
        self.assertEqual(
            (
                restored["original_journal_replay_steps"],
                restored["event_validation_kernel_steps"],
                restored["event_validation_bellman_terms"],
            ),
            (1, 1, 11),
        )
        retry = self.native.call({"command": "Observe", "observation": observation})
        self.assertEqual(
            (retry["native_transition_executed"], retry["checkpoint_after"]),
            (False, first["checkpoint_after"]),
        )
        successor = self.native.call(
            {"command": "Observe", "observation": self.event(10, 3, "event.1")}
        )
        self.assertEqual(
            (
                successor["sequence"],
                successor["checkpoint_before"],
                successor["readout"]["action"],
            ),
            (2, first["checkpoint_after"], "stop"),
        )

    def test_native_calibration_expiry_stays_abstention(self):
        self.start(expires=1)
        self.native.call(
            {"command": "Observe", "observation": self.event(self.continue_state())}
        )
        result = self.native.call(
            {"command": "Observe", "observation": self.event(10, 3, "event.1")}
        )
        self.assertEqual(
            (
                result["native_abstain"],
                result["terminal"],
                result["confidence_ppm"],
                result["owner_authority"],
            ),
            (True, True, 0, "DENY_ALL"),
        )

    def test_fixed_pair_has_the_same_early_abstention_action(self):
        self.start(policy={"kind": "constant_threshold", "lower": -0.5, "upper": 1.0})
        result = self.native.call({"command": "Observe", "observation": self.event(0)})
        self.assertEqual(
            (result["readout"]["action"], result["terminal"], result["native_abstain"]),
            ("abstain", True, False),
        )

    def test_corrupt_checkpoint_bound_event_rejects_cold_restore(self):
        self.start()
        self.native.call(
            {"command": "Observe", "observation": self.event(self.continue_state())}
        )
        self.native.call({"command": "Close"})
        self.native.close()
        self.native = None
        path = self.root / "fixture/events.jsonl"
        value = json.loads(path.read_text())
        value["observation"]["state"] = 10
        path.write_text(json.dumps(value) + "\n")
        witness = self.root / "fixture/owner.witness"
        before = sha(witness)
        self.native = Native(self.binary, self.root)
        self.native.call(
            {"command": "Resume", "request": self.request}, expect_error=True
        )
        self.assertEqual(before, sha(witness))

    def test_outside_domain_rejects_before_state_and_no_fake_receipt(self):
        self.start()
        before = self.native.call({"command": "Status"})
        self.native.call(
            {"command": "Observe", "observation": self.event(999)}, expect_error=True
        )
        self.assertEqual(before, self.native.call({"command": "Status"}))
        valid = self.native.call({"command": "Observe", "observation": self.event(10)})
        self.assertEqual(valid["sequence"], 1)

    def test_torn_event_ledger_is_not_silently_repaired(self):
        self.start()
        self.native.call(
            {"command": "Observe", "observation": self.event(self.continue_state())}
        )
        self.native.call({"command": "Close"})
        self.native.close()
        self.native = None
        path = self.root / "fixture/events.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
        original = sha(path)
        self.native = Native(self.binary, self.root)
        self.native.call(
            {"command": "Resume", "request": self.request}, expect_error=True
        )
        self.assertEqual(original, sha(path))

    def test_killed_observation_persists_and_stops_work(self):
        self.start()
        self.native.call(
            {"command": "Observe", "observation": self.event(self.continue_state())}
        )
        self.native.call(
            {"command": "Killed", "evidence_digest": digest("observed-kill-fixture")}
        )
        self.cold()
        before = self.native.call({"command": "Status"})
        self.native.call(
            {"command": "Observe", "observation": self.event(5, 3, "event.1")},
            expect_error=True,
        )
        self.assertEqual(before, self.native.call({"command": "Status"}))

    def test_small_fixture_driver_stops_and_auditor_reconstructs(self):
        paths = []
        for kind in ("free_boundary", "exact_dp"):
            summary = episode(
                self.binary,
                self.root,
                self.model_path,
                self.calibration,
                self.model,
                {"kind": kind},
                17,
                self.continue_state(),
            )
            record = json.loads(
                (self.root / summary["case"] / "EPISODE.json").read_text()
            )
            total, actions = reconstruct(record, self.model)
            self.assertEqual(total, record["realized_discounted_task_return"])
            self.assertEqual(sum(actions.values()), record["work"]["owner_ticks"])
            self.assertGreater(record["work"]["original_journal_replay_steps"], 0)
            self.assertGreater(record["work"]["failed_requests"], 0)
            paths.append(
                [
                    (step["state"], step["remaining"], step["action"])
                    for step in record["steps"]
                ]
            )
        self.assertEqual(paths[0], paths[1])


if __name__ == "__main__":
    unittest.main()
