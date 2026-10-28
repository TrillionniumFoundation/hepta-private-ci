"""Regressions for provenance accounting and final qualification exit status.

The process/model boundaries are deliberately mocked: transport and real-tool
validation have separate tests. These cases exercise the benchmark's complete
report/exit path, including warmup and retained negative rows.
"""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import benchmark


class BenchmarkGateTests(unittest.TestCase):
    def exercise(self, lane="native", *, answer='{"sum":6}', feedback=True, inventory=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            fixture.mkdir()
            (fixture / "fixture.txt").write_text("1\n2\n3\n")
            (fixture / "fixture_tool.py").write_text("# Synthetic test fixture\n")
            binaries = {}
            for name in ("native", "codex", "facade"):
                binaries[name] = root / name
                binaries[name].write_bytes((name + "-fixture").encode())
            args = SimpleNamespace(
                lane=lane, mode="replay", output=root / "run", fixture=fixture,
                upstream="http://127.0.0.1:1/v1", repeats=1, timeout=1,
                tasks=["sum"], warmup=True, **binaries)
            window = {"active": False}
            hashed = []
            real_digest = benchmark.digest

            def checked_digest(path):
                self.assertFalse(window["active"], "provenance entered the measured resource window")
                hashed.append(path)
                return real_digest(path)

            class Metrics:
                def __init__(self, **_):
                    pass

                def start(self):
                    window["active"] = True
                    return self

                def stop(self):
                    window["active"] = False
                    return {"test": "resource-window probe"}

            class Gateway:
                def __init__(self, *_args, **_kwargs):
                    self.url = "http://127.0.0.1:1/v1"
                    self.records = []

                def begin(self, *_):
                    pass

                def close(self):
                    pass

            class Process:
                def __init__(self, *_args, **_kwargs):
                    self.command = None

                def send(self, command):
                    self.command = command

                def receive(self, _deadline):
                    if self.command is None:
                        return {"ready": True, "protocol": "qualification.jsonl.v1", "tools": [{}]}
                    return {"status": "completed", "session": self.command["session"],
                            "answer": answer, "tool_calls": 1}

                def close(self):
                    pass

            class Driver:
                def __init__(self, *_args):
                    self.initialize_response = {"test": "initialized"}

                def run(self, _session, _prompt, **_kwargs):
                    return {"status": "completed", "answer": answer, "tool_calls": 1}

            groups = SimpleNamespace(parent=None, known={}, errors=[], scopes=lambda: [])
            replacements = {
                "ModelGateway": Gateway, "JsonProcess": Process, "CodexDriver": Driver,
                "ProcessMetrics": Metrics, "RuntimeGroups": lambda _: groups,
                "digest": checked_digest, "capture_settled": lambda *_: True,
                "audit_tool_feedback": lambda *_: {"valid": feedback},
                "inventory": lambda _: [{"only_shared_tool": inventory}],
            }
            original_umask = os.umask(0o077)
            try:
                with ExitStack() as stack:
                    for name, replacement in replacements.items():
                        stack.enter_context(patch.object(benchmark, name, replacement))
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    code = benchmark.run(args)
            finally:
                os.umask(original_umask)
            report = json.loads((args.output / "REPORT.json").read_text())
            self.assertFalse(window["active"])
            self.assertEqual(report["summary"]["planned"], 1)
            self.assertEqual(report["summary"]["attempted"], 1)
            self.assertEqual([row["warmup"] for row in report["rows"]], [True, False])
            return code, report, {path.name for path in hashed}

    def test_all_lane_provenance_is_outside_resource_window(self):
        for lane, executor in (("native", "native"), ("app-server", "codex"), ("facade", "facade")):
            with self.subTest(lane=lane):
                code, report, hashed = self.exercise(lane)
                self.assertEqual(code, 0)
                self.assertTrue(report["summary"]["qualification_passed"])
                self.assertTrue({"fixture.txt", "fixture_tool.py", "native", executor} <= hashed)

    def test_completed_but_failed_qualification_exits_nonzero_and_keeps_rows(self):
        for failure in ({"answer": '{"sum":999}'}, {"feedback": False}, {"inventory": False}):
            with self.subTest(failure=failure):
                code, report, _ = self.exercise(**failure)
                self.assertEqual(code, 1)
                self.assertTrue(report["summary"]["completed_lane"])
                self.assertFalse(report["summary"]["qualification_passed"])
                self.assertEqual(len(report["rows"]), 2)
                self.assertTrue(all("tool_feedback_audit" in row for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()
