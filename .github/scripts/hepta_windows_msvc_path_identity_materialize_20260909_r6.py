#!/usr/bin/env python3
"""Materialize Windows-safe canonical path identity checks after the r5 repairs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


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


def patch_private_directory_checks() -> None:
    old = """    fs::create_dir_all(path).map_err(unavailable)?;
    if path.canonicalize().map_err(unavailable)? != path {
"""
    new = """    fs::create_dir_all(path).map_err(unavailable)?;
    let canonical_path = AbsolutePathBuf::try_from(path)
        .map_err(unavailable)?
        .canonicalize()
        .map_err(unavailable)?;
    if canonical_path.as_path() != path {
"""
    for relative in (
        "codex-rs/hepta-memory/src/cognitive_store.rs",
        "codex-rs/hepta-automation/src/store.rs",
        "codex-rs/hepta-matrix-store/src/store.rs",
    ):
        replace_once(ROOT / relative, old, new, "private-directory canonical path")


def patch_federation_database_check() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_federation.rs"
    old = """    let metadata = std::fs::metadata(path).map_err(unavailable)?;
    if !metadata.is_file() || path.canonicalize().map_err(unavailable)? != path {
"""
    new = """    let metadata = std::fs::metadata(path).map_err(unavailable)?;
    let canonical_path = AbsolutePathBuf::try_from(path)
        .map_err(unavailable)?
        .canonicalize()
        .map_err(unavailable)?;
    if !metadata.is_file() || canonical_path.as_path() != path {
"""
    replace_once(path, old, new, "federated-database canonical path")


def add_windows_regression_test() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs"
    text = read(path)
    module_name = "windows_canonical_path_identity_tests"
    if module_name in text:
        raise SystemExit(f"{module_name} already exists")
    test_module = r'''

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
'''
    text = text.rstrip() + test_module + "\n"
    if text.count(module_name) != 1:
        raise SystemExit(f"unexpected {module_name} count")
    write(path, text)


def verify_materialized_shape() -> None:
    files = (
        ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs",
        ROOT / "codex-rs/hepta-memory/src/cognitive_federation.rs",
        ROOT / "codex-rs/hepta-automation/src/store.rs",
        ROOT / "codex-rs/hepta-matrix-store/src/store.rs",
    )
    combined = "\n".join(read(path) for path in files)
    checks = {
        "path.canonicalize().map_err(unavailable)? != path": 0,
        "let canonical_path = AbsolutePathBuf::try_from(path)": 4,
        ".canonicalize()\n        .map_err(unavailable)?;": 4,
        "ordinary_absolute_temp_root_survives_verbatim_canonicalization": 1,
    }
    for fragment, expected in checks.items():
        observed = combined.count(fragment)
        if observed != expected:
            raise SystemExit(
                f"path identity fragment count mismatch: {fragment!r}: "
                f"expected {expected}, observed {observed}"
            )


def main() -> None:
    patch_private_directory_checks()
    patch_federation_database_check()
    add_windows_regression_test()
    verify_materialized_shape()


if __name__ == "__main__":
    main()
