"""Adversarial tests: exact source Delta, SQLite links and runtime E2EE."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sqlite_abi_trial as trial

HEPTA = "a" * 40

def fixture():
    return (b'[package]\nname = "matrix-sdk-sqlite"\nversion = "0.19.1"\n'
            b'\n[features]\ndefault = ["state-store"]\n'
            b'\n[dependencies]\n' + trial.OLD + b'\nserde = "1"\n')

def cargo_graph(sdk, hepta):
    specs = [
        ("codex-hepta-matrix-sdk", "hepta", "0.0.0", f"{hepta}/codex-rs/hepta-matrix-sdk/Cargo.toml"),
        ("matrix-sdk", "sdk", "0.19.1", f"{sdk}/crates/matrix-sdk/Cargo.toml"),
        ("matrix-sdk-sqlite", "sqlite", "0.19.1", f"{sdk}/crates/matrix-sdk-sqlite/Cargo.toml"),
        ("matrix-sdk-crypto", "crypto", "0.19.1", f"{sdk}/crates/matrix-sdk-crypto/Cargo.toml"),
        ("rusqlite", "rusqlite", "0.39.0", "/tmp/registry/rusqlite/Cargo.toml"),
        ("libsqlite3-sys", "ffi", "0.37.0", "/tmp/registry/libsqlite3-sys/Cargo.toml"),
        ("blake3", "blake", "1.8.7", "/tmp/registry/blake3/Cargo.toml"),
        ("anymap3", "anymap", "0.15.0", "/tmp/registry/anymap3/Cargo.toml"),
    ]
    pkgs = [{"name": n, "id": ident, "version": version, "manifest_path": path}
            for n, ident, version, path in specs]
    next(p for p in pkgs if p["name"] == "libsqlite3-sys")["links"] = "sqlite3"
    for package in pkgs:
        if package["name"] in ("rusqlite", "libsqlite3-sys"):
            package["source"] = "registry+https://github.com/rust-lang/crates.io-index"
            package["checksum"] = "a" * 64
    def deps(*names):
        return [{"pkg": n, "dep_kinds": [{"kind": None, "target": None}]} for n in names]
    nodes = [
        {"id": "hepta", "features": [], "deps": deps("sdk")},
        {"id": "sdk", "features": ["e2e-encryption", "sqlite"],
         "deps": deps("sqlite", "crypto", "anymap")},
        {"id": "sqlite", "features": [], "deps": deps("rusqlite")},
        {"id": "crypto", "features": [], "deps": deps("blake")},
        {"id": "rusqlite", "features": [], "deps": deps("ffi")},
        {"id": "ffi", "features": [], "deps": []},
        {"id": "blake", "features": [], "deps": []},
        {"id": "anymap", "features": [], "deps": []},
    ]
    return {"packages": pkgs, "workspace_members": ["hepta"],
            "resolve": {"nodes": nodes}}

class SqliteAbiTrialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sdk = self.root / "upstream"
        self.hepta = self.root / "hepta"
        (self.sdk / "crates/matrix-sdk-sqlite").mkdir(parents=True)
        (self.sdk / "crates/matrix-sdk").mkdir()
        (self.hepta / "codex-rs/hepta-matrix-sdk").mkdir(parents=True)
        self.manifest = self.sdk / trial.MANIFEST
        self.source = fixture()
        self.manifest.write_bytes(self.source)
        pinned = patch.object(trial, "MANIFEST_BLOB", trial.git_blob(self.source))
        pinned.start()
        self.addCleanup(pinned.stop)
        self.report = {
            "schema": trial.SOURCE_SCHEMA, "hepta_source_sha": HEPTA,
            "signed_upstream_release_sha": trial.RELEASE,
            "upstream_anymap_change_sha": trial.MIGRATION,
            "hepta_candidate_manifest_sha256": "d" * 64,
            "minimal_upstream_patch_sha256": "c" * 64,
            "sdk_source_root": str(self.sdk),
            "cargo_resolution_verified": False,
            "production_authorized": False,
        }
        self.narrowed = {
            "schema": trial.WORKSPACE_SCHEMA, "source_sha": HEPTA,
            "previous_stage_manifest_sha256": "d" * 64,
            "only_direct_workspace_member": "hepta-matrix-sdk",
            "cargo_resolution_verified": False, "production_authorized": False,
        }

    def stage(self):
        return trial.stage(self.sdk, self.hepta, self.report, self.narrowed, HEPTA)

    def test_only_one_pinned_release_delta(self):
        changed = trial.candidate_bytes(self.source)
        self.assertEqual(changed.count(trial.NEW), 1)
        self.assertEqual(changed.replace(trial.NEW, trial.OLD), self.source)
        self.assertEqual(changed.count(b'serde = "1"'), 1)

    def test_mismatched_upstream_blob_or_version_rejected(self):
        for blob in [self.source + b'\n# drift', self.source.replace(b'"cache"', b'"other"'),
                     self.source.replace(b'"0.40.2"', b'"0.40.1"'),
                     self.source.replace(b'"0.19.1"', b'"0.19.0"'), self.source * 200]:
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                trial.candidate_bytes(blob)

    def test_staging_never_claims_source_review_or_production_authority(self):
        receipt = self.stage()
        self.assertEqual(receipt["trial_manifest_sha256"], trial.sha256(self.manifest.read_bytes()))
        for field in ("production_authorized", "cargo_resolution_verified",
                      "cargo_deny_verified", "reviewer_approved", "compile_verified"):
            self.assertFalse(receipt[field])
        with self.assertRaises(ValueError):
            self.stage()

    def test_signing_or_scope_waivers_never_pass_staging(self):
        for key, bad in [("hepta_source_sha", "b"*40),
                         ("signed_upstream_release_sha", "b"*40),
                         ("upstream_anymap_change_sha", "b"*40),
                         ("production_authorized", True),
                         ("cargo_resolution_verified", True)]:
            replacement = {**self.report, key: bad}
            with self.subTest(key=key), self.assertRaises(ValueError):
                trial.stage(self.sdk, self.hepta, replacement, self.narrowed, HEPTA)
            self.assertEqual(self.manifest.read_bytes(), self.source)
        for key, bad in [("source_sha", "b"*40),
                         ("only_direct_workspace_member", "cli"),
                         ("previous_stage_manifest_sha256", "f"*64),
                         ("production_authorized", True)]:
            replacement = {**self.narrowed, key: bad}
            with self.subTest(key=key), self.assertRaises(ValueError):
                trial.stage(self.sdk, self.hepta, self.report, replacement, HEPTA)
            self.assertEqual(self.manifest.read_bytes(), self.source)

    def test_linked_runtime_sqlite_crypto_and_anymap_audit(self):
        receipt = self.stage()
        audit = trial.audit_metadata(cargo_graph(self.sdk, self.hepta),
                                     receipt, self.sdk, self.hepta)
        self.assertTrue(audit["actual_cargo_metadata_checked"])
        self.assertFalse(audit["production_authorized"])
        self.assertFalse(audit["compile_verified"])

    def test_conflicting_versions_and_fake_links_rejected(self):
        receipt = self.stage()
        for name, key, bad in [
            ("rusqlite", "version", "0.40.2"),
            ("libsqlite3-sys", "version", "0.38.2"),
            ("libsqlite3-sys", "links", "fake"),
            ("matrix-sdk-crypto", "version", "0.18.0"),
            ("blake3", "version", "1.8.2"),
        ]:
            sample = cargo_graph(self.sdk, self.hepta)
            next(p for p in sample["packages"] if p["name"] == name)[key] = bad
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                trial.audit_metadata(sample, receipt, self.sdk, self.hepta)

    def test_foreign_sqlite_or_crypto_sources_rejected(self):
        receipt = self.stage()
        for pkgname, field, value in [
            ("rusqlite", "source", "path+file:///tmp/impersonator"),
            ("rusqlite", "checksum", "not-a-checksum"),
            ("libsqlite3-sys", "checksum", "a" * 63),
            ("matrix-sdk-crypto", "manifest_path", "/tmp/fake/crypto/Cargo.toml"),
        ]:
            sample = cargo_graph(self.sdk, self.hepta)
            next(p for p in sample["packages"] if p["name"] == pkgname)[field] = value
            with self.subTest(pkg=pkgname, field=field), self.assertRaises(ValueError):
                trial.audit_metadata(sample, receipt, self.sdk, self.hepta)

    def test_dev_only_edges_or_disabled_e2ee_never_pass(self):
        receipt = self.stage()
        for src, dst in [("sdk","sqlite"), ("sqlite","rusqlite"),
                         ("rusqlite","ffi"), ("sdk","crypto")]:
            sample = cargo_graph(self.sdk,self.hepta)
            item = next(n for n in sample["resolve"]["nodes"] if n["id"] == src)
            edge = next(d for d in item["deps"] if d["pkg"] == dst)
            edge["dep_kinds"] = [{"kind": "dev", "target": None}]
            with self.subTest(edge=(src,dst)), self.assertRaises(ValueError):
                trial.audit_metadata(sample, receipt, self.sdk, self.hepta)
        sample = cargo_graph(self.sdk,self.hepta)
        next(n for n in sample["resolve"]["nodes"] if n["id"]=="sdk")["features"]=["sqlite"]
        with self.assertRaises(ValueError):
            trial.audit_metadata(sample, receipt, self.sdk, self.hepta)

    def test_duplicate_source_decoy_and_tampering_rejected(self):
        receipt = self.stage()
        sample = cargo_graph(self.sdk,self.hepta)
        sample["packages"].append(copy.deepcopy(sample["packages"][-1]))
        with self.assertRaises(ValueError):
            trial.audit_metadata(sample, receipt, self.sdk, self.hepta)
        sample = cargo_graph(self.sdk,self.hepta)
        next(p for p in sample["packages"] if p["name"] == "anymap3")["name"] = "anymap2"
        with self.assertRaises(ValueError):
            trial.audit_metadata(sample, receipt, self.sdk, self.hepta)
        self.manifest.write_bytes(self.manifest.read_bytes() + b'\n# unreviewed')
        with self.assertRaises(ValueError):
            trial.audit_metadata(cargo_graph(self.sdk,self.hepta), receipt,self.sdk,self.hepta)

if __name__ == "__main__":
    unittest.main()
