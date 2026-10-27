"""Exercise artifact/source binding and real subprocess failure preservation."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import ndu_dependency_candidate_common as common
import ndu_tls_lock_candidate as candidate


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.STDOUT)


class CandidateBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "repository"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Candidate fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "config", "commit.gpgsign", "false")
        self.vendor = f"{common.VENDOR}/Cargo.toml"
        for name in (*common.FILES[:4], *common.POLICIES, self.vendor):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"baseline {name}\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "fixture baseline")
        self.source = git(self.root, "rev-parse", "HEAD").decode().strip()
        policy = common.describe(self.root, common.POLICIES)
        vendor = common.describe(self.root, (self.vendor,))
        for name in common.FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                b"\0ZIP fixture\xff"
                if name.endswith(".zip")
                else f"candidate {name}\n".encode()
            )
        git(self.root, "add", ".")
        self.artifact = self.directory / "artifact"
        self.artifact.mkdir()
        self.patch = self.artifact / "candidate.patch"
        git(
            self.root,
            "diff",
            "--binary",
            "--no-renames",
            f"--output={self.patch}",
            "HEAD",
        )
        self.record = {
            "schema": common.SCHEMA,
            "status": "candidate_generated",
            "source_commit": self.source,
            "files": common.describe(self.root, common.FILES),
            "changed_paths": list(common.FILES),
            "policy_inputs": policy,
            "vendor_inputs": vendor,
            "candidate_patch_sha256": common.checksum(self.patch),
            "original_dependency_policy_unchanged": True,
        }
        for name in common.FILES:
            target = self.artifact / "files" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / name, target)
        self.seal()
        git(self.root, "reset", "--hard", "HEAD")

    def seal(self):
        (self.artifact / "RESULT.json").write_text(
            json.dumps(self.record, indent=2) + "\n"
        )
        self.expected_result = common.checksum(self.artifact / "RESULT.json")

    def runner(self, suffix="test"):
        return common.Recorder(self.root, self.directory / f"report-{suffix}", "test")

    def restore(self, runner):
        return common.restore_candidate(
            runner, self.artifact, self.expected_result, self.source
        )

    def test_bound_binary_patch_reconstructs_all_exact_snapshots(self):
        runner = self.runner()
        restored = self.restore(runner)
        self.assertEqual(common.describe(self.root, common.FILES), restored["files"])
        self.assertEqual(
            (self.root / common.FILES[-1]).read_bytes(), b"\0ZIP fixture\xff"
        )
        for command in runner.record["commands"]:
            self.assertEqual(command["exit_code"], 0)
            self.assertEqual(
                common.checksum(runner.output / command["log"]), command["log_sha256"]
            )

    def test_tampered_result_patch_or_snapshot_is_rejected_before_apply(self):
        paths = [
            self.artifact / "RESULT.json",
            self.patch,
            self.artifact / "files/codex-rs/Cargo.lock",
        ]
        original = (self.root / common.FILES[0]).read_bytes()
        for index, path in enumerate(paths):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                path.write_bytes(before + b"tampered")
                with self.assertRaises(ValueError):
                    self.restore(self.runner(str(index)))
                path.write_bytes(before)
                self.assertEqual((self.root / common.FILES[0]).read_bytes(), original)

    def test_new_checkout_head_cannot_consume_the_old_artifact(self):
        git(self.root, "commit", "--allow-empty", "-qm", "different source")
        with self.assertRaisesRegex(ValueError, "Checkout HEAD"):
            self.restore(self.runner())

    def test_even_a_resealed_policy_patch_is_rejected_before_apply(self):
        git(self.root, "apply", "--index", str(self.patch))
        policy = self.root / common.POLICIES[0]
        policy.write_text("unapproved ignore policy\n")
        git(
            self.root,
            "diff",
            "--binary",
            "--no-renames",
            f"--output={self.patch}",
            "HEAD",
        )
        self.record["changed_paths"].append(common.POLICIES[0])
        self.record["candidate_patch_sha256"] = common.checksum(self.patch)
        self.seal()
        git(self.root, "reset", "--hard", "HEAD")
        with self.assertRaisesRegex(ValueError, "unapproved path"):
            self.restore(self.runner())
        self.assertEqual(
            common.describe(self.root, common.POLICIES), self.record["policy_inputs"]
        )

    def test_post_apply_vendor_or_policy_mutation_is_rejected(self):
        runner = self.runner()
        record = self.restore(runner)
        for name in (self.vendor, common.POLICIES[0]):
            with self.subTest(path=name):
                path = self.root / name
                before = path.read_bytes()
                path.write_bytes(before + b"changed")
                with self.assertRaisesRegex(ValueError, "bound"):
                    common.verify_tree(runner, record)
                if name == common.POLICIES[0]:
                    self.assertFalse(
                        runner.record["original_dependency_policy_unchanged"]
                    )
                path.write_bytes(before)


class ProcessEvidenceTests(unittest.TestCase):
    def test_failure_stdout_stderr_and_later_success_are_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "repository"
            root.mkdir()
            runner = common.Recorder(root, directory / "evidence", "test")
            status = runner.run(
                "failing-process",
                [
                    sys.executable,
                    "-c",
                    "import sys; print('failed output'); print('failed detail', file=sys.stderr); sys.exit(7)",
                ],
                required=False,
            )
            self.assertEqual(status, 7)
            runner.run(
                "later-process", [sys.executable, "-c", "print('later command ran')"]
            )
            record = json.loads((runner.output / "RESULT.json").read_text())
            self.assertEqual([row["exit_code"] for row in record["commands"]], [7, 0])
            first = record["commands"][0]
            log = runner.output / first["log"]
            self.assertEqual(
                set(log.read_text().splitlines()), {"failed output", "failed detail"}
            )
            self.assertEqual(common.checksum(log), first["log_sha256"])

    def test_required_failure_raises_after_persisting_actual_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "repository"
            root.mkdir()
            runner = common.Recorder(root, directory / "evidence", "generate")
            with self.assertRaisesRegex(RuntimeError, "exit 19"):
                runner.run("resolver", [sys.executable, "-c", "raise SystemExit(19)"])
            self.assertEqual(
                json.loads((runner.output / "RESULT.json").read_text())["commands"][0][
                    "exit_code"
                ],
                19,
            )


class ResolvedGraphTests(unittest.TestCase):
    def test_old_parallel_version_or_registry_parser_cannot_masquerade_as_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "codex-rs").mkdir()
            packages = [
                f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
                for name, version in candidate.UPDATES
            ]
            parser = '[[package]]\nname = "i18n-config"\nversion = "0.4.8"\ndependencies = ["toml 0.9.5"]\n'
            lock = root / "codex-rs/Cargo.lock"
            lock.write_text("\n".join(packages + [parser]))
            candidate.validate_graph(root)
            for addition in (
                '[[package]]\nname = "zstd"\nversion = "0.13.3"\n',
                '[[package]]\nname = "basic-toml"\nversion = "0.1.10"\n',
            ):
                lock.write_text("\n".join(packages + [parser, addition]))
                with self.assertRaises(ValueError):
                    candidate.validate_graph(root)
            lock.write_text(
                "\n".join(
                    packages
                    + [
                        parser
                        + 'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
                    ]
                )
            )
            with self.assertRaises(ValueError):
                candidate.validate_graph(root)


if __name__ == "__main__":
    unittest.main()
