"""Synthetic guard/parser tests only; never evidence of native Wine execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("wine_diagnostic", Path(__file__).with_name("a32_wine_diagnostic.py"))
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


def run(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT).decode().strip()


class SourceGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        run(self.root, "init", "-q")
        run(self.root, "config", "user.name", "Synthetic test")
        run(self.root, "config", "user.email", "synthetic@example.invalid")
        (self.root / "history.txt").write_text("older history\n")
        self.commit("older")
        (self.root / "source.rs").write_text("original product\n")
        (self.root / "MODULE.bazel.lock").write_text("original lock\n")
        (self.root / "link").symlink_to("source.rs")
        (self.root / ".gitignore").write_text("user.bazelrc\n")
        self.commit("base")
        self.base = run(self.root, "rev-parse", "HEAD")
        self.tree = run(self.root, "rev-parse", "HEAD^{tree}")
        self.allow = ("harness.py",)
        (self.root / "harness.py").write_text("pass\n")
        self.commit("harness")
        self.head = run(self.root, "rev-parse", "HEAD")

    def commit(self, message):
        run(self.root, "add", "--all")
        run(self.root, "commit", "-qm", message)

    def check(self):
        return D.guard(self.root, self.head, self.base, self.tree, self.allow)

    def test_clean_exact_parent_tree_and_bytes(self):
        self.assertTrue(self.check()["all_source_bytes_match"])

    def test_real_depth_two_checkout_has_required_parent_and_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            clone = Path(temp) / "checkout"
            subprocess.run(["git", "clone", "--no-local", "--depth", "2", self.root.as_uri(), str(clone)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(run(clone, "rev-parse", "--is-shallow-repository"), "true")
            self.assertEqual(run(clone, "rev-list", "--count", "HEAD"), "2")
            result = D.guard(clone, self.head, self.base, self.tree, self.allow)
            self.assertTrue(result["all_source_bytes_match"])
            self.assertEqual(result["parent"], self.base)

    def test_product_edit(self):
        (self.root / "source.rs").write_text("modified product\n")
        with self.assertRaisesRegex(RuntimeError, "source bytes"):
            self.check()

    def test_lock_edit(self):
        (self.root / "MODULE.bazel.lock").write_text("mutated lock\n")
        with self.assertRaisesRegex(RuntimeError, "source bytes"):
            self.check()

    def test_assume_unchanged(self):
        run(self.root, "update-index", "--assume-unchanged", "source.rs")
        with self.assertRaisesRegex(RuntimeError, "hidden index"):
            self.check()

    def test_skip_worktree(self):
        run(self.root, "update-index", "--skip-worktree", "source.rs")
        with self.assertRaisesRegex(RuntimeError, "hidden index"):
            self.check()

    def test_source_bytes_even_with_status_lie(self):
        (self.root / "source.rs").write_text("modified product\n")
        real_git = D.git
        def status_lie(root, *args):
            return b"" if args[0] == "status" else real_git(root, *args)
        with patch.object(D, "git", side_effect=status_lie):
            with self.assertRaisesRegex(RuntimeError, "source bytes"):
                self.check()

    def test_index_edit(self):
        (self.root / "source.rs").write_text("staged mutation\n")
        run(self.root, "add", "source.rs")
        with self.assertRaisesRegex(RuntimeError, "index differs"):
            self.check()

    def test_wrong_head(self):
        with self.assertRaisesRegex(RuntimeError, "HEAD differs"):
            D.guard(self.root, self.base, self.base, self.tree, self.allow)

    def test_product_changed_in_input_commit(self):
        (self.root / "source.rs").write_text("committed mutation\n")
        run(self.root, "add", "source.rs")
        run(self.root, "commit", "--amend", "--no-edit", "-q")
        self.head = run(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "product tree"):
            self.check()

    def test_extra_addition(self):
        (self.root / "unexpected").write_text("x")
        run(self.root, "add", "unexpected")
        run(self.root, "commit", "--amend", "--no-edit", "-q")
        self.head = run(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "allowlist"):
            self.check()

    def test_ignored_user_rc_rejected(self):
        (self.root / "user.bazelrc").write_text("test --test_arg=--ignored\n")
        with self.assertRaisesRegex(RuntimeError, "undeclared Bazel"):
            self.check()

    def test_source_symlink_type(self):
        (self.root / "link").unlink()
        (self.root / "link").write_text("source.rs")
        with self.assertRaisesRegex(RuntimeError, "symlink type"):
            self.check()

    def test_executable_mode(self):
        (self.root / "source.rs").chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "mode changed"):
            self.check()

    def test_extra_parent_commit(self):
        run(self.root, "commit", "--allow-empty", "-qm", "extra")
        self.head = run(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "exactly one parent"):
            self.check()


class ResultGuards(unittest.TestCase):
    def one(self, name=D.CASES[0], passed=1, failed=0, ignored=0, filtered=12, running=1):
        status = "FAILED" if failed else "ok"
        return (f"running {running} test\ntest {name} ... {status}\n"
                f"test result: {status}. {passed} passed; {failed} failed; {ignored} ignored; "
                f"0 measured; {filtered} filtered out; finished in 0.1s\n")

    def test_exact_one_pass(self):
        self.assertTrue(D.parse_test_log(self.one(), {D.CASES[0]})["count_and_name_guard_passed"])

    def test_zero_tests(self):
        self.assertFalse(D.parse_test_log(self.one(passed=0, running=0, filtered=13), {D.CASES[0]})["count_and_name_guard_passed"])

    def test_wrong_name(self):
        self.assertFalse(D.parse_test_log(self.one(name=D.CASES[1]), {D.CASES[0]})["count_and_name_guard_passed"])

    def test_ignored_not_pass(self):
        self.assertFalse(D.parse_test_log(self.one(passed=0, ignored=1), {D.CASES[0]})["count_and_name_guard_passed"])

    def test_duplicate_runs(self):
        self.assertFalse(D.parse_test_log(self.one() * 2, {D.CASES[0]})["count_and_name_guard_passed"])

    def test_failure_counts_retained(self):
        result = D.parse_test_log(self.one(passed=0, failed=1), {D.CASES[0]})
        self.assertFalse(result["count_and_name_guard_passed"])
        self.assertEqual(result["counts"]["failed"], 1)

    def test_timeout_incomplete_not_success(self):
        result = D.parse_test_log("running 13 tests\ntest tests::x ... ok\n", {"tests::x"})
        self.assertIsNone(result["counts"])
        self.assertFalse(result["count_and_name_guard_passed"])

    def test_full_suite_requires_all_thirteen(self):
        names = {f"tests::case_{n}" for n in range(13)}
        text = "running 13 tests\n" + "".join(f"test {n} ... ok\n" for n in sorted(names))
        text += "test result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
        self.assertTrue(D.parse_test_log(text, names)["count_and_name_guard_passed"])
        self.assertFalse(D.parse_test_log(text.replace("13 passed", "12 passed"), names)["count_and_name_guard_passed"])

    def test_bep_failure_missing_duplicate_cached(self):
        result = {"id": {"testResult": {"label": D.LABEL}}, "testResult": {"status": "PASSED"}}
        summary = {"id": {"testSummary": {"label": D.LABEL}}, "testSummary": {"overallStatus": "PASSED", "totalRunCount": 1, "runCount": 1, "attemptCount": 1}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bep.json"
            def parse(records):
                path.write_text("\n".join(json.dumps(r) for r in records))
                return D.parse_bep(path)
            self.assertTrue(parse([result, summary])["one_uncached_pass"])
            self.assertFalse(parse([summary])["one_uncached_pass"])
            self.assertFalse(parse([result, result, summary])["one_uncached_pass"])
            result["testResult"]["cachedLocally"] = True
            self.assertFalse(parse([result, summary])["one_uncached_pass"])
            result["testResult"]["cachedLocally"] = False
            summary["testSummary"]["overallStatus"] = "TIMEOUT"
            self.assertEqual(parse([result, summary])["overall_status"], "TIMEOUT")
            self.assertFalse(parse([result, summary])["one_uncached_pass"])

    def test_full_command_original_parallelism(self):
        with patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": "/tmp/fixture-output"}):
            command = D.command(Path("/checkout"), Path("/evidence"), D.PLAN[0])
        self.assertFalse(any("test-threads" in arg or "--exact" in arg or "test_timeout" in arg for arg in command))
        self.assertIn("--host_platform=//:local_linux", command)
        self.assertIn("--platforms=//:local_linux", command)
        self.assertEqual(command[-2:], ["--", D.LABEL])
        self.assertIn("--flaky_test_attempts=1", command)

    def test_individual_commands_exact_single_thread(self):
        with patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": "/tmp/fixture-output"}):
            for case in D.CASES:
                command = D.command(Path("/checkout"), Path("/evidence"), case)
                for flag in ("--test_arg=--exact", "--test_arg=" + case, "--test_arg=--nocapture",
                             "--test_arg=--test-threads=1", "--test_env=RUST_BACKTRACE=1"):
                    self.assertIn(flag, command)
                self.assertFalse(any("test_timeout" in arg for arg in command))

    def test_first_failure_does_not_skip_remaining_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            returns = [subprocess.CompletedProcess([], 3)] + [subprocess.CompletedProcess([], 0)] * 4
            logs = ["running 13 tests\n"] + [self.one(name=case) for case in D.CASES]
            with patch.object(D, "environment_guard"), patch.object(D, "guard", return_value={}), \
                 patch.object(D, "expected_tests", return_value={"tests::fixture"}), \
                 patch.object(D, "system_snapshot"), patch.object(D, "preserve_logs", side_effect=logs), \
                 patch.object(D, "quiescence", return_value={"settled": True}), \
                 patch.object(D, "parse_bep", return_value={"one_uncached_pass": True}), \
                 patch.object(D.subprocess, "check_output", return_value="bazel 9.3.0"), \
                 patch.object(D.subprocess, "Popen") as invocations, \
                 patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": "/tmp/fixture-output", "SOURCE_SHA": "fixture"}), \
                 patch("builtins.print"):
                process = invocations.return_value.__enter__.return_value
                process.pid = os.getpid()
                process.wait.side_effect = [r.returncode for r in returns]
                self.assertEqual(D.run_all(Path("/fixture"), out), 1)
                self.assertEqual(invocations.call_count, 5)
            results = [json.loads(p.read_text()) for p in sorted(out.glob("*/result.json"))]
            self.assertEqual([r["passed"] for r in results], [False, True, True, True, True])

    def test_contradictory_failed_status_rejected(self):
        text = self.one().replace(" ... ok", " ... FAILED")
        self.assertFalse(D.parse_test_log(text, {D.CASES[0]})["count_and_name_guard_passed"])

    def test_incomplete_case_status_rejected(self):
        text = self.one().replace(" ... ok", " ... ")
        self.assertFalse(D.parse_test_log(text, {D.CASES[0]})["count_and_name_guard_passed"])

    def test_serial_nocapture_split_status(self):
        text = self.one().replace(" ... ok", " ... \nexpected panic/backtrace\nok")
        self.assertTrue(D.parse_test_log(text, {D.CASES[0]})["count_and_name_guard_passed"])

    def simulate_block(self, guards=None, preserve_error=False, settled=True):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with patch.object(D, "environment_guard"), \
                 patch.object(D, "guard", side_effect=guards, return_value={}), \
                 patch.object(D, "expected_tests", return_value={"tests::fixture"}), \
                 patch.object(D, "system_snapshot"), \
                 patch.object(D, "preserve_logs", side_effect=RuntimeError("copy failed") if preserve_error else None, return_value=""), \
                 patch.object(D, "quiescence", return_value={"settled": settled}), \
                 patch.object(D, "parse_bep", return_value={"one_uncached_pass": False}), \
                 patch.object(D.subprocess, "check_output", return_value="bazel 9.3.0"), \
                 patch.object(D.subprocess, "Popen") as invocations, \
                 patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": "/tmp/fixture-output", "SOURCE_SHA": "fixture"}), \
                 patch("builtins.print"):
                process = invocations.return_value.__enter__.return_value
                process.pid = os.getpid()
                process.wait.return_value = 3
                self.assertEqual(D.run_all(Path("/fixture"), out), 1)
            results = [json.loads(p.read_text()) for p in sorted(out.glob("*/result.json"))]
            self.assertEqual([r["state"] for r in results][1:], ["blocked"] * 4)
            self.assertTrue(all(not r["passed"] for r in results))
            return invocations.call_count

    def test_transient_pre_guard_failure_sticks(self):
        self.assertEqual(self.simulate_block(guards=[RuntimeError("source changed"), {}]), 0)

    def test_transient_post_guard_failure_sticks(self):
        self.assertEqual(self.simulate_block(guards=[{}, RuntimeError("source changed")]), 1)

    def test_log_preservation_failure_sticks(self):
        self.assertEqual(self.simulate_block(preserve_error=True), 1)

    def test_unsettled_processes_block_later_cases(self):
        self.assertEqual(self.simulate_block(settled=False), 1)

    def test_partial_artifact_immutable_after_original_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "original"
            case = out / ("0-" + D.PLAN[0])
            case.mkdir(parents=True)
            D.save(case / "result.json", {"case": D.PLAN[0], "state": "running", "passed": False, "started_ns": 0})
            (case / "console.log").write_text("partial prefix\n")
            with patch.object(D, "quiescence", return_value={"settled": False}), \
                 patch.object(D, "guard", return_value={}), patch.object(D, "preserve_logs"), \
                 patch.dict(os.environ, {"SOURCE_SHA": "fixture"}), patch("builtins.print"):
                self.assertEqual(D.collect(Path("/fixture"), out), 1)
            frozen = Path(temp) / "a32-wine-frozen"
            (case / "console.log").write_text("later writer mutation\n")
            self.assertEqual((frozen / case.relative_to(out) / "console.log").read_text(), "partial prefix\n")
            report = json.loads((frozen / "summary.json").read_text())
            self.assertEqual(report["evidence_state"], "partial-unsettled")
            self.assertEqual(report["attempts"][0]["state"], "interrupted")
            for path, entry in json.loads((frozen / "artifact-hashes.json").read_text()).items():
                self.assertEqual(D.sha256((frozen / path).read_bytes()), entry["sha256"])

    def test_disappearing_snapshot_file_still_seals_partial_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "original"
            out.mkdir()
            source = out / "live.json.tmp"
            source.write_text("temporary result\n")
            original_open = Path.open
            def disappearing(path, *args, **kwargs):
                if path == source and args and args[0] == "rb":
                    raise FileNotFoundError("simulated concurrent atomic rename")
                return original_open(path, *args, **kwargs)
            with patch.object(D, "quiescence", return_value={"settled": True}), \
                 patch.object(D, "guard", return_value={}), patch.object(Path, "open", disappearing), \
                 patch.dict(os.environ, {"SOURCE_SHA": "fixture"}), patch("builtins.print"):
                self.assertEqual(D.collect(Path("/fixture"), out), 1)
            frozen = Path(temp) / "a32-wine-frozen"
            self.assertTrue((frozen / "artifact-hashes.json").is_file())
            metadata = json.loads((frozen / "snapshot-metadata.json").read_text())
            self.assertIn("snapshot_error", metadata["live.json.tmp"])
            self.assertEqual(json.loads((frozen / "summary.json").read_text())["evidence_state"], "partial-changing-or-unavailable")

    def test_changing_snapshot_is_partial_not_settled(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "original"
            out.mkdir()
            source = out / "live.log"
            source.write_text("initial prefix\n")
            original_open = Path.open
            class GrowingRead:
                def __enter__(self):
                    self.stream = original_open(source, "rb")
                    return self
                def read(self, size):
                    data = self.stream.read(size)
                    with original_open(source, "ab") as writer:
                        writer.write(b"later append\n")
                    return data
                def __exit__(self, *args):
                    self.stream.close()
            def growing(path, *args, **kwargs):
                return GrowingRead() if path == source and args and args[0] == "rb" else original_open(path, *args, **kwargs)
            with patch.object(D, "quiescence", return_value={"settled": True}), \
                 patch.object(D, "guard", return_value={}), patch.object(Path, "open", growing), \
                 patch.dict(os.environ, {"SOURCE_SHA": "fixture"}), patch("builtins.print"):
                self.assertEqual(D.collect(Path("/fixture"), out), 1)
            frozen = Path(temp) / "a32-wine-frozen"
            self.assertEqual((frozen / "live.log").read_text(), "initial prefix\n")
            report = json.loads((frozen / "summary.json").read_text())
            self.assertEqual(report["evidence_state"], "partial-changing-or-unavailable")
            self.assertFalse(json.loads((frozen / "snapshot-metadata.json").read_text())["live.log"]["source_stable_during_copy"])

    def test_bad_dotslash_asset_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            D.dotslash_binary(b"untrusted")

    def test_inherited_parallelism_override_rejected(self):
        with patch.dict(os.environ, {"RUST_TEST_THREADS": "1"}):
            with self.assertRaisesRegex(RuntimeError, "undeclared"):
                D.environment_guard()


class ProcessObservation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.base = self.root / "bazel"
        self.out = self.root / "evidence"
        self.out.mkdir()
        self.ownership = {"markers": [], "clients": [], "controller": {}, "execution_roots": [str(self.base)]}

    def process(self, pid=100, exe="/bin/sleep", marker=None, ppid=1, session=100):
        proc = self.proc / str(pid)
        proc.mkdir()
        fields = ["S", str(ppid), str(session), str(session)] + ["0"] * 15 + ["123"]
        (proc / "stat").write_text(str(pid) + " (fixture) " + " ".join(fields))
        (proc / "environ").write_bytes(("A32_WINE_DIAGNOSTIC_OWNER=" + marker).encode() + b"\0" if marker else b"")
        (proc / "exe").symlink_to(exe)
        (proc / "cmdline").write_bytes(b"fixture\0")
        (proc / "fd").mkdir()
        (proc / "fdinfo").mkdir()
        return proc

    def observe(self):
        def paths(path):
            text = str(path)
            return self.proc / text.removeprefix("/proc/") if text.startswith("/proc/") else self.proc if text == "/proc" else Path(path)
        with patch.object(D, "Path", side_effect=paths), patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": str(self.base)}):
            return D.observe_processes(self.out, self.ownership)

    def test_marker_owned_live_process_blocks(self):
        self.process(marker="fixture")
        self.ownership["markers"] = ["fixture"]
        result = self.observe()
        self.assertFalse(result["settled"])
        self.assertTrue(result["live_owned_processes_or_writers"][0]["owned_marker"])

    def test_reparented_untagged_executable_blocks(self):
        self.process(exe=str(self.base / "external/wine/bin/wine"))
        result = self.observe()
        self.assertFalse(result["settled"])
        self.assertTrue(result["live_owned_processes_or_writers"][0]["owned_executable"])

    def test_verified_settled_server_allowed_but_writer_blocks(self):
        proc = self.process(exe=str(self.base / "install/java"))
        (self.base / "server").mkdir(parents=True)
        (self.base / "server/server.pid.txt").write_text("100")
        (proc / "cmdline").write_bytes(("java\0--output_base=" + str(self.base) + "\0").encode())
        self.assertTrue(self.observe()["settled"])
        (proc / "fd/3").symlink_to(self.out / "bep.json")
        (proc / "fdinfo/3").write_text("flags:\t0100001\n")
        self.assertFalse(self.observe()["settled"])

    def test_recorded_client_ancestry_blocks(self):
        self.process(pid=100)
        self.process(pid=101, ppid=100, session=101)
        self.ownership["clients"] = [{"pid": 100, "start_ticks": "123", "session": 100}]
        result = self.observe()
        child = next(p for p in result["live_owned_processes_or_writers"] if p["pid"] == 101)
        self.assertTrue(child["owned_ancestry"])

    def test_incomplete_live_process_observation_fails_closed(self):
        proc = self.process()
        (proc / "environ").unlink()
        result = self.observe()
        self.assertFalse(result["settled"])
        self.assertTrue(result["uncertain"])


if __name__ == "__main__":
    unittest.main()
