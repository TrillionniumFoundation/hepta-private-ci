"""Synthetic integrity controls of the actual runner, not model/effect tests."""

from dataclasses import fields
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from . import dual_runtime
from .transition_capture import DevelopmentSource, TransitionCapture, file_identity
from .transition_capture_read import read_capture


class SyntheticBackend:
    def __init__(self, draw_error=None):
        self.calls = []
        self.draw_error = draw_error

    def identity(self):
        self.calls.append(("identity",))
        return {"synthetic_control_backend": True, "real_model_calls": 0}

    def describe(self, image, prompt):
        self.calls.append(("describe", Path(image).name, prompt))
        return f"public observation {len(self.calls)}"

    def draw(self, prompt, path, seed, initial_image=None):
        self.calls.append(("draw", prompt, seed, Path(initial_image).name if initial_image else None))
        if self.draw_error is not None:
            Path(path).write_bytes(b"partial synthetic output")
            raise self.draw_error
        Image.new("RGB", (2, 2), (seed % 256, 10, 30)).save(path)
        return {"synthetic_control_only": True, "seed": seed}

    def synchronize(self):
        self.calls.append(("synchronize",))


class TransitionCaptureTests(unittest.TestCase):
    # The standalone source-review runner may retain synthetic case artifacts.
    # Ordinary unittest invocation uses an automatically cleaned private tempdir.
    evidence_parent = None

    def setUp(self):
        if self.evidence_parent is None:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        else:
            self.root = Path(self.evidence_parent) / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=False)
        self.image = self.root / "synthetic-input.png"
        Image.new("RGB", (2, 2), (10, 20, 30)).save(self.image)
        self.request = dual_runtime.Request("synthetic-control", str(self.image),
                                            file_identity(self.image)["sha256"], "Describe visible shapes.")
        self.source = DevelopmentSource("development", self.request.source_id, self.request.image_sha256,
                         hashlib.sha256(self.request.instruction.encode()).hexdigest(),
                         hashlib.sha256(b"synthetic declared roster; no labels").hexdigest())
        self.sequence = 0

    def run_case(self, actions, *, backend=None, controller=None, captured=True, **kwargs):
        out = self.root / f"run-{self.sequence}"
        self.sequence += 1
        backend = backend or SyntheticBackend()
        recorder = TransitionCapture(self.source) if captured else None
        report = dual_runtime.run(self.request, backend,
            controller or dual_runtime.FixedSchedule(actions), out, recorder=recorder, **kwargs)
        return out, report, backend, recorder

    def test_observation_preserves_actual_choices_calls_and_output_bytes(self):
        actions = ("perceive", "text", "draft", "verify", "stop")
        plain, original, a, _ = self.run_case(actions, captured=False)
        traced, actual, b, _ = self.run_case(actions)
        self.assertEqual(a.calls, b.calls)
        for key in ("status", "error", "selected", "history", "artifacts", "retained_files"):
            self.assertEqual(original[key], actual[key])
        captured = read_capture(traced)
        self.assertEqual(captured["report"], json.loads((traced / "report.json").read_bytes()))
        self.assertEqual([row["choice"] for row in captured["transitions"]], list(actions))
        self.assertEqual(set(captured["transitions"][0]["before_view"]),
                         {field.name for field in fields(dual_runtime.View)})
        self.assertFalse((plain / "transition_capture").exists())
        self.assertEqual(captured["journal"][-2]["phase"], "episode_end")
        for event in actual["events"]:
            self.assertGreaterEqual(event["wall_seconds"], 0)
        self.assertTrue(any(cost["placement"] == "after_original_event_clock"
                            for cost in captured["summary"]["observation_costs"]))
        self.assertFalse(captured["training_performed"])

    def test_plan_invalidation_retains_old_work_and_actual_refinement_source(self):
        actions = ("perceive", "text", "draft", "revise", "text", "refine", "stop")
        out, report, backend, _ = self.run_case(actions)
        captured = read_capture(out)
        revision = captured["transitions"][3]
        self.assertEqual((revision["before_view"]["plan_version"],
                          revision["actual_after_state"]["plan_version"]), (1, 2))
        self.assertIsNone(revision["actual_after_state"]["text"])
        self.assertIsNone(revision["actual_after_state"]["image_path"])
        self.assertEqual(Path(revision["actual_after_state"]["last_image"]).name, "02-draft.png")
        self.assertEqual([item["path"] for item in report["selected"]], ["04-text.txt", "05-refine.png"])
        self.assertEqual([call[-1] for call in backend.calls if call[0] == "draw"], [None, "02-draft.png"])
        self.assertIn("02-draft.png", [item["path"] for item in captured["summary"]["result"]["unselected_retained_files"]])
        # Earlier View was copied before the later plan/file changes.
        self.assertEqual(captured["transitions"][2]["before_view"]["plan_version"], 1)

    def test_initial_stop_is_recorded_abstention_and_no_generator(self):
        out, report, backend, _ = self.run_case(("stop",))
        captured = read_capture(out)
        self.assertEqual((report["status"], report["selected"]), ("abstained", []))
        self.assertFalse(any(call[0] in ("draw", "describe") for call in backend.calls))
        self.assertEqual(captured["transitions"][0]["actual_after_state"]["episode_status_so_far"], "abstained")

    def test_partial_backend_failures_preserve_work_and_never_invent_after(self):
        for error, status in ((ValueError("failed draw"), "failed"),
                              (TimeoutError("provider timeout"), "timeout"),
                              (KeyboardInterrupt("cancelled draw"), "cancelled")):
            with self.subTest(status=status):
                out, report, backend, _ = self.run_case(("draft", "stop"), backend=SyntheticBackend(error))
                captured = read_capture(out)
                self.assertEqual(report["status"], status)
                self.assertEqual(len([call for call in backend.calls if call[0] == "draw"]), 1)
                self.assertEqual(captured["transitions"][0]["phase"], "before_action")
                self.assertNotIn("actual_after_state", captured["transitions"][0])
                self.assertEqual(captured["summary"]["result"]["unselected_retained_files"], report["retained_files"])
                self.assertEqual(report["retained_files"][0]["path"], "00-draft.png")
                self.assertEqual(report["artifacts"], [])

    def test_controller_failure_and_invalid_action_have_no_backend_operation(self):
        class Controller:
            def __init__(self, error): self.error = error
            def choose(self, view):
                if self.error: raise RuntimeError("controller failed")
                return "unregistered-action"
        for error in (True, False):
            with self.subTest(controller_raises=error):
                out, report, backend, _ = self.run_case((), controller=Controller(error))
                captured = read_capture(out)
                self.assertEqual(report["status"], "failed")
                self.assertNotIn("actual_after_state", captured["transitions"][0])
                self.assertFalse(any(call[0] in ("draw", "describe") for call in backend.calls))

    def test_after_controller_deadline_remains_original_no_action_boundary(self):
        # This control uses a synthetic clock offset, not a physical latency result.
        real = dual_runtime.time
        offset = [0.0]
        clock = SimpleNamespace(process_time=real.process_time,
                                perf_counter=lambda: real.perf_counter() + offset[0])
        class Controller:
            def choose(self, view):
                offset[0] = 1000.0
                return "draft"
        with patch.object(dual_runtime, "time", clock):
            out, report, backend, _ = self.run_case((), controller=Controller(), deadline_seconds=100)
        captured = read_capture(out)
        self.assertEqual(report["status"], "timeout")
        self.assertEqual(captured["transitions"][0]["phase"], "choice")
        self.assertFalse(any(call[0] in ("draw", "describe") for call in backend.calls))
        self.assertTrue(any(e["detail"] == {"check": "after_controller"} for e in report["events"]))

    def test_after_action_return_is_not_final_delivery_when_deadline_expires(self):
        real = dual_runtime.time
        offset = [0.0]
        clock = SimpleNamespace(process_time=real.process_time,
                                perf_counter=lambda: real.perf_counter() + offset[0])
        class Backend(SyntheticBackend):
            def draw(self, *args, **kwargs):
                result = super().draw(*args, **kwargs)
                offset[0] = 1000.0
                return result
        with patch.object(dual_runtime, "time", clock):
            out, report, _, _ = self.run_case(("draft", "stop"), backend=Backend(), deadline_seconds=100)
        captured = read_capture(out)
        self.assertEqual((report["status"], report["selected"]), ("timeout", []))
        self.assertIn("actual_after_state", captured["transitions"][0])
        self.assertTrue(any(e["detail"] == {"check": "after_action"} for e in report["events"]))

    def test_recorder_write_failure_preserves_episode_but_fences_capture(self):
        recorder = TransitionCapture(self.source)
        original = recorder._append
        def fail(phase, payload, placement):
            if phase == "choice":
                with (recorder._directory / "transitions.jsonl").open("ab") as handle:
                    handle.write(b'{"partial":')
                raise OSError("synthetic storage failure after partial append")
            return original(phase, payload, placement)
        recorder._append = fail
        backend = SyntheticBackend()
        out = self.root / "write-failure"
        report = dual_runtime.run(self.request, backend,
                                 dual_runtime.FixedSchedule(("text", "draft", "stop")), out, recorder=recorder)
        self.assertEqual(report["status"], "delivered")
        self.assertEqual(len([call for call in backend.calls if call[0] == "draw"]), 1)
        self.assertEqual(recorder.summary["status"], "INCOMPLETE")
        self.assertEqual(recorder.summary["fault"]["phase"], "choice")
        with self.assertRaises(ValueError): read_capture(out)

    def test_missing_or_modified_evidence_cannot_become_complete(self):
        original, _, _, _ = self.run_case(("perceive", "text", "draft", "stop"))
        for change in ("row_removed", "row_repeated", "partial_line", "report_changed", "old_file_missing", "no_close_receipt"):
            with self.subTest(change=change):
                out = self.root / change
                shutil.copytree(original, out)
                journal = out / "transition_capture/transitions.jsonl"
                lines = journal.read_bytes().splitlines(keepends=True)
                if change == "row_removed": journal.write_bytes(b"".join(lines[:2] + lines[3:]))
                if change == "row_repeated": journal.write_bytes(b"".join(lines[:2] + [lines[1]] + lines[2:]))
                if change == "partial_line": journal.write_bytes(journal.read_bytes()[:-4])
                if change == "report_changed": (out / "report.json").write_bytes(b"{}\n")
                if change == "old_file_missing": (out / "00-perceive.txt").unlink()
                if change == "no_close_receipt": (out / "transition_capture/summary_write_cost.json").unlink()
                with self.assertRaises((ValueError, FileNotFoundError, json.JSONDecodeError)):
                    read_capture(out)

    def test_development_binding_and_single_use_reject_without_backend_replay(self):
        with self.assertRaises(ValueError):
            DevelopmentSource("test", self.source.source_id, self.source.image_sha256,
                              self.source.instruction_sha256, self.source.roster_sha256)
        recorder = TransitionCapture(self.source)
        wrong = dual_runtime.Request("other-source", self.request.image_path,
                                     self.request.image_sha256, self.request.instruction)
        backend = SyntheticBackend()
        with self.assertRaises(ValueError):
            dual_runtime.run(wrong, backend, dual_runtime.FixedSchedule(("stop",)),
                             self.root / "rejected", recorder=recorder)
        self.assertEqual(backend.calls, [])
        out, _, _, used = self.run_case(("stop",))
        before = file_identity(out / "transition_capture/transitions.jsonl")
        with self.assertRaises(ValueError):
            dual_runtime.run(self.request, backend, dual_runtime.FixedSchedule(("stop",)),
                             self.root / "reuse", recorder=used)
        self.assertEqual(backend.calls, [])
        self.assertEqual(file_identity(out / "transition_capture/transitions.jsonl"), before)
        self.assertFalse((self.root / "reuse").exists())

    def test_changed_output_before_stop_retains_original_hash_rejection(self):
        class Controller(dual_runtime.FixedSchedule):
            def choose(self, view):
                choice = super().choose(view)
                if choice == "stop":
                    path = Path(view.image_path)
                    path.write_bytes(path.read_bytes() + b"changed after draft")
                return choice
        out, report, _, _ = self.run_case((), controller=Controller(("text", "draft", "stop")))
        captured = read_capture(out)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error"]["message"], "Candidate bytes changed before delivery")
        self.assertNotIn("actual_after_state", captured["transitions"][-1])
        self.assertEqual(report["selected"], [])

    def test_preflight_failure_is_observed_without_fabricated_transition(self):
        self.image.write_bytes(b"changed input bytes")
        out, report, backend, _ = self.run_case(("stop",))
        captured = read_capture(out)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(captured["transitions"], [])
        self.assertFalse(any(call[0] in ("draw", "describe") for call in backend.calls))
        self.assertEqual(captured["summary"]["result"]["request_file"], None)

    def test_changed_observed_source_fences_capture_without_rewriting_episode(self):
        observed = self.root / "observed-runtime.py"
        observed.write_bytes(Path(dual_runtime.__file__).read_bytes())
        class Backend(SyntheticBackend):
            def draw(self, *args, **kwargs):
                result = super().draw(*args, **kwargs)
                observed.write_bytes(observed.read_bytes() + b"\n# changed after the recorded source pin\n")
                return result
        # Only the observed copy changes; the imported code and candidate file
        # are never modified by this source-identity fault injection.
        with patch.object(dual_runtime, "__file__", str(observed)):
            out, report, _, recorder = self.run_case(("text", "draft", "stop"), backend=Backend())
        self.assertEqual(report["status"], "delivered")
        self.assertEqual(recorder.summary["status"], "INCOMPLETE")
        self.assertEqual(recorder.summary["fault"]["message"], "Runtime or recorder source changed during capture")
        with self.assertRaises(ValueError): read_capture(out)


if __name__ == "__main__":
    unittest.main()
