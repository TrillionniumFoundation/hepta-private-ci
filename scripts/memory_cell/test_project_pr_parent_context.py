"""Synthetic immutable Git object history; never reviewer certification."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_pr_parent_context import (
    CATEGORIES, collect_parent, inspect, reopen_parent,
)
from project_pr_source_materialize import (
    ObjectReader, blob_sha, canonical, digest,
)
from project_pr_source_precommit import read_pinned

PIN = "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
SOURCE = (
    Path(__file__).resolve().parent
    / "data/real-project-pr-source-cut-20261012.json"
)


def sha(label):
    return hashlib.sha1(label.encode()).hexdigest()


class SourceFixtures:
    def __init__(self):
        self.manifest = read_pinned(SOURCE, PIN)
        self.objects = {}
        self.originals = []
        self.changed = {}
        for case in self.manifest["cases"]:
            repo, head = case["repo"], case["head_sha"]
            self.objects[repo, "commits", head] = dict(
                sha=head, tree=dict(sha=case["tree_sha"]),
                parents=[dict(sha=p) for p in case["parents"]],
                author=dict(date=case["head_committed_at"]),
                committer=dict(date=case["head_committed_at"]),
            )
            root = {}
            for index, file in enumerate(case["files"]):
                oid = file["blob_sha"]
                self.originals.append(dict(
                    project=repo,
                    partition=case["partition"],
                    pull_number=case["pull_number"],
                    head_sha=head,
                    path=file["path"], blob_sha=oid, sha256=sha("head"+oid),
                ))
                if len(case["parents"]) > 1 or file["status"] == "renamed":
                    continue
                if file["status"] == "added" and index % 2 == 0:
                    continue
                # A file marked added in the full PR can already exist
                # unchanged in the HEAD's first parent. Create that distinct
                # synthetic category rather than assuming PR status is a
                # first-parent byte-diff classification.
                if (
                    (file["status"] == "modified" and index % 3 == 0)
                    or (file["status"] == "added" and index % 2 == 1)
                ):
                    prior_oid = oid
                else:
                    raw = ("prior bytes " + file["path"]).encode()
                    prior_oid = blob_sha(raw)
                    self.objects[repo, "blobs", prior_oid] = dict(
                        sha=prior_oid, size=len(raw), encoding="base64",
                        content=base64.b64encode(raw).decode(),
                    )
                    self.changed[prior_oid] = raw
                node = root
                parts = file["path"].split("/")
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = dict(
                    type="blob", mode="100644", sha=prior_oid,
                )
            for parent_oid in case["parents"]:
                tree_oid = sha(head + parent_oid + "root")
                self.objects[repo, "commits", parent_oid] = dict(
                    sha=parent_oid, tree=dict(sha=tree_oid),
                    committer=dict(date="2026-10-10T00:00:00Z"),
                )
                if parent_oid != case["parents"][0]:
                    self.objects[repo, "trees", tree_oid] = dict(
                        sha=tree_oid, truncated=False, tree=[],
                    )
                    continue

                def emit(prefix, tree_node, current_oid):
                    entries = []
                    for name, value in sorted(tree_node.items()):
                        if isinstance(value, dict) and "sha" in value:
                            entries.append(dict(path=name, **value))
                        else:
                            sub = sha(head + parent_oid + prefix + "/" + name)
                            emit(prefix + "/" + name, value, sub)
                            entries.append(dict(
                                path=name, type="tree",
                                mode="040000", sha=sub,
                            ))
                    self.objects[repo, "trees", current_oid] = dict(
                        sha=current_oid, truncated=False, tree=entries,
                    )

                emit("", root, tree_oid)

    def fetch(self, repo, category, oid):
        return deepcopy(self.objects[repo, category, oid])

    def inspect(self):
        written = {}

        def save(oid, raw):
            written[oid] = raw
            return "before-blobs/" + oid + ".blob"

        report = inspect(
            self.manifest, self.originals,
            ObjectReader(self.fetch), retain=save,
        )
        return report, written


class FirstParentContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SourceFixtures()

    def test_all_eighty_head_refs_and_all_eight_immutable_parent_sets(self):
        report, saved = self.fixture.inspect()
        self.assertEqual(report["original_file_count"], 80)
        self.assertEqual(report["original_pr_count"], 8)
        self.assertEqual(sum(report["comparison_counts"].values()), 80)
        self.assertEqual(
            report["comparison_counts"]["ambiguous-multi-parent-head"], 31
        )
        self.assertEqual(
            report["comparison_counts"]["unresolved-renamed-previous-path"], 1
        )
        self.assertTrue(saved)
        self.assertTrue(set(report["comparison_counts"]).issubset(CATEGORIES))
        self.assertFalse(report["complete_pr_change_intent_verified"])
        self.assertFalse(report["production_accepted"])

    def test_old_blob_sha_and_original_bytes_are_both_verified(self):
        report, saved = self.fixture.inspect()
        pairs = [r for r in report["files"]
                 if r["comparison_status"] == "byte-different-versus-first-parent"]
        self.assertTrue(pairs)
        for row in pairs:
            oid = row["previous_git_blob_sha1"]
            raw = saved[oid]
            self.assertEqual(blob_sha(raw), oid)
            self.assertEqual(digest(raw), row["previous_sha256"])
            self.assertEqual(
                row["before_blob_path"], "before-blobs/" + oid + ".blob"
            )

    def test_added_parent_presence_is_not_assumed_from_pr_status(self):
        report, _ = self.fixture.inspect()
        outcomes = {
            row["comparison_status"]
            for row in report["files"] if row["declared_pr_file_status"] == "added"
        }
        self.assertIn("added-at-first-parent-step", outcomes)
        self.assertIn("added-already-present-in-first-parent", outcomes)
        exact = [
            row for row in report["files"]
            if row["comparison_status"] == "added-already-present-in-first-parent"
        ]
        self.assertTrue(exact)
        self.assertTrue(all(
            row["previous_git_blob_sha1"] == row["original_head_sha1"]
            and row["previous_sha256"] == row["original_head_sha256"]
            and row["before_blob_path"] is None
            for row in exact
        ))

    def test_merge_and_rename_are_never_fake_first_parent_patches(self):
        report, _ = self.fixture.inspect()
        unresolved = [r for r in report["files"] if r["comparison_status"]
                      in ("ambiguous-multi-parent-head",
                          "unresolved-renamed-previous-path")]
        self.assertEqual(len(unresolved), 32)
        self.assertTrue(all(row["before_blob_path"] is None for row in unresolved))
        self.assertTrue(all(row["first_parent_commit_sha"] is None
                            for row in unresolved
                            if row["comparison_status"] == "ambiguous-multi-parent-head"))

    def test_original_head_census_swap_and_parent_hash_drift_fail(self):
        first = SourceFixtures()
        first.originals[0], first.originals[1] = (
            first.originals[1], first.originals[0]
        )
        with self.assertRaisesRegex(ValueError, "order"):
            first.inspect()
        second = SourceFixtures()
        case = second.manifest["cases"][0]
        second.objects[case["repo"], "commits", case["parents"][0]][
            "committer"
        ]["date"] = "2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "postdates"):
            second.inspect()

    def test_corrupt_blob_and_truncated_parent_tree_fail_closed(self):
        for mode in ("blob", "tree"):
            sample = SourceFixtures()
            if mode == "blob":
                repo, oid = next(
                    (k[0], k[2]) for k in sample.objects
                    if k[1] == "blobs"
                )
                sample.objects[repo, "blobs", oid]["content"] = "Zm9yZ2Vk"
            else:
                case = sample.manifest["cases"][0]
                oid = sample.objects[case["repo"], "commits",
                                     case["parents"][0]]["tree"]["sha"]
                sample.objects[case["repo"], "trees", oid]["truncated"] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                sample.inspect()

    def test_atomic_ready_and_separate_incomplete_manifest(self):
        fixture = SourceFixtures()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "original"
            original.mkdir()
            inventory = dict(originals=fixture.originals)
            (original / "inventory.json").write_bytes(canonical(inventory) + b"\n")
            raw_sha = digest((original / "inventory.json").read_bytes())
            readback = dict(
                original_inventory_sha256=raw_sha,
                original_ready_sha256="e" * 64,
            )
            with patch(
                "project_pr_parent_context.reopen_materialized",
                return_value=readback,
            ):
                ready = collect_parent(
                    fixture.manifest, original, base / "parent",
                    manifest_sha=PIN, fetch=fixture.fetch,
                )
            self.assertEqual(ready["original_file_count"], 80)
            self.assertFalse(ready["complete_pr_diff_certified"])
            self.assertTrue((base / "parent/READY.json").is_file())
            report = json.loads((base / "parent/context.json").read_text())
            self.assertEqual(len(report["files"]), 80)
            with patch(
                "project_pr_parent_context.reopen_materialized",
                return_value=readback,
            ):
                with self.assertRaises(ValueError):
                    collect_parent(fixture.manifest, original, base / "parent",
                                   manifest_sha=PIN, fetch=fixture.fetch)

    def test_acquisition_failure_never_publishes_ready(self):
        fixture = SourceFixtures()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "original"
            original.mkdir()
            (original / "inventory.json").write_bytes(
                canonical(dict(originals=fixture.originals)) + b"\n"
            )
            readback = dict(
                original_inventory_sha256=digest(
                    (original / "inventory.json").read_bytes()
                ),
                original_ready_sha256="e"*64,
            )
            def broken_fetch(repo, kind, oid):
                if kind == "trees":
                    raise ValueError("original Git history unavailable")
                return fixture.fetch(repo, kind, oid)

            with patch("project_pr_parent_context.reopen_materialized",
                       return_value=readback):
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    collect_parent(
                        fixture.manifest, original, base / "parent",
                        manifest_sha=PIN, fetch=broken_fetch,
                    )
            self.assertFalse((base / "parent/READY.json").exists())
            self.assertTrue((base / "parent/INCOMPLETE.json").exists())


    def test_offline_reopen_rehashes_every_stored_original_parent_byte(self):
        fixture = SourceFixtures()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "original"
            original.mkdir()
            inventory_raw = canonical(dict(originals=fixture.originals)) + b"\n"
            (original / "inventory.json").write_bytes(inventory_raw)
            receipt = dict(
                original_inventory_sha256=digest(inventory_raw),
                original_ready_sha256="e" * 64,
            )
            with patch("project_pr_parent_context.reopen_materialized",
                       return_value=receipt):
                collect_parent(
                    fixture.manifest, original, base / "parent",
                    manifest_sha=PIN, fetch=fixture.fetch,
                )
                review = reopen_parent(
                    fixture.manifest, original, base / "parent",
                    manifest_sha=PIN,
                )
            self.assertTrue(review["offline_source_hash_verification"])
            self.assertEqual(review["original_file_count"], 80)
            self.assertFalse(review["complete_pr_diff_certified"])
            self.assertGreater(review["saved_before_blobs"], 0)

            member = next((base / "parent/before-blobs").glob("*.blob"))
            member.write_bytes(b"maliciously changed original Git content")
            with patch("project_pr_parent_context.reopen_materialized",
                       return_value=receipt):
                with self.assertRaisesRegex(ValueError, "tampered"):
                    reopen_parent(
                        fixture.manifest, original, base / "parent",
                        manifest_sha=PIN,
                    )

    def test_unreviewed_receipt_cannot_be_upgraded_by_rehashing_metadata(self):
        fixture = SourceFixtures()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / "original"
            original.mkdir()
            raw = canonical(dict(originals=fixture.originals)) + b"\n"
            (original / "inventory.json").write_bytes(raw)
            receipt = dict(
                original_inventory_sha256=digest(raw),
                original_ready_sha256="e" * 64,
            )
            with patch("project_pr_parent_context.reopen_materialized",
                       return_value=receipt):
                collect_parent(fixture.manifest, original, base / "parent",
                               manifest_sha=PIN, fetch=fixture.fetch)
            context_path = base / "parent/context.json"
            ready_path = base / "parent/READY.json"
            report = json.loads(context_path.read_text())
            report["complete_pr_change_intent_verified"] = True
            changed = canonical(report) + b"\n"
            context_path.write_bytes(changed)
            ready = json.loads(ready_path.read_text())
            ready["context_sha256"] = digest(changed)
            ready_path.write_bytes(canonical(ready) + b"\n")
            with patch("project_pr_parent_context.reopen_materialized",
                       return_value=receipt):
                with self.assertRaisesRegex(ValueError, "promoted"):
                    reopen_parent(fixture.manifest, original, base / "parent",
                                  manifest_sha=PIN)



if __name__ == "__main__":
    unittest.main()
