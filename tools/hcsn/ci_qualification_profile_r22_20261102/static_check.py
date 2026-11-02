"""Static patch checks; this does not replace Bazel analysis or a Rust build."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "defs.bzl": "3b1f8f54c975404fcfc596d5fcac15546ad703aa",
    "codex-rs/hepta-agentd/BUILD.bazel": "9492a351a24c98a5195b4aa493b4e950839231e1",
}


def calls(source, function):
    return [ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function]


def check():
    baselines, candidates = {}, {}
    for name, expected in EXPECTED.items():
        raw = (ROOT / "baseline" / name).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == expected
        baselines[name], candidates[name] = raw.decode(), (ROOT / "candidate" / name).read_text()
        ast.parse(candidates[name])  # Python-compatible syntax subset only, not Starlark evaluation.
    before, after = baselines["defs.bzl"], candidates["defs.bzl"]
    assert calls(before, "rust_binary") == calls(after, "rust_binary")
    assert calls(before, "lib_rule") == calls(after, "lib_rule")[:2]
    assert len(calls(after, "lib_rule")) == 3
    assert before.count("deps = all_crate_deps(normal = True, normal_dev = True) + maybe_deps + deps_extra,") == 3
    assert after.count("deps = integration_test_deps,") == 3
    start = after.index("    integration_test_deps = all_crate_deps(")
    end = after.index("    integration_test_binaries = sanitized_binaries", start)
    block = "\n".join(line[4:] if line.startswith("    ") else line for line in after[start:end].splitlines())
    records = []
    for library, mapped in ((True, False), (True, True), (False, True)):
        declarations, dependency_calls = [], []
        maybe = ["sample-build-script"] + (["sample"] if library else [])

        def workspace_dependencies(replacements, normal_dev=False):
            dependency_calls.append(normal_dev)
            return ["qualified-ledger"] + (["dev-only"] if normal_dev else [])

        context = dict(all_crate_deps=lambda **kw: ["ordinary-ledger", "dev-only"],
            rust_test_dependencies=workspace_dependencies,
            integration_test_dependency_replacements={"ordinary-ledger": "qualified-ledger"} if mapped else {},
            maybe_deps=maybe, deps_extra=["extra"], lib_srcs=["lib.rs"] if library else [],
            name="sample", lib_rule=lambda **kw: declarations.append(kw), crate_name="sample",
            crate_features=[], compile_data=[], lib_data_extra=[], crate_edition="2024",
            rustc_flags_extra=[], rustc_env={}, rustc_env_files=[])
        exec(compile(block, "integration-profile-static-model", "exec"), context)
        assert maybe == ["sample-build-script"] + (["sample"] if library else [])
        deps = context["integration_test_deps"]
        if not mapped:
            assert not declarations and deps == ["ordinary-ledger", "dev-only"] + maybe + ["extra"]
        elif library:
            assert len(declarations) == 1 and declarations[0]["testonly"] is True
            assert declarations[0]["visibility"] == ["//visibility:private"]
            assert "sample" not in deps and "sample-integration-test-lib" in deps
            assert "sample" not in declarations[0]["deps"] and "qualified-ledger" in declarations[0]["deps"]
            assert dependency_calls == [False, True]
        else:
            assert not declarations and "qualified-ledger" in deps and dependency_calls == [True]
        records.append(dict(library=library, mapped=mapped, integration_dependencies=deps,
                            testonly_library_declarations=len(declarations)))
    process = subprocess.run(["git", "apply", "--check", "../candidate.patch"],
        cwd=ROOT / "baseline", capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    return dict(schema="hcsn-r22-ci-profile-static-check-v1", passed=True,
        baseline_git_blobs=EXPECTED, patch_applies_to_exact_baseline=True,
        production_library_and_binary_calls_unchanged=True, integration_rule_sites_rewired=3,
        static_profile_models=records, git_apply_check=dict(exit_code=process.returncode,
            stdout=process.stdout, stderr=process.stderr),
        limitations=["AST syntax/model checks do not execute Starlark or resolve generated workspace dependencies",
                     "Bazel/buildifier/Rust tools unavailable locally; no compile, test or CI pass claim",
                     "Hosted integration test and transitive Rust crate identity verification remain required"])


if __name__ == "__main__":
    with (ROOT / "STATIC_VALIDATION.json").open("x") as stream:
        json.dump(check(), stream, indent=2)
        stream.write("\n")
