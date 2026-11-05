"""Verify the actual failure mechanism against frozen primary code, without Windows/Bazel."""

import ast
from collections.abc import Mapping, MutableMapping
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types


ROOT = Path(__file__).resolve().parent
NATIVE = ROOT.parent / "b11-pr4884-ci-20261105/terminal/probe-127567774212"
CONTROL = ".github/scripts/run_b11_acl_identity_counterfactual.py"
CANONICAL = ("UCRTVersion", "UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsLibPath",
             "WindowsSdkBinPath", "WindowsSdkDir", "WindowsSDKLibVersion", "WindowsSDKVersion")
REQUIRED = ("UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsSdkDir")


def digest(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    wrapper = (ROOT / "primary/run-bazel-ci.sh.source.txt").read_text()
    primary = (ROOT / "primary/cpython-v3.12.10-Lib-os.py.source.txt").read_text()
    control = (ROOT / "candidate" / CONTROL).read_text()
    primary_ast = ast.parse(primary)
    primary_nodes = [node for node in primary_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                     and node.name in {"_Environ", "_createenviron"}]
    assert len(primary_nodes) == 2
    primary_module = ast.Module(body=primary_nodes, type_ignores=[])
    compiled_primary = compile(primary_module, "actual-cpython-v3.12.10-Lib-os.py", "exec")
    helper, = [node for node in ast.parse(control).body if isinstance(node, ast.FunctionDef) and node.name == "bazel_environment"]
    compiled_helper = compile(ast.Module(body=[helper], type_ignores=[]), "candidate-bazel-environment", "exec")

    # Extract the actual recorded toolchain values from the failed counterfactual
    # step only. No values are invented or put into the production candidate.
    lines = (NATIVE / "job.log").read_text().splitlines()
    start, = [i for i, line in enumerate(lines) if "python3 .github/scripts/run_b11_acl_identity_counterfactual.py" in line]
    end = next(i for i in range(start + 1, len(lines)) if "##[endgroup]" in lines[i])
    all_names = re.search(r"    windows_action_env_vars=\(\n(.*?)    \)", wrapper, re.S).group(1).split()
    inherited = {}
    evidence_lines = []
    for i in range(start, end):
        match = re.search(r"Z   ([A-Za-z_][A-Za-z_0-9]*): (.*)$", lines[i])
        if match and match[1] in all_names:
            assert match[1] not in inherited
            inherited[match[1]] = match[2]
            evidence_lines.append({"line": i + 1, "name": match[1], "value_sha256": hashlib.sha256(match[2].encode()).hexdigest()})
    assert set(inherited) == set(all_names) and all(inherited.values())
    inherited["UNRELATED_PRESERVATION_MARKER"] = "unchanged-test-marker"

    def native_mapping(seed):
        namespace = {"name": "nt", "environ": seed.copy(), "MutableMapping": MutableMapping, "Mapping": Mapping}
        exec(compiled_primary, namespace)
        return namespace["_createenviron"]()

    def candidate(mapping):
        namespace = {"os": types.SimpleNamespace(environ=mapping), "require": require}
        exec(compiled_helper, namespace)
        return namespace["bazel_environment"](Path("owned-evidence-archive"))

    env = native_mapping(inherited)
    before = env.copy()
    assert all(name not in before and before[name.upper()] == inherited[name] for name in CANONICAL)
    after = candidate(env)
    assert env.copy() == before
    assert all(after[name] == inherited[name] and name.upper() not in after for name in CANONICAL)
    assert all(after[name] == value for name, value in before.items() if name not in {key.upper() for key in CANONICAL})
    assert set(after) == (set(before) - {name.upper() for name in CANONICAL}) | set(CANONICAL) | {"CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"}

    guard_source = wrapper.split("    windows_action_env_vars=(\n", 1)[1].split('  fi\n\n  if [[ -z "${CODEX_BAZEL_WINDOWS_PATH:-}" ]]', 1)[0]
    guard_source = 'set -euo pipefail\npost_config_bazel_args=()\n    windows_action_env_vars=(\n' + guard_source + 'declare -p post_config_bazel_args\n'
    bash = shutil.which("bash")
    assert bash
    old_guard = subprocess.run([bash, "--noprofile", "--norc", "-c", guard_source], env=before, capture_output=True, check=False)
    new_guard = subprocess.run([bash, "--noprofile", "--norc", "-c", guard_source], env=after, capture_output=True, check=False)
    observed = (NATIVE / "members/b11-token-mechanism-probe/acl-identity-counterfactual/positive-01/console.log").read_bytes()
    assert old_guard.returncode == 1 and old_guard.stderr == observed and not old_guard.stdout
    assert new_guard.returncode == 0 and not new_guard.stderr
    for name in all_names:
        assert f'--action_env={name}'.encode() in new_guard.stdout and f'--host_action_env={name}'.encode() in new_guard.stdout

    omissions = {key: value for key, value in inherited.items() if key not in set(CANONICAL) - set(REQUIRED)}
    optional_absent = candidate(native_mapping(omissions))
    assert all(name not in optional_absent and name.upper() not in optional_absent for name in set(CANONICAL) - set(REQUIRED))
    negatives = []
    for name in REQUIRED:
        for mode in ("missing", "empty"):
            seed = inherited.copy()
            if mode == "missing":
                del seed[name]
            else:
                seed[name] = ""
            try:
                candidate(native_mapping(seed))
            except RuntimeError as error:
                assert str(error) == f"missing required inherited Windows toolchain environment: {name}"
                negatives.append({"name": name, "mode": mode, "rejected": True})
            else:
                raise AssertionError((name, mode))
    collision = before.copy()
    collision[REQUIRED[0]] = before[REQUIRED[0].upper()] + "different"
    try:
        candidate(collision)
    except RuntimeError as error:
        assert str(error) == f"conflicting inherited Windows toolchain environment: {REQUIRED[0]}"
    else:
        raise AssertionError("conflicting aliases were accepted")
    equal_alias = before.copy()
    equal_alias[REQUIRED[0]] = before[REQUIRED[0].upper()]
    assert candidate(equal_alias) == after

    sources = json.loads((ROOT / "source-map.json").read_text())
    commands = []
    with tempfile.TemporaryDirectory(prefix="b11-env-roundtrip-") as temporary:
        work = Path(temporary)
        for row in sources:
            target = work / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(row["preimage_file"]).read_bytes())
        for argv in (["git", "init", "-q"], ["git", "apply", "--check", str(ROOT / "full.patch")],
                     ["git", "apply", str(ROOT / "full.patch")]):
            result = subprocess.run(argv, cwd=work, capture_output=True, check=False)
            assert result.returncode == 0, result.stderr
            commands.append({"argv": argv, "exit_code": result.returncode})
        assert all((work / row["path"]).read_bytes() == Path(row["postimage_file"]).read_bytes() for row in sources)
        for argv in (["git", "apply", "--reverse", "--check", str(ROOT / "full.patch")],
                     ["git", "apply", "--reverse", str(ROOT / "full.patch")]):
            result = subprocess.run(argv, cwd=work, capture_output=True, check=False)
            assert result.returncode == 0, result.stderr
            commands.append({"argv": argv, "exit_code": result.returncode})
        assert all((work / row["path"]).read_bytes() == Path(row["preimage_file"]).read_bytes() for row in sources)

    report = {
        "schema": "b11-env-casing-cloud-mechanism-and-roundtrip-v1",
        "status": "CLOUD_MECHANISM_STATIC_ACCEPT_WINDOWS_PENDING",
        "native_run": {"run_id": 42119482548, "job_id": 127567774212, "head": "855733b0f88c82c68135b1879682358a818daa84"},
        "original_job": digest((NATIVE / "job.log").read_bytes()),
        "actual_counterfactual_step_recorded_toolchain_keys": evidence_lines,
        "interpreter_version": {"actual_resolved_executable_and_sys_version": "NOT_RECORDED",
                                "recorded_PATH_contains": "C:\\hostedtoolcache\\windows\\Python\\3.12.10\\x64",
                                "primary_code_used": "CPython tagged v3.12.10; not a claim that actual child version was independently measured"},
        "primary_sources": [{"url": "https://github.com/python/cpython/blob/v3.12.10/Lib/os.py", **digest(primary.encode())},
                            {"url": "https://github.com/python/cpython/blob/v3.12.10/Modules/_winapi.c", **digest((ROOT / "primary/cpython-v3.12.10-Modules-_winapi.c.source.txt").read_bytes())},
                            {"url": "https://docs.python.org/3.12/library/os.html#os.environ", "fact": "Windows environment mapping normalizes keys to uppercase"}],
        "mechanism": "Actual CPython v3.12.10 _Environ/_createenviron definitions executed with the 12 original step SDK values; copy uppercases eight names. Original unchanged Bash guard exactly reproduces native106B failure with old mapping; corrected mapping passes that same extracted guard and forwards all12 action/host names.",
        "old_extracted_guard": {"exit_code": old_guard.returncode, "stdout": old_guard.stdout.decode(), "stderr": old_guard.stderr.decode(), "equals_original_native_console_bytes": True},
        "corrected_extracted_guard": {"exit_code": new_guard.returncode, "stdout": new_guard.stdout.decode(), "stderr": new_guard.stderr.decode()},
        "all_existing_values_preserved": True, "inherited_mapping_not_mutated": True,
        "optional_absent_names_not_created": True, "required_negative_controls": negatives,
        "conflicting_aliases_rejected": True, "equal_aliases_collapse_without_value_change": True,
        "alias_limit": "Only aliases present in the copied mapping can be checked; earlier OS/Python normalization has already collapsed any pre-import duplicates.",
        "git_patch_commands": commands, "complete_apply_postimage_and_reverse_preimage_bytes_equal": True,
        "scope_limits": ["Cloud Bash tests only the frozen guard fragment; no project targets, Bazel, Rust or Windows process ran.",
                         "Actual Windows subprocess behavior and all four positives, one negative, exact restore and helper target still require the original native workflow.",
                         "No B11 closure; all source assertions, retries, target rosters, budgets and source custody guards remain unchanged."],
        "sources": sources,
    }
    output = ROOT / "cloud-verification.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "cloud_guard_old_exit": old_guard.returncode,
                      "cloud_guard_corrected_exit": new_guard.returncode, "required_negative_controls": len(negatives),
                      "git_commands": len(commands), "report": str(output), **digest(output.read_bytes())}))


if __name__ == "__main__":
    main()
