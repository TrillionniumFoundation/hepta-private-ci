import subprocess
import tempfile
from pathlib import Path
import unittest

from staged_resolution_probe import stage_manifest, CANDIDATE_SPEC, SOURCE_SPEC


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name)
        self.source=base/'source'
        self.stage=base/'stage'
        for p in (self.source,self.stage):
            (p/'codex-rs').mkdir(parents=True)
            (p/'codex-rs/Cargo.toml').write_text('[workspace.dependencies]\\n'+SOURCE_SPEC+'\\n')
        subprocess.run(['git','init','-q',str(self.stage)],check=True)
        subprocess.run(['git','-C',str(self.stage),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.stage),'-c','user.name=Test','-c','user.email=ci@example.invalid','commit','-qm','fixture'],check=True)
        self.sha=subprocess.run(['git','-C',str(self.stage),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()

    def test_candidate_modifies_only_isolated_stage(self):
        r=stage_manifest(self.source,self.stage,self.sha)
        self.assertEqual((self.source/'codex-rs/Cargo.toml').read_text(),'[workspace.dependencies]\\n'+SOURCE_SPEC+'\\n')
        self.assertIn(CANDIDATE_SPEC,(self.stage/'codex-rs/Cargo.toml').read_text())
        self.assertTrue(r['preserved_e2ee_and_sqlite'])
        self.assertFalse(r['production_authorized'])
        self.assertFalse(r['cargo_graph_resolution_passed'])

    def test_reject_source_tree_as_stage(self):
        with self.assertRaises(ValueError):
            stage_manifest(self.source,self.source,self.sha)

    def test_reject_modified_unpinned_staging_commit(self):
        with self.assertRaises(ValueError):
            stage_manifest(self.source,self.stage,'0'*40)

    def test_reject_schema_drift_or_unpinned_features(self):
        path=self.stage/'codex-rs/Cargo.toml'
        path.write_text(path.read_text().replace('"e2e-encryption", ','') )
        with self.assertRaises(ValueError):
            stage_manifest(self.source,self.stage,self.sha)


if __name__=='__main__':
    unittest.main()
