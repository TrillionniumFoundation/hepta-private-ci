from __future__ import annotations

import unicodedata
import unittest

from control_engineering_v2.control_plane import (
    EngineeringError,
    canonical_paths,
    canonical_repo_path,
    path_is_within,
    paths_overlap,
)


class CanonicalRepositoryPathHardening(unittest.TestCase):
    def test_rejects_platform_aliases_and_admin_names(self) -> None:
        invalid = (
            "src//file",
            "src/./file",
            "src\\file",
            "src/file.",
            "src/file ",
            " src/file",
            "src/name:stream",
            "CON",
            "aux.txt",
            "src/COM1.log",
            ".git/config",
            "GIT~1/config",
            unicodedata.normalize("NFD", "src/café"),
        )
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaises(EngineeringError):
                    canonical_repo_path(value)

    def test_accepts_one_canonical_repository_path(self) -> None:
        self.assertEqual(
            canonical_repo_path("tools/hepta-engineering-control/file.txt"),
            "tools/hepta-engineering-control/file.txt",
        )

    def test_casefold_aliases_conflict(self) -> None:
        self.assertTrue(paths_overlap("Source/Module", "source/module/file"))
        self.assertTrue(path_is_within("SOURCE/module/file", ("source",)))
        with self.assertRaises(EngineeringError):
            canonical_paths(("Source/Module", "source/module"))

    def test_segment_boundaries_do_not_use_plain_string_prefixes(self) -> None:
        self.assertFalse(paths_overlap("source/mod", "source/module"))
        self.assertFalse(path_is_within("source/module", ("source/mod",)))


if __name__ == "__main__":
    unittest.main()
