"""Real owner/file boundaries with a stub encoder; no task-benefit claim."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from perc1.acquisition import train_head
from perc1.active_capture import observe, observed_prefix, read_decision
from perc1.capture_entry import OwnedProducer, model_sha256
from perc1.owner import Owner
from perc1.schema import Invalid, canonical, sha
from test_perc1_acquisition import pair


@unittest.skipUnless(os.name == "posix", "existing POSIX capture owner")
class ActiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "captured-source.txt"
        self.source.write_text("Amount: USD 12.50; date: 2026-11-11; mass: 3 kg")
        self.grant = {
            "schema": "perc1.capture-grant.v1",
            "owner_id": "active-owner",
            "generation": 1,
            "source_frontier": sha("frontier"),
            "source_ids": ["image-1"],
            "scope_digest": sha("scope"),
        }
        self.weights, self.projection = sha("stub-weights"), {"stub": True}
        self.binding = {
            **{
                k: self.grant[k]
                for k in ("owner_id", "generation", "source_frontier")
            },
            "grant_sha256": sha(self.grant),
            "encoder_sha256": model_sha256(self.weights, self.projection),
        }
        self.task_sha = sha("original-task")
        train = [
            pair(f"train-{i}", "train", x)
            for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        dev = [
            pair(f"dev-{i}", "dev", x) for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        self.head = train_head(
            train,
            dev,
            {
                "train": [p["source_group"] for p in train],
                "dev": [p["source_group"] for p in dev],
                "confirmation": ["heldout"],
            },
            feature_extractor_sha256=sha("fixture-extractor"),
            ridge=0.01,
            cost_value=0.1,
        )
        self.owner = Owner(self.root / "owner", self.binding, 8)
        self.owner.execute(
            "initial",
            {},
            dispatch=lambda _: {"initial_source": "exact retained text"},
        )
        self.producer = self.make_producer()
        self.calls = []

    def tearDown(self):
        self.owner.close()
        self.temporary.cleanup()

    def make_producer(self):
        return OwnedProducer(
            self.owner, self.grant, "unused.pth", self.weights, self.projection
        )

    def candidate(self, value=1.0, kind="expand_roi"):
        prefix = observed_prefix(self.owner, self.task_sha, ["initial"])
        features = pair("heldout", "confirmation", value)["features"]
        features.update(
            prefix_sha256=sha(prefix),
            acquired_receipt_sha256s=prefix["receipt_sha256s"],
        )
        return {
            "id": "additional",
            "kind": kind,
            "upper_cost": 4,
            "features": features,
            "request": {
                "source_id": "image-1",
                "representation": "dense",
                "regions": [
                    {
                        "evidence_id": "region",
                        "x": 0,
                        "y": 0,
                        "width": 16,
                        "height": 16,
                    }
                ],
            },
        }

    def run_choice(
        self, operation_id, candidates=None, *, head=None, capture=None
    ):
        selected_head = self.head if head is None else head
        return observe(
            self.producer,
            operation_id,
            selected_head,
            [self.candidate()] if candidates is None else candidates,
            self.capture if capture is None else capture,
            expected_head_sha256=sha(selected_head),
            task_sha256=self.task_sha,
            observed_operations=["initial"],
        )

    def capture(self, request):
        self.calls.append(copy.deepcopy(request))
        return self.source.read_bytes()

    def encoder_stub(self, operation_id, request, capture):
        raw = capture(request)
        return {
            "operation_id": operation_id,
            "source_sha256": sha(raw),
            "exact_text": raw.decode(),
        }

    def test_actions_execute_registered_capture_and_stop_does_no_effect(self):
        with patch.object(self.producer, "_capture", side_effect=self.encoder_stub):
            for kind in ("expand_roi", "change_view", "reobserve"):
                result = self.run_choice(kind, [self.candidate(kind=kind)])
                self.assertEqual(result["outcome"], "executed")
                self.assertEqual(result["decision"]["kind"], kind)
                self.assertEqual(
                    result["owner_receipt"]["result"]["exact_text"],
                    self.source.read_text(),
                )
                self.assertEqual(result["new_attempt_reservations"], 1)
            before = self.owner.status()
            stopped = self.run_choice("stop", [self.candidate(-1.0)])
        self.assertEqual(stopped["outcome"], "stopped")
        self.assertEqual(stopped["owner_status"], before)
        self.assertEqual(len(self.calls), 3)
        self.assertIsNone(stopped["terminal_quality"])
        self.assertIsNone(result["observed_net_benefit"])
        self.assertIsNone(result["measurements"]["provider_billing"])
        self.assertFalse(result["quoted_microcredits_enforced"])

    def test_replay_rejects_head_prefix_quote_action_changes(self):
        with patch.object(self.producer, "_capture", side_effect=self.encoder_stub):
            original = self.run_choice("one")
            replay = self.run_choice("one")
            self.assertEqual(original["owner_receipt"], replay["owner_receipt"])
            self.assertEqual(original["decision"], replay["decision"])
            self.assertEqual(replay["new_attempt_reservations"], 0)
            for key, value in (("kind", "change_view"), ("upper_cost", 5)):
                candidate = self.candidate()
                candidate[key] = value
                with self.subTest(key=key), self.assertRaises(Invalid):
                    self.run_choice("one", [candidate])
            changed_head = copy.deepcopy(self.head)
            changed_head["training_receipt"]["seed"] += 1
            with self.assertRaises(Invalid):
                self.run_choice("one", head=changed_head)
            self.task_sha = sha("changed-task")
            with self.assertRaises(Invalid):
                self.run_choice("one")
        self.assertEqual(len(self.calls), 1)

    def test_stop_survives_reopen_and_cannot_be_reassigned_to_acquire(self):
        stopped = self.run_choice("stop", [self.candidate(-1.0)])
        self.owner.close()
        self.owner = Owner(self.root / "owner", self.binding, 8)
        self.producer = self.make_producer()
        same = self.run_choice("stop", [self.candidate(-1.0)])
        self.assertEqual(same["decision"], stopped["decision"])
        self.assertEqual(read_decision(self.owner, "stop"), stopped["decision"])
        with self.assertRaises(Invalid):
            self.run_choice("stop")
        with self.assertRaises(Invalid):
            self.producer.observe("stop", self.candidate()["request"], self.capture)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.owner.status()["reserved_units"], 1)

    def test_failure_and_unknown_are_retained_and_never_retried(self):
        def fail(request):
            self.calls.append(request)
            raise OSError("capture unavailable")

        def crash(request):
            self.calls.append(request)
            raise SystemExit("lost after effect")

        with patch.object(self.producer, "_capture", side_effect=self.encoder_stub):
            failed = self.run_choice("failed", capture=fail)
            again = self.run_choice("failed")
            self.assertEqual(failed["outcome"], "failed")
            self.assertEqual(failed["owner_receipt"], again["owner_receipt"])
            with self.assertRaises(SystemExit):
                self.run_choice("unknown", capture=crash)
            unresolved = self.run_choice("unknown")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(unresolved["outcome"], "unknown")
        self.assertIsNone(unresolved["owner_receipt"])
        self.assertTrue(unresolved["owner_status"]["unresolved_dispatch"])
        self.assertEqual(unresolved["owner_status"]["reserved_units"], 3)
        self.owner.close()
        self.owner = Owner(self.root / "owner", self.binding, 8)
        self.producer = self.make_producer()
        with patch.object(
            self.producer, "_capture", side_effect=AssertionError("must not replay")
        ):
            after_reopen = self.run_choice("unknown")
        self.assertEqual(after_reopen["outcome"], "unknown")
        self.assertEqual(after_reopen["new_attempt_reservations"], 0)
        self.assertEqual(read_decision(self.owner, "unknown")["selection"]["action"], "ACQUIRE")

    def test_stop_refuses_an_existing_ordinary_capture_token(self):
        self.owner.execute("ordinary", {}, dispatch=lambda _: {"value": "observed"})
        before = self.owner.status()
        with self.assertRaises(Invalid):
            self.run_choice("ordinary", [self.candidate(-1.0)])
        self.assertEqual(self.owner.status(), before)
        self.assertEqual(self.calls, [])

    def test_decision_read_requires_original_head_and_recomputes_choice(self):
        result = self.run_choice("stop", [self.candidate(-1.0)])
        head_path = self.owner.root / "active-heads" / (sha(self.head) + ".json")
        head_bytes = head_path.read_bytes()
        head_path.write_bytes(head_bytes.replace(b'"cost_value":0.1', b'"cost_value":0.2'))
        with self.assertRaises(Invalid):
            read_decision(self.owner, "stop")
        head_path.write_bytes(head_bytes)
        self.assertEqual(read_decision(self.owner, "stop"), result["decision"])
        path = self.owner.root / "active-decisions" / (sha(b"stop") + ".json")
        altered = json.loads(path.read_bytes())
        altered["catalog"][0]["features"]["task_goal"] = [1.0]
        altered["catalog_sha256"] = sha(altered["catalog"])
        path.write_bytes(canonical(altered))
        with self.assertRaises(Invalid):
            read_decision(self.owner, "stop")
        self.assertEqual(self.calls, [])

    def test_prefix_requires_original_owner_receipts_and_retained_latents(self):
        for key, value in (
            ("acquired_receipt_sha256s", [sha("invented")]),
            ("acquired_latent", [1.0]),
            ("prefix_sha256", sha("invented-prefix")),
        ):
            candidate = self.candidate()
            candidate["features"][key] = value
            with self.subTest(key=key), self.assertRaises(Invalid):
                self.run_choice("bad-prefix", [candidate])
        with self.assertRaises(Invalid):
            observed_prefix(self.owner, self.task_sha, ["does-not-exist"])
        self.assertEqual(self.owner.status()["reserved_units"], 1)

    def test_truncated_decision_refuses_new_dispatch(self):
        result = self.run_choice("stop", [self.candidate(-1.0)])
        path = (
            self.owner.root / "active-decisions" / (sha(b"stop") + ".json")
        )
        path.write_bytes(path.read_bytes()[:12])
        with self.assertRaises(Invalid):
            self.run_choice("stop", [self.candidate(-1.0)])
        self.assertEqual(result["outcome"], "stopped")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
