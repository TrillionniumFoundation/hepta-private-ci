"""Synthetic guard/parser tests only; never evidence of native Wine execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
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

    def test_inaccessible_owned_descendant_still_blocks_legacy_observer(self):
        proc = self.process(exe=str(self.base / "wine"), marker="fixture")
        self.ownership["markers"] = ["fixture"]
        original_read = Path.read_bytes
        def read(path):
            if path == proc / "environ":
                raise PermissionError("fixture inaccessible owned descendant")
            return original_read(path)
        with patch.object(Path, "read_bytes", read):
            result = self.observe()
        self.assertFalse(result["settled"])
        self.assertTrue(result["uncertain"])

    def test_inaccessible_preexisting_service_is_not_whitelisted_by_name(self):
        proc = self.process(exe="/usr/lib/systemd/systemd", ppid=1)
        original_read = Path.read_bytes
        def read(path):
            if path == proc / "environ":
                raise PermissionError("fixture inaccessible baseline service")
            return original_read(path)
        with patch.object(Path, "read_bytes", read):
            result = self.observe()
        self.assertFalse(result["settled"])
        self.assertTrue(result["uncertain"])


class FreshJobIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path("/fixture")
        self.out = Path(self.temp.name) / "original"
        self.out.mkdir()
        self.names = set(D.CASES) | {"tests::fixture_" + str(i) for i in range(9)}
        self.guard = {"head": "fixture", "all_source_bytes_match": True}
        self.environment = {"SOURCE_SHA": "fixture", "BAZEL_OUTPUT_BASE": "/tmp/fresh-output",
                            "A32_WINE_CASE": D.PLAN[0], "GITHUB_JOB": "original", "GITHUB_RUN_ID": "123",
                            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "push", "RUNNER_ENVIRONMENT": "github-hosted",
                            "RUNNER_NAME": "fixture-host", "GITHUB_OUTPUT": str(Path(self.temp.name) / "outputs")}
        self.env_patch = patch.dict(os.environ, self.environment)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.steps = {name: {"outcome": "success"} for name in
                      ("checkout_bytes", "checkout", "python", "guard", "contracts", "build", "dotslash", "bazel", "native")}

    def receipt(self, status="PASSED", case=None):
        case = case or D.PLAN[0]
        os.environ["A32_WINE_CASE"] = case
        os.environ["GITHUB_JOB"] = "original" if case == D.PLAN[0] else "isolated"
        plan = (case,)
        D.save(self.out / "fresh-job.json", D.fresh_context(plan))
        D.save(self.out / "input.json", self.guard)
        directory = self.out / ("0-" + case.replace("::", "-"))
        for name in ("guard-before.json", "guard-after.json"):
            D.save(directory / name, self.guard)
        names = sorted(self.names if case == D.PLAN[0] else {case})
        text = "running " + str(len(names)) + " tests\n"
        if status == "TIMEOUT":
            text += "test " + names[0] + " ... ok\n"
        else:
            text += "".join("test " + name + " ... " + ("FAILED" if status == "FAILED" and i == 0 else "ok") + "\n"
                            for i, name in enumerate(names))
            failed = int(status == "FAILED")
            text += f"test result: {'FAILED' if failed else 'ok'}. {len(names)-failed} passed; {failed} failed; 0 ignored; 0 measured; {13-len(names)} filtered out;\n"
        (directory / "testlogs").mkdir()
        (directory / "testlogs/test.log").write_text(text)
        events = [{"id": {"testResult": {"label": D.LABEL}}, "testResult": {"status": status}},
                  {"id": {"testSummary": {"label": D.LABEL}}, "testSummary":
                   {"overallStatus": status, "totalRunCount": 1, "runCount": 1, "attemptCount": 1}}]
        (directory / "bep.json").write_text("".join(json.dumps(event) + "\n" for event in events))
        record = {"case": case, "state": "completed", "passed": status == "PASSED",
                  "exit_code": 0 if status == "PASSED" else 3, "ownership_marker": "fixture-owner",
                  "command": D.command(self.root, directory, case, "fixture-owner")}
        D.save(directory / "result.json", record)
        self.steps["native"]["outcome"] = "success" if status == "PASSED" else "failure"
        os.environ["STEP_RESULTS"] = json.dumps(self.steps)
        return plan, directory, record

    def collect(self, plan):
        with patch.object(D, "guard", return_value=self.guard), patch.object(D, "environment_guard"), \
             patch.object(D, "expected_tests", return_value=self.names), \
             patch.object(D, "quiescence", side_effect=AssertionError("no global host observation")), \
             patch.object(D, "observe_processes", side_effect=AssertionError("no unrelated /proc inspection")), \
             patch("builtins.print"):
            code = D.collect(self.root, self.out, plan=plan, fresh_job=True)
        frozen = self.out.with_name("a32-wine-frozen")
        report = json.loads((frozen / "summary.json").read_text())
        for name, entry in json.loads((frozen / "artifact-hashes.json").read_text()).items():
            self.assertEqual(D.sha256((frozen / name).read_bytes()), entry["sha256"])
        return code, report

    def test_one_full_suite_native_pass_without_global_quiescence_claim(self):
        plan, _, _ = self.receipt()
        code, report = self.collect(plan)
        self.assertEqual(code, 0)
        self.assertTrue(report["provenance_valid"])
        self.assertEqual(report["isolation"]["global_quiescence"], "not-claimed")
        self.assertNotIn("final_quiescence", report)
        self.assertIn("not-global-quiescence", report["evidence_state"])

    def test_one_focused_case_is_one_not_thirteen(self):
        plan, _, _ = self.receipt(case=D.CASES[0])
        code, report = self.collect(plan)
        self.assertEqual(code, 0)
        self.assertEqual(len(report["attempts"]), 1)

    def test_ordinary_failure_preserves_failed_job_but_allows_next_fresh_jobs(self):
        plan, _, _ = self.receipt(status="FAILED")
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertTrue(report["provenance_valid"])
        self.assertEqual(Path(os.environ["GITHUB_OUTPUT"]).read_text(), "provenance_valid=true\n")

    def test_original_native_timeout_allows_fresh_cases_without_changing_deadline(self):
        plan, directory, _ = self.receipt(status="TIMEOUT")
        other = sorted(self.names - {D.CASES[0]})[0]
        raw = "running 13 tests\ntest " + D.CASES[0] + " ... FAILED\ntest " + other + " ... ok\n"
        (directory / "testlogs/test.log").write_text(raw)
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertTrue(report["provenance_valid"])
        self.assertFalse(report["provenance"]["native_passed"])
        self.assertEqual(report["attempts"][0]["exit_code"], 3)
        frozen = self.out.with_name("a32-wine-frozen") / directory.name
        self.assertEqual((frozen / "testlogs/test.log").read_text(), raw)
        parsed = D.parse_test_log(raw, self.names)
        self.assertEqual(parsed["running_counts"], [13])
        self.assertEqual(len(parsed["per_case_outcomes"]), 2)
        self.assertIsNone(parsed["counts"])
        self.assertFalse(parsed["count_and_name_guard_passed"])
        self.assertEqual(D.parse_bep(frozen / "bep.json")["overall_status"], "TIMEOUT")

    def test_completed_timeout_with_source_failure_cannot_release(self):
        plan, directory, record = self.receipt(status="TIMEOUT")
        record["block_latched"] = {"source_integrity": "fixture post-native mutation"}
        D.save(directory / "result.json", record)
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])

    def test_timeout_before_first_parallel_completion_is_not_zero_test_success(self):
        plan, directory, _ = self.receipt(status="TIMEOUT")
        (directory / "testlogs/test.log").write_text("running 13 tests\n")
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertTrue(report["provenance_valid"])

    def test_timeout_contradicting_all_pass_summary_blocks_dependents(self):
        plan, directory, _ = self.receipt(status="TIMEOUT")
        names = sorted(self.names)
        text = "running 13 tests\n" + "".join("test " + name + " ... ok\n" for name in names)
        text += "test result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
        (directory / "testlogs/test.log").write_text(text)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_zero_actual_tests_blocks_dependents(self):
        plan, directory, _ = self.receipt()
        (directory / "testlogs/test.log").write_text("running 0 tests\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 13 filtered out;\n")
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])

    def test_compile_only_without_native_result_blocks_dependents(self):
        plan, directory, _ = self.receipt()
        (directory / "bep.json").write_text(json.dumps({"id": {"buildFinished": {}}, "finished": {"exitCode": {"code": 0}}}) + "\n")
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])

    def test_interrupted_record_never_reclassified_as_complete(self):
        plan, directory, record = self.receipt()
        record.update(state="running", started_ns=0)
        D.save(directory / "result.json", record)
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertEqual(report["attempts"][0]["state"], "interrupted")
        self.assertFalse(report["provenance_valid"])

    def test_cached_native_result_blocks_dependents(self):
        plan, directory, _ = self.receipt()
        path = directory / "bep.json"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[0]["testResult"]["cachedLocally"] = True
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_duplicate_failed_test_names_block_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        text = path.read_text()
        one = next(line for line in text.splitlines() if line.startswith("test tests::"))
        path.write_text(text + one + "\n")
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_signal_and_non_test_bazel_exits_block_dependents(self):
        for exit_code in (-15, 1, 4, 8, 37):
            with self.subTest(exit_code=exit_code):
                fixture = FreshJobIsolation()
                fixture.setUp()
                try:
                    plan, directory, record = fixture.receipt(status="FAILED")
                    record["exit_code"] = exit_code
                    D.save(directory / "result.json", record)
                    code, report = fixture.collect(plan)
                    self.assertEqual(code, 1)
                    self.assertFalse(report["provenance_valid"])
                finally:
                    fixture.doCleanups()

    def test_failed_bep_with_all_pass_log_blocks_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        path.write_text(path.read_text().replace(" ... FAILED", " ... ok")
                        .replace("test result: FAILED. 12 passed; 1 failed;", "test result: ok. 13 passed; 0 failed;"))
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_impossible_failure_summary_blocks_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        path.write_text(path.read_text().replace("12 passed; 1 failed;", "999 passed; 999 failed;"))
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_duplicate_failure_summaries_block_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        text = path.read_text()
        path.write_text(text + next(line for line in text.splitlines() if line.startswith("test result:")) + "\n")
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_malformed_failure_summary_blocks_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        path.write_text(path.read_text().replace("12 passed;", "invalid passed;"))
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_failure_case_outcomes_cannot_exceed_summary_failures(self):
        plan, directory, _ = self.receipt(status="FAILED")
        path = directory / "testlogs/test.log"
        path.write_text(path.read_text().replace(" ... ok", " ... FAILED"))
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_failed_native_with_no_named_cases_blocks_dependents(self):
        plan, directory, _ = self.receipt(status="FAILED")
        (directory / "testlogs/test.log").write_text("running 13 tests\n")
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_failed_step_cannot_reclassify_passed_native_as_success(self):
        plan, _, _ = self.receipt()
        self.steps["native"]["outcome"] = "failure"
        os.environ["STEP_RESULTS"] = json.dumps(self.steps)
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertFalse(report["provenance_valid"])

    def test_successful_step_cannot_release_failed_native(self):
        plan, _, _ = self.receipt(status="FAILED")
        self.steps["native"]["outcome"] = "success"
        os.environ["STEP_RESULTS"] = json.dumps(self.steps)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_corrupt_result_still_seals_original_bytes_as_partial(self):
        plan, directory, _ = self.receipt()
        (directory / "result.json").write_text('{"state":')
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])
        self.assertEqual(report["attempts"][0]["state"], "record-unavailable")
        frozen = self.out.with_name("a32-wine-frozen")
        self.assertEqual((frozen / directory.name / "result.json").read_text(), '{"state":')

    def test_nondict_result_still_seals_partial_artifact(self):
        plan, directory, _ = self.receipt()
        D.save(directory / "result.json", [])
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("record_error", report["attempts"][0])

    def test_missing_state_result_still_seals_partial_artifact(self):
        plan, directory, record = self.receipt()
        del record["state"]
        D.save(directory / "result.json", record)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("record_error", report["attempts"][0])

    def test_initial_record_read_error_still_seals_partial_artifact(self):
        plan, directory, _ = self.receipt()
        original_read = Path.read_text
        failed_once = False
        def read(path, *args, **kwargs):
            nonlocal failed_once
            if path == directory / "result.json" and not failed_once:
                failed_once = True
                raise FileNotFoundError("atomic result replacement race")
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("record_error", report["attempts"][0])

    def test_interrupted_invalid_bep_still_seals_partial_artifact(self):
        plan, directory, record = self.receipt(status="TIMEOUT")
        record.update(state="running", started_ns=0)
        D.save(directory / "result.json", record)
        (directory / "bep.json").write_text("[]\n")
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        self.assertEqual(report["attempts"][0]["state"], "interrupted")
        self.assertIn("bep_error", report["attempts"][0])
        self.assertIn("log_error", report["attempts"][0])

    def test_interrupted_invalid_bep_does_not_prevent_available_raw_log_copy(self):
        plan, directory, record = self.receipt(status="TIMEOUT")
        record.update(state="running", started_ns=0)
        D.save(directory / "result.json", record)
        (directory / "bep.json").write_text("[]\n")
        raw = "original raw native log remains available despite malformed BEP\n"
        def preserve(root, destination, started):
            (destination / "testlogs/test.log").write_text(raw)
            return raw
        with patch.object(D, "preserve_logs", side_effect=preserve) as copy:
            _, report = self.collect(plan)
        copy.assert_called_once_with(self.root, directory, 0)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("bep_error", report["attempts"][0])
        self.assertNotIn("log_error", report["attempts"][0])
        self.assertEqual((self.out.with_name("a32-wine-frozen") / directory.name / "testlogs/test.log").read_text(), raw)

    def test_malformed_step_results_still_seal_partial_artifact(self):
        plan, _, _ = self.receipt()
        os.environ["STEP_RESULTS"] = "{"
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("step_results_error", report)

    def test_invalid_fresh_context_at_main_still_seals_partial_artifact(self):
        self.receipt(case=D.CASES[0])
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        os.environ["GITHUB_WORKSPACE"] = str(self.root)
        with patch.object(D.sys, "argv", ["diagnostic", "collect-job", str(self.out)]), \
             patch.object(D, "guard", return_value=self.guard), patch("builtins.print"):
            self.assertEqual(D.main(), 1)
        frozen = self.out.with_name("a32-wine-frozen")
        report = json.loads((frozen / "summary.json").read_text())
        self.assertFalse(report["provenance_valid"])
        self.assertEqual(report["attempts"][0]["case"], D.CASES[0])
        self.assertTrue((frozen / "artifact-hashes.json").is_file())

    def test_disappearing_enumerated_evidence_file_marks_snapshot_partial(self):
        plan, _, _ = self.receipt()
        missing = self.out / "disappearing.tmp"
        missing.write_text("temporary")
        original_stat = Path.stat
        def stat_file(path, *args, **kwargs):
            if path == missing:
                raise FileNotFoundError("fixture disappeared after enumeration")
            return original_stat(path, *args, **kwargs)
        with patch.object(Path, "stat", stat_file):
            _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])
        metadata = json.loads((self.out.with_name("a32-wine-frozen") / "snapshot-metadata.json").read_text())
        self.assertIn("snapshot_error", metadata[missing.name])

    def test_final_arm_gate_requires_all_native_results_and_provenance(self):
        workflow = Path(D.__file__).parents[1] / "workflows/a32-wine-diagnostic.yml"
        gate = workflow.read_text().split("\n  complete:\n", 1)[1]
        self.assertIn("needs: [original, isolated]", gate)
        self.assertIn("if: ${{ always() }}", gate)
        self.assertIn("runs-on: ubuntu-24.04-arm", gate)
        self.assertIn("timeout-minutes: 2", gate)
        self.assertNotIn("uses:", gate)
        self.assertNotIn("continue-on-error", gate)
        script = textwrap.dedent(gate.split("        run: |\n", 1)[1])
        for original in ("success", "failure", "skipped", "cancelled", "", "unknown"):
            for isolated in ("success", "failure", "skipped", "cancelled", "", "unknown"):
                for provenance in ("true", "false", ""):
                    result = subprocess.run(["bash", "-c", script], env={**os.environ,
                        "ORIGINAL_RESULT": original, "ISOLATED_RESULT": isolated, "ORIGINAL_PROVENANCE": provenance})
                    self.assertEqual(result.returncode == 0, (original, isolated, provenance) == ("success", "success", "true"))

    def test_sticky_source_error_blocks_dependents_even_if_final_guard_matches(self):
        plan, directory, record = self.receipt()
        record.update(passed=False, block_latched={"source_integrity": "transient mutation"})
        D.save(directory / "result.json", record)
        code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])

    def test_missing_initial_guard_blocks_dependents(self):
        plan, _, _ = self.receipt()
        (self.out / "input.json").unlink()
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_changed_pre_guard_blocks_dependents(self):
        plan, directory, _ = self.receipt()
        D.save(directory / "guard-before.json", {"head": "different"})
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_wrong_command_blocks_dependents(self):
        plan, directory, record = self.receipt()
        record["command"].insert(-1, "--test_timeout=300")
        D.save(directory / "result.json", record)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_cancelled_native_step_blocks_dependents(self):
        plan, _, _ = self.receipt()
        self.steps["native"]["outcome"] = "cancelled"
        os.environ["STEP_RESULTS"] = json.dumps(self.steps)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_failed_contracts_block_dependents(self):
        plan, _, _ = self.receipt()
        self.steps["contracts"]["outcome"] = "failure"
        os.environ["STEP_RESULTS"] = json.dumps(self.steps)
        _, report = self.collect(plan)
        self.assertFalse(report["provenance_valid"])

    def test_stable_but_changed_between_validation_and_copy_is_revalidated(self):
        plan, directory, _ = self.receipt()
        original = D.validate_fresh_provenance
        first = True
        def validate(*args, **kwargs):
            nonlocal first
            result = original(*args, **kwargs)
            if first:
                first = False
                log = directory / "testlogs/test.log"
                log.write_text(log.read_text().replace(" ... ok", " ... FAILED", 1))
            return result
        with patch.object(D, "validate_fresh_provenance", side_effect=validate):
            code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])
        self.assertIn("sealed_provenance_error", report)

    def test_fresh_plan_rejects_self_hosted_runner(self):
        os.environ["RUNNER_ENVIRONMENT"] = "self-hosted"
        with self.assertRaisesRegex(RuntimeError, "fresh hosted VM"):
            D.fresh_job_plan()

    def test_fresh_plan_rejects_reruns(self):
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaisesRegex(RuntimeError, "reruns"):
            D.fresh_job_plan()

    def test_fresh_plan_rejects_wrong_role(self):
        os.environ["GITHUB_JOB"] = "isolated"
        with self.assertRaisesRegex(RuntimeError, "role"):
            D.fresh_job_plan()

    def test_fresh_plan_rejects_unknown_filter(self):
        os.environ["A32_WINE_CASE"] = "tests::not_reviewed"
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            D.fresh_job_plan()

    def test_fresh_executor_runs_only_one_exact_case_and_never_observes_host(self):
        case = D.CASES[0]
        os.environ.update(A32_WINE_CASE=case, GITHUB_JOB="isolated")
        D.save(self.out / "fresh-job.json", D.fresh_context((case,)))
        log = f"running 1 test\ntest {case} ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 12 filtered out;\n"
        with patch.object(D, "environment_guard"), patch.object(D, "guard", return_value=self.guard), \
             patch.object(D, "expected_tests", return_value=self.names), \
             patch.object(D, "preserve_logs", return_value=log), \
             patch.object(D, "parse_bep", return_value={"one_uncached_pass": True}), \
             patch.object(D, "quiescence", side_effect=AssertionError("no host observation")), \
             patch.object(D, "system_snapshot") as resources, \
             patch.object(D.subprocess, "check_output", return_value="bazel 9.3.0"), \
             patch.object(D.subprocess, "Popen") as invocations, patch("builtins.print"):
            process = invocations.return_value.__enter__.return_value
            process.pid = os.getpid()
            process.wait.return_value = 0
            self.assertEqual(D.run_all(self.root, self.out, plan=(case,), fresh_job=True), 0)
            self.assertEqual(invocations.call_count, 1)
            self.assertIn("--test_arg=" + case, invocations.call_args.args[0])
            self.assertIn("--test_arg=--test-threads=1", invocations.call_args.args[0])
            resources.assert_called_once()
            self.assertEqual(resources.call_args.kwargs, {"include_processes": False})
            with self.assertRaisesRegex(RuntimeError, "second native invocation"):
                D.run_all(self.root, self.out, plan=(case,), fresh_job=True)
            self.assertEqual(invocations.call_count, 1)
        record = json.loads(next(self.out.glob("*/result.json")).read_text())
        self.assertFalse(record["original_internal_parallelism"])
        self.assertEqual(record["libtest"]["counts"]["passed"], 1)

    def test_fresh_executor_refuses_multi_attempt_plan(self):
        D.save(self.out / "fresh-job.json", D.fresh_context((D.PLAN[0],)))
        with patch.object(D, "environment_guard"), patch.object(D, "expected_tests", return_value=self.names), \
             patch.object(D.subprocess, "check_output", return_value="bazel 9.3.0"):
            with self.assertRaisesRegex(RuntimeError, "fresh-job plan"):
                D.run_all(self.root, self.out, plan=D.PLAN, fresh_job=True)

    def test_fresh_snapshot_error_seals_evidence_and_blocks_dependents(self):
        plan, _, _ = self.receipt()
        temporary = self.out / "writer.json.tmp"
        temporary.write_text("partial\n")
        original_open = Path.open
        def opened(path, *args, **kwargs):
            if path == temporary and args and args[0] == "rb":
                raise FileNotFoundError("concurrent rename")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", opened):
            code, report = self.collect(plan)
        self.assertEqual(code, 1)
        self.assertFalse(report["provenance_valid"])

    def test_workflow_graph_is_bounded_and_artifact_gated(self):
        workflow = (Path(__file__).parent.parent / "workflows/a32-wine-diagnostic.yml").read_text()
        self.assertIn("needs: original", workflow)
        self.assertIn("!cancelled() && needs.original.outputs.provenance_valid == 'true'", workflow)
        self.assertIn("steps.artifact.outcome == 'success'", workflow)
        self.assertIn("max-parallel: 2", workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertNotIn("continue-on-error", workflow)
        self.assertEqual(workflow.count("run-job"), 2)
        self.assertEqual(workflow.count("timeout-minutes: 32"), 2)
        self.assertEqual(workflow.count("timeout-minutes: 45"), 2)
        self.assertIn("a32-wine-evidence-${{ github.run_id }}-${{ github.run_attempt }}-original", workflow)
        self.assertIn("a32-wine-evidence-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.case_id }}", workflow)


class RawLogSnapshots(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root, self.out, self.output_base = base / "source", base / "evidence", base / "bazel"
        self.out.mkdir()
        self.location = self.output_base / "raw-testlogs"
        self.location.mkdir(parents=True)
        link = self.root / "bazel-testlogs/bazel/rules/testing/wine/wine-test-support-unit-tests"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.location, target_is_directory=True)
        self.log = self.location / "test.log"
        self.log.write_text("initial raw log\n")
        environment = patch.dict(os.environ, {"BAZEL_OUTPUT_BASE": str(self.output_base)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_stable_raw_log_has_copy_boundary_receipt(self):
        self.assertEqual(D.preserve_logs(self.root, self.out, 0), "initial raw log\n")
        metadata = json.loads((self.out / "raw-log-snapshots.json").read_text())
        self.assertTrue(metadata["test.log"]["source_stable_during_copy"])

    def grow_during_read(self, target):
        original_open = Path.open
        sizes = []
        class Reader:
            def __enter__(self):
                self.file = original_open(target, "rb")
                return self
            def read(self, size):
                sizes.append(size)
                data = self.file.read(size)
                with original_open(target, "ab") as writer:
                    writer.write(b"appended while copying\n")
                return data
            def __exit__(self, *args):
                self.file.close()
        def open_file(path, mode="r", *args, **kwargs):
            return Reader() if path == target and mode == "rb" else original_open(path, mode, *args, **kwargs)
        return patch.object(Path, "open", open_file), sizes

    def test_growing_raw_log_copies_only_initial_prefix_and_fails_closed(self):
        initial = self.log.read_bytes()
        growth, sizes = self.grow_during_read(self.log)
        with growth, self.assertRaisesRegex(RuntimeError, "bounded preservation"):
            D.preserve_logs(self.root, self.out, 0)
        self.assertEqual(sizes, [len(initial)])
        self.assertEqual((self.out / "testlogs/test.log").read_bytes(), initial)
        metadata = json.loads((self.out / "raw-log-snapshots.json").read_text())
        self.assertFalse(metadata["test.log"]["source_stable_during_copy"])
        self.assertGreater(metadata["test.log"]["source_size_after"], len(initial))

    def test_unavailable_raw_file_does_not_prevent_other_copies(self):
        missing = self.location / "a-disappearing.tmp"
        missing.write_text("temporary")
        original_open = Path.open
        def open_file(path, mode="r", *args, **kwargs):
            if path == missing and mode == "rb":
                raise FileNotFoundError("fixture raw file disappeared")
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, "open", open_file), self.assertRaises(RuntimeError):
            D.preserve_logs(self.root, self.out, 0)
        self.assertEqual((self.out / "testlogs/test.log").read_text(), "initial raw log\n")
        metadata = json.loads((self.out / "raw-log-snapshots.json").read_text())
        self.assertIn("snapshot_error", metadata[missing.name])
        self.assertTrue(metadata["test.log"]["source_stable_during_copy"])

    def test_disappearing_enumerated_raw_file_is_not_silently_skipped(self):
        missing = self.location / "disappearing.tmp"
        missing.write_text("temporary")
        original_stat = Path.stat
        def stat_file(path, *args, **kwargs):
            if path == missing:
                raise FileNotFoundError("fixture raw file disappeared after enumeration")
            return original_stat(path, *args, **kwargs)
        with patch.object(Path, "stat", stat_file), self.assertRaises(RuntimeError):
            D.preserve_logs(self.root, self.out, 0)
        metadata = json.loads((self.out / "raw-log-snapshots.json").read_text())
        self.assertIn("snapshot_error", metadata[missing.name])
        self.assertEqual((self.out / "testlogs/test.log").read_text(), "initial raw log\n")

    def test_growing_bep_read_is_bounded_and_rejected(self):
        path = self.location / "bep.json"
        path.write_text("{}\n")
        growth, sizes = self.grow_during_read(path)
        with growth, self.assertRaisesRegex(RuntimeError, "BEP changed during bounded read"):
            D.parse_bep(path)
        self.assertEqual(sizes, [3])


if __name__ == "__main__":
    unittest.main()
