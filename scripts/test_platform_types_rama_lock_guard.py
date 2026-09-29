"""Regression tests for the exact coherent Rama prerelease graph."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.platform_types_rama_lock_guard import (
    DIRECT_MANIFEST_PACKAGES,
    EXPECTED_VERSION,
    LOCK_EXPECTED_VERSIONS,
    RamaLockError,
    validate,
)

STABLE_VERSION = "0.3.0"


def manifest_text(*, omit: str | None = None, override: dict[str, str] | None = None) -> str:
    rows = ["[dependencies]"]
    override = override or {}
    for package in DIRECT_MANIFEST_PACKAGES:
        if package == "rama-unix" or package == omit:
            continue
        version = override.get(package, EXPECTED_VERSION)
        rows.append(f'{package} = "={version}"')
    rows.extend(
        [
            "",
            "[target.'cfg(target_family = \"unix\")'.dependencies]",
        ]
    )
    if omit != "rama-unix":
        version = override.get("rama-unix", EXPECTED_VERSION)
        rows.append(f'rama-unix = "={version}"')
    return "\n".join(rows) + "\n"


def lock_text(
    *, override: dict[str, str] | None = None, unexpected: str | None = None
) -> str:
    rows = ["version = 4", ""]
    override = override or {}
    for package, expected in LOCK_EXPECTED_VERSIONS.items():
        version = override.get(package, expected)
        rows.extend(
            [
                "[[package]]",
                f'name = "{package}"',
                f'version = "{version}"',
                "",
            ]
        )
    if unexpected is not None:
        rows.extend(
            [
                "[[package]]",
                f'name = "{unexpected}"',
                f'version = "{EXPECTED_VERSION}"',
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

    def test_coherent_alpha4_graph_passes(self):
        self.assertEqual(LOCK_EXPECTED_VERSIONS["rama-error"], EXPECTED_VERSION)
        self.assertEqual(LOCK_EXPECTED_VERSIONS["rama-macros"], EXPECTED_VERSION)
        self.assertEqual(LOCK_EXPECTED_VERSIONS["rama-utils"], EXPECTED_VERSION)
        self.validate_fixture(manifest_text(), lock_text())

    def test_stable_support_crate_is_rejected(self):
        for package in ("rama-error", "rama-macros", "rama-utils"):
            with self.subTest(package=package), self.assertRaises(RamaLockError):
                self.validate_fixture(
                    manifest_text(), lock_text(override={package: STABLE_VERSION})
                )

    def test_stable_product_crate_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(
                manifest_text(), lock_text(override={"rama-core": STABLE_VERSION})
            )

    def test_missing_direct_support_constraint_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(manifest_text(omit="rama-error"), lock_text())

    def test_missing_direct_product_constraint_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(manifest_text(omit="rama-net"), lock_text())

    def test_nonexact_direct_constraint_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(
                manifest_text(
                    override={"rama-core": f"{EXPECTED_VERSION}, <0.4.0"}
                ),
                lock_text(),
            )

    def test_unreviewed_rama_package_is_rejected(self):
        with self.assertRaises(RamaLockError):
            self.validate_fixture(
                manifest_text(), lock_text(unexpected="rama-unreviewed")
            )


if __name__ == "__main__":
    unittest.main()
