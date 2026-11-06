"""Synthetic-clock controls for actual recorder overhead and admission.

No provider, model, reference label or training is used. Actual recorder fsync
runs; a logical elapsed clock then advances by the declared delay.
"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from . import dual_runtime as runtime
from . import transition_capture as capture
from .transition_capture_read import read_capture


OBSERVATIONS = []


def exercise(phase, delay, *, recorded=True, controller_failure=False):
    clock = SimpleNamespace(now=0.0, phase=None, delayed=False, calls=[])

    def elapsed():
        clock.calls.append(("elapsed", clock.now))
        return clock.now

    def cpu():
        clock.calls.append(("synthetic_cpu", clock.now))
        return clock.now

    fake_time = SimpleNamespace(perf_counter=elapsed, process_time=cpu)
    controllers, providers, delays = [], [], []
    original_fsync = capture.os.fsync

    class Backend:
        def identity(self):
            return {"synthetic_backend_only": True, "actual_model_calls": 0}

        def describe(self, image_path, prompt):
            providers.append({"entered_at": clock.now, "prompt": prompt})
            return "synthetic shapes"

        def synchronize(self):
            return None

    class Controller:
        def choose(self, view):
            controllers.append({"entered_at": clock.now, "view": json.loads(json.dumps(vars(view))),
                                "actual_remaining_seconds": 1.0 - clock.now})
            if controller_failure:
                raise RuntimeError("declared synthetic controller failure")
            return "perceive" if not view.history else "stop"

    class DelayedCapture(capture.TransitionCapture):
        def observe(self, current_phase, *args, **kwargs):
            clock.phase = current_phase
            try:
                return super().observe(current_phase, *args, **kwargs)
            finally:
                clock.phase = None

    def fsync(fd):
        result = original_fsync(fd)
        if clock.phase == phase and not clock.delayed:
            delays.append({"phase": phase, "before": clock.now,
                           "logical_delay": delay, "real_fsync_returned": True})
            clock.now += delay
            clock.delayed = True
        return result

    with TemporaryDirectory(prefix="hepta-observer-admission-") as directory:
        root = Path(directory)
        image = root / "input.png"
        Image.new("RGB", (2, 2), (10, 20, 30)).save(image)
        request = runtime.Request("synthetic-development-only", str(image),
                                  hashlib.sha256(image.read_bytes()).hexdigest(),
                                  "Describe visible shapes.")
        kwargs = {}
        if recorded:
            source = capture.DevelopmentSource(
                "development", request.source_id, request.image_sha256,
                hashlib.sha256(request.instruction.encode()).hexdigest(),
                hashlib.sha256(b"synthetic fixture; no independent labels").hexdigest())
            kwargs["recorder"] = DelayedCapture(source)
        output = root / "run"
        with patch.object(runtime, "time", fake_time), patch.object(capture, "time", fake_time), \
                patch.object(capture.os, "fsync", fsync):
            report = runtime.run(request, Backend(), Controller(), output,
                                 seed=17, horizon=2, deadline_seconds=1.0, **kwargs)
        trace = read_capture(output) if recorded else None
        result = {"phase": phase, "delay": delay, "recorded": recorded,
                  "budget_seconds": 1.0, "controllers": controllers,
                  "providers": providers, "delays": delays, "clock_calls": clock.calls,
                  "report": report, "capture": trace, "actual_model_calls": 0}
        OBSERVATIONS.append(result)
        return result


class ObserverAdmissionTests(unittest.TestCase):
    def test_before_controller_delay_cannot_admit_an_expired_controller(self):
        actual = exercise("before_controller", 2.0)
        self.assertEqual(actual["controllers"], [],
                         "observer expiry must reject before controller entry")
        self.assertEqual(actual["providers"], [])
        self.assertEqual(actual["report"]["status"], "timeout")
        self.assertEqual([e["detail"] for e in actual["report"]["events"]
                          if e["action"] == "deadline"],
                         [{"check": "after_before_controller_capture"}])
        self.assertEqual(actual["capture"]["summary"]["status"], "COMPLETE")

    def test_before_action_delay_cannot_admit_an_expired_provider(self):
        actual = exercise("before_action", 2.0)
        self.assertEqual(len(actual["controllers"]), 1)
        self.assertEqual(actual["providers"], [],
                         "observer expiry must reject before provider entry")
        self.assertEqual(actual["report"]["status"], "timeout")
        self.assertEqual([e["detail"] for e in actual["report"]["events"]
                          if e["action"] == "deadline"],
                         [{"check": "after_before_action_capture"}])
        self.assertEqual(actual["capture"]["transitions"][0]["phase"], "before_action")

    def test_nonexpired_controller_receives_and_records_the_fresh_view(self):
        actual = exercise("before_controller", 0.25)
        first = actual["controllers"][0]
        self.assertEqual(first["entered_at"], 0.25)
        self.assertEqual(first["view"]["remaining_seconds"], 0.75,
                         "controller view must be refreshed after observer overhead")
        self.assertEqual(first["actual_remaining_seconds"], 0.75)
        transition = actual["capture"]["transitions"][0]
        self.assertEqual(transition["before_capture_view"]["remaining_seconds"], 1.0)
        self.assertEqual(transition["before_view"], first["view"])
        self.assertEqual(actual["report"]["status"], "abstained")
        self.assertEqual(len(actual["providers"]), 1)

    def test_controller_exception_preserves_the_actual_fresh_view(self):
        actual = exercise("before_controller", 0.25, controller_failure=True)
        self.assertEqual(actual["report"]["status"], "failed")
        self.assertEqual(actual["providers"], [])
        transition = actual["capture"]["transitions"][0]
        self.assertEqual(transition["before_view"]["remaining_seconds"], 0.75,
                         "controller exception must retain its actual fresh input")
        self.assertEqual(transition["before_capture_view"]["remaining_seconds"], 1.0)
        self.assertEqual(transition["before_view"], actual["controllers"][0]["view"])
        self.assertEqual(transition["failure_state"]["episode_error_so_far"]["type"],
                         "RuntimeError")

    def test_recorder_none_has_no_observer_delay_or_new_admission(self):
        actual = exercise("before_action", 2.0, recorded=False)
        self.assertEqual(actual["delays"], [])
        self.assertEqual(len(actual["controllers"]), 2)
        self.assertEqual(actual["providers"][0]["entered_at"], 0.0)
        self.assertEqual(actual["report"]["status"], "abstained")
        self.assertEqual(actual["report"]["wall_seconds"], 0.0)
        self.assertIsNone(actual["capture"])


if __name__ == "__main__":
    unittest.main()
