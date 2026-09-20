import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("hepta-implementation-maps.py")
SPEC = importlib.util.spec_from_file_location("hepta_implementation_maps", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ImplementationMapSourceBaseTests(unittest.TestCase):
    def module(self):
        return {
            "id": "compact.engine",
            "rootBindings": [{"path": "codex-rs/hepta-compact-engine"}],
            "technicalDocument": "docs/modules/compact.engine/TECHNICAL.md",
        }

    def test_relevant_source_change_marks_source_base_stale(self):
        def fake_git(*args):
            if args[:2] == ("rev-parse", "abc^{tree}"):
                return "tree"
            if args[:3] == ("merge-base", "--is-ancestor", "abc"):
                return ""
            if args[:2] == ("diff", "--name-only"):
                return "codex-rs/hepta-compact-engine/src/lib.rs"
            raise AssertionError(args)

        with patch.object(MODULE, "git", side_effect=fake_git):
            failures = MODULE.verify_source_base(
                self.module(), {"commit": "abc", "tree": "tree"}
            )
        self.assertEqual(1, len(failures))
        self.assertIn("source base stale", failures[0])

    def test_generated_map_only_commit_does_not_create_self_reference_failure(self):
        def fake_git(*args):
            if args[:2] == ("rev-parse", "abc^{tree}"):
                return "tree"
            if args[:3] == ("merge-base", "--is-ancestor", "abc"):
                return ""
            if args[:2] == ("diff", "--name-only"):
                # git diff is path-restricted to implementation-relevant
                # sources and therefore excludes IMPLEMENTATION_MAP.json.
                return ""
            raise AssertionError(args)

        with patch.object(MODULE, "git", side_effect=fake_git):
            failures = MODULE.verify_source_base(
                self.module(), {"commit": "abc", "tree": "tree"}
            )
        self.assertEqual([], failures)

    def test_wrong_tree_for_commit_is_rejected(self):
        def fake_git(*args):
            if args[:2] == ("rev-parse", "abc^{tree}"):
                return "actual-tree"
            if args[:3] == ("merge-base", "--is-ancestor", "abc"):
                return ""
            if args[:2] == ("diff", "--name-only"):
                return ""
            raise AssertionError(args)

        with patch.object(MODULE, "git", side_effect=fake_git):
            failures = MODULE.verify_source_base(
                self.module(), {"commit": "abc", "tree": "wrong-tree"}
            )
        self.assertTrue(any("tree does not match commit" in value for value in failures))


if __name__ == "__main__":
    unittest.main()
