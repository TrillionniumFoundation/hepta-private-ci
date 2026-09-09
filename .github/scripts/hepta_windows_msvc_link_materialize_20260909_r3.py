#!/usr/bin/env python3
"""Materialize the bounded rules_rust/MSVC final-link repair from effective source."""

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

    generic_function = [
        "def _add_user_link_flags(ret, linker_input):",
        '    ret.extend(["--codegen=link-arg={}".format(flag) for flag in linker_input.user_link_flags])',
    ]
    generic_matches = [
        index
        for index in range(len(modified) - len(generic_function) + 1)
        if modified[index : index + len(generic_function)] == generic_function
    ]
    if len(generic_matches) != 1:
        raise SystemExit(
            f"expected one generic user-link function, found {len(generic_matches)}"
        )

    helper = [
        "",
        "def _normalize_windows_msvc_direct_user_link_flag(flag):",
        '    if flag == "-pthread":',
        "        return None",
        "",
        '    for prefix in ("-lstatic=", "-ldylib="):',
        "        if flag.startswith(prefix):",
        "            library = flag[len(prefix):]",
        '            return library if library.endswith(".lib") else library + ".lib"',
        "",
        '    if flag.startswith("-l:") and len(flag) > 3:',
        "        return flag[3:]",
        "",
        '    if flag.startswith("-l") and len(flag) > 2:',
        "        library = flag[2:]",
        '        return library if library.endswith(".lib") else library + ".lib"',
        "",
        '    if flag.startswith("-Lnative="):',
        '        return "/LIBPATH:" + flag[len("-Lnative="):]',
        "",
        '    if flag.startswith("-L") and len(flag) > 2:',
        '        return "/LIBPATH:" + flag[2:]',
        "",
        "    return flag",
        "",
        "def _add_windows_user_link_flags(",
        "        ret,",
        "        linker_input,",
        "        flavor_msvc,",
        "        use_direct_driver):",
        "    if not (flavor_msvc and use_direct_driver):",
        "        _add_user_link_flags(ret, linker_input)",
        "        return",
        "",
        "    for flag in linker_input.user_link_flags:",
        "        normalized = _normalize_windows_msvc_direct_user_link_flag(flag)",
        "        if normalized != None:",
        '            ret.append("--codegen=link-arg={}".format(normalized))',
    ]
    insert_at = generic_matches[0] + len(generic_function)
    modified[insert_at:insert_at] = helper

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
    call = "    _add_user_link_flags(ret, linker_input)"
    call_matches = [
        index
        for index in range(windows_start, windows_end)
        if modified[index] == call
    ]
    if len(call_matches) != 1:
        raise SystemExit(
            "expected one generic user-link call inside the Windows link function, "
            f"found {len(call_matches)}"
        )
    modified[call_matches[0]] = (
        "    _add_windows_user_link_flags("
        "ret, linker_input, flavor_msvc, use_direct_driver)"
    )

    patch_lines = list(
        difflib.unified_diff(
            original,
            modified,
            fromfile="a/rust/private/rustc.bzl",
            tofile="b/rust/private/rustc.bzl",
            n=5,
            lineterm="",
        )
    )
    patch_text = "\n".join(patch_lines) + "\n"
    if patch_text.count("def _normalize_windows_msvc_direct_user_link_flag") != 1:
        raise SystemExit("generated patch is missing the normalization helper")
    if patch_text.count("_add_windows_user_link_flags(") < 2:
        raise SystemExit("generated patch is missing the Windows-scoped helper/call")

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
