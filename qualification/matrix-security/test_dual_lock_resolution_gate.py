"""Synthetic adversarial tests; these are not Matrix runtime/E2EE evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from dual_lock_resolution_gate import EXPECTED_REVISION
from dual_lock_resolution_gate import inspect
from dual_lock_resolution_gate import main

REG = "registry+https://github.com/rust-lang/crates.io-index"
UPSTREAM = (
    "git+https://github.com/matrix-org/matrix-rust-sdk?rev="
    + EXPECTED_REVISION + "#" + EXPECTED_REVISION
)
GOOD_SOURCE = "a" * 40


def pack(name, version, *, source=REG, checksum="a" * 64):
    item = {"name": name, "version": version, "source": source}
    if checksum is not None:
        item["checksum"] = checksum
    return item


def lock(records):
    lines = ["# test-only Cargo.lock fixture", "version = 4", ""]
    for item in records:
        lines.append("[[package]]")
        for key in ("name", "version", "source", "checksum"):
            if key in item:
                lines.append(key + " = " + json.dumps(item[key]))
        lines.append("")
    return "\n".join(lines).encode()


def base():
    return [
        pack("async-trait", "0.1.89"),
        pack("bytes", "1.11.1"),
        pack("anymap2", "0.13.0"),
        pack("matrix-sdk", "0.18.0"),
        pack("matrix-sdk-crypto", "0.18.0"),
    ]


def fixed():
    return [
        pack("async-trait", "0.1.92", checksum="b" * 64),
        pack("bytes", "1.12.1", checksum="c" * 64),
        pack("anymap3", "0.15.0", checksum="d" * 64),
        pack("matrix-sdk", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-base", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-crypto", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-sqlite", "0.19.1", source=UPSTREAM, checksum=None),
    ]


def metadata(records):
    return {"packages": [dict(p) for p in records]}


class DualResolutionTests(unittest.TestCase):
    def inspect(self, new=None, observed=None, old=None, **kwargs):
        new = fixed() if new is None else new
        observed = metadata(new) if observed is None else observed
        old = base() if old is None else old
        sha = kwargs.pop("source_sha", GOOD_SOURCE)
        return inspect(lock(old), lock(new), observed, source_sha=sha, **kwargs)

    def test_valid_candidate_is_explicitly_non_authoritative(self):
        result = self.inspect()
        self.assertTrue(result["cargo_lock_metadata_consistent"])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["cargo_deny_verified"])
        self.assertFalse(result["matrix_e2ee_verified"])
        self.assertFalse(result["sqlite_wal_recovery_verified"])
        self.assertFalse(result["isolated_worktree_attested"])
        self.assertIsNone(result["original_checkout_modified"])
        self.assertEqual(
            result["upgraded_locks"]["async-trait"],
            {"old": "0.1.89", "resolved": "0.1.92"},
        )
        self.assertEqual(result["original_lock_sha256"], hashlib.sha256(lock(base())).hexdigest())

    def test_missing_anymap3_refused(self):
        with self.assertRaisesRegex(ValueError, "anymap3"):
            self.inspect(new=[p for p in fixed() if p["name"] != "anymap3"])

    def test_anymap2_survival_refused(self):
        with self.assertRaisesRegex(ValueError, "anymap2"):
            self.inspect(new=fixed() + [pack("anymap2", "0.13.0")])

    def test_mixed_matrix_family_refused(self):
        for name in ("matrix-sdk-crypto", "matrix-sdk-base", "matrix-sdk-sqlite"):
            items = fixed()
            next(p for p in items if p["name"] == name)["version"] = "0.18.0"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe family"):
                self.inspect(new=items)

    def test_nonpinned_git_source_refused(self):
        items = fixed()
        invalid_sha = "f" * 40
        next(p for p in items if p["name"] == "matrix-sdk")["source"] = (
            "git+https://github.com/matrix-org/matrix-rust-sdk?rev="
            + invalid_sha + "#" + invalid_sha
        )
        with self.assertRaisesRegex(ValueError, "exact reviewed Git"):
            self.inspect(new=items)

    def test_both_stale_transitive_versions_refused(self):
        for name, version in (("async-trait", "0.1.89"), ("bytes", "1.11.1")):
            items = fixed()
            next(p for p in items if p["name"] == name)["version"] = version
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unresolved"):
                self.inspect(new=items)

    def test_newer_semver_compatible_transitives_allowed(self):
        items = fixed()
        next(p for p in items if p["name"] == "async-trait")["version"] = "0.1.93"
        next(p for p in items if p["name"] == "bytes")["version"] = "1.13.0"
        self.assertTrue(self.inspect(new=items)["cargo_lock_metadata_consistent"])

    def test_incompatible_transitive_major_versions_refused(self):
        for name, version in (("async-trait", "0.2.0"), ("bytes", "2.0.0")):
            items = fixed()
            next(p for p in items if p["name"] == name)["version"] = version
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unresolved"):
                self.inspect(new=items)

    def test_nonhex_registry_checksum_refused(self):
        items = fixed()
        next(p for p in items if p["name"] == "bytes")["checksum"] = "?" * 64
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.inspect(new=items)

    def test_metadata_version_drift_refused(self):
        items = fixed()
        observed = metadata(items)
        next(p for p in observed["packages"] if p["name"] == "bytes")["version"] = "1.12.0"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.inspect(new=items, observed=observed)

    def test_metadata_checksum_drift_refused(self):
        items = fixed()
        observed = metadata(items)
        next(p for p in observed["packages"] if p["name"] == "bytes")["checksum"] = "c" * 63 + "d"
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.inspect(new=items, observed=observed)

    def test_duplicate_lock_and_metadata_packages_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate Cargo package"):
            self.inspect(new=fixed() + [fixed()[0]])
        items = fixed()
        with self.assertRaisesRegex(ValueError, "duplicate Cargo metadata"):
            self.inspect(new=items, observed=metadata(items + [items[0]]))

    def test_unpinned_hepta_source_and_upstream_revision_refused(self):
        with self.assertRaisesRegex(ValueError, "source SHA"):
            self.inspect(source_sha="f" * 39 + "X")
        with self.assertRaisesRegex(ValueError, "unexpected upstream"):
            self.inspect(pinned_upstream="f" * 40)

    def test_invalid_lock_schema_and_registry_source_refused(self):
        with self.assertRaisesRegex(ValueError, "schema"):
            inspect(b"version = 3\n", lock(fixed()), metadata(fixed()), source_sha=GOOD_SOURCE)
        items = fixed()
        next(p for p in items if p["name"] == "bytes")["source"] = "registry+https://invalid.example"
        with self.assertRaisesRegex(ValueError, "untrusted bytes"):
            self.inspect(new=items)

    def test_cli_never_overwrites_evidence_or_source_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            paths = [directory / name for name in (
                "original.lock", "resolved.lock", "cargo-metadata.json", "report.json",
            )]
            paths[0].write_bytes(lock(base()))
            paths[1].write_bytes(lock(fixed()))
            paths[2].write_text(json.dumps(metadata(fixed())), encoding="utf-8")
            args = [
                "--original-lock", str(paths[0]),
                "--resolved-lock", str(paths[1]),
                "--metadata", str(paths[2]),
                "--hepta-sha", GOOD_SOURCE,
                "--output", str(paths[3]),
            ]
            self.assertEqual(main(args), 0)
            self.assertFalse(json.loads(paths[3].read_text())["production_authorized"])
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual(paths[0].read_bytes(), lock(base()))
            self.assertEqual(paths[1].read_bytes(), lock(fixed()))


if __name__ == "__main__":
    unittest.main()
