#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path.cwd()
CHANGED: list[str] = []


def replace_exact(path: str, old: str, new: str, *, count: int = 1) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"{path}: expected {count} occurrence(s), found {actual}: {old[:120]!r}"
        )
    file_path.write_text(text.replace(old, new, count), encoding="utf-8")
    if path not in CHANGED:
        CHANGED.append(path)


def replace_all_nonzero(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual == 0:
        raise SystemExit(f"{path}: missing expected text: {old!r}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")
    if path not in CHANGED:
        CHANGED.append(path)


# Platform-specific imports must be compiled only where their users exist.
replace_exact(
    "codex-rs/utils/home-dir/src/lib.rs",
    "    use super::find_hepta_home_from_env;\n    use super::parse_env_value;\n",
    "    use super::find_hepta_home_from_env;\n    #[cfg(unix)]\n    use super::parse_env_value;\n",
)
replace_exact(
    "codex-rs/hepta-fleet/src/registry.rs",
    "use std::collections::BTreeMap;\nuse std::fs::File;\n",
    "use std::collections::BTreeMap;\n#[cfg(unix)]\nuse std::fs::File;\n",
)
replace_exact(
    "codex-rs/hepta-fleet/src/registry_tests.rs",
    "use std::path::Path;\nuse std::sync::Arc;\nuse std::sync::Barrier;\n",
    "use std::path::Path;\n#[cfg(unix)]\nuse std::sync::Arc;\n#[cfg(unix)]\nuse std::sync::Barrier;\n",
)
replace_exact(
    "codex-rs/hepta-operator-acceptance/src/g5_trust.rs",
    "use std::io::Write;\nuse std::path::Path;\nuse std::process::Command;\nuse std::process::Stdio;\n",
    "#[cfg(unix)]\nuse std::io::Write;\nuse std::path::Path;\n#[cfg(unix)]\nuse std::process::Command;\n#[cfg(unix)]\nuse std::process::Stdio;\n",
)

# Keep the lock file alive on every platform while making the intentional
# guard ownership explicit to the compiler on platforms without flock(2).
replace_exact(
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    "pub(crate) struct SidecarLock {\n    file: File,\n}\n",
    "pub(crate) struct SidecarLock {\n    _file: File,\n}\n",
)
replace_exact(
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    "    Ok(SidecarLock { file })\n",
    "    Ok(SidecarLock { _file: file })\n",
)
replace_exact(
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    "self.file.as_raw_fd()",
    "self._file.as_raw_fd()",
)
replace_exact(
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    """fn verify_private_mode(metadata: &std::fs::Metadata, label: &str) -> Result<(), AcceptanceError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(invalid(format!(
                "{label} must not grant group or other access"
            )));
        }
        // SAFETY: `geteuid` takes no arguments, has no preconditions, and does
        // not expose or mutate memory.
        let effective_uid = unsafe { libc::geteuid() };
        if metadata.uid() != effective_uid {
            return Err(invalid(format!(
                "{label} must be owned by the effective user"
            )));
        }
    }
    Ok(())
}
""",
    """#[cfg(unix)]
fn verify_private_mode(metadata: &std::fs::Metadata, label: &str) -> Result<(), AcceptanceError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(invalid(format!(
            "{label} must not grant group or other access"
        )));
    }
    // SAFETY: `geteuid` takes no arguments, has no preconditions, and does
    // not expose or mutate memory.
    let effective_uid = unsafe { libc::geteuid() };
    if metadata.uid() != effective_uid {
        return Err(invalid(format!(
            "{label} must be owned by the effective user"
        )));
    }
    Ok(())
}

#[cfg(not(unix))]
fn verify_private_mode(
    _metadata: &std::fs::Metadata,
    _label: &str,
) -> Result<(), AcceptanceError> {
    Ok(())
}
""",
)

# Bazel test crates need direct dependencies for imports compiled in test mode.
replace_exact(
    "codex-rs/hepta-shadow-qualification/BUILD.bazel",
    """rust_test(
    name = "hepta-shadow-qualification-tests",
    compile_data = ["fixtures/live_product_oracle_v2_2f704.json"],
    crate = ":hepta-shadow-qualification-lib",
    deps = [
        "@crates//:pretty_assertions",
        "@crates//:tempfile",
    ],
)
""",
    """rust_test(
    name = "hepta-shadow-qualification-tests",
    compile_data = ["fixtures/live_product_oracle_v2_2f704.json"],
    crate = ":hepta-shadow-qualification-lib",
    deps = [
        "//codex-rs/hepta-learning-artifacts",
        "//codex-rs/hepta-learning-ledger",
        "//codex-rs/hepta-ndu",
        "//codex-rs/hepta-objective",
        "//codex-rs/hepta-types",
        "@crates//:pretty_assertions",
        "@crates//:tempfile",
    ],
)
""",
)

# Keep all Windows host-loaded proc macros and native archives on the MSVC ABI.
bazel = ".github/workflows/bazel.yml"
replace_exact(
    bazel,
    """  test-windows-shard:
    # Split the Windows Bazel test leg across separate Windows hosts. Jobs with
    # BuildBuddy credentials use Linux RBE for build actions; test execution
    # remains on a Windows runner.
""",
    """  test-windows-shard:
    # Split the native Windows Bazel test leg across separate Windows hosts.
    # Build actions and host-loaded proc macros use the same MSVC ABI as the
    # test binaries, avoiding cross-ABI native archive linkage.
""",
)
replace_exact(
    bazel,
    """          bazel_test_args=(
            test
            --skip_incompatible_explicit_targets
""",
    """          bazel_test_args=(
            test
            --platforms=//:windows_x86_64_msvc
            --skip_incompatible_explicit_targets
""",
)
replace_exact(
    bazel,
    """            --windows-cross-compile \\
            --remote-download-toplevel \\
""",
    """            --windows-msvc-host-platform \\
            --remote-download-toplevel \\
""",
)
replace_exact(
    bazel,
    """          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # Keep this aligned with the fast Windows Bazel test job: use
            # Linux RBE for clippy build actions while targeting Windows
            # gnullvm. Fork/community PRs without the BuildBuddy secret fall
            # back through the shared wrappers to a local gnullvm target and
            # host, matching the pinned MinGW C/C++ toolchain ABI.
            bazel_wrapper_args+=(--windows-cross-compile)
            bazel_target_list_args+=(--windows-cross-compile)
            if [[ -z "${BUILDBUDDY_API_KEY:-}" ]]; then
              # The fork fallback can see incompatible explicit Windows-cross
              # internal test binaries in the generated target list. Preserve
              # the old local-fallback behavior there.
              bazel_clippy_args+=(--skip_incompatible_explicit_targets)
            fi
          fi
""",
    """          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # Keep host-loaded proc macros and native libraries on one Windows
            # ABI while preserving the complete Bazel clippy target set.
            bazel_wrapper_args+=(--windows-msvc-host-platform)
            bazel_clippy_args+=(--platforms=//:windows_x86_64_msvc)
          fi
""",
)
replace_exact(
    bazel,
    """          bazel_wrapper_args=()
          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # This is build-only signal, so use the same Linux-RBE
            # cross-compile path as the fast Windows test and clippy jobs.
            # Fork/community PRs without the BuildBuddy secret fall back
            # through the shared wrappers to the matching local gnullvm
            # target and host ABI.
            bazel_wrapper_args+=(--windows-cross-compile)
          fi
""",
    """          bazel_wrapper_args=()
          if [[ "${RUNNER_OS}" == "Windows" ]]; then
            # Release-mode compile coverage must use one coherent native ABI
            # for target crates, proc macros, SQLite, and cryptographic code.
            bazel_wrapper_args+=(--windows-msvc-host-platform)
          fi
""",
)
replace_exact(
    bazel,
    """          bazel_build_args=(
            --compilation_mode=fastbuild
""",
    """          bazel_build_args=(
            --compilation_mode=fastbuild
            --platforms=//:windows_x86_64_msvc
""",
)
replace_all_nonzero(
    bazel,
    "x86_64-pc-windows-gnullvm",
    "x86_64-pc-windows-msvc",
)
bazel_text = (ROOT / bazel).read_text(encoding="utf-8")
if "--windows-cross-compile" in bazel_text or "x86_64-pc-windows-gnullvm" in bazel_text:
    raise SystemExit("bazel.yml still contains the retired PR Windows cross-ABI path")
if bazel_text.count("--windows-msvc-host-platform") != 4:
    raise SystemExit("bazel.yml must contain four MSVC host selections")
if bazel_text.count("--platforms=//:windows_x86_64_msvc") != 4:
    raise SystemExit("bazel.yml must contain four native MSVC target selections")

# Retry only the known Bazel 9 macOS ARM internal crash (exit 37), once.
v8 = ".github/workflows/v8-canary.yml"
replace_exact(
    v8,
    """          ./.github/scripts/run_bazel_with_buildbuddy.py \\
            --noexperimental_remote_repo_contents_cache \\
            "${bazel_args[@]}" \\
            "--config=${{ matrix.bazel_config }}"
""",
    """          run_v8_bazel() {
            ./.github/scripts/run_bazel_with_buildbuddy.py \\
              --noexperimental_remote_repo_contents_cache \\
              "${bazel_args[@]}" \\
              "--config=${{ matrix.bazel_config }}"
          }

          set +e
          run_v8_bazel
          bazel_status=$?
          set -e
          if [[ ${bazel_status} -eq 0 ]]; then
            exit 0
          fi
          if [[ ${bazel_status} -ne 37 || "${RUNNER_OS}" != "macOS" || "${TARGET}" != "aarch64-apple-darwin" ]]; then
            exit "${bazel_status}"
          fi

          echo "Bazel exited 37 on macOS ARM; shutting down and retrying the identical V8 build once." >&2
          ./.github/scripts/run_bazel_with_buildbuddy.py \\
            --noexperimental_remote_repo_contents_cache \\
            shutdown || true
          run_v8_bazel
""",
)
v8_text = (ROOT / v8).read_text(encoding="utf-8")
if v8_text.count("Bazel exited 37 on macOS ARM") != 1:
    raise SystemExit("v8-canary.yml must contain exactly one bounded exit-37 retry")

expected = {
    ".github/workflows/bazel.yml",
    ".github/workflows/v8-canary.yml",
    "codex-rs/hepta-fleet/src/registry.rs",
    "codex-rs/hepta-fleet/src/registry_tests.rs",
    "codex-rs/hepta-operator-acceptance/src/durable.rs",
    "codex-rs/hepta-operator-acceptance/src/g5_trust.rs",
    "codex-rs/hepta-shadow-qualification/BUILD.bazel",
    "codex-rs/utils/home-dir/src/lib.rs",
}
if set(CHANGED) != expected:
    raise SystemExit(f"unexpected changed-file set: {sorted(CHANGED)}")

subprocess.run(["git", "diff", "--check"], check=True)
actual = {
    line
    for line in subprocess.check_output(
        ["git", "diff", "--name-only"], text=True
    ).splitlines()
    if line
}
if actual != expected:
    raise SystemExit(f"git diff changed-file set differs: {sorted(actual)}")

out = ROOT / "hepta-final-patch"
if out.exists():
    shutil.rmtree(out)
(out / "files").mkdir(parents=True)
manifest_files: list[dict[str, str]] = []
for rel in sorted(expected):
    source = ROOT / rel
    destination = out / "files" / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_files.append({"path": rel, "sha256": digest})

(out / "final.patch").write_bytes(
    subprocess.check_output(["git", "diff", "--binary", "--", *sorted(expected)])
)
manifest = {
    "schema": "hepta_final_blocker_patch_v1",
    "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "files": manifest_files,
}
(out / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, indent=2, sort_keys=True))
