"""Rebuild each original acquisition directory's Git tree from verified bytes."""

import hashlib
import json
from pathlib import Path
import sys
import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "qa/repository-consolidation/20261115"))

import restore_raw_evidence as storage


def git_object_id(kind, data):
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).digest()


def tree_id(files):
    children = []
    directories = {}
    for path, oid in files.items():
        name, separator, remainder = path.partition("/")
        if separator:
            directories.setdefault(name, {})[remainder] = oid
        else:
            children.append((name.encode(), b"100644", oid))
    for name, members in directories.items():
        children.append((name.encode() + b"/", b"40000", tree_id(members)))
    encoded = b"".join(
        mode + b" " + key.rstrip(b"/") + b"\0" + oid
        for key, mode, oid in sorted(children)
    )
    return git_object_id("tree", encoded)


class EvaluatedReadLogsTests(unittest.TestCase):
    def test_original_directory_trees_and_registered_carriers(self):
        self.verify_directory_trees(storage.EVALUATED_READ_INDEX)

    def test_hosted_qualification_directory_trees(self):
        self.verify_directory_trees(storage.HOSTED_QUALIFICATION_INDEX)

    def verify_directory_trees(self, index_path):
        inventory = storage.entries(REPOSITORY)
        index = json.loads((REPOSITORY / index_path).read_bytes())
        witness = index["original_directories"]
        raw = storage.read_regular(REPOSITORY, witness["path"], 1024 * 1024)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), witness["sha256"])
        source = json.loads(raw)
        self.assertEqual(source["source_commit"], index["source_commit"])
        registered = {row["original_path"] for row in index["files"]}
        recovered = set()
        for directory, expected in source["directories"].items():
            members = {}
            for name in expected["files"]:
                path = f"{directory}/{name}"
                if path in registered:
                    record = inventory[path]
                    self.assertFalse((REPOSITORY / path).exists())
                    self.assertEqual(record["original_source_commit"], source["source_commit"])
                    self.assertEqual(record["original_mode"], "100644")
                    data = storage.read_verified(
                        REPOSITORY, path, record["original_bytes"], record["original_sha256"]
                    )
                    self.assertEqual(git_object_id("blob", data).hex(), record["original_git_blob"])
                    recovered.add(path)
                else:
                    data = storage.read_regular(REPOSITORY, path, storage.MAX_BYTES)
                members[name] = git_object_id("blob", data)
            with self.subTest(directory=directory):
                self.assertEqual(tree_id(members).hex(), expected["tree"])
        self.assertEqual(recovered, registered)
