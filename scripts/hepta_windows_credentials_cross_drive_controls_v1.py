#!/usr/bin/env python3
"""Pure lexical regression controls for the admitted cross-drive successor.

Only the caller may invoke observe() once with its checked original collector
buffer, original cancellation observer and already-running absolute deadline.
No process/account/native command is started by these eight controls.
"""

import hashlib
import math
import ntpath
from pathlib import Path
import time
import types
import unittest
from unittest import mock


CONTROL_METHODS = (
    "test_windows_component_and_volume_boundaries",
    "test_bytes_preserve_strict_component_and_drive_rules",
    "test_mixed_bytes_and_text_keep_original_type_error",
    "test_invalid_pathlike_types_keep_original_type_error",
    "test_relative_paths_keep_the_original_normalization_contract",
    "test_same_drive_commonpath_failure_is_not_swallowed",
    "test_normalization_failure_is_not_swallowed",
    "test_foreign_volume_compiler_artifact_still_fails_the_original_gate",
)
_attempted = False
_control_candidate = None


def load_pinned_collector(raw, expected_sha256, source_name):
    if (
        not isinstance(raw, bytes)
        or len(raw) > 65536
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("control candidate bytes differ from the reviewed source")
    module = types.ModuleType("hepta_cross_drive_control_candidate")
    module.__file__ = source_name
    module.__package__ = ""
    exec(compile(raw, source_name, "exec"), module.__dict__)
    return module


class BeneathCrossDriveControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if _control_candidate is None:
            raise ValueError("controls require the original checked collector buffer")
        cls.collector = _control_candidate

    def setUp(self):
        # Replace this isolated candidate module's reference only. Do not
        # mutate the shared os module, ntpath globals, or a native owner.
        patch = mock.patch.object(
            self.collector, "os", types.SimpleNamespace(path=ntpath)
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_windows_component_and_volume_boundaries(self):
        rows = [
            ("same_drive_child", r"D:\repo\pkg\a.py", r"D:\repo", True),
            ("same_drive_equal", r"D:\repo", r"D:\repo", False),
            ("same_drive_prefix", r"D:\repository\a.py", r"D:\repo", False),
            ("same_drive_sibling", r"D:\other\a.py", r"D:\repo", False),
            ("case_normalized", r"d:\REPO\pkg\a.py", r"D:\repo", True),
            ("case_equal", r"d:\REPO", r"D:\repo", False),
            ("different_drive", r"C:\Python\Lib\a.py", r"D:\repo", False),
            ("different_drive_reverse", r"D:\repo\a.py", r"C:\Python", False),
            ("dot_escape", r"D:\repo\..\other\a.py", r"D:\repo", False),
            ("dot_child", r"D:\repo\pkg\..\a.py", r"D:\repo", True),
            ("separator_normalized", "D:/repo/pkg/a.py", r"d:\REPO", True),
            ("unc_child", r"\\host\share\repo\a.py", r"\\host\share\repo", True),
            ("unc_equal", r"\\host\share\repo", r"\\host\share\repo", False),
            ("unc_case", r"\\HOST\SHARE\repo\a.py", r"\\host\share\repo", True),
            (
                "unc_other_share",
                r"\\host\other\repo\a.py",
                r"\\host\share\repo",
                False,
            ),
            (
                "unc_other_host",
                r"\\other\share\repo\a.py",
                r"\\host\share\repo",
                False,
            ),
            ("unc_vs_drive", r"\\host\share\repo\a.py", r"D:\repo", False),
        ]
        for label, child, root, expected in rows:
            with self.subTest(label=label):
                self.assertIs(self.collector.beneath(child, root), expected)

    def test_bytes_preserve_strict_component_and_drive_rules(self):
        self.assertTrue(self.collector.beneath(rb"d:\REPO\a.py", rb"D:\repo"))
        self.assertFalse(self.collector.beneath(rb"D:\repo", rb"D:\repo"))
        self.assertFalse(self.collector.beneath(rb"D:\repository\a.py", rb"D:\repo"))
        self.assertFalse(self.collector.beneath(rb"C:\Python\a.py", rb"D:\repo"))

    def test_mixed_bytes_and_text_keep_original_type_error(self):
        for child, root in [
            (rb"D:\repo\a.py", r"D:\repo"),
            (r"D:\repo\a.py", rb"D:\repo"),
            (rb"C:\Python\a.py", r"D:\repo"),
            (r"C:\Python\a.py", rb"D:\repo"),
        ]:
            with self.subTest(child=child, root=root):
                with self.assertRaises(TypeError):
                    self.collector.beneath(child, root)

    def test_invalid_pathlike_types_keep_original_type_error(self):
        class InvalidPathLike:
            def __fspath__(self):
                return object()

        for child in [None, object(), InvalidPathLike()]:
            with self.subTest(child=type(child).__name__):
                with self.assertRaises(TypeError):
                    self.collector.beneath(child, r"D:\repo")

    def test_relative_paths_keep_the_original_normalization_contract(self):
        # The old predicate normalizes relative inputs with abspath; it never
        # claimed all relative strings were rejected. Compare that same-drive
        # contract without inventing a different current drive or changing cwd.
        for child, root in [
            ("child.py", "."),
            (".", "."),
            (r"pkg\..\child.py", "."),
            (r"..\outside.py", "."),
            (r"..\outside.py", ".."),
        ]:
            with self.subTest(child=child, root=root):
                left = ntpath.normcase(ntpath.abspath(child))
                right = ntpath.normcase(ntpath.abspath(root))
                self.assertEqual(
                    ntpath.splitdrive(left)[0], ntpath.splitdrive(right)[0]
                )
                expected = ntpath.commonpath((left, right)) == right and left != right
                self.assertIs(self.collector.beneath(child, root), expected)

    def test_same_drive_commonpath_failure_is_not_swallowed(self):
        commonpath = mock.Mock(side_effect=ValueError("original path failure"))
        paths = types.SimpleNamespace(
            abspath=ntpath.abspath,
            normcase=ntpath.normcase,
            splitdrive=ntpath.splitdrive,
            commonpath=commonpath,
        )
        with mock.patch.object(self.collector, "os", types.SimpleNamespace(path=paths)):
            with self.assertRaisesRegex(ValueError, "^original path failure$"):
                self.collector.beneath(r"D:\repo\a.py", r"D:\repo")
        commonpath.assert_called_once_with((r"d:\repo\a.py", r"d:\repo"))

    def test_normalization_failure_is_not_swallowed(self):
        paths = types.SimpleNamespace(
            abspath=mock.Mock(side_effect=OSError("original normalization failure")),
            normcase=ntpath.normcase,
            splitdrive=ntpath.splitdrive,
            commonpath=ntpath.commonpath,
        )
        with mock.patch.object(self.collector, "os", types.SimpleNamespace(path=paths)):
            with self.assertRaisesRegex(OSError, "^original normalization failure$"):
                self.collector.beneath(r"C:\Python\a.py", r"D:\repo")

    def test_foreign_volume_compiler_artifact_still_fails_the_original_gate(self):
        package = {"id": "sandbox-test-package"}
        workspace = r"D:\repo\codex-rs"
        row = {
            "reason": "compiler-artifact",
            "package_id": package["id"],
            "manifest_path": str(Path(workspace) / "windows-sandbox-rs/Cargo.toml"),
            "target": {
                "name": self.collector.HELPERS[0],
                "kind": ["bin"],
                "edition": "2024",
            },
            "profile": {"test": False},
            "executable": r"C:\outside\codex-windows-sandbox-setup.exe",
            "filenames": [r"C:\outside\codex-windows-sandbox-setup.exe"],
        }
        raw = (
            self.collector.json.dumps(row)
            + "\n"
            + self.collector.json.dumps({"reason": "build-finished", "success": True})
            + "\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(
            self.collector.CollectionFailure,
            "^compiler executable escaped the fresh target$",
        ):
            self.collector.compiler_artifacts(
                raw, package, workspace, r"D:\fresh-target", helpers=True
            )


def observe(collector_raw, expected_sha256, source_name, deadline, cancel, observation):
    global _attempted, _control_candidate
    if _attempted:
        raise ValueError("cross-drive controls may not be attempted twice")
    _attempted = True
    if not isinstance(observation, dict) or observation:
        raise ValueError("fresh control observation object required")
    observation.update(
        schema="hepta.windows_credentials.cross_drive_controls.v1",
        status="FAIL_OR_UNKNOWN",
        expected_methods=list(CONTROL_METHODS),
        started_methods=[],
        finished_methods=[],
        failures=[],
        errors=[],
        skipped=[],
        expected_failures=[],
        unexpected_successes=[],
        tests_run=0,
        attempt_count=1,
        candidate_sha256=expected_sha256,
        deadline=deadline,
        source_bytes=len(collector_raw) if isinstance(collector_raw, bytes) else None,
        started_monotonic=time.monotonic(),
    )

    def check():
        cancel()
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
            or time.monotonic() >= deadline
        ):
            raise ValueError("controls exhausted the original work deadline")

    class OriginalControlResult(unittest.TestResult):
        def startTest(self, test):
            check()
            observation["started_methods"].append(test._testMethodName)
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            observation["finished_methods"].append(test._testMethodName)
            check()

    result = OriginalControlResult()
    original_os = None
    try:
        check()
        _control_candidate = load_pinned_collector(
            collector_raw, expected_sha256, source_name
        )
        original_os = _control_candidate.os
        suite = unittest.TestSuite(
            BeneathCrossDriveControls(name) for name in CONTROL_METHODS
        )
        suite.run(result)
        check()
        if (
            result.testsRun != len(CONTROL_METHODS)
            or observation["started_methods"] != list(CONTROL_METHODS)
            or observation["finished_methods"] != list(CONTROL_METHODS)
            or not result.wasSuccessful()
            or result.errors
            or result.failures
            or result.skipped
            or result.expectedFailures
            or result.unexpectedSuccesses
            or _control_candidate.os is not original_os
        ):
            raise ValueError("the exact eight cross-drive controls did not all pass")
        observation["all_case_assertions_completed"] = True
    except BaseException as error:
        observation["invocation_error"] = repr(error)
        raise
    finally:
        observation["tests_run"] = result.testsRun
        observation["failures"] = [
            {"test": test.id(), "original_traceback": detail}
            for test, detail in result.failures
        ]
        observation["errors"] = [
            {"test": test.id(), "original_traceback": detail}
            for test, detail in result.errors
        ]
        observation["skipped"] = [
            {"test": test.id(), "reason": detail} for test, detail in result.skipped
        ]
        observation["expected_failures"] = [
            {"test": test.id(), "original_traceback": detail}
            for test, detail in result.expectedFailures
        ]
        observation["unexpected_successes"] = [
            test.id() for test in result.unexpectedSuccesses
        ]
        observation["isolated_os_reference_restored"] = (
            _control_candidate is not None and _control_candidate.os is original_os
        )
        observation["after_control_cleanup_monotonic"] = time.monotonic()
        observation["within_original_work_deadline"] = (
            isinstance(deadline, (int, float))
            and not isinstance(deadline, bool)
            and observation["after_control_cleanup_monotonic"] < deadline
        )
        _control_candidate = None
    try:
        check()
    except BaseException as error:
        observation["invocation_error"] = repr(error)
        raise
    observation["status"] = "PASS"


if __name__ == "__main__":
    raise SystemExit("Use the admitted caller's once-only original control scope")
