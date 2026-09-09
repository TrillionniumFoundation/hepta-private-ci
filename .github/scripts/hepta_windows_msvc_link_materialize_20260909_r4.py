#!/usr/bin/env python3
"""Materialize a Windows-scoped rules_rust/MSVC final-link repair."""

from __future__ import annotations

import difflib
import os
from pathlib import Path

ROOT = Path.cwd()


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def insert_after_unique(lines: list[str], anchor: str, value: str, label: str) -> None:
    matches = [index for index, line in enumerate(lines) if line == anchor]
    if len(matches) != 1:
        raise SystemExit(f"expected one {label} anchor, found {len(matches)}")
    lines.insert(matches[0] + 1, value)


def patch_wrapper() -> None:
    path = ROOT / ".github/scripts/run-bazel-ci.sh"
    lines = read(path).splitlines()
    needle = (
        '        post_config_bazel_args+=("--action_env=${env_var}" '
        '"--host_action_env=${env_var}")'
    )
    matches = [index for index, line in enumerate(lines) if line == needle]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one Windows action-environment line, found {len(matches)}"
        )
    index = matches[0]
    expected_window = [
        '    for env_var in "${windows_action_env_vars[@]}"; do',
        '      if [[ -n "${!env_var:-}" ]]; then',
        needle,
        "      fi",
        "    done",
        "  fi",
    ]
    if lines[index - 2 : index + 4] != expected_window:
        raise SystemExit("Windows action-environment control-flow window changed")

    insertion = [
        "",
        "    # rules_rust Rustc actions do not reliably inherit LIB even when Bazel's",
        "    # generic action environment contains it. Bind every VsDevCmd-provided",
        "    # MSVC/Windows SDK library directory into target and exec rustc links.",
        '    if [[ -n "${LIB:-}" && $windows_cross_compile -eq 0 ]]; then',
        "      IFS=';' read -r -a windows_msvc_lib_dirs <<<\"${LIB}\"",
        '      for windows_msvc_lib_dir in "${windows_msvc_lib_dirs[@]}"; do',
        "        windows_msvc_lib_dir=\"${windows_msvc_lib_dir%$'\\r'}\"",
        '        [[ -n "${windows_msvc_lib_dir}" ]] || continue',
        "        if command -v cygpath >/dev/null 2>&1; then",
        '          windows_msvc_lib_dir="$(cygpath -m "${windows_msvc_lib_dir}")"',
        "        fi",
        "        post_config_bazel_args+=(",
        '          "--@rules_rust//rust/settings:extra_rustc_flag=-Clink-arg=/LIBPATH:${windows_msvc_lib_dir}"',
        '          "--@rules_rust//rust/settings:extra_exec_rustc_flag=-Clink-arg=/LIBPATH:${windows_msvc_lib_dir}"',
        "        )",
        "      done",
        "    fi",
    ]
    lines[index + 3 : index + 3] = insertion
    write(path, "\n".join(lines) + "\n")


def create_rules_rust_patch() -> None:
    source_value = os.environ.get("RULES_RUST_EFFECTIVE_SOURCE", "")
    source = Path(source_value)
    if not source.is_file():
        raise SystemExit(f"effective rules_rust source not found: {source}")

    original = read(source).splitlines()
    modified = list(original)

    windows_header = (
        "def _make_link_flags_windows("
        "make_link_flags_args, flavor_msvc, use_direct_driver):"
    )
    windows_matches = [
        index for index, line in enumerate(modified) if line == windows_header
    ]
    if len(windows_matches) != 1:
        raise SystemExit(
            f"expected one Windows link function, found {len(windows_matches)}"
        )
    windows_start = windows_matches[0]
    windows_end = next(
        (
            index
            for index in range(windows_start + 1, len(modified))
            if modified[index].startswith("def ")
        ),
        len(modified),
    )

    old_block = [
        "    # Windows toolchains can inherit POSIX defaults like -pthread from C deps,",
        "    # which fails to link with the MinGW/LLD toolchain. Drop them here.",
        "    for flag in linker_input.user_link_flags:",
        '        if flag in ("-pthread", "-lpthread"):',
        "            continue",
        '        ret.append("--codegen=link-arg={}".format(flag))',
        "    return _link_arg_compatible_link_flags(ret, link_libraries_as_link_args)",
    ]
    block_matches = [
        index
        for index in range(windows_start, windows_end - len(old_block) + 1)
        if modified[index : index + len(old_block)] == old_block
    ]
    if len(block_matches) != 1:
        raise SystemExit(
            f"expected one effective Windows user-link block, found {len(block_matches)}"
        )

    new_block = [
        "    # Windows toolchains can inherit POSIX/GNU linker spellings from C deps.",
        "    # Preserve non-MSVC behavior, but normalize direct MSVC linker inputs.",
        "    for flag in linker_input.user_link_flags:",
        '        if flag in ("-pthread", "-lpthread"):',
        "            continue",
        "",
        "        normalized_flag = flag",
        "        if flavor_msvc and use_direct_driver:",
        '            if flag.startswith("-lstatic="):',
        '                library = flag[len("-lstatic="):]',
        '                normalized_flag = library if library.endswith(".lib") else library + ".lib"',
        '            elif flag.startswith("-ldylib="):',
        '                library = flag[len("-ldylib="):]',
        '                normalized_flag = library if library.endswith(".lib") else library + ".lib"',
        '            elif flag.startswith("-l:") and len(flag) > 3:',
        "                normalized_flag = flag[3:]",
        '            elif flag.startswith("-l") and len(flag) > 2:',
        "                library = flag[2:]",
        '                normalized_flag = library if library.endswith(".lib") else library + ".lib"',
        '            elif flag.startswith("-Lnative="):',
        '                normalized_flag = "/LIBPATH:" + flag[len("-Lnative="):]',
        '            elif flag.startswith("-L") and len(flag) > 2:',
        '                normalized_flag = "/LIBPATH:" + flag[2:]',
        "",
        '        ret.append("--codegen=link-arg={}".format(normalized_flag))',
        "    return _link_arg_compatible_link_flags(ret, link_libraries_as_link_args)",
    ]
    block_start = block_matches[0]
    modified[block_start : block_start + len(old_block)] = new_block

    if modified[:windows_start] != original[:windows_start]:
        raise SystemExit("generated transformation changed content before Windows function")
    original_tail = original[windows_end:]
    modified_tail_start = windows_end + len(new_block) - len(old_block)
    if modified[modified_tail_start:] != original_tail:
        raise SystemExit("generated transformation changed content after Windows function")

    patch_lines = list(
        difflib.unified_diff(
            original,
            modified,
            fromfile="a/rust/private/rustc.bzl",
            tofile="b/rust/private/rustc.bzl",
            n=6,
            lineterm="",
        )
    )
    patch_text = "\n".join(patch_lines) + "\n"
    required_fragments = [
        "if flavor_msvc and use_direct_driver:",
        'normalized_flag = "/LIBPATH:" + flag[len("-Lnative="):]',
        'normalized_flag = library if library.endswith(".lib") else library + ".lib"',
    ]
    for fragment in required_fragments:
        if patch_text.count(fragment) != 1:
            raise SystemExit(f"generated patch missing unique fragment: {fragment}")

    patch = ROOT / "patches/rules_rust_windows_msvc_user_link_flags.patch"
    if patch.exists():
        raise SystemExit(f"new patch path already exists: {patch}")
    write(patch, patch_text)


def register_patch() -> None:
    build = ROOT / "patches/BUILD.bazel"
    build_lines = read(build).splitlines()
    insert_after_unique(
        build_lines,
        '    "rules_rust_windows_msvc_direct_link_args.patch",',
        '    "rules_rust_windows_msvc_user_link_flags.patch",',
        "patches BUILD",
    )
    write(build, "\n".join(build_lines) + "\n")

    module = ROOT / "MODULE.bazel"
    module_lines = read(module).splitlines()
    insert_after_unique(
        module_lines,
        '        "//patches:rules_rust_process_wrapper_response_file.patch",',
        '        "//patches:rules_rust_windows_msvc_user_link_flags.patch",',
        "final rules_rust MODULE patch",
    )
    write(module, "\n".join(module_lines) + "\n")


def main() -> None:
    patch_wrapper()
    create_rules_rust_patch()
    register_patch()


if __name__ == "__main__":
    main()
