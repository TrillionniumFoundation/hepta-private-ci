#!/usr/bin/env python3

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    ".github/workflows/bazel.yml",
    '''          bazel_wrapper_args=()
          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # Release-mode compile coverage must use one coherent native ABI
            # for target crates, proc macros, SQLite, and cryptographic code.
            bazel_wrapper_args+=(--windows-msvc-host-platform)
          fi

          bazel_build_args=(
            --compilation_mode=fastbuild
            --platforms=//:windows_x86_64_msvc
            --@rules_rust//rust/settings:extra_rustc_flag=-Cdebug-assertions=no
            --@rules_rust//rust/settings:extra_exec_rustc_flag=-Cdebug-assertions=no
            --build_metadata=COMMIT_SHA=${GITHUB_SHA}
            --build_metadata=TAG_job=verify-release-build
            --build_metadata=TAG_rust_debug_assertions=off
          )
''',
    '''          bazel_wrapper_args=()
          bazel_build_args=(
            --compilation_mode=fastbuild
            --@rules_rust//rust/settings:extra_rustc_flag=-Cdebug-assertions=no
            --@rules_rust//rust/settings:extra_exec_rustc_flag=-Cdebug-assertions=no
            --build_metadata=COMMIT_SHA=${GITHUB_SHA}
            --build_metadata=TAG_job=verify-release-build
            --build_metadata=TAG_rust_debug_assertions=off
          )
          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # Release-mode compile coverage must use one coherent native ABI
            # for target crates, proc macros, SQLite, and cryptographic code.
            bazel_wrapper_args+=(--windows-msvc-host-platform)
            bazel_build_args+=(--platforms=//:windows_x86_64_msvc)
          fi
''',
)

replace_once(
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    '''#[cfg(not(unix))]
fn verify_private_mode(
    _metadata: &std::fs::Metadata,
    _label: &str,
) -> Result<(), AcceptanceError> {
    Ok(())
}
''',
    '''#[cfg(not(unix))]
fn verify_private_mode(_metadata: &std::fs::Metadata, _label: &str) -> Result<(), AcceptanceError> {
    Ok(())
}
''',
)

bazel = Path(".github/workflows/bazel.yml").read_text(encoding="utf-8")
if bazel.count("--platforms=//:windows_x86_64_msvc") != 4:
    raise SystemExit("unexpected native MSVC platform selector count")
