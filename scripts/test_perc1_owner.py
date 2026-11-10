"""Local owner fault boundaries; synthetic callbacks prove engineering only."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from perc1.capture_entry import OwnedProducer, model_sha256
from perc1.owner import Owner, UnknownOutcome
from perc1.schema import Invalid, sha


def binding():
    return {
        "owner_id": "test-owner",
        "generation": 1,
        "source_frontier": sha(b"source-frontier"),
        "encoder_sha256": sha(b"encoder"),
        "grant_sha256": sha(b"operator-grant"),
    }


@unittest.skipUnless(os.name == "posix", "local POSIX owner contract")
class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "owner"

    def tearDown(self):
        self.temporary.cleanup()

    def test_replay_and_next_task_return_original_receipt_without_dispatch(self):
        calls = []
        request = {"source": "a", "regions": [1, 2]}
        with Owner(self.root, binding(), 2) as owner:
            result = owner.execute(
                "a", request, dispatch=lambda x: calls.append(x) or {"value": 19}
            )
            self.assertEqual(
                owner.execute("a", request, dispatch=lambda _: self.fail("replayed")),
                result,
            )
            request["regions"].append(3)
            with self.assertRaises(Invalid):
                owner.execute(
                    "a",
                    request,
                    dispatch=lambda _: self.fail("changed identity dispatched"),
                )
            self.assertEqual(calls, [{"source": "a", "regions": [1, 2]}])
        with Owner(self.root, binding(), 2) as resumed:
            self.assertEqual(resumed.receipt("a"), result)
            self.assertEqual(resumed.status()["reserved_units"], 1)
            self.assertEqual(result["reserved_units"], 1)
            self.assertGreaterEqual(result["measurements"]["wall_ns"], 0)

    def test_budget_and_history_limit_precede_effect_and_hold_failures(self):
        with Owner(self.root, binding(), 1, max_operations=1) as owner:

            def failing(_):
                raise OSError("source unavailable")

            failed = owner.execute("a", {}, dispatch=failing)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["effect_outcome"], "unverified")
            self.assertEqual(
                owner.execute("a", {}, dispatch=lambda _: self.fail("failure retried")),
                failed,
            )
            with self.assertRaises(Invalid):
                owner.execute(
                    "b", {}, dispatch=lambda _: self.fail("budget denied too late")
                )
            self.assertEqual(owner.status()["remaining_units"], 0)
        other = self.root.parent / "second"
        with Owner(other, binding(), 1) as owner:
            with self.assertRaises(Invalid):
                owner.execute(
                    "over",
                    {},
                    units=2,
                    dispatch=lambda _: self.fail("unreserved dispatch"),
                )
            self.assertEqual(owner.status()["reserved_units"], 0)

    def test_writer_generation_frontier_model_grant_and_budget_are_bound(self):
        with Owner(self.root, binding(), 2):
            with self.assertRaises(Invalid):
                Owner(self.root, binding(), 2)
        for key, value in (
            ("generation", 2),
            ("source_frontier", sha(b"changed source")),
            ("encoder_sha256", sha(b"changed encoder")),
            ("grant_sha256", sha(b"changed grant")),
        ):
            changed = binding()
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(Invalid):
                Owner(self.root, changed, 2)
        with self.assertRaises(Invalid):
            Owner(self.root, binding(), 3)

    def test_corrupted_receipt_fails_closed_on_cold_open(self):
        with Owner(self.root, binding(), 2) as owner:
            owner.execute("a", {}, dispatch=lambda _: {"value": 19})
        connection = sqlite3.connect(self.root / "owner.sqlite3")
        raw = json.loads(
            connection.execute("SELECT receipt FROM operations").fetchone()[0]
        )
        raw["result"]["value"] = 20
        connection.execute(
            "UPDATE operations SET receipt=?",
            (json.dumps(raw, sort_keys=True, separators=(",", ":")),),
        )
        connection.commit()
        connection.close()
        with self.assertRaises(Invalid):
            Owner(self.root, binding(), 2)

    def test_nonfinite_and_oversize_returns_retain_failure_without_repeat(self):
        with Owner(self.root, binding(), 2) as owner:
            for name, result in (
                ("nan", {"v": float("nan")}),
                ("large", {"v": "x" * 1048576}),
            ):
                receipt = owner.execute(name, {}, dispatch=lambda _, r=result: r)
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(owner.receipt(name), receipt)
            self.assertEqual(owner.status()["remaining_units"], 0)

    def test_process_crash_boundaries_reconcile_without_duplicate_effects(self):
        code = r"""
import json, os, sys
from pathlib import Path
from perc1.owner import Owner
root, stage, encoded = sys.argv[1:]
binding = json.loads(encoded)
marker = Path(root).parent / (stage + ".effect")
class CrashOwner(Owner):
    def _begin_dispatch(self, operation_id):
        if stage == "reserved":
            os._exit(61)
        return super()._begin_dispatch(operation_id)
    def _settle(self, operation_id):
        if stage == "retained":
            os._exit(63)
        return super()._settle(operation_id)
def effect(request):
    marker.write_text("one effect")
    if stage == "dispatched":
        os._exit(62)
    return {"value": 19}
with CrashOwner(root, binding, 1) as owner:
    owner.execute("op", {"source": "a"}, dispatch=effect)
"""
        for stage, code_expected in (
            ("reserved", 61),
            ("dispatched", 62),
            ("retained", 63),
        ):
            root = self.root.parent / stage
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
            completed = subprocess.run(
                [sys.executable, "-c", code, str(root), stage, json.dumps(binding())],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, code_expected, completed.stderr)
            marker = self.root.parent / (stage + ".effect")
            with Owner(root, binding(), 1) as resumed:
                self.assertEqual(resumed.status()["reserved_units"], 1)
                if stage == "reserved":
                    self.assertFalse(marker.exists())
                    receipt = resumed.execute(
                        "op", {"source": "a"}, dispatch=lambda _: {"value": 19}
                    )
                    self.assertEqual(receipt["status"], "executed")
                elif stage == "dispatched":
                    with self.assertRaises(UnknownOutcome):
                        resumed.execute(
                            "op",
                            {"source": "a"},
                            dispatch=lambda _: self.fail("unknown effect retried"),
                        )
                    with self.assertRaises(UnknownOutcome):
                        resumed.receipt("op")
                    self.assertTrue(resumed.status()["unresolved_dispatch"])
                    with self.assertRaises(Invalid):
                        resumed.execute(
                            "new",
                            {},
                            dispatch=lambda _: self.fail("unknown budget reused"),
                        )
                else:
                    receipt = resumed.execute(
                        "op",
                        {"source": "a"},
                        dispatch=lambda _: self.fail("retained effect repeated"),
                    )
                    self.assertEqual(receipt["result"], {"value": 19})
                    self.assertEqual(
                        resumed.status()["states"],
                        {"settled": {"operations": 1, "units": 1}},
                    )
                if stage != "reserved":
                    self.assertEqual(marker.read_text(), "one effect")

    def test_capture_grant_and_native_bound_reject_before_callback_or_load(self):
        grant = {
            "schema": "perc1.capture-grant.v1",
            "owner_id": "test-owner",
            "generation": 1,
            "source_frontier": binding()["source_frontier"],
            "source_ids": ["image-1"],
            "scope_digest": sha(b"scope"),
        }
        weights_sha = sha(b"not-loaded-test-weights")
        projection = {"placeholder": "not loaded by rejected requests"}
        owner_binding = dict(
            binding(),
            encoder_sha256=model_sha256(weights_sha, projection),
            grant_sha256=sha(grant),
        )
        region = {"evidence_id": "region-1", "x": 0, "y": 0, "width": 16, "height": 16}
        request = {
            "source_id": "image-1",
            "representation": "dense",
            "regions": [region],
        }
        with Owner(self.root, owner_binding, 1) as owner:
            producer = OwnedProducer(
                owner, grant, "missing.pth", weights_sha, projection
            )
            for rejected in (
                dict(request, source_id="other"),
                dict(request, regions=[dict(region, width=64, height=64)]),
            ):
                with self.assertRaises(Invalid):
                    producer.observe(
                        "op", rejected, lambda _: self.fail("unauthorized capture")
                    )
            self.assertIsNone(producer.worker)
            self.assertEqual(owner.status()["reserved_units"], 0)
            bad_grant = copy.deepcopy(grant)
            bad_grant["source_ids"].append("other")
            with self.assertRaises(Invalid):
                OwnedProducer(owner, bad_grant, "missing.pth", weights_sha, projection)


if __name__ == "__main__":
    unittest.main()
