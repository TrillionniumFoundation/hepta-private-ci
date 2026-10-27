"""Real tiny Git candidate recovery with the existing port guard implementation."""

from pathlib import Path
import shutil
import sys
import types
import unittest

from .commands import Commands
from .files import describe, read_json
from .source import prepare_source, restore_source


class ProducerRestore(unittest.TestCase):
    def test_original_restore_guards_then_identical_private_tree_without_host_rust(
        self,
    ):
        # Reuse the existing synthetic artifact fixture, not a relaxed copy of
        # the production port guard. Its setup exercises actual Git patching.
        repo = Path(__file__).resolve().parents[5]
        scripts = repo / "scripts"
        previous_path = list(sys.path)
        loaded = {}
        try:
            sys.path.insert(0, str(scripts))
            for name in (
                "ndu_port_candidate_common",
                "ndu_port_candidate",
                "test_ndu_port_candidate",
            ):
                loaded[name] = sys.modules.pop(name, None)
            name = "test_ndu_port_candidate"
            module = types.ModuleType(name)
            module.__file__ = str(scripts / (name + ".py"))
            exec(
                compile(Path(module.__file__).read_bytes(), module.__file__, "exec"),
                module.__dict__,
            )
            fixture = module.PortArtifactTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            helper = fixture.root / "scripts/ndu_port_candidate_common.py"
            helper.parent.mkdir(exist_ok=True)
            shutil.copyfile(scripts / "ndu_port_candidate_common.py", helper)
            helper.chmod(0o644)
            paths = (
                "codex-rs/Cargo.toml",
                "justfile",
                "scripts/run-nextest.py",
                "codex-rs/.config/nextest.toml",
                "codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs",
                "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse-linux.py",
                "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
                "codex-rs/hepta-matrixd/tests/fixtures/synapse-loopback-proxy.py",
            )
            for relative in paths:
                path = fixture.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "# synthetic source fixture; never compiled or qualified\n"
                )
            module.git(fixture.root, "add", ".")
            module.git(
                fixture.root,
                "commit",
                "-qm",
                "bind real guard and small test-only source fixture",
            )
            fixture.source = (
                module.git(fixture.root, "rev-parse", "HEAD").decode().strip()
            )
            fixture.record["source_commit"] = fixture.source
            fixture.seal()
            output = fixture.base / "linux-restore"
            output.mkdir()
            git = Path(shutil.which("git")).resolve()
            environment = {
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_OPTIONAL_LOCKS": "0",
            }
            commands = Commands(
                output / "commands",
                {"git": {"path": str(git), **describe(git)}},
                environment,
                fixture.root,
            )
            tree = restore_source(
                fixture.root,
                fixture.artifact,
                fixture.result_sha,
                fixture.source,
                output,
                commands,
            )
            self.assertTrue(
                read_json(output / "RESTORED_SOURCE.json")[
                    "original_dependency_policy_unchanged"
                ]
            )
            self.assertEqual(
                module.git(fixture.root, "rev-parse", "HEAD").decode().strip(),
                fixture.source,
            )
            original_index = describe(fixture.root / ".git/index")
            evidence = fixture.base / "private-tree-evidence"
            evidence.mkdir()
            seal = prepare_source(
                fixture.root,
                fixture.artifact,
                fixture.result_sha,
                fixture.source,
                fixture.base / "private-checkout",
                evidence,
                commands,
            )
            self.assertEqual(
                (seal["candidate_tree"], seal["qualification_tree"]), (tree, tree)
            )
            self.assertNotEqual(seal["qualification_commit"], fixture.source)
            self.assertTrue(seal["original_head_unchanged"])
            self.assertEqual(describe(fixture.root / ".git/index"), original_index)
            self.assertEqual({item["tool"] for item in commands.records}, {"git"})
            self.assertEqual(
                module.git(
                    fixture.base / "private-checkout",
                    "status",
                    "--porcelain",
                    "--ignored",
                ),
                b"",
            )
        finally:
            sys.path[:] = previous_path
            for name, previous in loaded.items():
                sys.modules.pop(name, None)
                if previous is not None:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
