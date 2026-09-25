import unittest
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from hepta_rust_surface import without_disabled_feature_items

GATE = '#[cfg(feature = "qualification-legacy-learning-write")]\n'
FEATURE = "qualification-legacy-learning-write"

class ProductSurfaceTests(unittest.TestCase):
    def project(self, text):
        return without_disabled_feature_items(text, FEATURE)

    def test_only_guarded_item_is_removed(self):
        source = GATE + 'pub fn old() { LedgerEvent::Decision(x); }\n' + 'fn product() { LedgerEvent::Outcome(x); }'
        projected = self.project(source)
        self.assertNotIn('Decision', projected)
        self.assertIn('Outcome', projected)
        self.assertEqual(len(projected), len(source))

    def test_guarded_import_and_extra_attribute(self):
        self.assertNotIn('DurableLearningJournal', self.project(GATE + 'use x::DurableLearningJournal;\n'))
        self.assertNotIn('Decision', self.project(GATE + '#[allow(clippy::too_many_arguments)]\npub fn old() { LedgerEvent::Decision(x); }'))

    def test_raw_strings_and_nested_comments_cannot_end_item(self):
        source = GATE + 'pub fn old() { let s = r##"} ;"##; /* /* } */ } */ LedgerEvent::Decision(x); }\nfn product() { forbidden(); }'
        projected = self.project(source)
        self.assertNotIn('Decision', projected)
        self.assertIn('forbidden', projected)

    def test_comments_and_similar_cfg_do_not_hide_product_code(self):
        for source in ['/*\n' + GATE + '*/\nfn product() { forbidden(); }',
                       '#[cfg(any(feature = "qualification-legacy-learning-write", unix))]\nfn product() { forbidden(); }',
                       GATE + 'macro! { forbidden(); }',
                       GATE + 'fn broken() { forbidden();']:
            self.assertIn('forbidden', self.project(source))

class RepositorySourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        cargo = self.root / "codex-rs/hepta-agentd/Cargo.toml"
        cargo.parent.mkdir(parents=True)
        cargo.write_text('[features]\ndefault = []\nqualification-legacy-learning-write = []\n')
        spec = importlib.util.spec_from_file_location("lane_inventory_test", Path(__file__).with_name("hepta-lane-e-closure.py"))
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        self.lane = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.lane
        spec.loader.exec_module(self.lane)

    def tearDown(self):
        self.directory.cleanup()
        sys.modules.pop("lane_inventory_test", None)

    def findings(self):
        findings = self.lane.Findings()
        with patch.object(self.lane, "ROOT", self.root):
            self.lane.verify_product_writer_exclusivity(findings)
        return findings.items

    def test_untracked_product_writer_cannot_hide(self):
        source = self.root / "codex-rs/real-product/src/lib.rs"
        source.parent.mkdir(parents=True)
        source.write_text('fn write() { LedgerEvent::Decision(value); }')
        self.assertTrue(self.findings())

    def test_tracked_source_remains_checked_even_if_ignored(self):
        (self.root / ".gitignore").write_text('target/\n')
        source = self.root / "codex-rs/target/committed.rs"
        source.parent.mkdir(parents=True)
        source.write_text('fn write() { LedgerEvent::Outcome(value); }')
        subprocess.run(["git", "-C", str(self.root), "add", "-f", str(source.relative_to(self.root))], check=True)
        self.assertTrue(self.findings())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named-pipe fixture requires Unix")
    def test_ignored_fault_injection_pipe_is_not_opened(self):
        (self.root / ".gitignore").write_text('target/\n')
        source = self.root / "codex-rs/target/fixture.rs"
        source.parent.mkdir(parents=True)
        os.mkfifo(source)
        self.assertEqual(self.findings(), [])

if __name__ == '__main__':
    unittest.main()
