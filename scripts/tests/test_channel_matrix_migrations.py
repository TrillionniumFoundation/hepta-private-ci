"""The generated inventory and native schema sources must track migration SQL."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import channel_matrix_migrations as migrations
from channel_matrix_diagnostics import SCHEMA_VERSION


class MigrationInventoryTests(unittest.TestCase):
    def test_inventory_and_reader_version_follow_sql(self):
        self.assertEqual(migrations.OUTPUT.read_text(),migrations.render())
        files=sorted((ROOT/'codex-rs/hepta-matrix-store/migrations').glob('*.sql'))
        self.assertEqual(SCHEMA_VERSION,int(files[-1].name[:4]))
        source=(ROOT/'codex-rs/hepta-matrix-store/src/store.rs').read_text()
        for path in files[5:]:
            self.assertIn('include_str!("../migrations/'+path.name+'")',source)
