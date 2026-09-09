#!/usr/bin/env python3
r"""Normalize Windows path identities without weakening symlink rejection.

This bounded r7 materializer runs after the r5 schema-oracle and r6 path
materializers. r6 converted four security checks to AbsolutePathBuf but still
compared a normalized/dunce-canonical path with the caller's raw Path. A
Windows `std::fs::canonicalize` result commonly carries the `\\?\` device
prefix, so the raw/normalized comparison rejected an otherwise identical path.

r7 compares normalized logical identity with normalized canonical identity.
A real symlink/junction rewrite still changes canonical identity and remains
rejected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path.cwd()

PATH_IDENTITY_FILES = (
    "codex-rs/hepta-memory/src/cognitive_store.rs",
    "codex-rs/hepta-memory/src/cognitive_federation.rs",
    "codex-rs/hepta-automation/src/store.rs",
    "codex-rs/hepta-matrix-store/src/store.rs",
)

R6_IDENTITY_CHECK = """    let canonical_path = AbsolutePathBuf::try_from(path)
        .map_err(unavailable)?
        .canonicalize()
        .map_err(unavailable)?;
    if canonical_path.as_path() != path {
"""

R7_IDENTITY_CHECK = """    let logical_path = AbsolutePathBuf::try_from(path).map_err(unavailable)?;
    let canonical_path = logical_path.canonicalize().map_err(unavailable)?;
    if canonical_path != logical_path {
"""

R6_WINDOWS_TEST_MODULE = r"""
#[cfg(all(test, windows))]
mod windows_canonical_path_identity_tests {
    use super::create_private_directory;

    #[test]
    fn ordinary_absolute_temp_root_survives_verbatim_canonicalization() {
        let temp = tempfile::tempdir().expect("temporary directory");
        let cognitive_root = temp.path().join("cognitive");
        create_private_directory(&cognitive_root)
            .expect("ordinary Windows path must not be rejected as a namespace alias");
        assert!(cognitive_root.is_dir());
    }
}
"""

R7_WINDOWS_TEST_MODULE = r"""
#[cfg(all(test, windows))]
mod windows_canonical_path_identity_tests {
    use super::create_private_directory;

    #[test]
    fn ordinary_absolute_temp_root_survives_verbatim_canonicalization() {
        let temp = tempfile::tempdir().expect("temporary directory");
        let cognitive_root = temp.path().join("cognitive");
        create_private_directory(&cognitive_root)
            .expect("ordinary Windows path must not be rejected as a namespace alias");
        assert!(cognitive_root.is_dir());
    }

    #[test]
    fn device_prefixed_temp_root_normalizes_before_identity_comparison() {
        let temp = tempfile::tempdir().expect("temporary directory");
        let canonical_temp =
            std::fs::canonicalize(temp.path()).expect("canonical temporary directory");
        let cognitive_root = canonical_temp.join("cognitive");
        create_private_directory(&cognitive_root)
            .expect("equivalent Windows device-prefix path must preserve canonical identity");
        assert!(cognitive_root.is_dir());
    }
}
"""


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != 1:
        raise SystemExit(
            f"expected one {label} anchor in {path.as_posix()}, observed {observed}"
        )
    text = text.replace(old, new, 1)
    if old in text:
        raise SystemExit(f"stale {label} anchor remains in {path.as_posix()}")
    write(path, text)


def patch_normalized_identity_checks() -> None:
    for relative in PATH_IDENTITY_FILES:
        replace_once(
            ROOT / relative,
            R6_IDENTITY_CHECK,
            R7_IDENTITY_CHECK,
            "r6 raw-vs-normalized path identity",
        )


def strengthen_windows_regression() -> None:
    replace_once(
        ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs",
        R6_WINDOWS_TEST_MODULE,
        R7_WINDOWS_TEST_MODULE,
        "r6 Windows path identity test module",
    )


def rustfmt_materialized_workspace() -> None:
    subprocess.run(
        [
            "cargo",
            "fmt",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--all",
        ],
        check=True,
    )


def verify_materialized_shape() -> None:
    files = tuple(ROOT / relative for relative in PATH_IDENTITY_FILES)
    combined = "\n".join(read(path) for path in files)
    checks = {
        "let logical_path = AbsolutePathBuf::try_from(path).map_err(unavailable)?;": 4,
        "let canonical_path = logical_path.canonicalize().map_err(unavailable)?;": 4,
        "if canonical_path != logical_path {": 4,
        "canonical_path.as_path() != path": 0,
        "path.canonicalize().map_err(unavailable)? != path": 0,
        "device_prefixed_temp_root_normalizes_before_identity_comparison": 1,
    }
    for fragment, expected in checks.items():
        observed = combined.count(fragment)
        if observed != expected:
            raise SystemExit(
                f"normalized identity fragment count mismatch: {fragment!r}: "
                f"expected {expected}, observed {observed}"
            )


def main() -> None:
    patch_normalized_identity_checks()
    strengthen_windows_regression()
    rustfmt_materialized_workspace()
    verify_materialized_shape()


if __name__ == "__main__":
    main()
