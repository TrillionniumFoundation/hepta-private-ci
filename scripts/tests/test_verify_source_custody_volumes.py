"""Synthetic boundary tests for registered historical source volumes."""

import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_source_custody_volumes as volumes


class SourceVolumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.group = "library-recovery/fixture-source"
        self.directory = self.repository / self.group
        self.directory.mkdir(parents=True)
        patch = mock.patch.dict(volumes.REGISTRATIONS, {}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.payloads = {
            "README.md": b"Original source-only record.\n",
            "objects/recipe(1).py": b"raise RuntimeError('archived code must never execute')\n",
        }
        self.document = {
            "schema": volumes.SCHEMA,
            "source_commit": volumes.SOURCE_COMMIT,
            "original_directory": self.group,
            "member_count": len(self.payloads),
            "member_bytes": sum(map(len, self.payloads.values())),
            "source_executed": False,
            "scientific_or_runtime_qualification": False,
            "members": [],
            "volumes": [],
        }
        self.tar_bytes = []
        for number, (name, raw) in enumerate(self.payloads.items(), 1):
            volume_name = "source-custody-%03d.tar.gz" % number
            row = {
                "path": self.group + "/" + name,
                "member": name,
                "mode": "100644",
                **volumes.identity(raw),
                "surface": "retained_original"
                if name == "README.md"
                else "container_only",
                "volume": volume_name,
            }
            self.document["members"].append(row)
            tar = self.tar([(name, raw, tarfile.REGTYPE, {})])
            self.tar_bytes.append(tar)
            compressed = gzip.compress(tar, mtime=0)
            (self.directory / volume_name).write_bytes(compressed)
            self.document["volumes"].append(
                {
                    "path": volume_name,
                    "bytes": len(compressed),
                    "sha256": hashlib.sha256(compressed).hexdigest(),
                    "tar_bytes": len(tar),
                    "tar_sha256": hashlib.sha256(tar).hexdigest(),
                    "member_count": 1,
                    "member_bytes": len(raw),
                }
            )
        (self.directory / "README.md").write_bytes(self.payloads["README.md"])
        self.publish()

    @staticmethod
    def tar(entries, pax=False):
        stream = io.BytesIO()
        with tarfile.open(
            fileobj=stream,
            mode="w",
            format=tarfile.PAX_FORMAT if pax else tarfile.USTAR_FORMAT,
        ) as archive:
            for name, raw, kind, headers in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.mode = 0o644
                item.size = len(raw) if kind == tarfile.REGTYPE else 0
                item.uid = item.gid = item.mtime = 0
                item.uname = item.gname = ""
                item.pax_headers = headers
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    item.linkname = "README.md"
                archive.addfile(
                    item, io.BytesIO(raw) if kind == tarfile.REGTYPE else None
                )
        return stream.getvalue()

    def publish(self, rebind=True, raw=None):
        if raw is None:
            raw = (json.dumps(self.document, indent=2) + "\n").encode()
        (self.directory / "SOURCE_VOLUMES.json").write_bytes(raw)
        if rebind:
            volumes.REGISTRATIONS[self.group] = hashlib.sha256(raw).hexdigest()

    def replace_volume(self, index, tar=None, compressed=None):
        row = self.document["volumes"][index]
        if tar is not None:
            row["tar_bytes"] = len(tar)
            row["tar_sha256"] = hashlib.sha256(tar).hexdigest()
        if compressed is None:
            compressed = gzip.compress(tar, mtime=0)
        row["bytes"] = len(compressed)
        row["sha256"] = hashlib.sha256(compressed).hexdigest()
        (self.directory / row["path"]).write_bytes(compressed)
        self.publish()

    def verify(self):
        return volumes.verify_collection(self.repository, self.group)

    def test_two_volumes_preserve_exact_bytes_without_materializing_or_executing(self):
        before = {
            str(path.relative_to(self.repository)): path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }
        result = self.verify()
        self.assertEqual(
            result,
            {self.group + "/" + name: raw for name, raw in self.payloads.items()},
        )
        self.assertEqual(
            before,
            {
                str(path.relative_to(self.repository)): path.read_bytes()
                for path in self.repository.rglob("*")
                if path.is_file()
            },
        )
        self.assertFalse((self.directory / "objects").exists())

    def test_manifest_must_match_registered_hash(self):
        self.document["member_bytes"] += 1
        self.publish(rebind=False)
        with self.assertRaisesRegex(ValueError, "registered original roster changed"):
            self.verify()

    def test_duplicate_json_and_changed_original_commit_fail(self):
        original = copy.deepcopy(self.document)
        raw = json.dumps(self.document).encode().replace(b"{", b'{"schema":"other",', 1)
        self.publish(raw=raw)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.verify()
        self.document = original
        self.document["source_commit"] = "0" * 40
        self.publish()
        with self.assertRaisesRegex(ValueError, "original source identity changed"):
            self.verify()

    def test_unregistered_collection_is_rejected_before_input_read(self):
        with mock.patch.object(volumes, "read_regular") as reader:
            with self.assertRaisesRegex(ValueError, "unregistered"):
                volumes.verify_collection(
                    self.repository, "library-recovery/unregistered"
                )
            reader.assert_not_called()

    def test_finite_manifest_bounds_reject_before_archive_read(self):
        original = copy.deepcopy(self.document)
        cases = [
            ("member_count", volumes.MAX_COLLECTION_MEMBERS + 1),
            ("member_bytes", volumes.MAX_COLLECTION_BYTES + 1),
            ("member_count", True),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.document = copy.deepcopy(original)
                self.document[key] = value
                self.publish()
                with self.assertRaises(ValueError):
                    self.verify()
        for key, value in [
            ("bytes", volumes.MAX_ARCHIVE + 1),
            ("tar_bytes", volumes.MAX_TAR + 1),
            ("member_count", volumes.MAX_VOLUME_MEMBERS + 1),
            ("member_bytes", volumes.MAX_MEMBER_BYTES + 1),
        ]:
            with self.subTest(volume_key=key):
                self.document = copy.deepcopy(original)
                self.document["volumes"][0][key] = value
                self.publish()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_original_path_and_duplicate_volume_members_reject(self):
        original = copy.deepcopy(self.document)
        for name in ("../escape.py", "/absolute.py", "a//b.py", "a/./b.py", "a\\b.py"):
            with self.subTest(name=name):
                self.document = copy.deepcopy(original)
                self.document["members"][1]["member"] = name
                self.document["members"][1]["path"] = self.group + "/" + name
                self.publish()
                with self.assertRaisesRegex(ValueError, "unsafe or noncanonical"):
                    self.verify()
        self.document = copy.deepcopy(original)
        self.document["members"][1]["member"] = "README.md"
        self.document["members"][1]["path"] = self.group + "/README.md"
        self.publish()
        with self.assertRaisesRegex(ValueError, "duplicate or inconsistent"):
            self.verify()

    def test_tar_links_pax_duplicate_and_unexpected_members_reject(self):
        name = "objects/recipe(1).py"
        raw = self.payloads[name]
        cases = [
            ([(name, raw, tarfile.SYMTYPE, {})], False),
            ([(name, raw, tarfile.LNKTYPE, {})], False),
            (
                [(name, raw, tarfile.REGTYPE, {"comment": "unregistered metadata"})],
                True,
            ),
            (
                [(name, raw, tarfile.REGTYPE, {}), (name, raw, tarfile.REGTYPE, {})],
                False,
            ),
            ([("../escape.py", raw, tarfile.REGTYPE, {})], False),
            ([("unexpected.py", raw, tarfile.REGTYPE, {})], False),
            ([], False),
        ]
        for entries, pax in cases:
            with self.subTest(
                entries=[row[0:1] + row[2:3] for row in entries], pax=pax
            ):
                self.replace_volume(1, tar=self.tar(entries, pax=pax))
                with self.assertRaises((ValueError, tarfile.TarError)):
                    self.verify()

    def test_gnu_header_is_not_accepted_as_ustar(self):
        name = "objects/recipe(1).py"
        raw = self.payloads[name]
        stream = io.BytesIO()
        with tarfile.open(
            fileobj=stream, mode="w", format=tarfile.GNU_FORMAT
        ) as archive:
            item = tarfile.TarInfo(name)
            item.type = tarfile.REGTYPE
            item.mode = 0o644
            item.size = len(raw)
            item.uid = item.gid = item.mtime = 0
            item.uname = item.gname = ""
            archive.addfile(item, io.BytesIO(raw))
        self.replace_volume(1, tar=stream.getvalue())
        with self.assertRaisesRegex(ValueError, "USTAR"):
            self.verify()

    def test_payload_and_tar_mode_cannot_be_rebound_by_outer_hash(self):
        name = "objects/recipe(1).py"
        wrong = b"x" * len(self.payloads[name])
        self.replace_volume(1, tar=self.tar([(name, wrong, tarfile.REGTYPE, {})]))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.verify()
        tar = bytearray(self.tar_bytes[1])
        # Build a valid header with a different mode so this reaches the mode guard.
        item = tarfile.TarInfo(name)
        item.type = tarfile.REGTYPE
        item.mode = 0o755
        item.size = len(self.payloads[name])
        item.uid = item.gid = item.mtime = 0
        tar[:512] = item.tobuf(format=tarfile.USTAR_FORMAT)
        self.replace_volume(1, tar=bytes(tar))
        with self.assertRaisesRegex(ValueError, "mode or size"):
            self.verify()

    def test_gzip_truncation_concatenation_and_expansion_bound_reject(self):
        compressed = gzip.compress(self.tar_bytes[1], mtime=0)
        for raw in (compressed[:-1], compressed + compressed):
            with self.subTest(length=len(raw)):
                self.replace_volume(1, compressed=raw)
                with self.assertRaisesRegex(
                    ValueError, "truncated, oversized or concatenated"
                ):
                    self.verify()
        self.replace_volume(1, tar=self.tar_bytes[1])
        self.document["volumes"][1]["tar_bytes"] = 512
        self.publish()
        with self.assertRaisesRegex(ValueError, "truncated, oversized or concatenated"):
            self.verify()

    def test_nonzero_tar_trailer_rejects_even_with_rebound_transport_hashes(self):
        raw = bytearray(self.tar_bytes[1])
        raw[-1] = 1
        self.replace_volume(1, tar=bytes(raw))
        with self.assertRaisesRegex(ValueError, "noncanonical tar trailer"):
            self.verify()

    def test_visible_original_control_cannot_drift_or_be_a_link(self):
        control = self.directory / "README.md"
        control.write_bytes(b"altered\n")
        with self.assertRaisesRegex(ValueError, "visible original control"):
            self.verify()
        control.unlink()
        target = self.directory / "other.txt"
        target.write_bytes(self.payloads["README.md"])
        control.symlink_to(target.name)
        with self.assertRaises((ValueError, OSError)):
            self.verify()
        control.unlink()
        os.link(target, control)
        with self.assertRaisesRegex(ValueError, "single-link"):
            self.verify()

    def test_original_path_resolution_preserves_duplicate_name_and_rejects_missing(
        self,
    ):
        path = self.group + "/objects/recipe(1).py"
        self.assertEqual(
            volumes.resolve_original_paths(self.repository, [path]),
            {path: self.payloads["objects/recipe(1).py"]},
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            volumes.resolve_original_paths(self.repository, [path, path])
        with self.assertRaisesRegex(ValueError, "missing original"):
            volumes.resolve_original_paths(
                self.repository, [self.group + "/missing.py"]
            )

    def test_optimized_interpreter_refuses_verification(self):
        source = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); "
            "import verify_source_custody_volumes as v; "
            "v.REGISTRATIONS.clear(); v.REGISTRATIONS[sys.argv[3]]=sys.argv[4]; "
            "v.verify_collection(Path(sys.argv[2]), sys.argv[3])"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-O",
                "-c",
                source,
                str(Path(volumes.__file__).parent),
                str(self.repository),
                self.group,
                volumes.REGISTRATIONS[self.group],
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("optimized verification refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
