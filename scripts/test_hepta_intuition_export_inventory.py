"""Closed-world inventory must retain actual nested compatibility re-exports."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "intuition_maps", Path(__file__).with_name("hepta-implementation-maps.py")
)
MAPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAPS)


class ExportInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / "owner/src"
        self.src.mkdir(parents=True)
        (self.src / "lib.rs").write_text(
            "mod calibrated;\npub use calibrated::legacy;\npub use calibrated::Record;\n"
        )
        (self.src / "calibrated.rs").write_text(
            '#[path = "binding.rs"]\nmod binding;\npub use binding::legacy;\npub struct Record;\nimpl Record { pub fn method() {} }\n'
        )
        (self.src / "binding.rs").write_text("pub fn legacy() {}\nfn private() {}\n")

    def test_nested_path_reexport_is_counted_without_type_methods(self):
        with mock.patch.object(MAPS, "ROOT", self.root):
            self.assertEqual(MAPS.public_rust_functions("owner"), {"legacy"})

    def test_comments_and_strings_do_not_create_reexports(self):
        with (self.src / "lib.rs").open("a") as f:
            f.write(
                '// pub use calibrated::private;\nconst TEXT: &str = "pub use binding::private;";\n'
            )
        with mock.patch.object(MAPS, "ROOT", self.root):
            self.assertEqual(MAPS.public_rust_functions("owner"), {"legacy"})

    def test_module_path_escape_is_rejected(self):
        (self.src / "calibrated.rs").write_text(
            '#[path = "../escape.rs"]\nmod binding;\npub use binding::legacy;\n'
        )
        with mock.patch.object(MAPS, "ROOT", self.root), self.assertRaises(ValueError):
            MAPS.public_rust_functions("owner")

    def test_actual_policy_has_all_seventeen_exported_functions(self):
        self.assertEqual(
            len(MAPS.public_rust_functions("codex-rs/hepta-intuition")), 17
        )


if __name__ == "__main__":
    unittest.main()
