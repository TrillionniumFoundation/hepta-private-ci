#!/usr/bin/env python3
"""Reject unreviewed source/tree changes around the exact Darwin addition."""
from pathlib import Path
import unittest

from file_update_oracle import dependency_projection as projection
from test_file_update_dependency_admission import PINNED_LISTING


def actual_listing():
    listing = PINNED_LISTING
    for path, (old, new) in projection.LEAVES.items():
        row = f"100644 blob {new}\t{path}\0".encode()
        if old:
            before = f"100644 blob {old}\t{path}\0".encode()
            if listing.count(before) != 1:
                raise RuntimeError("complete original leaf fixture differs")
            listing = listing.replace(before, row, 1)
        else:
            listing += row
    return listing


class DarwinDependencyAdmission(unittest.TestCase):
    def project(self, listing):
        return projection.tree(projection.DEPENDENCY, projection.ORIGINAL_TREE,
                               projection.ACTUAL_TREE, listing)

    def test_complete_current_tree_recovers_both_unchanged_predecessors(self):
        result = self.project(actual_listing())
        self.assertEqual(result["projected_original_tree"], projection.ORIGINAL_TREE)
        self.assertEqual(result["intermediate_tree"], projection.INTERMEDIATE_TREE)
        self.assertEqual(result["leaf_count"], 144)
        self.assertEqual(result["original_wine_projection"]["leaf_count"], 143)

    def test_each_reviewed_leaf_must_have_its_exact_bytes_and_mode(self):
        for path, (_, digest) in projection.LEAVES.items():
            row = f"100644 blob {digest}\t{path}\0".encode()
            for changed in (row.replace(digest.encode(), b"0" * 40),
                            row.replace(b"100644", b"100755")):
                with self.subTest(path=path, changed=changed), self.assertRaises(RuntimeError):
                    self.project(actual_listing().replace(row, changed, 1))

    def test_missing_duplicate_and_extra_leaves_fail_closed(self):
        row = actual_listing().split(b"\0")[-2] + b"\0"
        for listing in (actual_listing().replace(row, b"", 1), actual_listing() + row,
                        actual_listing() + b"100644 blob " + b"0" * 40 + b"\textra.rs\0"):
            with self.subTest(listing_bytes=len(listing)), self.assertRaises(RuntimeError):
                self.project(listing)

    def test_unrelated_library_leaf_is_still_rejected(self):
        listing = actual_listing().replace(b"8a2616a2001bcbb06b2b9bd1420c274c1c73cb81",
                                           b"0" * 40, 1)
        with self.assertRaises(RuntimeError):
            self.project(listing)

    def test_other_dependency_or_tree_pins_are_rejected(self):
        for args in (("another", projection.ORIGINAL_TREE, projection.ACTUAL_TREE),
                     (projection.DEPENDENCY, "0" * 40, projection.ACTUAL_TREE),
                     (projection.DEPENDENCY, projection.ORIGINAL_TREE, "0" * 40)):
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                projection.tree(*args, actual_listing())

    def source_pair(self):
        root = Path(__file__).resolve().parents[2]
        current = (root / projection.DEPENDENCY / projection.SOURCE).read_bytes()
        original = current.replace(projection.MODULE, b"", 1).replace(
            projection.ACTUAL_READ, projection.ORIGINAL_READ, 1)
        return current, original

    def test_complete_source_inverse_binds_original_git_blob(self):
        actual, original = self.source_pair()
        self.assertEqual(projection.source(actual, original)["original_blob"],
                         "0a1be1295388173a8aebc3e81980e3edecb9f12a")

    def test_changed_predicate_candidate_cfg_and_unrelated_source_are_rejected(self):
        actual, original = self.source_pair()
        for changed in (actual.replace(b"if denied || !allowed", b"if denied && !allowed"),
                        actual.replace(b"[final_path]", b"[]"),
                        actual.replace(projection.MODULE, b""), actual + b"\n"):
            with self.subTest(changed_bytes=len(changed)), self.assertRaises(RuntimeError):
                projection.source(changed, original)

    def test_original_source_cannot_be_refreshed(self):
        actual, original = self.source_pair()
        with self.assertRaises(RuntimeError):
            projection.source(actual, original + b"\n")


if __name__ == "__main__":
    unittest.main()
