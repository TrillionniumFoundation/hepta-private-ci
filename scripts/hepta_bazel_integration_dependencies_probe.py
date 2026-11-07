"""Check the real macro's generated dependency graph without compiling Rust.

The isolated Bazel workspace loads the supplied defs.bzl and the repository's
actual rust_test_dependencies helper. Stand-in Rust rules record their labels;
this is a macro-loading regression, not Rust type-checking qualification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


CAPTURE_RULES = """
def _empty(ctx):
    return []

_capture = rule(
    implementation = _empty,
    attrs = {
        "deps": attr.label_list(),
        "srcs": attr.label_list(allow_files = True),
        "data": attr.label_list(allow_files = True),
        "crate_features": attr.string_list(),
    },
)

def _record(**kwargs):
    _capture(
        name = kwargs["name"],
        deps = kwargs.get("deps", []) + ([kwargs["crate"]] if "crate" in kwargs else []),
        srcs = kwargs.get("srcs", []),
        data = kwargs.get("data", []),
        crate_features = kwargs.get("crate_features", []),
    )

rust_binary = _record
rust_library = _record
rust_proc_macro = _record
rust_test = _record
"""

FIXTURE_BUILD = """
load("//:defs.bzl", "codex_rust_crate")

filegroup(name = "fixture-qualified")

codex_rust_crate(
    name = "fixture",
    crate_name = "fixture",
    crate_features = ["product-feature"],
    integration_test_dependency_replacements = {
        "short": {
            "//fixture": "//fixture:fixture-qualified",
            "//deps:normal": "//deps:qualified",
            "//fixture:fixture-build-script": "//deps:wrong-build-script",
        },
        "canonical": {
            "//fixture:fixture": "//fixture:fixture-qualified",
            "//deps:normal": "//deps:qualified",
        },
        "external_only": {"//deps:normal": "//deps:qualified"},
    },
)
"""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def fixture(root, defs, helper):
    write(root, "defs.bzl", defs)
    write(root, "BUILD.bazel", 'exports_files(["defs.bzl"])\n')
    modules = ["crates", "rules_rust", "platforms", "llvm"]
    write(
        root,
        "MODULE.bazel",
        'module(name = "integration_self_probe")\n'
        + "".join(
            f'bazel_dep(name = "{name}", version = "0.0.0")\n'
            f'local_path_override(module_name = "{name}", path = "repos/{name}")\n'
            for name in modules
        ),
    )
    for name in modules:
        write(
            root,
            f"repos/{name}/MODULE.bazel",
            f'module(name = "{name}", version = "0.0.0")\n',
        )
        write(root, f"repos/{name}/BUILD.bazel", "")
    write(root, "repos/rules_rust/rust/BUILD.bazel", "")
    write(root, "repos/rules_rust/rust/defs.bzl", CAPTURE_RULES)
    write(root, "repos/rules_rust/cargo/private/BUILD.bazel", "")
    write(
        root,
        "repos/rules_rust/cargo/private/cargo_build_script_wrapper.bzl",
        'def cargo_build_script(**kwargs):\n    native.filegroup(name = kwargs["name"])\n',
    )
    write(
        root,
        "repos/crates/data.bzl",
        'DEP_DATA = {"fixture": {"deps": ["//deps:normal"], "dev_deps": [], '
        '"binaries": {"probe-bin": "src/main.rs"}}}\n',
    )
    write(
        root,
        "repos/crates/defs.bzl",
        "def all_crate_deps(normal = True, normal_dev = False, cargo_only = False, build = False):\n"
        '    return [] if cargo_only or build else ["//deps:normal"]\n',
    )
    write(root, "bazel/rules/testing/BUILD.bazel", "")
    write(root, "bazel/rules/testing/rust_test_dependencies.bzl", helper)
    write(
        root,
        "bazel/rules/testing/foreign_platform_binary.bzl",
        'def foreign_platform_binary(**kwargs):\n    native.filegroup(name = kwargs["name"])\n',
    )
    write(root, "bazel/rules/testing/wine/BUILD.bazel", "")
    write(
        root,
        "bazel/rules/testing/wine/wine_runtime.bzl",
        "WINE_TEST_TARGET_COMPATIBLE_WITH = []\n"
        "def wine_test_runtime(binaries):\n    return struct(data = [], runfile_env = {})\n",
    )
    write(
        root,
        "deps/BUILD.bazel",
        'filegroup(name = "normal")\nfilegroup(name = "qualified")\n'
        'filegroup(name = "wrong-build-script")\n',
    )
    write(root, "fixture/BUILD.bazel", FIXTURE_BUILD)
    for name in ["build.rs", "src/lib.rs", "src/main.rs"]:
        write(root, f"fixture/{name}", "// No Rust compilation is performed.\n")
    for name in ["short", "canonical", "external_only", "unmapped"]:
        write(root, f"fixture/tests/{name}.rs", "// Macro-loading fixture.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bazel", type=Path, required=True)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--defs", type=Path, help="Explicit baseline for the defect negative control"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    defs_path = args.defs or args.repo_root / "defs.bzl"
    helper_path = args.repo_root / "bazel/rules/testing/rust_test_dependencies.bzl"
    defs = defs_path.read_text()
    helper = helper_path.read_text()
    workspace = output / "workspace"
    workspace.mkdir()
    fixture(workspace, defs, helper)
    labels = [
        "//fixture:fixture-short-test",
        "//fixture:fixture-canonical-test",
        "//fixture:fixture-external_only-test",
        "//fixture:fixture-unmapped-test",
        "//fixture:fixture",
        "//fixture:probe-bin",
    ]
    argv = [
        str(args.bazel.resolve()),
        "--batch",
        f"--output_user_root={output / 'bazel-output'}",
        "--nosystem_rc",
        "--nohome_rc",
        "--noworkspace_rc",
        "query",
        "--enable_bzlmod",
        "--lockfile_mode=off",
        "--noshow_progress",
        "--output=xml",
        "set(" + " ".join(labels) + ")",
    ]
    timed_out = False
    try:
        result = subprocess.run(argv, cwd=workspace, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        result = subprocess.CompletedProcess(
            argv, 124, error.stdout or b"", error.stderr or b""
        )
    (output / "query.xml").write_bytes(result.stdout)
    (output / "query.stderr").write_bytes(result.stderr)
    actual = {}
    if result.returncode == 0:
        for rule in ET.fromstring(result.stdout).findall("rule"):
            actual[rule.attrib["name"]] = {
                key: [
                    item.attrib["value"]
                    for item in rule.findall(f"list[@name='{key}']/*")
                ]
                for key in ["deps", "crate_features"]
            }
    build_script = "//fixture:fixture-build-script"
    expected = {
        labels[0]: ["//deps:qualified", build_script, "//fixture:fixture-qualified"],
        labels[1]: ["//deps:qualified", build_script, "//fixture:fixture-qualified"],
        labels[2]: ["//deps:qualified", build_script, "//fixture:fixture"],
        labels[3]: ["//deps:normal", build_script, "//fixture:fixture"],
        labels[4]: ["//deps:normal", build_script],
        labels[5]: ["//deps:normal", build_script, "//fixture:fixture"],
    }
    mismatches = [
        label
        for label, deps in expected.items()
        if sorted(actual.get(label, {}).get("deps", [])) != sorted(deps)
        or actual.get(label, {}).get("crate_features") != ["product-feature"]
    ]
    receipt = {
        "qualification": "actual Bazel macro loading only; stand-in rules; no Rust compilation",
        "defs_path": str(defs_path.resolve()),
        "defs_sha256": sha256(defs.encode()),
        "helper_path": str(helper_path.resolve()),
        "helper_sha256": sha256(helper.encode()),
        "bazel_sha256": sha256(args.bazel.read_bytes()),
        "argv": argv,
        "returncode": result.returncode,
        "timed_out": timed_out,
        "actual": actual,
        "expected_dependencies": expected,
        "mismatches": mismatches,
        "passed": result.returncode == 0 and not mismatches,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
