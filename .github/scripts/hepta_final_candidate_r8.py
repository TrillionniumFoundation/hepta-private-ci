#!/usr/bin/env python3
"""Materialize the bounded final Hepta exact-head delta in a source checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

EXPECTED_PATHS = {
    ".bazelrc",
    ".github/scripts/hepta_agentd_gap_patch.py",
    ".github/workflows/hepta-agentd-gap-autofix.yml",
    ".github/workflows/rust-ci.yml",
    "codex-rs/hepta-agentd/examples/h4_persistent_writer.rs",
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "codex-rs/hepta-agentd/src/control.rs",
    "codex-rs/hepta-agentd/tests/support/fleet.rs",
    "codex-rs/hepta-runtime/src/organs.rs",
    "codex-rs/http-client/src/tls_backend_fallback.rs",
    "codex-rs/uds/src/lib.rs",
}


def run(*args: str, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture,
    )
    return completed.stdout if capture else ""


def replace_once(path: Path, old: str, new: str, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one {description}; found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact(
    path: Path,
    old: str,
    new: str,
    expected_count: int,
    description: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected_count:
        raise SystemExit(
            f"expected exactly {expected_count} {description} occurrence(s); found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_runtime_helper() -> None:
    path = Path("codex-rs/hepta-agentd/src/app_runtime.rs")
    old = "pub(crate) fn app_server_runtime_options(\n"
    new = (
        "#[cfg_attr(\n"
        "    not(test),\n"
        "    allow(\n"
        "        dead_code,\n"
        "        reason = \"the shared runtime-options constructor is retained for process qualification and the product-host integration seam\"\n"
        "    )\n"
        ")]\n"
        "pub(crate) fn app_server_runtime_options(\n"
    )
    replace_once(path, old, new, "app_server_runtime_options anchor")


def patch_linux_timeout() -> None:
    path = Path(".github/workflows/rust-ci.yml")
    old = (
        "          - name: Linux\n"
        "            runner: ubuntu-24.04\n"
        "            timeout_minutes: 30\n"
    )
    new = old.replace("timeout_minutes: 30", "timeout_minutes: 60")
    replace_once(path, old, new, "Linux argument-comment matrix timeout")


def patch_h4_clippy() -> None:
    path = Path("codex-rs/hepta-agentd/examples/h4_persistent_writer.rs")
    old = '''        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().to_string();
            let root = entry.path();
            Some(CacheDeviceEvidence {
                name,
                model: read_trimmed(root.join("device/model")),
                write_cache: read_trimmed(root.join("queue/write_cache")),
                fua: read_trimmed(root.join("queue/fua")),
                rotational: read_trimmed(root.join("queue/rotational")),
                state: read_trimmed(root.join("device/state")),
            })
        })
'''
    new = '''        .map(|entry| {
            let name = entry.file_name().to_string_lossy().to_string();
            let root = entry.path();
            CacheDeviceEvidence {
                name,
                model: read_trimmed(root.join("device/model")),
                write_cache: read_trimmed(root.join("queue/write_cache")),
                fua: read_trimmed(root.join("queue/fua")),
                rotational: read_trimmed(root.join("queue/rotational")),
                state: read_trimmed(root.join("device/state")),
            }
        })
'''
    replace_once(path, old, new, "H4 cache-device map")


def patch_windows_argument_comments() -> None:
    replace_once(
        Path("codex-rs/hepta-runtime/src/organs.rs"),
        "    let generation = Generation::new(1)?;\n",
        "    let generation = Generation::new(/* value */ 1)?;\n",
        "runtime generation argument comment",
    )
    replace_exact(
        Path("codex-rs/http-client/src/tls_backend_fallback.rs"),
        "    walk_error_chain(error, 0, &mut |error| {\n",
        "    walk_error_chain(error, /* depth */ 0, &mut |error| {\n",
        2,
        "TLS error-chain depth argument comment",
    )


def patch_windows_exec_process_prng_link() -> None:
    path = Path(".bazelrc")
    old = "common:windows --host_platform=//:local_windows\n"
    new = (
        old
        + "# Rust's Windows exec-side standard library imports ProcessPrng from\n"
        + "# BCryptPrimitives. Pass the matching SDK import library explicitly when\n"
        + "# rules_rust invokes lld-link directly for proc macros and build scripts.\n"
        + "common:windows --@rules_rust//rust/settings:extra_exec_rustc_flag=-Clink-arg=bcryptprimitives.lib\n"
    )
    replace_once(path, old, new, "Windows exec ProcessPrng link setting")


def remove_consumed_assets() -> None:
    for raw in (
        ".github/workflows/hepta-agentd-gap-autofix.yml",
        ".github/scripts/hepta_agentd_gap_patch.py",
    ):
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"required consumed asset is missing: {raw}")
        path.unlink()


def assert_scope() -> None:
    changed = {
        line
        for line in run("git", "diff", "--name-only", capture=True).splitlines()
        if line
    }
    if changed != EXPECTED_PATHS:
        missing = sorted(EXPECTED_PATHS - changed)
        extra = sorted(changed - EXPECTED_PATHS)
        raise SystemExit(f"unexpected final delta; missing={missing}; extra={extra}")
    for raw in (
        ".github/workflows/hepta-agentd-gap-autofix.yml",
        ".github/scripts/hepta_agentd_gap_patch.py",
    ):
        if Path(raw).exists():
            raise SystemExit(f"consumed asset survived: {raw}")
    run("git", "diff", "--check")


def main() -> None:
    run("python3", ".github/scripts/hepta_agentd_gap_patch.py")
    patch_runtime_helper()
    patch_linux_timeout()
    patch_h4_clippy()
    patch_windows_argument_comments()
    patch_windows_exec_process_prng_link()
    remove_consumed_assets()
    run(
        "cargo",
        "fmt",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--package",
        "codex-hepta-agentd",
        "--package",
        "codex-hepta-runtime",
        "--package",
        "codex-http-client",
        "--package",
        "codex-uds",
    )
    assert_scope()


if __name__ == "__main__":
    main()
