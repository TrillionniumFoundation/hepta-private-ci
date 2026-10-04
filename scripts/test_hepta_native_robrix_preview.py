import copy
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import unittest
import tempfile
import subprocess
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "preview", ROOT / "apps/hepta-native/tools/linux_robrix_preview.py"
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.startup = {
            "gui_frame_callback_completed": True,
            "session": {"session_id": "s1", "generation": 2},
            "view_digest": "digest",
            "view_revision": 4,
        }
        identity = {
            "sessionId": "s1",
            "sessionGeneration": 2,
            "generation": 3,
            "revision": 4,
            "digest": "digest",
            "modules": ["runtime"],
        }
        self.draw = {
            "event": "status_draw_list",
            "identity": identity,
            "callback": 1,
            "glyphCount": 30,
            "status": "Verified runtime · session s1",
            "statusRect": [10, 750, 600, 20],
            "captionCloseRect": [1200, 0, 40, 30],
            "innerSize": [1280, 800],
            "dpi": 1,
        }
        self.records = [
            self.draw,
            {"event": "later_callback", "identity": identity, "callback": 2},
        ]
        self.closing = [
            {"event": "close_requested", "cause": "os"},
            {
                "event": "renderer_exit",
                "runtimeClosed": True,
                "allTasksIdle": True,
                "activationRequested": False,
            },
            {"event": "gui_loop_returned", "activationRequested": False},
        ]

    def test_failed_startup_capture_is_unqualified_and_process_scoped(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if command[0] == "import":
                    Path(command[-1]).write_bytes(b"diagnostic fixture pixels")
                return subprocess.CompletedProcess(command, 0, "456\n", "")

            m.capture_failed_startup(out, 0, process, {}, run)
            record = json.loads((out / "session-0-failed-startup.json").read_text())
            self.assertEqual(
                record,
                {
                    "qualified": False,
                    "captured": True,
                    "pngSha256": m.digest(out / "session-0-failed-startup.png"),
                },
            )
            self.assertEqual(
                commands[0], ["xdotool", "search", "--onlyvisible", "--pid", "123"]
            )
            self.assertEqual(commands[1][:3], ["import", "-window", "456"])
            self.assertFalse((out / "preview-receipt.json").exists())

    def test_failed_startup_capture_rejects_absent_ambiguous_or_invalid_window(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        for windows in ["", "456\n789\n", "-root"]:
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                run = Mock(return_value=subprocess.CompletedProcess([], 0, windows, ""))
                m.capture_failed_startup(out, 0, process, {}, run)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(
                    json.loads((out / "session-0-failed-startup.json").read_text()),
                    {
                        "qualified": False,
                        "captured": False,
                        "errorType": "ValueError",
                    },
                )
                self.assertFalse(list(out.glob("*.png")))

    def test_failed_startup_capture_does_not_replace_original_error(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        run = Mock(side_effect=RuntimeError("private tool output must not leak"))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            m.capture_failed_startup(out, 0, process, {}, run)
            text = (out / "session-0-failed-startup.json").read_text()
            self.assertNotIn("private", text)
            self.assertEqual(
                json.loads(text),
                {
                    "qualified": False,
                    "captured": False,
                    "errorType": "RuntimeError",
                },
            )

    def test_failed_startup_capture_never_captures_an_exited_process(self):
        process = Mock(pid=123)
        process.poll.return_value = 0
        run = Mock()
        with tempfile.TemporaryDirectory() as directory:
            m.capture_failed_startup(Path(directory), 0, process, {}, run)
            run.assert_not_called()

    def test_failed_startup_receipt_write_does_not_mask_readiness_error(self):
        process = Mock(pid=123)
        process.poll.return_value = 0
        with patch.object(m, "write_json", side_effect=OSError("private path")):
            with patch("sys.stderr") as stderr:
                m.capture_failed_startup(Path("unused"), 0, process, {}, Mock())
                self.assertNotIn("private", str(stderr.write.call_args_list))

    def test_rejected_glyph_diagnostics_cannot_replace_complete_draw_witness(self):
        # Actual first-glyph bounds from the failing Linux renderer: the quad
        # extends 1.4133 pixels beyond the status turtle's left clip boundary.
        diagnostic = {
            "event": "glyph_rejected",
            "index": 0,
            "rect": [6.586666584014893, 9.083332061767578, 11.25, 12.916666030883789],
            "clipped": [8.0, 9.083332061767578, 9.836666584014893, 12.916666030883789],
            "innerSize": [1280.0, 800.0],
        }
        records = [diagnostic, self.records[1]]
        with self.assertRaises(ValueError):
            m.ready_observation(records, self.startup)

    def test_status_ocr_crop_uses_only_bound_pixels_and_actual_dpi(self):
        self.assertEqual(m.status_ocr_crop(self.draw), "600x20+10+750")
        self.draw["dpi"] = 2
        self.assertEqual(m.status_ocr_crop(self.draw), "1200x40+20+1500")
        self.draw["statusRect"] = [10.25, 15.25, 20.5, 10.5]
        self.assertEqual(m.status_ocr_crop(self.draw), "42x22+20+30")
        for dpi in [0, -1, True, float("nan"), float("inf")]:
            self.draw["dpi"] = dpi
            with self.assertRaises(ValueError):
                m.status_ocr_crop(self.draw)
        self.draw["dpi"] = 1
        self.draw["statusRect"] = [-1, 0, 20, 10]
        with self.assertRaises(ValueError):
            m.status_ocr_crop(self.draw)

    def test_status_and_desktop_labels_are_independently_required(self):
        m.verify_ocr_labels(
            "Verified runtime - session s1", "Conversation Console Aurora Graphite"
        )
        for status, window in [
            ("", "Verified runtime Conversation Aurora"),
            ("Verified runtime", "Console Aurora"),
            ("Verified runtime", "Conversation Console"),
            ("Unverified runtime", "Conversation Aurora"),
        ]:
            with self.assertRaises(ValueError):
                m.verify_ocr_labels(status, window)

    def test_actual_event_parser_rejects_malformed_observation(self):
        self.assertEqual(
            m.observations("unrelated\n" + m.PREFIX + json.dumps(self.draw)),
            [self.draw],
        )
        for value in ["[]", "{}", "invalid"]:
            with self.assertRaises(ValueError):
                m.observations(m.PREFIX + value)

    def test_matching_status_and_later_callback(self):
        self.assertEqual(m.ready_observation(self.records, self.startup), self.draw)

    def test_stale_view_or_callback_rejected(self):
        for field, value in [
            ("sessionId", "s2"),
            ("sessionGeneration", 9),
            ("digest", "other"),
            ("revision", 99),
        ]:
            records = copy.deepcopy(self.records)
            records[0]["identity"][field] = value
            with self.assertRaises(ValueError):
                m.ready_observation(records, self.startup)
        for value in [0, 1, True]:
            records = copy.deepcopy(self.records)
            records[1]["callback"] = value
            with self.assertRaises(ValueError):
                m.ready_observation(records, self.startup)
        with self.assertRaises(ValueError):
            m.ready_observation(self.records[::-1], self.startup)

    def test_no_glyphs_wrong_status_and_nonfinite_dpi_rejected(self):
        for key, value in [
            ("glyphCount", 0),
            ("status", "waiting"),
            ("dpi", float("nan")),
            ("dpi", 0),
        ]:
            records = copy.deepcopy(self.records)
            records[0][key] = value
            with self.assertRaises(ValueError):
                m.ready_observation(records, self.startup)

    def test_outside_or_absent_real_geometry_rejected(self):
        for rect in [
            None,
            [0, 0, 0, 2],
            [-1, 0, 20, 20],
            [1270, 0, 30, 20],
            [0, 790, 20, 30],
            [0, 0, float("inf"), 1],
        ]:
            for field in ["statusRect", "captionCloseRect"]:
                if field == "captionCloseRect" and rect is None:
                    continue
                records = copy.deepcopy(self.records)
                records[0][field] = rect
                with self.assertRaises(ValueError):
                    m.ready_observation(records, self.startup)

    def test_capture_geometry_uses_actual_dpi_and_window_size(self):
        self.assertEqual(m.capture_geometry(self.draw, 1280, 800), [1220, 15])
        with self.assertRaises(ValueError):
            m.capture_geometry(self.draw, 1400, 900)

    def test_ci_subject_and_merge_parents_are_exact(self):
        env = {
            "SOURCE_SHA": "1" * 40,
            "BASE_SHA": "2" * 40,
            "WORKFLOW_SHA": "3" * 40,
            "TESTED_SHA": "1" * 40,
            "HEPTA_CI_LANE": "source-head",
            "GITHUB_RUN_ID": "1",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        with patch.dict(m.os.environ, env, clear=True):
            self.assertEqual(
                m.ci_identity(Path("/repo"), "1" * 40, "4" * 40)["SOURCE_SHA"], "1" * 40
            )
            with self.assertRaises(ValueError):
                m.ci_identity(Path("/repo"), "5" * 40, "4" * 40)
        env.update(HEPTA_CI_LANE="base-merge", TESTED_SHA="5" * 40)
        with (
            patch.dict(m.os.environ, env, clear=True),
            patch.object(
                m.subprocess, "check_output", return_value="2" * 40 + " " + "1" * 40
            ),
        ):
            self.assertEqual(
                m.ci_identity(Path("/repo"), "5" * 40, "4" * 40)["HEPTA_CI_LANE"],
                "base-merge",
            )
        with (
            patch.dict(m.os.environ, env, clear=True),
            patch.object(m.subprocess, "check_output", return_value="1" * 40),
        ):
            with self.assertRaises(ValueError):
                m.ci_identity(Path("/repo"), "5" * 40, "4" * 40)

    def test_renderer_errors_never_become_success(self):
        for text in [
            "thread main panicked at",
            "ScriptError: missing value",
            "shader compilation failed",
            "Unknown os op: x",
        ]:
            with self.assertRaises(ValueError):
                m.check_health(text)

    def test_command_capture_retains_failure_and_redacts_credential_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = m.RecordedCommands(Path(tmp))
            result = subprocess.CompletedProcess(
                ["ordinary"], 3, "ordinary stdout", "ordinary stderr"
            )
            with (
                patch.object(m.subprocess, "run", return_value=result),
                self.assertRaises(RuntimeError),
            ):
                runner(["ordinary"])
            record = json.loads((Path(tmp) / "command-001.json").read_text())
            self.assertEqual(
                (record["exitCode"], record["stdout"], record["stderr"]),
                (3, "ordinary stdout", "ordinary stderr"),
            )
            result = subprocess.CompletedProcess(
                ["credential"], 1, "SECRET", "PRIVATE KEY"
            )
            with (
                patch.object(m.subprocess, "run", return_value=result),
                self.assertRaises(RuntimeError),
            ):
                runner(["/bin/hepta-native-credential", "provision", "test-account"])
            saved = (Path(tmp) / "command-002.json").read_text()
            self.assertNotIn("SECRET", saved)
            self.assertNotIn("PRIVATE KEY", saved)
            self.assertTrue(json.loads(saved)["credentialStreamsRedacted"])
            value = {
                "schema": "hepta.native-gateway-credential-provision.v1",
                "account": "test-account",
                "token_digest": "a" * 64,
            }
            result = subprocess.CompletedProcess([], 0, json.dumps(value), "SECRET")
            with patch.object(m.subprocess, "run", return_value=result):
                runner(["/bin/hepta-native-credential", "provision", "test-account"])
            record = json.loads((Path(tmp) / "command-003.json").read_text())
            self.assertEqual(record["safeReceipt"], value)
            self.assertNotIn("stderr", record)
            value["token"] = "SECRET"
            result.stdout = json.dumps(value)
            with (
                patch.object(m.subprocess, "run", return_value=result),
                self.assertRaises(RuntimeError),
            ):
                runner(["/bin/hepta-native-credential", "provision", "test-account"])
            self.assertNotIn("SECRET", (Path(tmp) / "command-004.json").read_text())

    def test_command_spawn_failure_is_retained_without_private_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = m.RecordedCommands(Path(tmp))
            with (
                patch.object(
                    m.subprocess, "run", side_effect=FileNotFoundError("SECRET")
                ),
                self.assertRaises(RuntimeError),
            ):
                runner(["missing-command"])
            text = (Path(tmp) / "command-001.json").read_text()
            self.assertNotIn("SECRET", text)
            self.assertTrue(json.loads(text)["startFailed"])
            self.assertIsNone(json.loads(text)["exitCode"])

    def test_cleanup_runs_every_action_after_an_earlier_failure(self):
        observed = []

        def failing():
            observed.append("gui")
            raise RuntimeError("SECRET diagnostic must not escape cleanup")

        def succeeding():
            observed.append("keyring")
            return {"returnCode": 0}

        results = m.cleanup_independently([("gui", failing), ("keyring", succeeding)])
        self.assertEqual(observed, ["gui", "keyring"])
        self.assertFalse(results[0]["passed"])
        self.assertTrue(results[1]["passed"])
        self.assertNotIn("SECRET", json.dumps(results))

    def test_existing_inventory_junit_verifier_requires_all_preview_cases(self):
        root = Path(os.environ.get("HEPTA_PREVIEW_TEST_SOURCE_ROOT", ROOT))
        sys.path.insert(0, str(root / "scripts"))
        try:
            spec = importlib.util.spec_from_file_location(
                "actual_native_verifier", root / "scripts/hepta_native_lifecycle_ci.py"
            )
            verifier = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
        finally:
            sys.path.pop(0)
        required = verifier.REQUIRED | m.PREVIEW_REQUIRED
        cases = {}
        for binary, name in required | verifier.IGNORED:
            cases.setdefault(binary, {"status": "listed", "testcases": {}})[
                "testcases"
            ][name] = {
                "ignored": (binary, name) in verifier.IGNORED,
                "filter-match": {"status": "matches"},
            }
        inventory = {
            "test-count": len(required | verifier.IGNORED),
            "rust-suites": cases,
        }

        def xml(exclude=None):
            document = ET.Element("testsuites", failures="0", errors="0")
            suite = ET.SubElement(document, "testsuite")
            for binary, name in required:
                if (binary, name) != exclude:
                    ET.SubElement(suite, "testcase", classname=binary, name=name)
            return ET.tostring(document)

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            inv, junit, receipt = (
                directory / "inventory.json",
                directory / "junit.xml",
                directory / "receipt.json",
            )
            inv.write_text(json.dumps(inventory))
            junit.write_bytes(xml())
            with (
                patch.object(m.subprocess, "check_output", return_value="1" * 40),
                patch.object(m, "ci_identity", return_value={"tested": "subject"}),
            ):
                result = m.verify_preview_tests(root, inv, junit, receipt)
                self.assertEqual(result["result"]["passed"], len(required))
                self.assertFalse(result["rendererObserved"])
                for missing in m.PREVIEW_REQUIRED:
                    receipt.unlink(missing_ok=True)
                    junit.write_bytes(xml(missing))
                    with self.assertRaises(ValueError):
                        m.verify_preview_tests(root, inv, junit, receipt)
                    self.assertFalse(receipt.exists())

    def test_x11_absent_caption_is_not_fabricated(self):
        self.draw["captionCloseRect"] = None
        self.assertEqual(m.ready_observation(self.records, self.startup), self.draw)
        self.assertIsNone(m.capture_geometry(self.draw, 1280, 800))

    def test_real_close_drain_and_return_required(self):
        self.assertEqual(m.validate_exit(self.closing, "os"), self.closing)
        for records in [
            self.closing[:-1],
            self.closing[::-1],
            self.closing + [self.closing[-1]],
        ]:
            with self.assertRaises(ValueError):
                m.validate_exit(records, "os")
        with self.assertRaises(ValueError):
            m.validate_exit(self.closing, "caption")
        for field in ["runtimeClosed", "allTasksIdle"]:
            records = copy.deepcopy(self.closing)
            records[1][field] = False
            with self.assertRaises(ValueError):
                m.validate_exit(records, "os")
        for i in [1, 2]:
            records = copy.deepcopy(self.closing)
            records[i]["activationRequested"] = True
            with self.assertRaises(ValueError):
                m.validate_exit(records, "os")


if __name__ == "__main__":
    unittest.main()
