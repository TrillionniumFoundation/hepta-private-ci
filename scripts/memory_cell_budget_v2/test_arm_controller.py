"""Admission order and durable accounting tests; effects are pure callbacks."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from arm_controller import ArmController
from common import BudgetExceeded, METERS, file_identity, quantities
from test_support import adapter, budget, capacity, plan, process


class Controller(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def controller(self, name="arm", **changes):
        args = {
            "arm": "data_split",
            "seed": 24111,
            "protocol_sha256": "a" * 64,
            "budget": budget(),
            "capacity": capacity(),
        }
        args.update(changes)
        return ArmController(self.root / name, **args)

    def test_training_then_gate_uses_same_remaining_before_effect(self):
        controller = self.controller()
        train = controller.begin(
            "train",
            "train",
            quantities({"cpu_ns": 70, "wall_ns": 60, "train_tokens": 80}),
            {"stage": "train"},
        )
        report = controller.finish(
            train, plan(process(self.root, "train-process", cpu=60, wall=40))
        )
        self.assertIsNone(report["measured"]["observation"]["train_tokens"])
        self.assertEqual(
            (report["charge"]["train_tokens"], report["charge_basis"]["train_tokens"]),
            (80, "unknown_reservation"),
        )
        reopened = self.controller()
        called = []
        with self.assertRaises(BudgetExceeded):
            reopened.run(
                "gate-too-large",
                "infer",
                quantities({"cpu_ns": 41}),
                {},
                lambda ticket: called.append(ticket),
            )
        self.assertEqual(called, [])
        gate = plan(process(self.root, "gate-process", cpu=25, wall=20))
        reopened.run(
            "gate",
            "infer",
            quantities({"cpu_ns": 30, "wall_ns": 30}),
            {},
            lambda ticket: gate,
        )
        remaining = controller.remaining()["meters"]
        self.assertEqual((remaining["cpu_ns"], remaining["train_tokens"]), (15, 20))

    def test_failed_timeout_and_lost_preserve_full_charge_and_deny_replay(self):
        for outcome in ("failed", "timeout", "lost"):
            with self.subTest(outcome=outcome):
                controller = self.controller(outcome)
                ticket = controller.begin(
                    "operation", "infer", quantities({"cpu_ns": 70, "wall_ns": 70}), {}
                )
                if outcome == "lost":
                    record = controller.lost(ticket, "crashed before receipt")
                else:
                    raw = process(
                        self.root,
                        outcome + "-raw",
                        cpu=5,
                        wall=10,
                        returncode=1 if outcome == "failed" else -9,
                        timeout=outcome == "timeout",
                    )
                    record = controller.finish(
                        ticket,
                        plan(raw),
                        status="failed" if outcome == "failed" else "completed",
                    )
                self.assertEqual(record["charge"]["cpu_ns"], 70)
                self.assertEqual(
                    self.controller(outcome).ledger.snapshot()["used"]["cpu_ns"], 70
                )
                with self.assertRaises(FileExistsError):
                    controller.begin("operation", "infer", ticket["upper"], {})
                with self.assertRaises(ValueError):
                    controller.finish(ticket, {"rows": [], "wall_owner": "none"})

    def test_exception_and_missing_raw_close_arm_without_refund(self):
        controller = self.controller()

        def crash(ticket):
            raise RuntimeError("effect crashed")

        with self.assertRaises(RuntimeError):
            controller.run("crash", "infer", quantities({"cpu_ns": 55}), {}, crash)
        self.assertTrue(controller.remaining()["closed"])
        with self.assertRaises(BudgetExceeded):
            controller.begin("later", "infer", quantities({"cpu_ns": 1}), {})
        other = self.controller("other")
        ticket = other.begin("read", "infer", quantities({"cpu_ns": 20}), {})
        raw = process(self.root, "missing")
        (Path(raw["path"]).parent / "stdout").unlink()
        with self.assertRaises(OSError):
            other.finish(ticket, plan(raw))
        self.assertEqual(
            (other.remaining()["closed"], other.ledger.snapshot()["used"]["cpu_ns"]),
            (True, 20),
        )

    def test_measured_overrun_is_retained_and_closes_arm(self):
        controller = self.controller()
        ticket = controller.begin(
            "too-much", "infer", quantities({"cpu_ns": 50, "wall_ns": 50}), {}
        )
        with self.assertRaises(BudgetExceeded):
            controller.finish(
                ticket, plan(process(self.root, "overrun", cpu=75, wall=10))
            )
        state = controller.ledger.snapshot()
        self.assertEqual(
            (state["closed"], state["used"]["cpu_ns"], state["events"][0]["state"]),
            (True, 75, "overrun"),
        )

    def test_concurrent_duplicate_claim_has_one_admission(self):
        first, second = self.controller(), self.controller()

        def enter(controller):
            try:
                return controller.begin("same", "infer", quantities({"cpu_ns": 20}), {})
            except FileExistsError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enter, [first, second]))
        self.assertEqual(sum(row is not None for row in results), 1)
        self.assertEqual(first.ledger.snapshot()["pending"]["cpu_ns"], 20)

    def test_identity_change_cross_seed_and_missing_reservation_dimensions(self):
        first = self.controller()
        with self.assertRaises(ValueError):
            self.controller(seed=1)
        other = self.controller("other", seed=1)
        ticket = other.begin("operation", "infer", quantities({"cpu_ns": 10}), {})
        with self.assertRaises(ValueError):
            first.finish(ticket, {"rows": [], "wall_owner": "none"})
        with self.assertRaises(ValueError):
            first.begin("incomplete", "infer", {"cpu_ns": 10}, {})
        self.assertEqual(set(ticket["upper"]), set(METERS))

    def test_checkpoint_over_capacity_or_drift_prevents_callback(self):
        entry = adapter(self.root, "checkpoint", 8)
        denied = self.controller("denied", capacity=capacity([entry], ceiling=230400))
        calls = []
        with self.assertRaises(ValueError):
            denied.run(
                "fit",
                "train",
                quantities({"cpu_ns": 50}),
                {},
                lambda ticket: calls.append(ticket),
            )
        self.assertEqual((calls, denied.ledger.snapshot()["events"]), ([], []))
        allowed = self.controller("allowed", capacity=capacity([entry]))
        Path(entry["path"]).write_bytes(b"drift")
        with self.assertRaises(ValueError):
            allowed.run(
                "fit",
                "train",
                quantities({"cpu_ns": 50}),
                {},
                lambda ticket: calls.append(ticket),
            )
        self.assertEqual(calls, [])

    def test_same_raw_receipt_cannot_settle_another_operation(self):
        controller = self.controller()
        raw = plan(process(self.root, "original", cpu=10, wall=10))
        upper = quantities({"cpu_ns": 20, "wall_ns": 20})
        controller.run("first", "infer", upper, {}, lambda ticket: raw)
        with self.assertRaises(FileExistsError):
            controller.run(
                "new-event-same-receipt", "infer", upper, {}, lambda ticket: raw
            )
        state = controller.ledger.snapshot()
        self.assertEqual((state["closed"], state["used"]["cpu_ns"]), (True, 30))

    def test_unknown_total_preserves_known_overrun_lower_bound(self):
        controller = self.controller()
        known = process(self.root, "known", cpu=80, wall=10)
        unknown = process(self.root, "unknown", cpu=1, wall=10)
        path = Path(unknown["path"])
        raw = json.loads(path.read_bytes())
        raw["usage"] = None
        path.write_text(json.dumps(raw))
        unknown["identity"] = file_identity(path)
        ticket = controller.begin(
            "mixed", "infer", quantities({"cpu_ns": 50, "wall_ns": 50}), {}
        )
        with self.assertRaises(BudgetExceeded):
            controller.finish(ticket, plan(known, unknown, wall_owner="known"))
        state = controller.ledger.snapshot()
        self.assertEqual((state["closed"], state["used"]["cpu_ns"]), (True, 80))
        record = json.loads(
            next(controller.claims.glob("*/settlement.json")).read_bytes()
        )
        self.assertIsNone(record["measured"]["observation"]["cpu_ns"])
        self.assertEqual(record["charge"]["cpu_ns"], 80)
