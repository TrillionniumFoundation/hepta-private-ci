"""Local source/provenance oracle tests; no Rust or native-Windows claims."""
import json
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock

import a32_memory_qualification_guard as guard
import a32_memory_qualification as runner

BEFORE = b'''version = 4
[[package]]
name = "codex-hepta-memory"
version = "0.0.0"
dependencies = ["codex-state"]
[[package]]
name = "codex-state"
version = "0.0.0"
dependencies = ["anyhow"]
[[package]]
name = "anyhow"
version = "1.0.100"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "unchanged"
'''
AFTER = BEFORE.replace(b'["codex-state"]', b'["codex-state", "codex-utils-path"]')
AFTER = AFTER.replace(b'["anyhow"]', b'["anyhow", "codex-utils-path"]')


class BootstrapTests(unittest.TestCase):
    def archive(self, names, symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                if symlink:
                    info.type, info.linkname = tarfile.SYMTYPE, "elsewhere"
                    archive.addfile(info)
                else:
                    info.size = 6
                    archive.addfile(info, io.BytesIO(b"binary"))
        return output.getvalue()

    def test_checksum_pinned_archive_only_returns_binary_bytes(self):
        data = self.archive(["folder/dotslash.exe"])
        self.assertEqual(runner.dotslash_binary(data, len(data), guard.digest(data)), b"binary")
        for size, digest in ((len(data) + 1, guard.digest(data)), (len(data), "0" * 64)):
            with self.assertRaisesRegex(RuntimeError, "hash/size"):
                runner.dotslash_binary(data, size, digest)

    def test_missing_duplicate_and_symlink_binaries_rejected(self):
        for names, symlink in ((["README"], False), (["dotslash", "dotslash.exe"], False), (["dotslash"], True)):
            data = self.archive(names, symlink)
            with self.assertRaisesRegex(RuntimeError, "archive member"):
                runner.dotslash_binary(data, len(data), guard.digest(data))


class RunnerGuardTests(unittest.TestCase):
    def fixture(self, directory):
        instance = object.__new__(runner.Qualification)
        instance.root = instance.evidence = Path(directory)
        instance.commands = []
        instance.guard, instance.flush = Mock(), Mock()
        return instance

    def test_failed_command_still_runs_post_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.fixture(directory)
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                instance.run("fixture", [sys.executable, "-c", "raise SystemExit(1)"])
            self.assertEqual(instance.guard.call_count, 2)
            self.assertEqual(instance.commands[0]["exit_code"], 1)

    def test_successful_command_with_bad_post_guard_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.fixture(directory)
            instance.guard.side_effect = [None, RuntimeError("hidden source")]
            with self.assertRaisesRegex(RuntimeError, "hidden source"):
                instance.run("fixture", [sys.executable, "-c", "pass"])
            self.assertEqual(instance.commands[0]["status"], "failed")
            self.assertEqual(instance.commands[0]["exit_code"], 0)
            self.assertEqual(instance.commands[0]["post_guard_error"], "hidden source")


class LockTests(unittest.TestCase):
    def test_only_two_real_edge_changes_accepted(self):
        self.assertEqual(sorted(guard.cargo_delta(BEFORE, AFTER)), ["codex-hepta-memory", "codex-state"])

    def test_no_edge_not_accepted_as_generated(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected lock"):
            guard.cargo_delta(BEFORE, BEFORE)

    def test_package_version_or_source_change_rejected(self):
        for replacement in (AFTER.replace(b"1.0.100", b"1.0.101"), AFTER.replace(b"registry+", b"other+")):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "resolution changed"):
                guard.cargo_delta(BEFORE, replacement)

    def test_checksum_and_extra_edge_rejected(self):
        for replacement in (AFTER.replace(b'"unchanged"', b'"changed"'), AFTER.replace(b'"anyhow",', b'"extra", "anyhow",')):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "unexpected lock"):
                guard.cargo_delta(BEFORE, replacement)

    def test_new_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "resolution changed"):
            guard.cargo_delta(BEFORE, AFTER + b'\n[[package]]\nname="extra"\nversion="0.0.0"\n')

    def test_duplicate_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            guard.cargo_delta(BEFORE, AFTER + b'\n[[package]]\nname="codex-state"\nversion="0.0.0"\n')

    def test_header_change_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "header"):
            guard.cargo_delta(BEFORE, AFTER.replace(b"version = 4", b"version = 3"))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {"source_sha": "source", "run_id": "12", "run_attempt": "1", "input_tree": "tree"}
        for path in guard.LOCKS:
            output = self.root / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(AFTER if path.endswith("Cargo.lock") else b"{}\n")
        guard.save(self.root / "manifest.json", {"identity": self.identity, "files": guard.inventory(self.root),
                                                "resolver_gates_passed": True})

    def test_same_run_exact_bundle_accepted(self):
        self.assertTrue(guard.verify_bundle(self.root, self.identity)["resolver_gates_passed"])

    def test_wrong_run_attempt_or_source_rejected(self):
        for field in ("run_id", "run_attempt", "source_sha", "input_tree"):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "source/run/attempt"):
                guard.verify_bundle(self.root, {**self.identity, field: "wrong"})

    def test_extra_path_rejected(self):
        (self.root / "unreviewed.rs").write_text("unsafe new source")
        with self.assertRaisesRegex(RuntimeError, "exactly"):
            guard.verify_bundle(self.root, self.identity)

    def test_post_download_tamper_rejected(self):
        (self.root / "MODULE.bazel.lock").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "hash/length"):
            guard.verify_bundle(self.root, self.identity)

    def test_manifest_matches_independent_resolver_step_digest(self):
        path = self.root / "manifest.json"
        expected = guard.digest(path.read_bytes())
        guard.verify_bundle(self.root, self.identity, expected)
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "resolver step output"):
            guard.verify_bundle(self.root, self.identity, expected)

    def test_failed_generator_rejected(self):
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["resolver_gates_passed"] = False
        guard.save(path, data)
        with self.assertRaisesRegex(RuntimeError, "gates"):
            guard.verify_bundle(self.root, self.identity)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        guard.git(self.root, "init", "-q")
        guard.git(self.root, "config", "user.name", "local guard test")
        guard.git(self.root, "config", "user.email", "test@invalid")
        guard.git(self.root, "config", "core.autocrlf", "false")
        (self.root / "native.rs").write_bytes(b"old\n")
        for path in guard.LOCKS:
            output = self.root / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(BEFORE if path.endswith("Cargo.lock") else b"{}\n")
        self.base = self.commit()
        (self.root / "native.rs").write_bytes(b"reviewed\n")
        self.manifest = {"base": self.base, "base_tree": guard.git(self.root, "rev-parse", "HEAD^{tree}").decode().strip(),
                         "branch": "diagnostic", "auxiliary_paths": [guard.MANIFEST],
                         "files": [{"path": "native.rs", "base_blob": guard.blob(b"old\n"),
                                    "candidate_blob": guard.blob(b"reviewed\n"), "candidate_sha256": guard.digest(b"reviewed\n")}]}
        guard.save(self.root / guard.MANIFEST, self.manifest)
        self.source = self.commit()

    def commit(self):
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "-qm", "local fixture")
        return guard.git(self.root, "rev-parse", "HEAD").decode().strip()

    def test_exact_input_accepted(self):
        self.assertEqual(guard.verify_input(self.root, self.source, "diagnostic"), self.manifest)

    def test_wrong_branch_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "branch"):
            guard.verify_input(self.root, self.source, "main")

    def test_noncanonical_worktree_bytes_rejected_not_refreshed(self):
        (self.root / "native.rs").write_bytes(b"reviewed\r\n")
        with self.assertRaisesRegex(RuntimeError, "noncanonical"):
            guard.verify_input(self.root, self.source, "diagnostic")
        self.assertEqual((self.root / "native.rs").read_bytes(), b"reviewed\r\n")

    def test_unexpected_committed_path_rejected(self):
        (self.root / "extra.rs").write_text("extra")
        new = self.commit()
        with self.assertRaisesRegex(RuntimeError, "parent"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_same_parent_unreviewed_path_rejected(self):
        (self.root / "extra.rs").write_text("extra")
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "--amend", "--no-edit", "-q")
        new = guard.git(self.root, "rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(RuntimeError, "allowlist"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_same_parent_wrong_reviewed_postimage_rejected(self):
        (self.root / "native.rs").write_text("unreviewed")
        guard.git(self.root, "add", ".")
        guard.git(self.root, "commit", "--amend", "--no-edit", "-q")
        new = guard.git(self.root, "rev-parse", "HEAD").decode().strip()
        with self.assertRaisesRegex(RuntimeError, "postimage"):
            guard.verify_input(self.root, new, "diagnostic")

    def test_untracked_tracked_and_index_changes_rejected(self):
        (self.root / "untracked").write_text("extra")
        with self.assertRaisesRegex(RuntimeError, "source changes"):
            guard.check_clean(self.root)
        (self.root / "untracked").unlink()
        (self.root / "native.rs").write_text("unreviewed")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_delta(self.root, self.source, guard.LOCKS)
        guard.git(self.root, "add", "native.rs")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_delta(self.root, self.source, guard.LOCKS)

    def hidden_flag_probe(self, flag):
        guard.git(self.root, "update-index", flag, "native.rs")
        operations = (lambda: guard.check_clean(self.root),
                      lambda: guard.check_delta(self.root, self.source, guard.LOCKS),
                      lambda: guard.local_candidate(self.root, self.source))
        for operation in operations:
            with self.assertRaisesRegex(RuntimeError, "index flags"):
                operation()
        (self.root / "native.rs").write_bytes(b"unreviewed hidden bytes\n")
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        for operation in operations:
            with self.assertRaisesRegex(RuntimeError, "index flags"):
                operation()
        self.assertEqual((self.root / "native.rs").read_bytes(), b"unreviewed hidden bytes\n")
        self.assertNotEqual(guard.git(self.root, "ls-files", "-v", "--", "native.rs")[:1], b"H")
        self.assertEqual(guard.git(self.root, "rev-parse", "HEAD").decode().strip(), self.source)

    def test_assume_unchanged_is_rejected_without_clearing(self):
        self.hidden_flag_probe("--assume-unchanged")

    def test_skip_worktree_is_rejected_without_clearing(self):
        self.hidden_flag_probe("--skip-worktree")

    def test_raw_auxiliary_and_lock_bytes_are_checked(self):
        manifest = self.root / guard.MANIFEST
        original = manifest.read_bytes()
        manifest.write_bytes(original + b"\n")
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_clean(self.root)
        manifest.write_bytes(original)
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        with self.assertRaisesRegex(RuntimeError, "worktree bytes"):
            guard.check_clean(self.root)
        guard.check_delta(self.root, self.source, guard.LOCKS)
        guard.git(self.root, "add", "--", guard.LOCKS[0])
        with self.assertRaisesRegex(RuntimeError, "staged"):
            guard.check_delta(self.root, self.source, guard.LOCKS)

    def test_local_commit_clean_deterministic_and_only_locks(self):
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        first = guard.local_candidate(self.root, self.source)
        guard.check_clean(self.root)
        self.assertEqual(first["changed_paths"], [guard.LOCKS[0]])
        self.assertFalse(first["published"])
        guard.git(self.root, "checkout", "--detach", self.source)
        (self.root / guard.LOCKS[0]).write_bytes(AFTER)
        self.assertEqual(guard.local_candidate(self.root, self.source), first)


class ObservationTests(unittest.TestCase):
    def test_native_pass_required_not_listing_skip_fail_or_crash(self):
        guard.verify_pass_cases("        PASS [0.01s] crate module::case\n", ("case",))
        for output in ("module::case", "SKIP [0.0s] crate module::case", "FAIL [0.0s] crate module::case",
                       "error[E0425]: case", "signal: 11 (SIGSEGV)", "timeout: module::case", "PASS [0.0s] crate module::case_extra"):
            with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, "PASS observation"):
                guard.verify_pass_cases(output, ("case",))


if __name__ == "__main__":
    unittest.main()
