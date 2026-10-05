"""Real-Git source guard regression; no compiler or external tool is installed."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "preview_builder", ROOT / "tools/build-product-preview.py"
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "source"
        self.root.mkdir()
        self.external = Path(temporary.name) / "runner-temp"
        self.external.mkdir()
        self.git("init", "-q")
        source = self.root / "codex-rs/hepta-native-gateway/src/lib.rs"
        source.parent.mkdir(parents=True)
        source.write_text("// committed fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        previous = BUILDER.ROOT
        BUILDER.ROOT = self.root
        self.addCleanup(setattr, BUILDER, "ROOT", previous)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=dot", "-c", "user.email=dot@localhost", *args],
            cwd=self.root,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def test_repository_tool_cache_is_rejected_but_external_cache_is_clean(self):
        before = BUILDER.identity()
        cache = self.root / ".tmp/ui-official-tools-robrix"
        cache.mkdir(parents=True)
        (cache / "tool-placeholder").write_text("nonexecutable test data")
        with self.assertRaisesRegex(ValueError, r"dirty paths:[\s\S]*\.tmp/"):
            BUILDER.identity()
        cache.rename(self.external / "ui-official-tools-robrix")
        self.assertEqual(BUILDER.identity(), before)

    def test_actual_tracked_or_untracked_source_still_fails(self):
        path = self.root / "codex-rs/hepta-native-gateway/src/lib.rs"
        path.write_text("// dirty source\n")
        with self.assertRaisesRegex(ValueError, "committed clean source"):
            BUILDER.identity()
        self.git("restore", "--", str(path.relative_to(self.root)))
        path.with_name("untracked.rs").write_text("// untracked source\n")
        with self.assertRaisesRegex(ValueError, "untracked.rs"):
            BUILDER.identity()


if __name__ == "__main__":
    unittest.main()
