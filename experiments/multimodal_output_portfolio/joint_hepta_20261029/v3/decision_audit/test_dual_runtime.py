"""Executed file/lifecycle contracts; fixtures are not neural generation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from .dual_runtime import FixedSchedule, Request, digest_file, run


class FixtureProvider:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    def identity(self):
        return {"fixture_only": True, "pretrained": False}

    def load(self):
        self.calls.append("load")

    def synchronize(self):
        pass

    def describe(self, image_path, prompt, max_tokens=80):
        self.calls.append("describe")
        if self.failure:
            raise self.failure
        return "fixture-visible description " + str(len(self.calls))

    def draw(self, prompt, output_path, seed, initial_image=None, steps=12):
        self.calls.append("refine" if initial_image else "draft")
        Image.new("RGB", (16, 16), (seed % 256, 40, 80)).save(output_path)
        return {"fixture_only": True}


class DualContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        image = self.root / "input.png"
        Image.new("RGB", (16, 16), "yellow").save(image)
        self.request = Request("fixture:1", str(image), digest_file(image),
                               "Explain this picture and make a diagram.")

    def execute(self, actions, backend=None, **kwargs):
        return run(self.request, backend or FixtureProvider(), FixedSchedule(actions),
                   self.root / "run", **kwargs)

    def test_actual_files_and_no_semantic_acceptance_from_verifier(self):
        result = self.execute(("perceive", "text", "draft", "verify", "stop"))
        self.assertEqual(result["status"], "delivered")
        self.assertEqual([x["kind"] for x in result["selected"]], ["text", "image"])
        self.assertEqual(result["semantic_acceptance"], "pending_independent_evaluation")
        events = result["events"]
        self.assertEqual([e["event_id"] for e in events], list(range(len(events))))
        self.assertGreater(result["cpu_seconds"], 0)
        self.assertGreater(result["wall_seconds"], 0)
        self.assertAlmostEqual(result["cpu_seconds"], sum(e["cpu_seconds"] for e in events))
        self.assertTrue(any(a["kind"] == "public_critique_not_independent_score"
                            for a in result["artifacts"]))
        self.assertFalse(result["training_performed"])

    def test_revision_invalidates_pair_and_retains_paid_unselected_candidates(self):
        result = self.execute(("perceive", "text", "draft", "revise", "text",
                               "refine", "verify", "stop"))
        self.assertEqual(result["status"], "delivered")
        self.assertEqual([a["plan_version"] for a in result["selected"]], [2, 2])
        images = [a for a in result["artifacts"] if a["kind"] == "image"]
        self.assertEqual(len(images), 2)
        self.assertNotEqual(images[0]["sha256"], images[1]["sha256"])
        self.assertTrue((self.root / "run" / images[0]["path"]).is_file())
        self.assertIn("draft", [e["action"] for e in result["events"]])

    def test_stale_pair_cannot_be_delivered_after_plan_revision(self):
        result = self.execute(("perceive", "text", "draft", "revise", "stop"))
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(result["selected"], [])
        self.assertEqual(len(result["artifacts"]), 4)

    def test_failures_and_cancellation_retain_partial_spend(self):
        for error, status in ((RuntimeError("provider unavailable"), "failed"),
                              (TimeoutError("provider deadline"), "timeout"),
                              (KeyboardInterrupt(), "cancelled")):
            with self.subTest(status=status):
                folder = self.root / status
                result = run(self.request, FixtureProvider(error),
                             FixedSchedule(("perceive",)), folder)
                self.assertEqual(result["status"], status)
                self.assertGreater(result["wall_seconds"], 0)
                self.assertTrue(any(e["status"] == status for e in result["events"]))
                self.assertEqual(json.loads((folder / "report.json").read_text())["status"], status)

    def test_initial_stop_and_expiry_do_not_auto_generate_or_deliver(self):
        backend = FixtureProvider()
        stopped = self.execute(("stop",), backend)
        self.assertEqual(stopped["status"], "abstained")
        self.assertEqual(backend.calls, [])
        expired = run(self.request, FixtureProvider(), FixedSchedule(("text", "draft")),
                      self.root / "expired", horizon=2)
        self.assertEqual(expired["status"], "incomplete")
        self.assertEqual(expired["selected"], [])
        timed = run(self.request, FixtureProvider(), FixedSchedule(("text",)),
                    self.root / "timed", deadline_seconds=1e-12)
        self.assertEqual(timed["status"], "timeout")
        self.assertIn("timeout", [e["status"] for e in timed["events"]])

    def test_missing_dependencies_and_changed_source_refuse_with_receipt(self):
        result = self.execute(("refine", "stop"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["artifacts"], [])
        Path(self.request.image_path).write_bytes(b"changed")
        backend = FixtureProvider()
        result = run(self.request, backend, FixedSchedule(("stop",)), self.root / "changed")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(backend.calls, [])

    def test_controller_receives_only_frozen_public_view(self):
        seen = []
        class Policy:
            def choose(self, view):
                seen.append(view)
                return "stop"
        result = run(self.request, FixtureProvider(), Policy(), self.root / "public")
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(seen[0].history, ())
        self.assertFalse(any(hasattr(seen[0], n) for n in ("reference", "target", "world", "score")))

    def test_finalization_timeout_and_cancel_cannot_publish_delivery(self):
        for outcome in ("timeout", "cancelled"):
            clock = [0.0]
            class FinalProvider(FixtureProvider):
                count = 0
                def identity(self):
                    self.count += 1
                    if self.count == 2:
                        if outcome == "cancelled":
                            raise KeyboardInterrupt()
                        clock[0] = 2.0
                    return super().identity()
            with self.subTest(outcome=outcome), patch(
                "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.dual_runtime.time.perf_counter",
                side_effect=lambda: clock[0]
            ):
                folder = self.root / outcome
                result = run(self.request, FinalProvider(), FixedSchedule(("text", "draft", "stop")),
                             folder, deadline_seconds=1.0)
                self.assertEqual(result["status"], outcome)
                self.assertEqual(result["selected"], [])
                self.assertIn(outcome, [e["status"] for e in result["events"]])
                self.assertTrue((folder / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
