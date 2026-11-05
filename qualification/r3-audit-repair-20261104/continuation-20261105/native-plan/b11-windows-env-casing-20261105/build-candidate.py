"""Prepare a source-bound Windows environment-casing repair; never launch native work."""

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
CONTROL = ".github/scripts/run_b11_acl_identity_counterfactual.py"
HELPER = ".github/scripts/run_b11_read_acl_readiness.py"
PRE = {
    CONTROL: "e6a191a2d3c66c740aa3cb2ccd42c3e4fdb6880e",
    HELPER: "01c99717b4dfc14d86858464be4798d4351830e6",
}
OLD_COLLECTOR = "e15bfb8a75678ff7d4bab4b82b2e54e80b8b61c9"
CANONICAL = (
    "UCRTVersion", "UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsLibPath",
    "WindowsSdkBinPath", "WindowsSdkDir", "WindowsSDKLibVersion", "WindowsSDKVersion",
)
REQUIRED = ("UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsSdkDir")
FUNCTION = '''def bazel_environment(archive):
    # Native Python uppercases environment keys. Git Bash needs the original
    # MSVC spellings used by run-bazel-ci.sh; keep the actual inherited values.
    env = os.environ.copy()
    for name in ("UCRTVersion", "UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsLibPath",
                 "WindowsSdkBinPath", "WindowsSdkDir", "WindowsSDKLibVersion", "WindowsSDKVersion"):
        aliases = [key for key in env if key.casefold() == name.casefold()]
        values = {env[key] for key in aliases}
        require(len(values) <= 1, f"conflicting inherited Windows toolchain environment: {name}")
        if name in ("UniversalCRTSdkDir", "VCToolsInstallDir", "WindowsSdkDir"):
            require(len(values) == 1 and next(iter(values)),
                    f"missing required inherited Windows toolchain environment: {name}")
        if aliases:
            value = env[aliases[0]]
            for key in aliases:
                del env[key]
            env[name] = value
    env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(archive)
    return env


'''


def digest(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def replace_once(body, old, new):
    assert body.count(old) == 1, (old, body.count(old))
    return body.replace(old, new, 1)


def save(name, value):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-file", type=Path)
    parser.add_argument("--collector-blob", default=OLD_COLLECTOR)
    args = parser.parse_args()
    before = {path: (ROOT / "source" / path).read_text(encoding="utf-8") for path in PRE}
    for path, body in before.items():
        assert digest(body.encode())["git_blob"] == PRE[path]
        ast.parse(body)
    assert re.fullmatch(r"[0-9a-f]{40}", args.collector_blob)
    if args.collector_file:
        assert digest(args.collector_file.read_bytes())["git_blob"] == args.collector_blob
    else:
        assert args.collector_blob == OLD_COLLECTOR

    wrapper = (ROOT / "primary/run-bazel-ci.sh.source.txt").read_text()
    assert digest(wrapper.encode())["git_blob"] == "42b59b6354b5933c8155b992519682c06d024ca1"
    all_names = re.search(r"    windows_action_env_vars=\(\n(.*?)    \)", wrapper, re.S).group(1).split()
    required_names = re.search(r"    required_windows_action_env_vars=\(\n(.*?)    \)", wrapper, re.S).group(1).split()
    assert tuple(name for name in all_names if name.upper() != name) == CANONICAL
    assert tuple(name for name in required_names if name.upper() != name) == REQUIRED

    replacements = {
        CONTROL: [
            ("def save(directory, name, value):\n", FUNCTION + "def save(directory, name, value):\n"),
            ('            positive_env = os.environ.copy()\n            positive_env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(positive_archive)\n',
             '            positive_env = bazel_environment(positive_archive)\n'),
            ('        env = os.environ.copy()\n        env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(negative_archive)\n',
             '        env = bazel_environment(negative_archive)\n'),
        ],
        HELPER: [
            ('        env = os.environ.copy()\n        env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(archive)\n',
             '        env = control.bazel_environment(archive)\n'),
        ],
    }
    after = dict(before)
    for path, changes in replacements.items():
        for old, new in changes:
            after[path] = replace_once(after[path], old, new)
    control_blob = digest(after[CONTROL].encode())["git_blob"]
    replacements[HELPER].append((f'CONTROL_BLOB = "{PRE[CONTROL]}"', f'CONTROL_BLOB = "{control_blob}"'))
    if args.collector_blob != OLD_COLLECTOR:
        replacements[HELPER].append((f'".github/scripts/collect_bazel_failed_test_logs.py": "{OLD_COLLECTOR}"',
                                     f'".github/scripts/collect_bazel_failed_test_logs.py": "{args.collector_blob}"'))
    for old, new in replacements[HELPER][1:]:
        after[HELPER] = replace_once(after[HELPER], old, new)

    sources = []
    diff = []
    for path in PRE:
        ast.parse(after[path])
        inverse = after[path]
        for old, new in reversed(replacements[path]):
            inverse = replace_once(inverse, new, old)
        assert inverse == before[path], path
        target = ROOT / "candidate" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after[path], encoding="utf-8", newline="")
        sources.append({"path": path, "preimage": digest(before[path].encode()), "postimage": digest(after[path].encode()),
                        "preimage_file": str((ROOT / "source" / path).resolve()), "postimage_file": str(target.resolve())})
        diff.extend(difflib.unified_diff(before[path].splitlines(True), after[path].splitlines(True),
                                        fromfile="a/" + path, tofile="b/" + path))
    (ROOT / "full.patch").write_text("".join(diff), encoding="utf-8", newline="")
    save("source-map.json", sources)
    save("static-verification.json", {
        "schema": "b11-windows-environment-key-casing-static-v1",
        "actual_source_preimages": PRE,
        "canonical_names_equal_all_mixed_case_wrapper_forwarding_names": list(CANONICAL),
        "required_names_equal_all_mixed_case_wrapper_required_names": list(REQUIRED),
        "uppercase_required_names_unchanged": [name for name in required_names if name.upper() == name],
        "all_three_subprocess_environment_construction_sites_share_one_helper": True,
        "AST_parses": True,
        "inverse_exact_edit_restores_both_complete_preimages": True,
        "all_other_bytes_including_arguments_guards_constants_finally_unchanged": True,
        "new_CONTROL_BLOB_equals_actual_control_postimage": control_blob,
        "collector_pin": {"old": OLD_COLLECTOR, "new": args.collector_blob,
                          "source_file": str(args.collector_file.resolve()) if args.collector_file else None,
                          "merge_acceptance": "Parent must bind this pin to actual HEAD worktree and git show HEAD:path; head-only versus merge differences cannot be waived."},
        "workflow_Rust_dependencies_locks_targets_no_change": True,
        "no_native_execution_no_source_ref_mutation": True,
        "windows_mechanism_qualification": "PENDING_NEXT_NATIVE; original native9 establishes only pre-Bazel environment guard failure",
        "sources": sources,
        "patch": digest((ROOT / "full.patch").read_bytes()),
    })
    print(json.dumps({"files": len(sources), "control_postimage": control_blob, "collector_pin": args.collector_blob,
                      "source_map": str((ROOT / "source-map.json").resolve())}))


if __name__ == "__main__":
    main()
