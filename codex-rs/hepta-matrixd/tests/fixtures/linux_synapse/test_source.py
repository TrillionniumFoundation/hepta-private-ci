"""The candidate helper must be verified before any Python top-level code runs."""

from pathlib import Path
import importlib.util
import marshal
import shutil
import struct
import sys
import tempfile
import unittest

from .commands import Commands
from .files import describe
from .source import prepare_source, replay_candidate_tree


class SourceImportBoundary(unittest.TestCase):
    def test_staged_stdlib_shadow_is_not_imported(self):
        with tempfile.TemporaryDirectory(prefix="hepta-stdlib-shadow-") as temporary:
            root = Path(temporary).resolve()
            repo, output, producer = root / "repo", root / "output", root / "producer"
            for directory in (repo, output, producer):
                directory.mkdir()
            helper = repo / "scripts/ndu_port_candidate_common.py"
            helper.parent.mkdir()
            helper.write_text(
                "import tomllib\ndef load_candidate(*args):\n    assert tomllib.loads('safe = true')['safe']\n    raise ValueError('trusted stdlib used')\n"
            )
            helper.chmod(0o644)
            git = Path(shutil.which("git")).resolve()
            environment = {
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@invalid",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@invalid",
            }
            commands = Commands(
                output / "commands",
                {"git": {"path": str(git), **describe(git)}},
                environment,
                repo,
            )
            for label, arguments in (
                ("init", ["init"]),
                ("add", ["add", "."]),
                ("commit", ["commit", "-m", "trusted helper"]),
            ):
                commands.run("git", arguments, label=label)
            source_sha = commands.text("git", ["rev-parse", "HEAD"], label="head")
            shadow = repo / "fixtures"
            shadow.mkdir()
            sentinel = root / "MUST_NOT_EXIST"
            (shadow / "tomllib.py").write_text(
                "from pathlib import Path\nPath("
                + repr(str(sentinel))
                + ").write_text('executed')\n"
            )
            commands.run("git", ["add", "fixtures/tomllib.py"], label="stage-shadow")
            previous_path, previous_module = (
                list(sys.path),
                sys.modules.pop("tomllib", None),
            )
            try:
                sys.path.insert(0, str(shadow))
                with self.assertRaisesRegex(ValueError, "trusted stdlib used"):
                    prepare_source(
                        repo,
                        producer,
                        "a" * 64,
                        source_sha,
                        root / "qualified",
                        output,
                        commands,
                    )
            finally:
                sys.path[:] = previous_path
                sys.modules.pop("tomllib", None)
                if previous_module is not None:
                    sys.modules["tomllib"] = previous_module
            self.assertFalse(sentinel.exists())

    def test_candidate_mode_drift_rejected_by_exact_patch_tree(self):
        with tempfile.TemporaryDirectory(prefix="hepta-mode-tree-") as temporary:
            root = Path(temporary).resolve()
            repo, output, producer = root / "repo", root / "output", root / "producer"
            for directory in (repo, output, producer):
                directory.mkdir()
            source = repo / "Cargo.toml"
            source.write_text("base\n")
            source.chmod(0o644)
            git = Path(shutil.which("git")).resolve()
            environment = {
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@invalid",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@invalid",
            }
            commands = Commands(
                output / "commands",
                {"git": {"path": str(git), **describe(git)}},
                environment,
                repo,
            )
            for label, arguments in (
                ("init", ["init"]),
                ("add", ["add", "."]),
                ("commit", ["commit", "-m", "base"]),
            ):
                commands.run("git", arguments, label=label)
            source_sha = commands.text("git", ["rev-parse", "HEAD"], label="head")
            source.write_text("reviewed candidate bytes\n")
            commands.run("git", ["add", "Cargo.toml"], label="stage-candidate")
            _, exported = commands.run(
                "git",
                ["diff", "--cached", "--binary", "--full-index", "HEAD"],
                label="export-producer-patch",
            )
            patch = producer / "candidate.patch"
            patch.write_bytes(exported.read_bytes())
            source.chmod(0o755)
            commands.run("git", ["add", "Cargo.toml"], label="stage-mode-tamper")
            original_index = describe(repo / ".git/index")
            with self.assertRaisesRegex(ValueError, "including file modes"):
                replay_candidate_tree(
                    commands,
                    producer,
                    {"artifacts": {"candidate.patch": describe(patch)}},
                    source_sha,
                    output,
                )
            self.assertEqual(describe(repo / ".git/index"), original_index)
            self.assertEqual(
                commands.text("git", ["rev-parse", "HEAD"], label="unchanged-head"),
                source_sha,
            )

    def test_staged_matching_bytecode_cache_is_never_executed(self):
        with tempfile.TemporaryDirectory(prefix="hepta-source-bytecode-") as temporary:
            root = Path(temporary).resolve()
            repo, output, producer = root / "repo", root / "output", root / "producer"
            for directory in (repo, output, producer):
                directory.mkdir()
            helper = repo / "scripts/ndu_port_candidate_common.py"
            helper.parent.mkdir()
            helper.write_text(
                "def load_candidate(*args):\n    raise ValueError('trusted source refused absent producer')\n"
            )
            helper.chmod(0o644)
            git = Path(shutil.which("git")).resolve()
            environment = {
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@invalid",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@invalid",
            }
            commands = Commands(
                output / "commands",
                {"git": {"path": str(git), **describe(git)}},
                environment,
                repo,
            )
            commands.run("git", ["init"], label="init")
            commands.run("git", ["add", "."], label="add")
            commands.run("git", ["commit", "-m", "trusted source"], label="commit")
            source_sha = commands.text("git", ["rev-parse", "HEAD"], label="head")
            sentinel = root / "MUST_NOT_EXIST"
            malicious = compile(
                "from pathlib import Path\nPath("
                + repr(str(sentinel))
                + ").write_text('executed')\n",
                str(helper),
                "exec",
            )
            cached = Path(importlib.util.cache_from_source(str(helper)))
            cached.parent.mkdir()
            header = importlib.util.MAGIC_NUMBER + struct.pack(
                "<III", 0, int(helper.stat().st_mtime), helper.stat().st_size
            )
            cached.write_bytes(header + marshal.dumps(malicious))
            commands.run(
                "git",
                ["add", str(cached.relative_to(repo))],
                label="stage-matching-malicious-bytecode",
            )
            with self.assertRaisesRegex(
                ValueError, "trusted source refused absent producer"
            ):
                prepare_source(
                    repo,
                    producer,
                    "a" * 64,
                    source_sha,
                    root / "qualified",
                    output,
                    commands,
                )
            self.assertFalse(sentinel.exists())
            self.assertFalse((root / "qualified").exists())

    def test_staged_or_unstaged_helper_tamper_never_executes(self):
        for staged in (False, True):
            with (
                self.subTest(staged=staged),
                tempfile.TemporaryDirectory(prefix="hepta-source-import-") as temporary,
            ):
                root = Path(temporary).resolve()
                repo, output, producer = (
                    root / "repo",
                    root / "output",
                    root / "producer",
                )
                for directory in (repo, output, producer):
                    directory.mkdir()
                helper = repo / "scripts/ndu_port_candidate_common.py"
                helper.parent.mkdir()
                helper.write_text(
                    "# Exact HEAD helper, never imported in this negative test.\n"
                )
                helper.chmod(0o644)
                (repo / "candidate.txt").write_text("base\n")
                git = Path(shutil.which("git")).resolve()
                environment = {
                    "PATH": "/usr/bin:/bin",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "test",
                    "GIT_AUTHOR_EMAIL": "test@invalid",
                    "GIT_COMMITTER_NAME": "test",
                    "GIT_COMMITTER_EMAIL": "test@invalid",
                }
                commands = Commands(
                    output / "commands",
                    {"git": {"path": str(git), **describe(git)}},
                    environment,
                    repo,
                )
                commands.run("git", ["init"], label="init")
                commands.run("git", ["add", "."], label="base-add")
                commands.run(
                    "git", ["commit", "-m", "trusted base"], label="base-commit"
                )
                source_sha = commands.text(
                    "git", ["rev-parse", "HEAD"], label="base-sha"
                )
                # A legitimate candidate is staged; HEAD-vs-index must not be
                # required to be empty merely to reject a changed helper.
                (repo / "candidate.txt").write_text("legitimate staged candidate\n")
                commands.run("git", ["add", "candidate.txt"], label="stage-candidate")
                sentinel = root / "MUST_NOT_EXIST"
                helper.write_text(
                    "from pathlib import Path\nPath("
                    + repr(str(sentinel))
                    + ").write_text('executed')\n"
                )
                if staged:
                    commands.run(
                        "git",
                        ["add", "scripts/ndu_port_candidate_common.py"],
                        label="stage-malicious-helper",
                    )
                with self.assertRaises((ValueError, RuntimeError)):
                    prepare_source(
                        repo,
                        producer,
                        "a" * 64,
                        source_sha,
                        root / "qualified",
                        output,
                        commands,
                    )
                self.assertFalse(sentinel.exists())
                self.assertFalse((root / "qualified").exists())
                self.assertEqual(
                    commands.text(
                        "git", ["rev-parse", "HEAD"], label="unchanged-original-head"
                    ),
                    source_sha,
                )


if __name__ == "__main__":
    unittest.main()
