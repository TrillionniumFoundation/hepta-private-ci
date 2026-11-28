#!/usr/bin/env python3
"""Keep the exact historical Cargo graph while admitting one Bazel-only leaf."""
import unittest

from file_update_oracle import dependency_projection as projection
from test_file_update_darwin_admission import actual_listing


def current_listing():
    before = f"100644 blob {projection.BAZEL_OLD_BLOB}\tBUILD.bazel\0".encode()
    after = f"100644 blob {projection.BAZEL_NEW_BLOB}\tBUILD.bazel\0".encode()
    old = actual_listing()
    if old.count(before) != 1:
        raise RuntimeError("complete independent predecessor fixture changed")
    return old.replace(before, after, 1)


class BazelDependencyAdmission(unittest.TestCase):
    def project(self, listing):
        return projection.tree(projection.DEPENDENCY, projection.ORIGINAL_TREE,
                               projection.BAZEL_TREE, listing)

    def test_full_tree_recovers_each_unchanged_original(self):
        result = self.project(current_listing())
        self.assertEqual(result["actual_tree"], projection.BAZEL_TREE)
        self.assertEqual(result["projected_original_tree"], projection.ORIGINAL_TREE)
        prior = result["original_darwin_projection"]
        self.assertEqual(prior["actual_tree"], projection.ACTUAL_TREE)
        self.assertEqual(prior["original_wine_projection"]["projected_original_tree"],
                         projection.ORIGINAL_TREE)
        self.assertIs(result["runtime_source_and_cargo_unchanged"], True)
        self.assertEqual(result["leaf_count"], 144)

    def test_original_darwin_domain_remains_exact(self):
        result = projection.tree(projection.DEPENDENCY, projection.ORIGINAL_TREE,
                                 projection.ACTUAL_TREE, actual_listing())
        self.assertEqual(result["schema"], "codex.hia.path-dependency-darwin-projection.v1")
        with self.assertRaises(RuntimeError):
            self.project(actual_listing())

    def test_changed_mode_blob_and_name_are_refused(self):
        row = f"100644 blob {projection.BAZEL_NEW_BLOB}\tBUILD.bazel\0".encode()
        for changed in (row.replace(b"100644", b"100755"),
                        row.replace(projection.BAZEL_NEW_BLOB.encode(), b"0" * 40),
                        row.replace(b"BUILD.bazel", b"other.bazel")):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                self.project(current_listing().replace(row, changed, 1))

    def test_missing_duplicate_extra_and_unrelated_rust_are_refused(self):
        row = f"100644 blob {projection.BAZEL_NEW_BLOB}\tBUILD.bazel\0".encode()
        current = current_listing()
        for changed in (current.replace(row, b"", 1), current + row,
                        current + b"100644 blob " + b"0" * 40 + b"\textra.rs\0",
                        current.replace(b"8a2616a2001bcbb06b2b9bd1420c274c1c73cb81",
                                        b"0" * 40, 1)):
            with self.subTest(bytes=len(changed)), self.assertRaises(RuntimeError):
                self.project(changed)

    def test_different_dependency_or_original_is_refused(self):
        for args in (("another", projection.ORIGINAL_TREE, projection.BAZEL_TREE),
                     (projection.DEPENDENCY, "0" * 40, projection.BAZEL_TREE),
                     (projection.DEPENDENCY, projection.ORIGINAL_TREE, "0" * 40)):
            with self.subTest(args=args), self.assertRaises(RuntimeError):
                projection.tree(*args, current_listing())


if __name__ == "__main__":
    unittest.main()
