"""Lightweight stdlib negative gates, entirely without pretrained models."""
import copy
import hashlib
import io
import json
import stat
import unittest
import zipfile
from e2_crossmodal_archive_audit import (
    AuditError, PREFIX, audit, canonical, cos, is_sha, jsonl, obj, sha,
    unzip, vector,
)


def package(entries):
    fp=io.BytesIO()
    with zipfile.ZipFile(fp,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for k,v in entries:
            z.writestr(k,v)
    return fp.getvalue()

class ArchiveAuditTests(unittest.TestCase):
    def test_valid_simple_archive_bytes(self):
        b=package([("readout.json",canonical({"ok":True}))])
        self.assertEqual(unzip(b,sha(b))["readout.json"],canonical({"ok":True}))

    def test_wrong_pin_rejected(self):
        b=package([("x",b"123")])
        with self.assertRaises(AuditError):unzip(b,sha(b"forged"))

    def test_duplicate_zip_member_rejected(self):
        b=package([("x",b"1"),("x",b"2")])
        with self.assertRaises(AuditError):unzip(b,sha(b))

    def test_parent_directory_and_absolute_paths_rejected(self):
        for name in ("../secret.json","/abs","a/../b","a\\b","a//b"):
            b=package([(name,b"1")])
            with self.assertRaises(AuditError):unzip(b,sha(b))

    def test_zip_symbolic_link_rejected(self):
        entry=zipfile.ZipInfo("link")
        entry.create_system=3
        entry.external_attr=(stat.S_IFLNK|0o777)<<16
        b=package([(entry,b"target")])
        with self.assertRaises(AuditError):unzip(b,sha(b))

    def test_json_duplicate_fields_rejected(self):
        with self.assertRaises(AuditError):obj(b'{"a":1,"a":2}\n')

    def test_noncanonical_document_rejected(self):
        with self.assertRaises(AuditError):obj(b'{"b":2, "a":1}\n')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(AuditError):obj(b'{"a":NaN}\n')

    def test_jsonl_cardinality_rejected(self):
        with self.assertRaises(AuditError):jsonl(canonical({"k":0}),count=8)

    def test_vector_width_dtype_bounds(self):
        self.assertEqual(len(vector([0.1]*384)),384)
        for row in ([0.1]*383,[False]*384,[float('nan')]*384,[9.0]*384):
            with self.assertRaises(AuditError):vector(row)

    def test_cosine_rejects_zero_vector(self):
        with self.assertRaises(AuditError):cos([0.0]*384,[1.0]*384)
        self.assertAlmostEqual(cos([1.0]*384,[1.0]*384),1)

    def test_exact_four_pins_required(self):
        with self.assertRaises(AuditError):audit(b'',b'',b'',b'',{})

    def test_old_manifest_label_digest_exposure_fails(self):
        leak={"schema":PREFIX+".source-plan","synthetic_data":True,
              "training_cases":16,"future_cases":8,"scope":"s",
              "file_sha256s":{"future_class_targets.jsonl":sha(b"guess")},
              "production_accepted":False,"model_selection_permitted":False,
              "authority":"DENY_ALL"}
        bags=[package([("source-manifest.json",canonical(leak))]),
              package([("target-manifest.json",b'{}\n')]),
              package([("producer_receipt.json",b'{}\n')]),
              package([("class_independent_readout.json",b'{}\n')])]
        with self.assertRaisesRegex(AuditError,"SOURCE_MANIFEST_TARGET_HASH_EXPOSED"):
            audit(*bags,dict(zip(("source","target","producer","evaluator"),map(sha,bags))))

if __name__=='__main__':unittest.main()
