#!/usr/bin/env python3
"""Materialize the bounded rules_rust/MSVC final-link repair."""

from __future__ import annotations

import re
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


def validate_patch_hunks(text: str) -> None:
    lines = text.splitlines()
    index = 0
    seen = 0
    header = re.compile(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@")
    while index < len(lines):
        match = header.match(lines[index])
        if match is None:
            index += 1
            continue
        seen += 1
        expected_old = int(match.group(2))
        expected_new = int(match.group(4))
        old_count = 0
        new_count = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith("--- ") or line.startswith("+++ "):
                break
            if line.startswith("-"):
                old_count += 1
            elif line.startswith("+"):
                new_count += 1
            elif line.startswith(" "):
                old_count += 1
                new_count += 1
            else:
                raise SystemExit(f"invalid unified diff body line: {line!r}")
            index += 1
        if (old_count, new_count) != (expected_old, expected_new):
            raise SystemExit(
                f"malformed hunk: expected {(expected_old, expected_new)}, "
                f"observed {(old_count, new_count)}"
            )
    if seen != 2:
        raise SystemExit(f"expected two patch hunks, found {seen}")


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
    path = ROOT / "patches/rules_rust_windows_msvc_user_link_flags.patch"
    if path.exists():
        raise SystemExit(f"new patch path already exists: {path}")
    text = """--- a/rust/private/rustc.bzl
+++ b/rust/private/rustc.bzl
@@ -3049,2 +3049,30 @@
-def _add_user_link_flags(ret, linker_input):
-    ret.extend([\"--codegen=link-arg={}\".format(flag) for flag in linker_input.user_link_flags])
+def _normalize_windows_msvc_direct_user_link_flag(flag):
+    if flag == \"-pthread\":
+        return None
+
+    for prefix in (\"-lstatic=\", \"-ldylib=\"):
+        if flag.startswith(prefix):
+            library = flag[len(prefix):]
+            return library if library.endswith(\".lib\") else library + \".lib\"
+
+    if flag.startswith(\"-l\") and len(flag) > 2:
+        library = flag[2:]
+        return library if library.endswith(\".lib\") else library + \".lib\"
+
+    if flag.startswith(\"-Lnative=\"):
+        return \"/LIBPATH:\" + flag[len(\"-Lnative=\"):]
+
+    if flag.startswith(\"-L\") and len(flag) > 2:
+        return \"/LIBPATH:\" + flag[2:]
+
+    return flag
+
+def _add_user_link_flags(ret, linker_input, windows_msvc_direct = False):
+    if not windows_msvc_direct:
+        ret.extend([\"--codegen=link-arg={}\".format(flag) for flag in linker_input.user_link_flags])
+        return
+
+    for flag in linker_input.user_link_flags:
+        normalized = _normalize_windows_msvc_direct_user_link_flag(flag)
+        if normalized != None:
+            ret.append(\"--codegen=link-arg={}\".format(normalized))
@@ -3073,1 +3101,5 @@
-    _add_user_link_flags(ret, linker_input)
+    _add_user_link_flags(
+        ret,
+        linker_input,
+        windows_msvc_direct = flavor_msvc and use_direct_driver,
+    )
"""
    validate_patch_hunks(text)
    write(path, text)


def register_patch() -> None:
    build = ROOT / "patches/BUILD.bazel"
    lines = read(build).splitlines()
    insert_after_unique(
        lines,
        '    "rules_rust_windows_msvc_direct_link_args.patch",',
        '    "rules_rust_windows_msvc_user_link_flags.patch",',
        "patches BUILD",
    )
    write(build, "\n".join(lines) + "\n")

    module = ROOT / "MODULE.bazel"
    lines = read(module).splitlines()
    insert_after_unique(
        lines,
        '        "//patches:rules_rust_windows_msvc_direct_link_args.patch",',
        '        "//patches:rules_rust_windows_msvc_user_link_flags.patch",',
        "MODULE patch",
    )
    write(module, "\n".join(lines) + "\n")


def main() -> None:
    patch_wrapper()
    create_rules_rust_patch()
    register_patch()


if __name__ == "__main__":
    main()
