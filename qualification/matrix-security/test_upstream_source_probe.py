import tempfile
from pathlib import Path
import unittest

from upstream_source_probe import inspect_upstream, compare_local, UPSTREAM_GIT_SHA


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for d in ('crates/matrix-sdk','crates/matrix-sdk-crypto','crates/matrix-sdk-sqlite','codex-rs'):
            (self.root/d).mkdir(parents=True,exist_ok=True)
        (self.root/'Cargo.toml').write_text('[workspace.package]\nrust-version="1.96"\n')
        (self.root/'crates/matrix-sdk/Cargo.toml').write_text('[package]\nversion="0.19.1"\n[dependencies]\nanymap3="1.1.0"\n')
        (self.root/'crates/matrix-sdk-crypto/Cargo.toml').write_text('[package]\nversion="0.19.1"\n')
        (self.root/'crates/matrix-sdk-sqlite/Cargo.toml').write_text('[package]\nversion="0.19.1"\n[dependencies.rusqlite]\nversion="0.40.2"\n')
        (self.root/'codex-rs/Cargo.toml').write_text('[workspace.dependencies]\nlibsqlite3-sys={version="0.37",default-features=false}\nmatrix-sdk={version="0.18.0",features=["e2e-encryption","sqlite"],default-features=false}\n[patch.crates-io]\nmatrix-sdk-sqlite={path="third_party/matrix-sdk-sqlite-0.18.0"}\n')
        (self.root/'codex-rs/rust-toolchain.toml').write_text('[toolchain]\nchannel="1.95.0"\n')

    def test_exact_pinned_sha_is_required(self):
        with self.assertRaises(ValueError):
            inspect_upstream(self.root, UPSTREAM_GIT_SHA, source_head='f'*40)
        with self.assertRaises(ValueError):
            inspect_upstream(self.root, 'branch-main', source_head='branch-main')

    def test_source_019_anymap3_crypto_proof_does_not_claim_release(self):
        audit=inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA)
        self.assertTrue(audit['upstream_manifest_shape_ok'])
        self.assertFalse(audit['anymap2_direct'])
        self.assertTrue(audit['anymap3_direct'])
        self.assertFalse(audit['production_authorized'])
        self.assertFalse(audit['cargo_resolution_verified'])

    def test_unmaintained_anymap2_returning_fails_source_review(self):
        p=self.root/'crates/matrix-sdk/Cargo.toml'
        p.write_text(p.read_text().replace('anymap3','anymap2'))
        r=inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA)
        self.assertIn('UPSTREAM_ANYMAP3_MIGRATION_MISSING',r['manifest_errors'])

    def test_integrated_019_native_sqlite_source_without_legacy_patch(self):
        file=self.root/'codex-rs/Cargo.toml'
        base=file.read_text()
        secured=base.replace(
            'libsqlite3-sys={version="0.37"',
            'libsqlite3-sys={version="=0.38.2"'
        ).replace('matrix-sdk={version="0.18.0"',
                  'matrix-sdk={version="=0.19.1"'
        ).replace('matrix-sdk-sqlite={path="third_party/matrix-sdk-sqlite-0.18.0"}',
                  'matrix-sdk={path="third_party/matrix-sdk-0.19.1"}')
        file.write_text(secured)
        (self.root/'codex-rs/rust-toolchain.toml').write_text(
            '[toolchain]\\nchannel="1.96.0"\\n')
        upstream=inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA)
        report=compare_local(upstream,self.root)
        self.assertEqual(report['migration_blockers'],[])
        self.assertEqual(report['local_matrix_sdk_version'],'=0.19.1')
        self.assertEqual(report['local_sqlite_source_mode'],
                         'pinned_sdk_native_sqlite_requires_wal_qualification')
        self.assertFalse(report['migration_ready'])
        self.assertFalse(report['upstream_source_reviewed'])
        self.assertFalse(report['full_E2EE_restoration_verified'])
        # Removing the exact reviewed SDK source pin is not a valid upgrade.
        file.write_text(secured.replace(
            'matrix-sdk={path="third_party/matrix-sdk-0.19.1"}',''))
        missing=compare_local(upstream,self.root)
        self.assertIn('HEPTA_NATIVE_SQLITE_UPSTREAM_SDK_SOURCE_UNBOUND',
                      missing['migration_blockers'])
        # Stale old native sqlite patch can never piggyback on a new SDK.
        file.write_text(secured.replace(
            'matrix-sdk={path="third_party/matrix-sdk-0.19.1"}',
            'matrix-sdk-sqlite={path="third_party/matrix-sdk-sqlite-0.18.0"}'))
        stale=compare_local(upstream,self.root)
        self.assertIn('HEPTA_SQLITE_PATCH_STILL_018',
                      stale['migration_blockers'])
        # Retain the mandatory encrypted sqlite capability.
        file.write_text(secured.replace('"e2e-encryption",',''))
        no_e2ee=compare_local(upstream,self.root)
        self.assertIn('HEPTA_E2EE_SQLITE_FEATURES_MISSING',
                      no_e2ee['migration_blockers'])

    def test_missing_legacy_sqlite_patch_is_not_a_safe_018_configuration(self):
        file=self.root/'codex-rs/Cargo.toml'
        file.write_text(file.read_text().replace(
            'matrix-sdk-sqlite={path="third_party/matrix-sdk-sqlite-0.18.0"}',''))
        upstream=inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA)
        local=compare_local(upstream,self.root)
        self.assertIn('HEPTA_SQLITE_PATCH_STILL_018',
                      local['migration_blockers'])
        self.assertFalse(local['migration_ready'])

    def test_unpatched_crypto_fails_source_review(self):
        (self.root/'crates/matrix-sdk-crypto/Cargo.toml').write_text('[package]\nversion="0.18.0"\n')
        r=inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA)
        self.assertIn('UPSTREAM_CRYPTO_UNPATCHED',r['manifest_errors'])

    def test_local_rust_sqlite_and_e2ee_migration_are_not_assumed(self):
        r=compare_local(inspect_upstream(self.root,UPSTREAM_GIT_SHA,source_head=UPSTREAM_GIT_SHA),self.root)
        self.assertEqual(set(r['migration_blockers']),{
            'LOCAL_RUST_TOOLCHAIN_BELOW_PINNED_UPSTREAM_MSRV',
            'LIBSQLITE3_SYS_037_VS_UPSTREAM_RUSQLITE_040_LINKS_038',
            'HEPTA_MATRIX_SDK_RELEASE_NEEDS_MIGRATION',
            'HEPTA_SQLITE_PATCH_STILL_018',
        })
        self.assertFalse(r['migration_ready'])
        self.assertFalse(r['full_E2EE_restoration_verified'])

if __name__=='__main__':
    unittest.main()