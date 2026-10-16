"""Forged byte receipts cannot turn historical source cuts into acceptance."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from ten_project_source_closure import (
    BASE_REPOS, EXTENSION_REPOS, BINARY_REPO, BINARY_COMMIT, BINARY_PATH,
    BINARY_SHA, BINARY_MANIFEST, RECEIPT_SCHEMA, SOURCE_CUT_A, SOURCE_CUT_B,
    reconcile, load_json,
)


def fixtures():
    base_repos = sorted(BASE_REPOS)
    ext_repos = sorted(EXTENSION_REPOS)
    a = [dict(repo=base_repos[i % 4],head_sha="a" * 40,
              path=f"path/{i}.py",git_blob_sha1="b" * 40,
              byte_length=1,sha1_recomputed=True,path_bound_to_head_commit=True)
         for i in range(80)]
    a[0]["byte_length"] += 6503104 - 80
    b = [dict(repo=ext_repos[i % 6], commit="c" * 40,
              path=f"src/{i}.rs",git_blob_sha1="d" * 40,utf8_bytes=1)
         for i in range(31)]
    b[0]["utf8_bytes"] += 1558437 - 31
    base = dict(verified_git_blob_bytes=80, original_file_references=80,
                total_verified_raw_source_bytes=6503104,
                source_manifest=dict(source_cut_utc=SOURCE_CUT_A),
                records=a, disposition=dict(production_accepted=False))
    extension = dict(source_cut_utc=SOURCE_CUT_B, expected_original_file_bindings=32,
                     independently_rehashed_utf8_source_files=31,
                     direct_rehashed_original_utf8_bytes=1558437,
                     pending_non_utf8_original_byte_files=1,
                     source_records=b, pending_original_raw_blobs=[dict(
                         repo=BINARY_REPO, commit=BINARY_COMMIT, path=BINARY_PATH,
                         expected_git_blob_sha1=BINARY_SHA,
                         requires_binary_blob_retrieval=True,
                     )])
    binary = dict(schema=RECEIPT_SCHEMA, original_repository=BINARY_REPO,
                  pinned_head_commit=BINARY_COMMIT, original_path=BINARY_PATH,
                  original_blob_sha1=BINARY_SHA,
                  original_task_manifest_sha256=BINARY_MANIFEST,
                  source_cut_utc=SOURCE_CUT_B, verified_binary_bytes=23,
                  head_tree_path_binding_verified=True,
                  canonical_original_git_blob_hash_recomputed=True,
                  utf8_recode_forbidden=True,
                  source_bytes_reuploaded=False,
                  task_answers_or_gold_labels_produced=False,
                  human_source_sufficiency_certified=False,
                  source_families_independent_review_certified=False,
                  parameter_memory_gain_established=False,
                  production_accepted=False, model_inference_calls=0)
    return base, extension, binary


class TenProjectClosure(unittest.TestCase):
    def test_exact_expected_result_never_promotes(self):
        out = reconcile(*fixtures())
        self.assertEqual(out["exact_original_file_bindings"], 112)
        self.assertEqual(out["total_verified_original_blob_bytes"], 8061564)
        self.assertEqual(len(out["ten_distinct_named_repositories"]), 10)
        self.assertFalse(out["production_accepted"])
        self.assertFalse(out["human_labels_available"])

    def test_missing_binary_proof_is_not_success(self):
        a,b,c = fixtures()
        c["canonical_original_git_blob_hash_recomputed"] = False
        with self.assertRaisesRegex(ValueError,"not actually performed"):
            reconcile(a,b,c)

    def test_forged_binary_byte_count_is_rejected(self):
        a,b,c = fixtures()
        c["verified_binary_bytes"] = 22
        with self.assertRaisesRegex(ValueError,"original source identity"):
            reconcile(a,b,c)

    def test_replacement_binary_blob_is_rejected(self):
        a,b,c = fixtures()
        c["original_blob_sha1"] = "0"*40
        with self.assertRaisesRegex(ValueError,"original source identity"):
            reconcile(a,b,c)

    def test_second_cut_no_utf8_proof_does_not_count(self):
        a,b,c = fixtures()
        b["source_records"] = b["source_records"][:-1]
        with self.assertRaisesRegex(ValueError,"31 records"):
            reconcile(a,b,c)

    def test_base_recomputed_flags_cannot_be_omitted(self):
        a,b,c = fixtures()
        a["records"][3]["sha1_recomputed"] = False
        with self.assertRaisesRegex(ValueError,"missing independent"):
            reconcile(a,b,c)

    def test_duplicate_source_binding_rejected(self):
        a,b,c = fixtures()
        a["records"][1] = copy.deepcopy(a["records"][0])
        with self.assertRaisesRegex(ValueError,"duplicate source"):
            reconcile(a,b,c)

    def test_unreviewed_code_never_promotes(self):
        a,b,c = fixtures()
        c["human_source_sufficiency_certified"] = True
        with self.assertRaisesRegex(ValueError,"promoted as task result"):
            reconcile(a,b,c)

    def test_source_cut_cannot_be_combined_as_single_study(self):
        a,b,c = fixtures()
        b["source_cut_utc"] = SOURCE_CUT_A
        with self.assertRaisesRegex(ValueError,"cutoff drift"):
            reconcile(a,b,c)

    def test_unpinned_manifest_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.json"
            path.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,"original tracked Git JSON source drift"):
                load_json(path,git_blob_sha="0"*40)
            with self.assertRaisesRegex(ValueError,"duplicate"):
                load_json(path)

    def test_path_traversal_rejected(self):
        a,b,c = fixtures()
        b["source_records"][0]["path"] = "../sneaky"
        with self.assertRaisesRegex(ValueError,"unsafe source path"):
            reconcile(a,b,c)


if __name__ == "__main__":
    unittest.main()
