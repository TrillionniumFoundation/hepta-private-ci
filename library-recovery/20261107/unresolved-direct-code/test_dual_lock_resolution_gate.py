import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from dual_lock_resolution_gate import EXPECTED_REVISION, inspect, main

REG = "registry+https://github.com/rust-lang/crates.io-index"
UPSTREAM = "git+https://github.com/matrix-org/matrix-rust-sdk?rev=" + EXPECTED_REVISION + "#" + EXPECTED_REVISION
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
        for k in ("name", "version", "source", "checksum"):
            if k in item:
                lines.append(k + " = " + json.dumps(item[k]))
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
        pack("async-trait", "0.1.92", checksum="b"*64),
        pack("bytes", "1.12.1", checksum="c"*64),
        pack("anymap3", "0.15.0", checksum="d"*64),
        pack("matrix-sdk", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-base", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-crypto", "0.19.1", source=UPSTREAM, checksum=None),
        pack("matrix-sdk-sqlite", "0.19.1", source=UPSTREAM, checksum=None),
    ]


def meta(records):
    return {"packages": [dict(p) for p in records]}


class DualResolutionTests(unittest.TestCase):
    def invoke(self, new=None, obs=None, old=None, **kw):
        new = fixed() if new is None else new
        obs = meta(new) if obs is None else obs
        old = base() if old is None else old
        return inspect(lock(old), lock(new), obs, source_sha=kw.pop("source_sha", GOOD_SOURCE), **kw)

    def test_valid_provenance_is_non_authoritative(self):
        receipt = self.invoke()
        self.assertTrue(receipt["cargo_lock_metadata_consistent"])
        self.assertFalse(receipt["production_authorized"])
        self.assertFalse(receipt["cargo_deny_verified"])
        self.assertFalse(receipt["matrix_e2ee_verified"])
        self.assertFalse(receipt["sqlite_wal_recovery_verified"])
        self.assertEqual(receipt["upgraded_locks"]["async-trait"], {"old":"0.1.89", "resolved":"0.1.92"})
        self.assertEqual(receipt["original_lock_sha256"], hashlib.sha256(lock(base())).hexdigest())

    def test_missing_anymap3_refuses(self):
        with self.assertRaisesRegex(ValueError, "anymap3"):
            self.invoke(new=[p for p in fixed() if p["name"] != "anymap3"])

    def test_anymap2_surviving_refuses(self):
        with self.assertRaisesRegex(ValueError, "anymap2"):
            self.invoke(new=fixed()+[pack("anymap2","0.13.0")])

    def test_unsafe_crypto_or_mixed_family_refuses(self):
        for component in ("matrix-sdk-crypto","matrix-sdk-base","matrix-sdk-sqlite"):
            new=fixed()
            next(p for p in new if p["name"]==component)["version"]="0.18.0"
            with self.subTest(component=component), self.assertRaisesRegex(ValueError,"unsafe family"):
                self.invoke(new=new)

    def test_wrong_git_revision_refuses(self):
        new=fixed()
        next(p for p in new if p["name"]=="matrix-sdk")["source"]="git+https://github.com/matrix-org/matrix-rust-sdk?rev="+"a"*40+"#"+"a"*40
        with self.assertRaisesRegex(ValueError,"exact reviewed Git"):
            self.invoke(new=new)

    def test_stale_lock_versions_refuse(self):
        for name in ("async-trait", "bytes"):
            new=fixed()
            next(p for p in new if p["name"]==name)["version"]="0.1.89" if name=="async-trait" else "1.11.1"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,"unresolved"):
                self.invoke(new=new)

    def test_mutated_registry_checksum_refuses(self):
        new=fixed()
        next(p for p in new if p["name"]=="bytes")["checksum"]="?"*64
        with self.assertRaisesRegex(ValueError,"checksum"):
            self.invoke(new=new)

    def test_metadata_mismatch_refuses(self):
        new=fixed()
        obs=meta(new)
        next(p for p in obs["packages"] if p["name"]=="bytes")["version"]="1.12.0"
        with self.assertRaisesRegex(ValueError,"disagrees"):
            self.invoke(new=new,obs=obs)

    def test_metadata_checksum_drift_refuses(self):
        new=fixed()
        obs=meta(new)
        next(p for p in obs["packages"] if p["name"]=="bytes")["checksum"]="c"*63+"d"
        with self.assertRaisesRegex(ValueError,"checksum mismatch"):
            self.invoke(new=new,obs=obs)

    def test_duplicate_package_and_metadata_refuse(self):
        with self.assertRaisesRegex(ValueError,"duplicate Cargo package"):
            self.invoke(new=fixed()+[fixed()[0]])
        orig=fixed()
        with self.assertRaisesRegex(ValueError,"duplicate Cargo metadata"):
            self.invoke(new=orig,obs=meta(orig + [orig[0]]))

    def test_unpinned_or_non_hex_source_refuses(self):
        with self.assertRaisesRegex(ValueError,"source SHA"):
            self.invoke(source_sha="f"*39+"X")
        with self.assertRaisesRegex(ValueError,"unexpected upstream"):
            self.invoke(pinned_upstream="f"*40)

    def test_lock_format_and_source_refuses(self):
        with self.assertRaisesRegex(ValueError,"schema"):
            inspect(b'version = 3\n',lock(fixed()),meta(fixed()),source_sha=GOOD_SOURCE)
        new=fixed()
        next(p for p in new if p["name"]=="bytes")["source"]="registry+https://example.invalid"
        with self.assertRaisesRegex(ValueError,"untrusted bytes"):
            self.invoke(new=new)

    def test_cli_writes_only_new_nonproduction_report(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            paths=[d/n for n in ("original.lock", "resolved.lock", "cargo-metadata.json", "out.json")]
            paths[0].write_bytes(lock(base()))
            paths[1].write_bytes(lock(fixed()))
            paths[2].write_text(json.dumps(meta(fixed())))
            args=["--original-lock",str(paths[0]),"--resolved-lock",str(paths[1]),"--metadata",str(paths[2]),"--hepta-sha",GOOD_SOURCE,"--output",str(paths[3])]
            self.assertEqual(main(args),0)
            self.assertFalse(json.loads(paths[3].read_text())["production_authorized"])
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual(paths[0].read_bytes(),lock(base()))
            self.assertEqual(paths[1].read_bytes(),lock(fixed()))


if __name__ == "__main__":
    unittest.main()
