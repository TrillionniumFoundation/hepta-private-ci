#!/usr/bin/env python3
"""Build the precise Bazel9 Windows output-drain backport in an isolated directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DESTINATION = ROOT / "bazel-windows-test-tools"


def digest(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = {"kind": "symlink", "target": os.readlink(path)}
        elif path.is_file():
            result[name] = {"kind": "file", **digest(path)}
        elif path.is_dir():
            result[name] = {"kind": "directory"}
        else:
            raise RuntimeError("unsupported embedded-tools entry: " + name)
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_gtest(path, manifest):
    tree = ET.parse(path)
    root = tree.getroot()
    require(root.tag == "testsuites", "missing complete GTest report")
    expected = set(manifest["original_gtest_cases"] + manifest["additional_upstream_cases"])
    require(len(expected) == manifest["required_gtest_count"] == 20, "incorrect fixed GTest denominator")
    require(root.get("tests") == "20", "not all original and upstream-added tests ran")
    nodes = list(root.iter("testcase"))
    actual = [node.get("classname", "") + "." + node.get("name", "") for node in nodes]
    require(len(nodes) == 20 and len(set(actual)) == 20 and set(actual) == expected,
            "GTest case identities changed or are incomplete")
    for suite in [root, *root.iter("testsuite")]:
        require(all(int(suite.get(key, "0")) == 0 for key in ("failures", "errors", "disabled", "skipped")),
                "GTest failure, disabled or skipped case")
    require(not list(root.iter("failure")) and not list(root.iter("error")) and not list(root.iter("skipped")),
            "GTest failure/error/skip element")
    require(all(node.get("status") == "run" and node.get("result") == "completed" for node in nodes),
            "GTest case did not complete")
    return {"count": 20, "original": 18, "additional_upstream": 2, "failures": 0, "skipped": 0,
            "cases": actual, "xml": digest(path)}


def save(work, receipt):
    outputs = work / "evidence"
    outputs.mkdir(exist_ok=True)
    receipt["evidence_outputs"] = {
        path.relative_to(outputs).as_posix(): digest(path)
        for path in sorted(outputs.rglob("*"))
        if path.is_file() and path.name != "receipt.json"
    }
    write_json(outputs / "receipt.json", receipt)


def prepare(work):
    require(platform.system() == "Windows" and platform.machine().lower() in ("amd64", "x86_64"),
            "requires the original native Windows x64 host")
    require(not work.exists() and not DESTINATION.exists(), "work or override destination already exists")
    work.mkdir(parents=True)
    outputs = work / "evidence"
    outputs.mkdir()
    manifest = json.loads((HERE / "source-binding.json").read_text(encoding="utf-8"))
    patch = HERE / "bazel9-windows-tee-drain.patch"
    receipt = {"schema": 1, "status": "failed", "steps": [], "native_host": platform.platform(),
               "upstream_base": manifest["upstream_base_commit"], "fix_commit": manifest["fix_commit"],
               "destination": str(DESTINATION), "work": str(work), "gtest": None}
    public_env = {key: value for key, value in os.environ.items()
                  if key not in ("BUILDBUDDY_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")}
    builder_env = {**public_env, "USE_BAZEL_VERSION": manifest["upstream_builder_version"]}
    product_env = {**public_env, "USE_BAZEL_VERSION": manifest["bazel_version"]}

    def run(name, command, cwd, env=public_env):
        started = time.monotonic()
        stdout_path, stderr_path = outputs / (name + ".stdout"), outputs / (name + ".stderr")
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
        receipt["steps"].append({"name": name, "command": [str(item) for item in command],
                                 "cwd": str(cwd), "exit": result.returncode,
                                 "elapsed_seconds": time.monotonic() - started})
        if result.returncode:
            for path in (stdout_path, stderr_path):
                print(path.read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)
            raise RuntimeError(name + " failed with exit " + str(result.returncode))
        return stdout_path.read_text(encoding="utf-8").strip()

    try:
        receipt["product_commit"] = run("product-identity", ["git", "rev-parse", "HEAD"], ROOT)
        run("product-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"], ROOT)
        require((ROOT / ".bazelversion").read_text().strip() == "9.0.0",
                "product Bazel version changed")
        require(digest(patch)["sha256"] == manifest["patch_sha256"], "backport patch identity mismatch")
        receipt["qualification_inputs"] = {
            path.relative_to(ROOT).as_posix(): digest(path)
            for path in sorted(HERE.iterdir()) if path.is_file()
        }
        receipt["qualification_inputs"][".bazelrc"] = digest(ROOT / ".bazelrc")
        source = work / "source"
        run("upstream-init", ["git", "init", str(source)], work)
        run("upstream-line-endings", ["git", "config", "core.autocrlf", "false"], source)
        run("upstream-remote", ["git", "remote", "add", "origin", manifest["upstream_repository"]], source)
        run("upstream-fetch", ["git", "fetch", "--depth=1", "--no-tags", "origin",
                               manifest["upstream_base_commit"]], source)
        run("upstream-checkout", ["git", "checkout", "--detach", "FETCH_HEAD"], source)
        require(run("upstream-identity", ["git", "rev-parse", "HEAD"], source) ==
                manifest["upstream_base_commit"], "upstream checkout identity mismatch")
        receipt["upstream_tree"] = run("upstream-tree", ["git", "rev-parse", "HEAD^{tree}"], source)
        run("upstream-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"], source)
        require((source / ".bazelversion").read_text().strip() == manifest["upstream_builder_version"],
                "official upstream builder version changed")
        for name, identity in manifest["files"].items():
            require(digest(source / name) == {"bytes": identity["original_bytes"],
                                             "sha256": identity["original_sha256"]},
                    "original upstream bytes mismatch: " + name)
        run("upstream-patch-check", ["git", "apply", "--check", str(patch)], source)
        run("upstream-patch", ["git", "apply", str(patch)], source)
        for name, identity in manifest["files"].items():
            require(digest(source / name) == {"bytes": identity["patched_bytes"],
                                             "sha256": identity["patched_sha256"]},
                    "patched upstream bytes mismatch: " + name)
            shutil.copyfile(source / name, outputs / Path(name).name)
        run("upstream-exact-diff", ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"], source)
        changed = run("upstream-changed-paths", ["git", "diff", "--name-only", "HEAD", "--"], source)
        require(set(changed.splitlines()) == set(manifest["files"]), "unrelated upstream files changed")
        bazel = shutil.which("bazel")
        require(bazel is not None, "Bazelisk executable missing")
        builder = [bazel, "--nosystem_rc", "--nohome_rc",
                   "--output_base=" + str(work / "b"), "--output_user_root=" + str(work / "u")]
        version = run("builder-version", [*builder, "--version"], source, builder_env)
        require(version == "bazel " + manifest["upstream_builder_version"], "builder version mismatch")
        run("build-original-tw-target", [*builder, "build", "--lockfile_mode=error",
                                         "//tools/test:tw"], source, builder_env)
        report = outputs / "tw-gtest.xml"
        run("test-complete-original-tw-target", [*builder, "test", "--lockfile_mode=error",
             "--nocache_test_results", "--test_output=all", "--flaky_test_attempts=1",
             "--test_env=GTEST_OUTPUT=xml:" + str(report), "//tools/test:tw_test"], source, builder_env)
        receipt["gtest"] = validate_gtest(report, manifest)
        bin_path = Path(run("upstream-bazel-bin", [*builder, "info", "bazel-bin"], source, builder_env))
        binary = bin_path / "tools" / "test" / "tw.exe"
        pe = binary.read_bytes()
        require(len(pe) > 64 and pe[:2] == b"MZ", "built wrapper is not a PE executable")
        pe_offset = struct.unpack_from("<I", pe, 60)[0]
        require(pe_offset + 6 <= len(pe) and pe[pe_offset:pe_offset + 4] == b"PE\0\0" and
                struct.unpack_from("<H", pe, pe_offset + 4)[0] == 0x8664,
                "built wrapper is not native Windows x64")
        shutil.copyfile(binary, outputs / "tw.exe")
        receipt["built_wrapper"] = digest(binary)
        changed = run("upstream-changed-paths-after", ["git", "diff", "--name-only", "HEAD", "--"], source)
        require(set(changed.splitlines()) == set(manifest["files"]), "build changed upstream tracked inputs")
        for name, identity in manifest["files"].items():
            require(digest(source / name)["sha256"] == identity["patched_sha256"],
                    "build changed patched source")
        product_version = run("product-bazel-version", [bazel, "--version"], ROOT, product_env)
        require(product_version == "bazel 9.0.0", "product Bazel executable changed")
        installed = Path(run("product-install-base", [bazel, "info", "install_base"], ROOT, product_env))
        embedded = installed / "embedded_tools"
        require(embedded.is_dir() and (embedded / "tools/test/tw.exe").is_file(),
                "original embedded Bazel tools not found")
        before = inventory(embedded)
        write_json(outputs / "installed-tools-before.json", before)
        shutil.copytree(embedded, DESTINATION, symlinks=True, copy_function=shutil.copyfile)
        require(inventory(DESTINATION) == before, "embedded-tools copy is incomplete")
        shutil.copyfile(binary, DESTINATION / "tools/test/tw.exe")
        after = inventory(DESTINATION)
        require(set(before) == set(after), "override changes the original embedded-tools entries")
        differences = [name for name in before if before[name] != after[name]]
        require(differences == ["tools/test/tw.exe"], "override changes more than the native test wrapper")
        require(after["tools/test/tw.exe"]["sha256"] == receipt["built_wrapper"]["sha256"],
                "override wrapper differs from qualified binary")
        require(inventory(embedded) == before, "original installed Bazel tools were modified")
        write_json(outputs / "override-tools.json", after)
        receipt["installed_tools"] = str(embedded)
        receipt["only_changed_tool"] = differences[0]
        receipt["embedded_entry_count"] = len(before)
        run("product-clean-after-prepare", ["git", "diff", "--exit-code", "HEAD", "--"], ROOT)
        receipt["status"] = "prepared"
    finally:
        save(work, receipt)
        print("BAZEL_TEE_BACKPORT " + json.dumps({key: receipt.get(key) for key in
              ("status", "product_commit", "upstream_base", "fix_commit", "gtest",
               "built_wrapper", "only_changed_tool")}), flush=True)


def finalize(work, robrix):
    outputs = work / "evidence"
    receipt = json.loads((outputs / "receipt.json").read_text(encoding="utf-8"))
    prepared = receipt["status"] == "prepared"
    receipt["status"] = "failed"
    try:
        require(prepared, "tool preparation did not pass")
        before = json.loads((outputs / "installed-tools-before.json").read_text(encoding="utf-8"))
        override = json.loads((outputs / "override-tools.json").read_text(encoding="utf-8"))
        require(inventory(Path(receipt["installed_tools"])) == before,
                "original installed tools changed during product qualification")
        require(inventory(DESTINATION) == override, "override tools changed during product qualification")
        result = json.loads((robrix / "receipt.json").read_text(encoding="utf-8"))
        require(result["commit"] == receipt["product_commit"] and result["status"] == "passed" and
                result["test_counts"] == [2, 0, 0, 0, 0] and result["source_inputs_unchanged"],
                "complete original two-case Robrix target and Clippy did not pass")
        require(subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT).returncode == 0,
                "product checkout changed")
        for name, expected in receipt["qualification_inputs"].items():
            require(digest(ROOT / name) == expected, "qualification input changed: " + name)
        receipt["robrix_receipt"] = digest(robrix / "receipt.json")
        receipt["original_installed_tools_unchanged"] = True
        receipt["qualified_override_unchanged"] = True
        receipt["status"] = "passed"
    finally:
        save(work, receipt)
        print("BAZEL_TEE_BACKPORT_FINAL " + json.dumps(
            {key: receipt.get(key) for key in ("status", "product_commit",
             "original_installed_tools_unchanged", "qualified_override_unchanged",
             "robrix_receipt")}), flush=True)


def main():
    if not __debug__:
        raise SystemExit("optimized Python execution is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--robrix", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if args.finalize:
        require(args.robrix is not None, "--robrix is required for finalization")
        finalize(work, args.robrix.resolve())
    else:
        prepare(work)


if __name__ == "__main__":
    main()
