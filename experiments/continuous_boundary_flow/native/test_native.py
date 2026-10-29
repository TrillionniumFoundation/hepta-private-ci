"""Behavioral checks against the compiled original native kernel and owner."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import time
import unittest

from .adapter import NativeBridge, Q, digest, features, make_profile, save_profile

BINARY = None
DESTINATION = None
COSTS = []


def fixture(stage="transform", channel="margin", enabled=True):
    matrix = [[0.0] * 4 for _ in range(10)]
    selected = {"margin": 1, "risk": 2, "flow": 3}[channel]
    matrix[0][selected], matrix[1][selected] = 1.0, -1.0
    head = [[0.0] * 10 for _ in range(3)]
    head[0][0], head[1][1] = 1.0, 1.0
    profile = make_profile(
        ["raw"],
        matrix,
        [0.0] * 10,
        head,
        [0.0] * 3,
        source_model_digest=digest("native-behavior-model"),
        objective_digest=digest("native-behavior-task"),
        arm_id="native-fixture",
        stage=stage,
    )
    profile["use_" + channel] = enabled
    return profile


class NativeBehavior(unittest.TestCase):
    def setUp(self):
        self.directory = DESTINATION / self.id().split(".")[-1]
        self.directory.mkdir()
        self.bridges = []

    def bridge(self, name="run"):
        bridge = NativeBridge(BINARY, self.directory / name)
        self.bridges.append(bridge)
        return bridge

    def load(self, bridge, profile):
        path, identity = save_profile(self.directory / "profiles", profile)
        self.assertEqual(bridge.load_profile(path), identity)
        return path, identity

    def tearDown(self):
        for bridge in self.bridges:
            COSTS.append(bridge.close())

    def test_each_continuous_channel_changes_actual_native_action(self):
        bridge = self.bridge()
        evidence = []
        for channel in ("margin", "risk", "flow"):
            for enabled in (True, False):
                profile = fixture("act", channel, enabled)
                profile["kernel"].update(temporal_decay_q24=0, threshold_rate_q24=0)
                _, key = self.load(bridge, profile)
                bridge.kernel_reset(key, [channel])
                values = {"margin": 0.0, "risk": 0.0, "flow": 0.0}
                values[channel] = 0.7
                row = bridge.kernel_advance(
                    key, [{"case_id": channel, "features": features([0.2], **values)}]
                )["rows"][0]
                self.assertEqual(
                    row["readout"]["action"], "keep" if enabled else "stop"
                )
                evidence.append(
                    {"channel": channel, "enabled": enabled, "receipt": row}
                )
        (self.directory / "consumption.json").write_text(json.dumps(evidence, indent=2))

    def test_pure_batch_causal_steps_and_original_owner_match_across_cold_replay(self):
        bridge = self.bridge()
        path, key = self.load(bridge, fixture())
        sequence = [
            features([t / 20], margin=v, risk=0.15, flow=0.1)
            for t, v in enumerate([0.7, -0.2, 0.5, -0.8, 0.3, 0.7, -0.1, 0.4])
        ]
        batch = bridge.kernel_batch(key, [sequence])["sequences"][0]
        bridge.kernel_reset(key, ["causal"])
        causal = [
            bridge.kernel_advance(key, [{"case_id": "causal", "features": x}])["rows"][
                0
            ]
            for x in sequence
        ]
        self.assertEqual(
            [x["activation_q24"] for x in batch], [x["activation_q24"] for x in causal]
        )
        bridge.open("owner", 19, key)
        owner = [bridge.tick(x) for x in sequence[:3]]
        before = bridge.close_owner()
        COSTS.append(bridge.close())
        self.bridges.remove(bridge)
        cold = self.bridge()
        cold.load_profile(path)
        receipt = cold.open("owner", 19, key, resume=True)
        self.assertEqual(receipt["original_journal_replay_steps"], 3)
        self.assertEqual(receipt["status"]["checkpoint"], before["checkpoint"])
        self.assertEqual(receipt["status"]["step"], 3)
        owner.extend(cold.tick(x) for x in sequence[3:])
        self.assertEqual(
            [x["activation_q24"] for x in batch], [x["activation_q24"] for x in owner]
        )
        self.assertEqual(
            [x["readout"]["scores_q24"] for x in causal],
            [x["readout"]["scores_q24"] for x in owner],
        )
        self.assertEqual(
            [x["readout"]["action"] for x in causal],
            [x["readout"]["action"] for x in owner],
        )
        (self.directory / "parity.json").write_text(
            json.dumps(
                {"pure": causal, "owner": owner, "cold_restore": receipt}, indent=2
            )
        )

    def test_unknown_profile_stale_checkpoint_and_zero_stop_head_reject(self):
        bridge = self.bridge()
        profile = fixture()
        _, key = self.load(bridge, profile)
        result = bridge.rpc(
            {"command": "KernelReset", "profile_sha256": "0" * 64, "case_ids": ["bad"]},
            allow_error=True,
        )
        self.assertFalse(result["ok"])
        invalid = copy.deepcopy(profile)
        invalid["head_bias_q24"][2] = Q
        path, bad = save_profile(self.directory / "profiles", invalid)
        result = bridge.rpc(
            {"command": "LoadProfile", "path": str(path), "sha256": bad},
            allow_error=True,
        )
        self.assertFalse(result["ok"])
        bridge.open("owner", 23, key)
        valid = bridge.tick(features([0.1], margin=0.7))
        wrong = {
            "event_id": "stale",
            "step": 2,
            "checkpoint": "0" * 64,
            "features": features([0.1], margin=0.4),
            "evidence_digest": digest("stale"),
        }
        self.assertFalse(
            bridge.rpc({"command": "Tick", "observation": wrong}, allow_error=True)[
                "ok"
            ]
        )
        self.assertEqual(
            bridge.rpc({"command": "Status"})["checkpoint"], valid["checkpoint_after"]
        )
        self.assertFalse(bridge.rpc({"command": "Status"})["host_poisoned"])

    def test_malformed_whole_batch_has_no_partial_transition(self):
        bridge = self.bridge()
        _, key = self.load(bridge, fixture())
        bridge.kernel_reset(key, ["a", "b"])
        bad = features([0.0])
        bad["raw_q24"][0] = -(1 << 63)
        result = bridge.rpc(
            {
                "command": "KernelAdvance",
                "profile_sha256": key,
                "observations": [
                    {"case_id": "a", "features": features([0.0], margin=0.4)},
                    {"case_id": "b", "features": bad},
                ],
            },
            allow_error=True,
        )
        self.assertFalse(result["ok"])
        rows = bridge.kernel_advance(
            key,
            [
                {"case_id": "a", "features": features([0.0], margin=0.4)},
                {"case_id": "b", "features": features([0.0], margin=0.4)},
            ],
        )["rows"]
        self.assertEqual([row["step"] for row in rows], [1, 1])

    def test_native_stop_cancels_further_owner_ticks_and_exact_retry_is_idempotent(
        self,
    ):
        bridge = self.bridge()
        _, key = self.load(bridge, fixture("act"))
        bridge.open("stop-case", 29, key)
        result = bridge.tick(features([0.0]))
        self.assertTrue(result["terminal"])
        self.assertEqual(result["effective_action"], "stop")
        event = json.loads((bridge.root / "stop-case/events.jsonl").read_text())
        retry = bridge.rpc({"command": "Tick", "observation": event["observation"]})
        self.assertTrue(retry["duplicate_event_ignored"])
        self.assertFalse(retry["native_transition_executed"])
        new = copy.deepcopy(event["observation"])
        new.update(event_id="after-stop", step=2, checkpoint=result["checkpoint_after"])
        self.assertFalse(
            bridge.rpc({"command": "Tick", "observation": new}, allow_error=True)["ok"]
        )
        self.assertEqual(bridge.rpc({"command": "Status"})["step"], 1)

    def test_altered_persisted_action_rejects_even_with_rehashed_receipt(self):
        bridge = self.bridge()
        path, key = self.load(bridge, fixture())
        bridge.open("owner", 31, key)
        bridge.tick(features([0.2], margin=0.6))
        bridge.close_owner()
        corrupted = self.directory / "corrupt"
        corrupted.mkdir()
        shutil.copytree(bridge.root / "owner", corrupted / "owner")
        file = corrupted / "owner/events.jsonl"
        event = json.loads(file.read_text())
        event["output"]["readout"]["action"] = "stop"
        payload = event["output"]
        payload.pop("receipt_digest")
        payload["receipt_digest"] = digest(payload)
        file.write_text(json.dumps(event, separators=(",", ":")) + "\n")
        cold = self.bridge("corrupt")
        cold.load_profile(path)
        response = cold.rpc(
            {
                "command": "Resume",
                "request": {"case": "owner", "seed": 31, "profile_sha256": key},
            },
            allow_error=True,
        )
        self.assertFalse(response["ok"])
        self.assertIn("mismatch", response["error"].lower())


def main():
    global BINARY, DESTINATION
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    BINARY = args.binary.resolve()
    DESTINATION = args.output.resolve()
    DESTINATION.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeBehavior)
    )
    report = {
        "schema": "hepta.continuous-boundary.native-tests.v1",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "successful": result.wasSuccessful(),
        "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
        "wall_seconds": time.perf_counter() - start,
        "process_costs": COSTS,
        "scope": "engineering behavior only, not neural efficacy or production qualification",
    }
    (DESTINATION / "VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
