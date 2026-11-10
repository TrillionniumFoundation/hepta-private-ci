"""Manufactured host tests; no native model efficacy claim."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from .metacontrol_native_pairs import bind_public_intervention, collect
from .metacontrol_macro_contract import sha
from .test_macro_pair_fixtures import FixtureHost, plan


class NativePairTests(unittest.TestCase):
    def test_effective_control_plan_uses_actual_default_and_rejects_nonreset(self):
        for fields, allowed in (
            ({}, True),
            ({"memory_mode": "reset"}, True),
            ({"memory_mode": "persistent"}, False),
            ({"memory_mode": False}, False),
            ({"memory_mode": True}, False),
            ({"memory_mode": None}, False),
        ):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                frozen = plan(root)
                path = Path(frozen["profile"]["control_plan"])
                raw = json.dumps({"control": fields}).encode()
                path.write_bytes(raw)
                frozen["profile"]["control_plan_sha256"] = sha(raw)
                if allowed:
                    result = collect(frozen, root / "out", host_class=FixtureHost)
                    self.assertEqual(result["completed_pairs"], 1)
                else:
                    with self.assertRaises(ValueError):
                        collect(frozen, root / "out", host_class=FixtureHost)
                    self.assertFalse((root / "out").exists())

    def test_fixed_suffix_both_branches_and_fixture_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = collect(plan(root), root / "out", host_class=FixtureHost)
            self.assertEqual(summary["completed_pairs"], 1)
            self.assertEqual(summary["evidence_kind"], "fixture")
            row = json.loads((root / "out/p1.json").read_text())
            self.assertTrue(row["initial_public_state_matched"])
            for b in row["branches"].values():
                self.assertEqual(
                    b["actual_native_actions"][-2:], ["WRITE_TEXT", "STOP"]
                )
                self.assertGreater(b["outer_wall_seconds"], 0)
                self.assertIsNone(b["provider_cost"])

    def test_failures_and_mismatched_state_keep_denominator_and_cost(self):
        for changes in (
            {"fail_read": True},
            {"wrong_initial": True},
            {"wrong_evaluator": True},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = type("AlteredFixture", (FixtureHost,), changes)
                result = collect(plan(root), root / "out", host_class=host)
                row = json.loads((root / "out/p1.json").read_text())
                self.assertEqual(
                    (result["planned_pairs"], result["completed_pairs"]), (1, 0)
                )
                self.assertEqual((row["source_group"], row["split"]), ("s", "train"))
                self.assertIsNone(row["net_latency_gain"])
                self.assertEqual(set(row["branches"]), {"STOP", "READ"})
                self.assertGreater(row["branches"]["READ"]["outer_wall_seconds"], 0)

    def test_expired_action_clock_stops_before_next_forced_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = FixtureHost(
                {}, {}, {}, Path(tmp) / "out", training=True, exploration=[]
            )
            bind_public_intervention(host, 0.001, "repeat", 1)
            self.assertEqual(json.loads(host.public_step())["remaining_seconds"], 0.001)
            time.sleep(0.005)
            self.assertIsNone(host.public_step())
            self.assertTrue(host.budget_stop)

    def test_noise_packet_is_immutable_and_actor_schema_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = plan(root)
            p["pairs"][0]["read_condition"] = "noise"
            summary = collect(p, root / "out", host_class=FixtureHost)
            self.assertEqual(summary["completed_pairs"], 1)
            self.assertTrue(
                (root / "out/p1-READ/public/declared-read-noise.png").is_file()
            )

    def test_invalid_launch_and_tampered_wire_never_admit_native_outcomes(self):
        for changes in (
            {"exit_code": 1},
            {"exit_code": False},
            {"enforced_before_actor_exec": False},
            {"launcher_source_sha256": "0" * 64},
            {"stdout": "changed"},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = type(
                    "InvalidLaunch", (FixtureHost,), {"launch_changes": changes}
                )
                summary = collect(plan(root), root / "out", host_class=host)
                self.assertEqual(summary["completed_pairs"], 0)
                row = json.loads((root / "out/p1.json").read_text())
                self.assertIsNone(row["net_latency_gain"])
