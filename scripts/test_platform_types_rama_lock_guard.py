"""Regression tests for exact Rama prerelease graph enforcement."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from platform_types_rama_lock_guard import (
    EXPECTED_VERSION,
    REQUIRED_PACKAGES,
    RamaLockError,
    validate,
)


def manifest_text(*, stable_error: bool = False, omit_utils: bool = False) -> str:
    rows = ["[dependencies]"]
    for package in REQUIRED_PACKAGES:
        if package == "rama-unix":
            continue
        if omit_utils and package == "rama-utils":
            continue
        version = "0.3.0" if stable_error and package == "rama-error" else EXPECTED_VERSION
        rows.append(f'{package} = "={version}"')
    rows.extend(
        [
            "",
            "[target.'cfg(target_family = \"unix\")'.dependencies]",
            f'rama-unix = "={EXPECTED_VERSION}"',
        ]
    )
    return "\n".join(rows) + "\n"


def lock_text(*, stable_error: bool = False) -> str:
    rows = ["version = 4", ""]
    for package in REQUIRED_PACKAGES:
        version = "0.3.0" if stable_error and package == "rama-error" else EXPECTED_VERSION
        rows.extend(
            [
                "[[package]]",
                f'name = "{package}"',
                f'version = "{version}"',
                "",
            ]
        )
    return "\n".join(rows)


class RamaLockGuardTests(unittest.TestCase):
    def validate_fixture(self, manifest: str, lock: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "Cargo.toml"
            lock_path = root / "Cargo.lock"
            manifest_path.write_text(manifest, encoding="utf-8")
            lock_path.write_text(lock, encoding="utf-8")
            validate(manifest_path, lock_path)

    def test_coherent_exact_prerelease_graph_passes(self):
        self.validate_fixture(manifest_text(), lock_text())

    def test_stable_support_crate_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(manifest_text(), lock_text(stable_error=True))

    def test_missing_direct_constraint_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(manifest_text(omit_utils=True), lock_text())


if __name__ == "__main__":
    unittest.main()
