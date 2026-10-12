import subprocess
import tempfile
from pathlib import Path
import unittest

from staged_resolution_probe import stage_manifest, CANDIDATE_SPEC, SOURCE_SPEC, SQLITE_PATCH_SPEC

BASELINE_MANIFEST = ('[workspace.dependencies]\n' + SOURCE_SPEC +
                     '\n\n[patch.crates-io]\n' + SQLITE_PATCH_SPEC + '\n')


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name)
        self.source=base/'source'
        self.stage=base/'stage'
        for p in (self.source,self.stage):
            (p/'codex-rs').mkdir(parents=True)
            (p/'codex-rs/Cargo.toml').write_text(BASELINE_MANIFEST)
        subprocess.run(['git','init','-q',str(self.stage)],check=True)
        subprocess.run(['git','-C',str(self.stage),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.stage),'-c','user.name=Test','-c','user.email=ci@example.invalid','commit','-qm','fixture'],check=True)
        self.sha=subprocess.run(['git','-C',str(self.stage),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()

    def test_candidate_modifies_only_isolated_stage(self):
        r=stage_manifest(self.source,self.stage,self.sha)
        self.assertEqual((self.source/'codex-rs/Cargo.toml').read_text(),BASELINE_MANIFEST)
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


    def test_isolated_upstream_sqlite_arm_removes_only_the_obsolete_patch(self):
        source = self.source/'codex-rs/Cargo.toml'
        stage = self.stage/'codex-rs/Cargo.toml'
        result = stage_manifest(
            self.source, self.stage, self.sha,
            sqlite_arm='use_upstream_sqlite',
        )
        self.assertEqual(result['schema'],'hepta.matrix-sdk-cargo-resolution-probe.v2')
        self.assertEqual(result['sqlite_arm'],'use_upstream_sqlite')
        self.assertFalse(result['legacy_sqlite_patch_preserved'])
        self.assertIn(SQLITE_PATCH_SPEC,source.read_text())
        self.assertNotIn(SQLITE_PATCH_SPEC,stage.read_text())
        self.assertIn(CANDIDATE_SPEC,stage.read_text())
        self.assertFalse(result['production_authorized'])

    def test_retained_sqlite_arm_keeps_exact_source_patch(self):
        stage = self.stage/'codex-rs/Cargo.toml'
        result = stage_manifest(self.source,self.stage,self.sha)
        self.assertTrue(result['legacy_sqlite_patch_preserved'])
        self.assertIn(SQLITE_PATCH_SPEC,stage.read_text())

    def test_unregistered_or_missing_sqlite_patch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'unregistered'):
            stage_manifest(self.source,self.stage,self.sha,sqlite_arm='disable_e2ee')
        stage = self.stage/'codex-rs/Cargo.toml'
        stage.write_text(BASELINE_MANIFEST.replace(SQLITE_PATCH_SPEC + '\n',''))
        with self.assertRaisesRegex(ValueError,'not the exact pinned source'):
            stage_manifest(self.source,self.stage,self.sha,sqlite_arm='use_upstream_sqlite')
        with self.assertRaisesRegex(ValueError,'not the exact pinned source'):
            stage_manifest(self.source,self.stage,self.sha,sqlite_arm='retain_legacy_sqlite_patch')
        stage.write_text(BASELINE_MANIFEST.replace(SQLITE_PATCH_SPEC,
                         SQLITE_PATCH_SPEC.replace('0.18.0','0.18.1')))
        with self.assertRaisesRegex(ValueError,'not the exact pinned source'):
            stage_manifest(self.source,self.stage,self.sha,sqlite_arm='use_upstream_sqlite')

    def test_sqlite_arm_never_weakens_e2ee_or_touches_source_lock(self):
        lock=self.source/'codex-rs/Cargo.lock'
        lock.write_text('immutable original lock\n')
        result=stage_manifest(self.source,self.stage,self.sha,
                              sqlite_arm='use_upstream_sqlite')
        self.assertEqual(lock.read_text(),'immutable original lock\n')
        self.assertTrue(result['preserved_e2ee_and_sqlite'])
        self.assertEqual(result['affected_workspace_files'],['codex-rs/Cargo.toml'])
        self.assertFalse(result['cargo_graph_resolution_passed'])


if __name__=='__main__':
    unittest.main()
