import tempfile
from pathlib import Path
import tomllib
import unittest

from build_group_native import production_closure, without_dev_dependencies


class NativeBuildSourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        for crate in ("hepta-types", "hepta-contracts", "hepta-ndu"):
            self.manifest(crate, f'[package]\nname = "{crate}"\nversion = "0.0.0"\n')

    def manifest(self, crate, text):
        path = self.repo / "codex-rs" / crate / "Cargo.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_windows_target_retains_transitive_workspace_and_build_paths(self):
        self.manifest("hepta-contracts", '''
[target.'cfg(windows)'.dependencies]
path-util = { workspace = true }
[dev-dependencies]
dev-only = { path = "../unavailable-test-fixture" }
''')
        self.manifest("utils/path-util", '''
[dependencies]
absolute-path = { workspace = true }
[build-dependencies]
source-generator = { path = "../source-generator" }
''')
        self.manifest("utils/absolute-path", '[dependencies]\nsha2 = { workspace = true }\n')
        self.manifest("utils/source-generator", '[package]\nname = "source-generator"\n')
        crates, dependencies = production_closure(self.repo, {"dependencies": {
            "path-util": {"path": "utils/path-util"},
            "absolute-path": {"path": "utils/absolute-path"},
            "sha2": "0.10",
        }})
        self.assertEqual(crates, ["hepta-contracts", "hepta-ndu", "hepta-types",
                                  "utils/absolute-path", "utils/path-util", "utils/source-generator"])
        self.assertEqual(dependencies, ["absolute-path", "path-util", "sha2"])

    def test_dev_pruning_preserves_trailing_library_and_target_tables(self):
        source = '''[package]
name = "fixture"
[dev-dependencies]
test-helper = "1"
[lib]
doctest = false
[target.'cfg(windows)'.dependencies]
native = { workspace = true }
[target.'cfg(windows)'.dev-dependencies]
test-native = "2"
[features]
default = []
'''
        cleaned = without_dev_dependencies(source)
        self.assertIn("[lib]\ndoctest = false\n", cleaned)
        self.assertEqual(tomllib.loads(cleaned), {
            "package": {"name": "fixture"}, "lib": {"doctest": False},
            "target": {"cfg(windows)": {"dependencies": {"native": {"workspace": True}}}},
            "features": {"default": []},
        })

    def test_production_path_outside_source_tree_is_rejected(self):
        outside = self.repo / "outside"
        outside.mkdir()
        (outside / "Cargo.toml").write_text('[package]\nname = "outside"\n')
        self.manifest("hepta-types", '[dependencies]\nexternal = { path = "../../outside" }\n')
        with self.assertRaisesRegex(ValueError, "outside codex-rs"):
            production_closure(self.repo, {"dependencies": {}})

    def test_symlinked_production_crate_is_rejected_before_copying(self):
        actual = self.manifest("utils/actual", '[package]\nname = "actual"\n').parent
        (actual.parent / "linked").symlink_to(actual, target_is_directory=True)
        self.manifest("hepta-types", '[dependencies]\nlinked = { path = "../utils/linked" }\n')
        with self.assertRaisesRegex(ValueError, "symlink source dependency"):
            production_closure(self.repo, {"dependencies": {}})


if __name__ == "__main__":
    unittest.main()
