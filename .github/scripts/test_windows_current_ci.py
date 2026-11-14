import json
import tempfile
import unittest
import time
from types import SimpleNamespace
from unittest import mock
import windows_process_observer as observation
from pathlib import Path
from windows_current_ci import (
    SANDBOX_HELPERS,
    assess,
    execute_groups,
    publish_sandbox_helpers,
    valid_source,
)

GROUP = {
    "id": "original",
    "package": "owner",
    "filter": "test(=original)",
    "expectedTestCount": 1,
    "requiredTests": ["original"],
}
PASS = "Starting 1 tests across 1 binary (99 tests skipped)\nPASS [ 0.1s] (1/1) owner original\n"


class StrictWindowsReceiptTests(unittest.TestCase):
    def test_nonzero_exit_is_never_pass(self):
        self.assertFalse(assess(GROUP, 100, PASS)["passed"])

    def test_skipped_or_different_test_is_not_the_original(self):
        for text in (
            "99 tests skipped",
            PASS.replace("owner original", "owner replacement"),
            PASS.replace("Starting 1 tests", "Starting 0 tests"),
        ):
            self.assertFalse(assess(GROUP, 0, text)["passed"])

    def test_actual_windows_ci_terminal_lines_without_progress_counts(self):
        actual = "Starting 1 tests across 1 binary (99 tests skipped)\n        PASS [   3.283s] owner original\nSummary [ 3.283s] 1 tests run: 1 passed, 99 skipped\n"
        self.assertTrue(assess(GROUP, 0, actual)["passed"])
        self.assertEqual(assess(GROUP, 0, actual)["observedTests"], ["original"])
        for replacement in ("SKIP", "FAIL", "TIMEOUT", "EXECFAIL", "LEAK"):
            self.assertFalse(
                assess(GROUP, 0, actual.replace("PASS [", replacement + " ["))["passed"]
            )
        self.assertFalse(
            assess(GROUP, 0, actual.replace("owner original", "other original"))[
                "passed"
            ]
        )
        self.assertFalse(
            assess(
                {**GROUP, "requiredTests": []}, 0, "Starting 1 tests across 1 binary"
            )["passed"]
        )

    def test_actual_single_native_materialization_keeps_exact_selection(self):
        name = (
            "sqlite_recovery::windows::tests::materialize_tests::"
            "retained_windows_materialization_preserves_bound_source_bundle"
        )
        group = {
            **GROUP,
            "id": "retained-windows-materialization",
            "package": "codex-state",
            "requiredTests": [name],
        }
        actual = (
            "Starting 1 test across 1 binary (213 tests skipped)\n"
            f"        PASS [   0.016s] codex-state {name}\n"
            "     Summary [   0.018s] 1 test run: 1 passed, 213 skipped\n"
        )
        result = assess(group, 0, actual)
        self.assertEqual(result["selectedTestCount"], 1)
        self.assertEqual(result["observedTests"], [name])
        self.assertTrue(result["passed"])
        for changed in (
            actual.replace("Starting 1 test", "Starting 0 tests"),
            actual.replace("Starting 1 test", "Starting 2 tests"),
            actual.replace("Starting 1 test across", "missing start record"),
            actual.replace(f"codex-state {name}", "codex-state replacement"),
            actual.replace(f"codex-state {name}", f"other-package {name}"),
            actual.replace("PASS [", "LEAK ["),
            actual.replace("PASS [", "FAIL ["),
        ):
            with self.subTest(log=changed):
                self.assertFalse(assess(group, 0, changed)["passed"])
        self.assertFalse(assess(group, 1, actual)["passed"])

    def test_diagnostics_continue_but_each_failure_is_retained(self):
        seen = []

        def invoke(command):
            seen.append(command)
            return (100 if len(seen) == 1 else 0), PASS

        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            results = execute_groups(
                output, output, [GROUP, {**GROUP, "id": "second"}], invoke
            )
        self.assertEqual([result["passed"] for result in results], [False, True])
        self.assertEqual(len(seen), 2)
        for command in seen:
            self.assertEqual(command[-2:], ["--retries", "0"])
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--no-tests") + 1], "fail")

    def test_changed_source_or_wrong_head_never_qualifies(self):
        before = {
            "head": "a" * 40,
            "tree": "b" * 40,
            "trackedChanges": "",
            "cargoLockSha256": "c" * 64,
        }
        self.assertTrue(valid_source("a" * 40, before, before))
        self.assertFalse(valid_source("d" * 40, before, before))
        self.assertFalse(
            valid_source("a" * 40, before, {**before, "cargoLockSha256": "d" * 64})
        )
        self.assertFalse(
            valid_source(
                "a" * 40,
                {**before, "trackedChanges": " M source.rs"},
                {**before, "trackedChanges": " M source.rs"},
            )
        )


class SandboxHelperArtifactTests(unittest.TestCase):
    def fixture(self, root):
        manifest = root / "codex-rs/windows-sandbox-rs/Cargo.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("[package]\nname = 'codex-windows-sandbox'\n")
        target = root / "target"
        profile = target / "dev-small"
        profile.mkdir(parents=True)
        records = []
        for name in SANDBOX_HELPERS:
            binary = profile / (name + ".exe")
            binary.write_bytes(b"MZ-unit-test-artifact-" + name.encode())
            records.append(
                {
                    "reason": "compiler-artifact",
                    "manifest_path": str(manifest),
                    "target": {"name": name, "kind": ["bin"]},
                    "profile": {"test": False},
                    "executable": str(binary),
                }
            )
        return target, records

    def test_both_real_artifact_paths_and_identical_bytes_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            result = publish_sandbox_helpers(
                root, target, "\n".join(json.dumps(item) for item in records)
            )
            self.assertEqual([item["name"] for item in result], list(SANDBOX_HELPERS))
            for item in result:
                self.assertEqual(
                    Path(item["source"]).read_bytes(),
                    Path(item["testSibling"]).read_bytes(),
                )

    def test_missing_or_wrong_manifest_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "both original"):
                publish_sandbox_helpers(root, target, json.dumps(records[0]))
            records[0]["manifest_path"] = str(root / "other/Cargo.toml")
            with self.assertRaisesRegex(ValueError, "different manifest"):
                publish_sandbox_helpers(
                    root, target, "\n".join(json.dumps(item) for item in records)
                )

    def test_existing_different_helper_is_never_overwritten_or_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, records = self.fixture(root)
            sibling = target / "dev-small/deps" / (SANDBOX_HELPERS[0] + ".exe")
            sibling.parent.mkdir()
            sibling.write_bytes(b"unrelated existing executable")
            with self.assertRaisesRegex(ValueError, "changed"):
                publish_sandbox_helpers(
                    root, target, "\n".join(json.dumps(item) for item in records)
                )
            self.assertEqual(sibling.read_bytes(), b"unrelated existing executable")


class FakeProcesses:
    def __init__(self, frames, states=None, current=None):
        self.frames = list(frames)
        self.states = {100: (100, None), **(states or {})}
        self.current = current or {}
        self.opens = []
        self.closed = []

    def anchor(self, process):
        return 100, self.state(100)

    def open(self, pid):
        self.opens.append(pid)
        value = self.current[pid]
        if isinstance(value, Exception):
            raise value
        return value

    def state(self, handle):
        value = self.states[handle]
        if isinstance(value, Exception):
            raise value
        return value

    def snapshot(self):
        value = self.frames.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self, handle):
        if handle in self.closed:
            raise AssertionError("double close")
        self.closed.append(handle)


class WindowsDescendantObservationTests(unittest.TestCase):
    def observer(self, backend):
        return observation.DescendantObserver(
            SimpleNamespace(pid=10), time.monotonic(), backend
        )

    def test_only_bound_descendants_including_reversed_snapshot_order(self):
        backend = FakeProcesses(
            [
                (
                    200,
                    [
                        (30, 20, "acl.exe"),
                        (40, 99, "unrelated.exe"),
                        (20, 10, "setup.exe"),
                    ],
                )
            ],
            {200: (110, None), 300: (120, None)},
            {20: 200, 30: 300},
        )
        observer = self.observer(backend)
        observer.sample()
        result = observer.finish()
        self.assertEqual(
            [(p["pid"], p["parentIdentity"]) for p in result["processes"]],
            [(10, None), (20, [10, 100]), (30, [20, 110])],
        )
        self.assertEqual(backend.opens, [20, 30])
        self.assertEqual(sorted(backend.closed), [100, 200, 300])
        self.assertEqual(result["handlesOpened"], result["handlesClosed"])
        self.assertNotIn("unrelated", json.dumps(result))
        self.assertFalse(result["exhaustive"])
        self.assertFalse(result["pipeOwnershipObserved"])

    def test_missing_snapshot_and_missing_parent_row_are_not_exit(self):
        backend = FakeProcesses(
            [
                (200, [(20, 10, "setup.exe")]),
                PermissionError("private setup payload"),
                (300, [(30, 20, "acl.exe")]),
            ],
            {200: (110, None), 300: (220, None)},
            {20: 200, 30: 300},
        )
        observer = self.observer(backend)
        for _ in range(3):
            observer.sample()
        result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10, 20, 30])
        self.assertIsNone(result["processes"][1]["exitFileTime"])
        self.assertEqual(result["errors"][0]["stage"], "snapshot")
        self.assertNotIn("private setup payload", json.dumps(result))

    def test_parent_exit_fences_a_reused_pid_and_keeps_late_original_child(self):
        backend = FakeProcesses(
            [
                (200, [(20, 10, "setup.exe")]),
                (
                    300,
                    [
                        (20, 99, "replacement.exe"),
                        (30, 20, "foreign.exe"),
                        (40, 20, "old-child.exe"),
                    ],
                ),
            ],
            {200: (110, None), 300: (170, None), 400: (120, None)},
            {20: 200, 30: 300, 40: 400},
        )
        observer = self.observer(backend)
        observer.sample()
        backend.states[200] = (110, 150)
        observer.sample()
        result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10, 20, 40])
        self.assertEqual(result["processes"][2]["parentIdentity"], [20, 110])
        self.assertNotIn("foreign", json.dumps(result))
        self.assertNotIn("replacement", json.dumps(result))

    def test_pid_generations_do_not_rebind_old_children(self):
        backend = FakeProcesses(
            [
                (150, [(20, 10, "first.exe")]),
                (
                    250,
                    [(20, 10, "second.exe"), (30, 20, "old.exe"), (40, 20, "new.exe")],
                ),
            ],
            {200: (110, None), 201: (180, None), 300: (130, None), 400: (190, None)},
            {20: 200, 30: 300, 40: 400},
        )
        observer = self.observer(backend)
        observer.sample()
        backend.states[200] = (110, 150)
        backend.current[20] = 201
        observer.sample()
        result = observer.finish()
        parents = {
            (p["pid"], p["createdFileTime"]): p["parentIdentity"]
            for p in result["processes"]
        }
        self.assertEqual(parents[(30, 130)], [20, 110])
        self.assertEqual(parents[(40, 190)], [20, 180])
        self.assertEqual(backend.closed.count(200), 1)
        self.assertEqual(backend.closed.count(201), 1)

    def test_birth_during_snapshot_is_a_gap_then_later_observable(self):
        backend = FakeProcesses(
            [(200, [(20, 10, "child.exe")]), (300, [(20, 10, "child.exe")])],
            {200: (200, None), 201: (200, None)},
            {20: 200},
        )
        observer = self.observer(backend)
        observer.sample()
        self.assertEqual(list(observer.nodes), [(10, 100)])
        backend.current[20] = 201
        observer.sample()
        result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10, 20])
        self.assertEqual(result["errors"][0]["reason"], "born_in_snapshot_window")

    def test_denied_candidate_and_its_children_are_not_claimed(self):
        backend = FakeProcesses(
            [(200, [(20, 10, "setup.exe"), (30, 20, "child.exe")])],
            current={20: PermissionError("credential must not be printed")},
        )
        observer = self.observer(backend)
        observer.sample()
        result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10])
        self.assertEqual(backend.opens, [20])
        self.assertEqual(result["errors"][0]["kind"], "PermissionError")
        self.assertNotIn("credential", json.dumps(result))

    def test_process_snapshot_and_error_caps_remain_visible(self):
        backend = FakeProcesses(
            [
                observation.ObservationGap("snapshot_capacity"),
                (200, [(20, 10, "first.exe"), (30, 10, "second.exe")]),
            ],
            {200: (110, None)},
            {20: 200},
        )
        observer = self.observer(backend)
        with (
            mock.patch.object(observation, "MAX_PROCESSES", 2),
            mock.patch.object(observation, "MAX_ERRORS", 1),
        ):
            observer.sample()
            observer.sample()
            result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10, 20])
        self.assertEqual(result["errors"][0]["reason"], "snapshot_capacity")
        self.assertEqual(result["suppressedErrors"], 1)
        self.assertEqual(backend.opens, [20])

    def test_clock_rollback_and_unknown_parent_state_fail_closed(self):
        backend = FakeProcesses(
            [(200, []), (190, [(20, 10, "child.exe")]), (300, [(20, 10, "child.exe")])],
            {200: (110, None)},
            {20: 200},
        )
        observer = self.observer(backend)
        observer.sample()
        observer.sample()
        backend.states[100] = OSError("private state")
        observer.sample()
        result = observer.finish()
        self.assertEqual([p["pid"] for p in result["processes"]], [10])
        self.assertIn("clock_moved_backwards", [e["stage"] for e in result["errors"]])
        self.assertNotIn("private state", json.dumps(result))
        self.assertEqual(sorted(backend.closed), [100, 200])

    def test_unexpected_observer_error_closes_its_handles(self):
        backend = FakeProcesses([RuntimeError("secret command payload")])
        observer = self.observer(backend)
        observer.start()
        result = observer.finish()
        self.assertEqual(result["status"], "observer_failed")
        self.assertEqual(backend.closed, [100])
        self.assertNotIn("secret command payload", json.dumps(result))

    def test_join_limit_does_not_close_a_handle_under_a_live_observer(self):
        backend = FakeProcesses([(200, [])])
        observer = self.observer(backend)
        observer.thread = mock.Mock(ident=1)
        observer.thread.is_alive.return_value = True
        result = observer.finish()
        self.assertEqual(result["status"], "cleanup_pending")
        observer.thread.join.assert_called_once_with(timeout=1)
        self.assertEqual(backend.closed, [])
        # The worker's own finally performs cleanup; it never kills a process.
        observer.run()
        self.assertEqual(backend.closed, [100])

    def test_observer_start_and_finish_errors_preserve_original_outcome(self):
        group = {**GROUP, "id": "sandbox-original-failures"}
        for status, code, text in (
            ("start", 0, PASS),
            ("start", 0, PASS.replace("PASS [", "LEAK [")),
            ("finish", 100, PASS),
        ):
            with (
                self.subTest(status=status, code=code),
                tempfile.TemporaryDirectory() as td,
            ):
                output = Path(td)
                calls = []

                def popen(command, **kwargs):
                    calls.append((command, kwargs))
                    kwargs["stdout"].write(text)
                    process = mock.MagicMock()
                    process.communicate.return_value = (None, None)
                    process.poll.return_value = code
                    process.__enter__.return_value = process
                    calls[-1] = (command, kwargs, process)
                    return process

                factory = mock.Mock()
                if status == "start":
                    factory.side_effect = RuntimeError("private observer detail")
                else:
                    factory.return_value.finish.side_effect = RuntimeError(
                        "private observer detail"
                    )
                with (
                    mock.patch.object(
                        observation.subprocess, "Popen", side_effect=popen
                    ),
                    mock.patch.object(observation, "DescendantObserver", factory),
                ):
                    result = execute_groups(output, output, [group])[0]
                self.assertEqual(
                    {key: result[key] for key in assess(group, code, text)},
                    assess(group, code, text),
                )
                self.assertEqual(
                    calls[0][0],
                    [
                        "just",
                        "test",
                        "--locked",
                        "-p",
                        "owner",
                        "--lib",
                        "--cargo-profile",
                        "dev-small",
                        "-E",
                        "test(=original)",
                        "--test-threads",
                        "1",
                        "--no-tests",
                        "fail",
                        "--retries",
                        "0",
                    ],
                )
                self.assertEqual(set(calls[0][1]), {"cwd", "stdout", "stderr"})
                self.assertEqual(calls[0][1]["cwd"], output / "codex-rs")
                self.assertEqual(calls[0][1]["stderr"], observation.subprocess.STDOUT)
                calls[0][2].communicate.assert_called_once_with(None, timeout=None)
                calls[0][2].poll.assert_called_once_with()
                calls[0][2].kill.assert_not_called()
                trace = json.loads(
                    (output / "sandbox-original-failures.processes.json").read_text()
                )
                self.assertEqual(trace["commandExitCode"], code)
                self.assertEqual(trace["status"], status + "_failed")
                self.assertFalse(trace["exhaustive"])
                self.assertNotIn("private observer detail", json.dumps(trace))

    def test_trace_write_failure_cannot_replace_a_failed_test(self):
        group = {**GROUP, "id": "sandbox-original-failures"}
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)

            def observed(command, cwd, stream):
                stream.write(PASS)
                return 100, {"status": "stopped"}

            original_write = Path.write_text

            def write(path, *args, **kwargs):
                if path.name.endswith(".processes.json"):
                    raise OSError("private diagnostic path")
                return original_write(path, *args, **kwargs)

            with (
                mock.patch(
                    "windows_current_ci.run_with_observation", side_effect=observed
                ),
                mock.patch.object(Path, "write_text", write),
            ):
                result = execute_groups(output, output, [group])[0]
            self.assertEqual(result["exitCode"], 100)
            self.assertFalse(result["passed"])
            self.assertEqual(result["processObservation"]["status"], "write_failed")
            self.assertNotIn("private diagnostic path", json.dumps(result))

    def test_command_owner_preserves_keyboard_interrupt_cleanup(self):
        self.check_wait_error_cleanup(KeyboardInterrupt("original interrupt"), False)

    def test_communication_error_is_preserved_even_if_observer_finish_fails(self):
        self.check_wait_error_cleanup(OSError("original communication error"), True)

    def check_wait_error_cleanup(self, original, observer_finish_fails):
        process = mock.MagicMock()
        process.__enter__.return_value = process
        process.communicate.side_effect = original
        observer = mock.Mock()
        observer.finish.return_value = {"status": "stopped"}
        if observer_finish_fails:
            observer.finish.side_effect = RuntimeError(
                "observer must not replace original"
            )
        with (
            mock.patch.object(observation.subprocess, "Popen", return_value=process),
            mock.patch.object(observation, "DescendantObserver", return_value=observer),
        ):
            with self.assertRaises(type(original)) as raised:
                observation.run_with_observation(
                    ["just", "test"], Path("."), mock.Mock()
                )
        self.assertIs(raised.exception, original)
        process.communicate.assert_called_once_with(None, timeout=None)
        process.kill.assert_called_once_with()
        process.poll.assert_not_called()
        observer.finish.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
