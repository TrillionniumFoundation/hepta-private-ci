import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import publish_diagnostic_originals as publisher


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.records = [{"path": "member-%03d" % i, "bytes": 1,
                         "sha256": publisher.digest(b"a")} for i in range(118)]
        self.manifest = {"schema": "hcsn-real-recovery-originals-v1",
                         "source_commit": publisher.MODEL_SOURCE, "audit_commit": publisher.AUDIT_SOURCE,
                         "native_training_job": "1a1ce749808-2564-1688", "file_count": 118,
                         "new_independent_complete_training_replays": 0, "scientific_admission": "HOLD_NO_GO",
                         "files": self.records, "uncompressed_bytes": 118}
        self.write_fixture()
        self.addCleanup(patch.stopall)
        patch.object(publisher, "ROOT", self.root).start()
        patch.object(publisher, "STATE", self.root/"state").start()
        patch.object(publisher, "EXPECTED", self.expected).start()

    def write_fixture(self, omit=None, extra=None):
        manifest_raw = (json.dumps(self.manifest, indent=2)+"\n").encode()
        (self.root/"ORIGINALS-MANIFEST.json").write_bytes(manifest_raw)
        with tarfile.open(self.root/"originals.tar.xz", "w:xz") as archive:
            for row in self.records:
                if row["path"] != omit:
                    info = tarfile.TarInfo(row["path"])
                    info.size = 1
                    archive.addfile(info, io.BytesIO(b"a"))
            info = tarfile.TarInfo("ORIGINALS-MANIFEST.json")
            info.size = len(manifest_raw)
            archive.addfile(info, io.BytesIO(manifest_raw))
            if extra:
                info = tarfile.TarInfo(extra)
                archive.addfile(info, io.BytesIO())
        archive_raw = (self.root/"originals.tar.xz").read_bytes()
        receipt = {"schema": "hcsn-real-recovery-archive-receipt-v1",
                   "path": str(self.root/"originals.tar.xz"), "bytes": len(archive_raw),
                   "sha256": publisher.digest(archive_raw), "manifest_sha256": publisher.digest(manifest_raw),
                   "original_files": 118, "new_optimizer_calls": 0,
                   "closed_source_and_outputs_rechecked": True, "uncompressed_bytes": 118}
        (self.root/"ARCHIVE.json").write_text(json.dumps(receipt)+"\n")
        self.expected = {name: (len((self.root/name).read_bytes()), publisher.digest((self.root/name).read_bytes()))
                         for name in ("originals.tar.xz", "ARCHIVE.json", "ORIGINALS-MANIFEST.json")}

    def test_all_original_bytes_and_members(self):
        raw, identities = publisher.checked_inputs()
        self.assertEqual(set(raw), set(self.expected))
        self.assertEqual(raw["ORIGINALS-MANIFEST.json"], (self.root/"ORIGINALS-MANIFEST.json").read_bytes())
        self.assertEqual(len(identities), 3)

    def test_one_byte_archive_mutation(self):
        path = self.root/"originals.tar.xz"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, "frozen input"):
            publisher.checked_inputs()

    def test_raw_manifest_mutation(self):
        path = self.root/"ORIGINALS-MANIFEST.json"
        path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaisesRegex(RuntimeError, "frozen input"):
            publisher.checked_inputs()

    def test_missing_tar_member(self):
        self.write_fixture(omit="member-000")
        with patch.object(publisher, "EXPECTED", self.expected):
            with self.assertRaisesRegex(RuntimeError, "missing original tar"):
                publisher.checked_inputs()

    def test_extra_tar_member(self):
        self.write_fixture(extra="../outside")
        with patch.object(publisher, "EXPECTED", self.expected):
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                publisher.checked_inputs()

    def test_existing_state_does_not_call_api(self):
        publisher.STATE.mkdir()
        with patch.object(publisher, "api") as api:
            with self.assertRaises(FileExistsError):
                publisher.main()
            api.assert_not_called()

    def test_head_drift_has_no_post(self):
        replies = [{"login": "ProfHepta"}, {"full_name": publisher.REPO, "permissions": {"push": True}},
                   {"head": {"sha": "0"*40}}]
        with patch.object(publisher, "api", side_effect=replies) as api:
            with self.assertRaisesRegex(RuntimeError, "base changed"):
                publisher.main()
            self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))

    def test_corrupt_input_has_no_post(self):
        (self.root/"ARCHIVE.json").write_bytes(b"wrong")
        replies = [{"login": "ProfHepta"}, {"full_name": publisher.REPO, "permissions": {"push": True}},
                   {"head": {"sha": publisher.PARENT}}]
        with patch.object(publisher, "api", side_effect=replies) as api:
            with self.assertRaisesRegex(RuntimeError, "frozen input"):
                publisher.main()
            self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))

    def test_wrong_blob_blocks_ref(self):
        replies = [{"login": "ProfHepta"}, {"full_name": publisher.REPO, "permissions": {"push": True}},
                   {"head": {"sha": publisher.PARENT}}, {"sha": "0"*40}]
        with patch.object(publisher, "api", side_effect=replies) as api:
            with self.assertRaisesRegex(RuntimeError, "Git blob"):
                publisher.main()
            self.assertFalse(any(call.args[0].endswith("/git/refs") for call in api.call_args_list))

    def test_git_blob_uses_nul(self):
        self.assertEqual(publisher.git_blob(b"test\n"), "9daeafb9864cf43055ae93beb0afd6c7d144bfa4")


if __name__ == "__main__":
    unittest.main()
