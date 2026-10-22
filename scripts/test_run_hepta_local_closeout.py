"""Test that the local acceptance runner cannot manufacture a closure claim."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_hepta_local_closeout as mod


class LocalCloseoutTests(unittest.TestCase):
    def setUp(self):
        # The hosted Python setup action injects two loader/build paths into
        # this *test process*. Model a clean local runner without deleting the
        # paths required to launch CPython subprocess fixtures. Production
        # unreviewed_environment_keys() still rejects these overrides.
        bootstrap_paths = {
            key: os.environ[key]
            for key in ("LD_LIBRARY_PATH", "PKG_CONFIG_PATH")
            if os.environ.get(key)
        }
        verifier = mod.unreviewed_environment_keys

        def fixture_environment(environment=None):
            names = verifier(environment)
            if environment is not None:
                return names
            return [
                name for name in names
                if name not in bootstrap_paths
                or os.environ.get(name) != bootstrap_paths[name]
            ]

        guard = patch.object(
            mod, "unreviewed_environment_keys", side_effect=fixture_environment
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_unmounted_checkout_is_not_a_source(self):
        with tempfile.TemporaryDirectory() as root:
            result = mod.git_snapshot(Path(root) / "not-mount")
            self.assertFalse(result["usable"])
            self.assertNotIn("commit", result)

    def test_real_local_git_source_identity(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root)
            subprocess.run(["git", "init", "-q", str(src)], check=True)
            subprocess.run(["git", "-C", str(src), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                            "commit", "-q", "--allow-empty", "-m", "baseline"], check=True)
            result = mod.git_snapshot(src)
            self.assertTrue(result["usable"])
            self.assertEqual(len(result["commit"]), 40)
            self.assertEqual(len(result["tree"]), 40)
            self.assertTrue(result["clean"])
            (src / "untracked").write_text("x")
            self.assertFalse(mod.git_snapshot(src)["clean"])

    def test_linked_worktree_is_a_supported_exact_source(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            original = base / "original"
            sibling = base / "sibling"
            subprocess.run(["git", "init", "-q", str(original)], check=True)
            subprocess.run(["git", "-C", str(original), "-c", "user.name=LocalTest",
                            "-c", "user.email=local@example.invalid",
                            "commit", "-q", "--allow-empty", "-m", "baseline"], check=True)
            subprocess.run(["git", "-C", str(original), "worktree", "add", "-qb",
                            "test-sibling", str(sibling)], check=True)
            self.assertTrue((sibling / ".git").is_file())
            snap = mod.git_snapshot(sibling)
            self.assertTrue(snap["usable"])
            self.assertTrue(snap["clean"])
            self.assertEqual(snap["tree"], mod.git_snapshot(original)["tree"])

    def test_subdirectory_cannot_impersonate_repository_root(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            subprocess.run(["git", "init", "-q", str(base)], check=True)
            (base / "nested").mkdir()
            self.assertFalse(mod.git_snapshot(base / "nested")["usable"])

    def test_p3_checks_moved_pure_contract_not_removed_adapter_file(self):
        required = mod.STAGES["P3"]["required"]
        self.assertIn(("hepta", "codex-rs/hepta-types/src/execution_contract.rs"), required)
        self.assertNotIn(("hepta", "codex-rs/hepta-codex-adapter/src/execution_contract.rs"), required)

    def test_dirty_repository_blocks_exact_source_checks_even_if_mocked_green(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for path in roots.values():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            for path in roots.values():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest",
                                "-c", "user.email=local@example.invalid", "commit", "-qm", "baseline"], check=True)
            (roots["hepta"] / "untracked-src").write_text("uncommitted bytes")
            with patch.object(mod, "run_check", return_value={"status": "PASS_LOCAL"}) as mocked, patch.object(
                sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]),
                              "--report-dir", str(base / "results"), "--execute-checks"]
            ), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            self.assertEqual(mocked.call_count, 0)
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertTrue(all(s["status"] == "BLOCKED_DIRTY_WORKTREE" for s in report["stages"].values()))

    def test_p6_exact_head_workflow_includes_contract_and_native_owner_triggers(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/hepta-p6-codex-native-parity.yml"
        self.assertTrue(workflow.is_file())
        source = workflow.read_text(encoding="utf-8")
        for path in (
            "qa/meta-network-scale/p6_fallback_gate.py",
            "scripts/run_hepta_local_closeout.py",
            "codex-rs/hepta-types/src/execution_contract.rs",
            "codex-rs/hepta-codex-adapter/src/**",
            "codex-rs/hepta-operations/src/**",
            "codex-rs/hepta-agentd/src/**",
        ):
            with self.subTest(path=path):
                self.assertIn(path, source)
        self.assertIn("github.event.pull_request.head.sha || github.sha", source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"', source)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("git status --porcelain=v1 --untracked-files=all", source)
        self.assertNotIn("production_qualified: true", source)

    def test_absent_binary_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check(["nonexistent-hepta-executor-check-binary-000", "--version"], Path(root), 10, Path(root) / "log")
            self.assertEqual(r["status"], "BLOCKED_TOOL_MISSING")

    def test_passing_check_produces_nonworldwritable_provenance_log(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "test.log"
            r = mod.run_check([sys.executable, "-c", "print('test-only')"], Path(root), 10, p)
            self.assertEqual(r["status"], "PASS_LOCAL")
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertIn("test-only", p.read_text())
            self.assertEqual(len(r["log_sha256"]), 64)

    def test_failing_check_not_relabelled(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check([sys.executable, "-c", "raise SystemExit(7)"], Path(root), 10, Path(root) / "f.log")
            self.assertEqual(r["status"], "FAIL_LOCAL")
            self.assertEqual(r["exit_code"], 7)

    def test_timed_out_check_stays_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check([sys.executable, "-c", "import time; time.sleep(3)"], Path(root), 1, Path(root) / "x.log")
            self.assertEqual(r["status"], "BLOCKED_TIMEOUT")

    def test_missing_repositories_report_every_stage_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            report_path = Path(root) / "results"
            args = ["run", "--hepta", str(Path(root) / "missing1"), "--runtime", str(Path(root) / "missing2"), "--report-dir", str(report_path)]
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            reports = list(report_path.glob("run-*/acceptance.json"))
            self.assertEqual(len(reports), 1)
            data = json.loads(reports[0].read_text())
            self.assertFalse(data["production_qualified"])
            self.assertEqual(set(data["stages"]), set(mod.STAGES))
            self.assertTrue(all(s["status"].startswith("BLOCKED") for s in data["stages"].values()))

    def test_mounted_clean_sources_but_not_run_are_still_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for name, path in roots.items():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            for name, path in roots.items():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                                "commit", "-q", "--allow-empty", "-m", "test"], check=True)
            with patch.object(sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]), "--report-dir", str(base / "results")]), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertTrue(all(s["status"] == "BLOCKED_NOT_RUN" for s in report["stages"].values()))
            self.assertFalse(report["production_qualified"])

    def test_source_mutation_during_green_tests_never_reports_exact_source(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for path in roots.values():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text("baseline")
            for path in roots.values():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest",
                                "-c", "user.email=local@example.invalid", "commit", "-qm", "baseline"], check=True)

            def claims_pass_but_changes_source(*args, **kwargs):
                (roots["hepta"] / "uncommitted-during-test").write_text("mutation")
                return {"status": "PASS_LOCAL"}

            with patch.object(mod, "run_check", side_effect=claims_pass_but_changes_source), patch.object(
                sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]),
                              "--report-dir", str(base / "results"), "--execute-checks"]
            ), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertEqual(report["stages"]["P0"]["status"], "BLOCKED_SOURCE_CHANGED_DURING_CHECKS")
            self.assertFalse(report["production_qualified"])

    def test_all_local_checks_cannot_claim_full_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for path in roots.values():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            for path in roots.values():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                                "commit", "-q", "--allow-empty", "-m", "test"], check=True)
            with patch.object(mod, "run_check", return_value={"status": "PASS_LOCAL"}), patch.object(
                sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]),
                              "--report-dir", str(base / "results"), "--execute-checks"]
            ), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 3, "passing local checks must never give a green production exit code")
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertFalse(report["production_qualified"])
            self.assertTrue(all(x["status"] == "SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" for x in report["stages"].values()))


    def test_missing_local_git_binary_fails_closed(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
            mod.subprocess, "run", side_effect=FileNotFoundError()
        ):
            proof = mod.git_snapshot(Path(root))
            self.assertFalse(proof["usable"])
            self.assertEqual(proof["reason"], "FileNotFoundError")

    def test_bounded_cargo_log_flood_kills_child_and_records_digest(self):
        with tempfile.TemporaryDirectory() as root:
            location = Path(root) / "flood.log"
            code = (
                "import os\n"
                "chunk = b'x' * 65536\n"
                "while True: os.write(1, chunk)\n"
            )
            with patch.object(mod, "MAX_CHECK_LOG_BYTES", 128 * 1024):
                receipt = mod.run_check(
                    [sys.executable, "-c", code], Path(root), 5, location
                )
            self.assertEqual(receipt["status"], "BLOCKED_OUTPUT_LIMIT")
            self.assertLessEqual(location.stat().st_size, 128 * 1024 + 64)
            self.assertEqual(location.stat().st_mode & 0o777, 0o600)
            import hashlib

            self.assertEqual(
                receipt["log_sha256"], hashlib.sha256(location.read_bytes()).hexdigest()
            )

    def test_successful_wrapper_with_live_descendant_is_not_a_success(self):
        if os.name != "posix":
            self.skipTest("POSIX process groups required")
        with tempfile.TemporaryDirectory() as root:
            code = (
                "import subprocess, sys\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL)\n"
                "print('wrapper exited')\n"
            )
            result = mod.run_check(
                [sys.executable, "-c", code],
                Path(root), 5, Path(root) / "descendant.log",
            )
            self.assertEqual(result["status"], "BLOCKED_DESCENDANTS")


    def test_unreviewed_execution_env_is_rejected_without_disclosing_values(self):
        cases = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "RUSTFLAGS": "--cfg=unreviewed",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "/tmp/fake-linker",
            "RUSTC_WRAPPER": "/tmp/fake-rustc-wrapper",
            "LD_PRELOAD": "/tmp/fake.so",
            "PYTHONPATH": "/tmp/fake-python-tests",
            "CARGO_HOME": "/tmp/fake-cargo-config",
        }
        for name, value in cases.items():
            with self.subTest(variable=name):
                self.assertEqual(
                    mod.unreviewed_environment_keys({name: value}), [name]
                )
        self.assertEqual(
            mod.unreviewed_environment_keys(
                {"RUST_BACKTRACE": "full", "RUST_LOG": "warn", "CARGO_TERM_COLOR": "always"}
            ),
            [],
        )

    def test_env_poisoning_blocks_git_source_identity_before_subprocess(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            mod.os.environ, {"GIT_CONFIG_COUNT": "1"}
        ), patch.object(mod.subprocess, "run") as invoked:
            proof = mod.git_snapshot(Path(root))
            self.assertFalse(proof["usable"])
            self.assertEqual(proof["reason"], "unreviewed local execution environment")
            self.assertIn("GIT_CONFIG_COUNT", proof["blocked_environment_keys"])
            self.assertNotIn("1", proof["blocked_environment_keys"])
            invoked.assert_not_called()

    def test_changed_loader_path_cannot_reuse_fixture_baseline(self):
        with patch.dict(mod.os.environ, {"LD_LIBRARY_PATH": "/tmp/unreviewed-loader"}):
            self.assertIn(
                "LD_LIBRARY_PATH", mod.unreviewed_environment_keys()
            )

    def test_env_poisoning_blocks_checks_without_executing_any_binary(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            mod.os.environ, {"RUSTFLAGS": "--cfg=unreviewed"}
        ), patch.object(mod.subprocess, "Popen") as invoked:
            location = Path(root) / "no-binary-executed.log"
            result = mod.run_check(
                [sys.executable, "-c", "print('fake green')"],
                Path(root), 5, location
            )
            self.assertEqual(result["status"], "BLOCKED_UNREVIEWED_ENVIRONMENT")
            self.assertEqual(result["blocked_environment_keys"], ["RUSTFLAGS"])
            self.assertFalse(location.exists())
            invoked.assert_not_called()


    def test_required_source_must_be_exact_tracked_regular_head_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / ".gitignore").write_text("ignored.rs\n")
            (source / "tracked.rs").write_bytes(b"committed bytes\n")
            (source / "ignored.rs").write_bytes(b"untracked ignored payload")
            (source / "symlink.rs").symlink_to(source / "tracked.rs")
            subprocess.run(
                ["git", "-C", str(source), "add", ".gitignore", "tracked.rs", "symlink.rs"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "-c", "user.name=LocalTest",
                 "-c", "user.email=local@example.invalid",
                 "commit", "-qm", "baseline"],
                check=True,
            )
            self.assertTrue(mod.git_snapshot(source)["clean"])
            self.assertTrue(mod.committed_regular_file(source, "tracked.rs"))
            self.assertFalse(mod.committed_regular_file(source, "ignored.rs"))
            self.assertFalse(mod.committed_regular_file(source, "symlink.rs"))
            # Git can intentionally hide dirty bytes from porcelain status.
            subprocess.run(
                ["git", "-C", str(source), "update-index",
                 "--assume-unchanged", "tracked.rs"], check=True,
            )
            (source / "tracked.rs").write_bytes(b"tampered after HEAD")
            self.assertTrue(mod.git_snapshot(source)["clean"])
            self.assertFalse(mod.committed_regular_file(source, "tracked.rs"))


if __name__ == "__main__":
    unittest.main()
