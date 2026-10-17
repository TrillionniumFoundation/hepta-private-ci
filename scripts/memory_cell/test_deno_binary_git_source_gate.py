"""Offline source/tree/binary forgery regressions: no network or model calls."""

import base64
import hashlib
import unittest
from unittest.mock import patch

from deno_binary_git_source_gate import (
    BLOB,
    CUTOFF,
    COMMIT,
    PATH,
    ROOT_TREE,
    capture,
    git_blob_sha,
    recover_blob,
    strict_json,
    tree_entry,
)


class OriginalBinaryGitObjectTests(unittest.TestCase):
    def setUp(self):
        self.original = b"const cafe = 'caf\xe9';\n"
        self.sha = git_blob_sha(self.original)
        self.response = dict(
            sha=self.sha,
            encoding="base64",
            size=len(self.original),
            content=base64.b64encode(self.original).decode(),
        )

    def test_canonical_real_binary_blobs_can_be_recomputed(self):
        self.assertEqual(recover_blob(self.response, self.sha), self.original)
        self.assertNotEqual(
            hashlib.sha1(self.original.decode("latin-1").encode()).hexdigest(),
            self.sha,
        )

    def test_historical_sha_substitution_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            recover_blob(self.response, "0" * 40)

    def test_mismatched_bytes_rejected(self):
        changed = dict(self.response, content=base64.b64encode(b"bad").decode())
        with self.assertRaisesRegex(ValueError, "canonical original Git SHA"):
            recover_blob(changed, self.sha)

    def test_invalid_binary_transport_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid original base64"):
            recover_blob(dict(self.response, content="\ud800"), self.sha)

    def test_utf8_recode_cannot_replace_nonutf8_original(self):
        text = "café".encode("utf-8")
        good_sha = git_blob_sha(text)
        response = dict(
            sha=good_sha,
            encoding="base64",
            size=len(text),
            content=base64.b64encode(text).decode(),
        )
        with self.assertRaisesRegex(ValueError, "unexpectedly became UTF-8"):
            recover_blob(response, good_sha)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate API JSON"):
            strict_json(b'{"sha":"x","sha":"x"}')

    def test_original_nested_tree_path_is_type_and_sha_bound(self):
        tree = {
            "sha": ROOT_TREE,
            "tree": [
                {
                    "path": "tests",
                    "type": "tree",
                    "sha": COMMIT,
                }
            ],
        }
        self.assertEqual(tree_entry(tree, ROOT_TREE, "tests", "tree"), COMMIT)
        with self.assertRaisesRegex(ValueError, "path/type binding missing"):
            tree_entry(tree, ROOT_TREE, "tests", "blob")
        with self.assertRaisesRegex(ValueError, "tree or nontruncated"):
            tree_entry(dict(tree, truncated=True), ROOT_TREE, "tests", "tree")

    def test_original_task_requires_provenance_bindings(self):
        filename = PATH.split("/")[-1]
        paths = PATH.split("/")[:-1]
        chain = [ROOT_TREE, *[str(i).zfill(40) for i in range(len(paths))]]
        data = {}
        data[f"/repos/denoland/deno/git/commits/{COMMIT}"] = dict(
            sha=COMMIT, tree=dict(sha=ROOT_TREE), committer=dict(date=CUTOFF)
        )
        for i, name in enumerate(paths):
            data[f"/repos/denoland/deno/git/trees/{chain[i]}"] = dict(
                sha=chain[i], tree=[dict(path=name, type="tree", sha=chain[i + 1])]
            )
        data[f"/repos/denoland/deno/git/trees/{chain[-1]}"] = dict(
            sha=chain[-1], tree=[dict(path=filename, type="blob", sha=BLOB)]
        )
        # Real source manifests must always be independently SHA verified.
        fake_manifest = {"source_cut_utc": CUTOFF}
        with patch(
            "deno_binary_git_source_gate.validate_manifest",
            return_value=fake_manifest,
        ):
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                capture(lambda path: data.get(path, self.response), "test.json")


if __name__ == "__main__":
    unittest.main()
