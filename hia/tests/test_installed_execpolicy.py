#!/usr/bin/env python3
"""Exercise relocated native/default executables through execpolicy's real CLI.

Require the statically linked HIA owners, then evaluate real rule files
with both binaries from a different working directory. Complete JSON objects,
raw stdout/stderr and exit statuses must agree; explicit expected decisions and
rule lists keep a shared wrong result from passing. No commands in the rules
are executed. This gate does not qualify an interactive agent or other targets.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from test_installed_patch import inspect_binary, sha256


ROOT = Path(__file__).resolve().parents[2]
NATIVE_SYMBOLS = ("codex_hia_prefix_match", "codex_hia_prefix_admission", "codex_hia_policy_summary", "codex_hia_command_dispatch", "codex_hia_network_host")


def rule(prefix, decision, *, resolved=None, justification=None):
    value = {"matchedPrefix": prefix, "decision": decision}
    if resolved is not None:
        value["resolvedProgram"] = resolved
    if justification is not None:
        value["justification"] = justification
    return {"prefixRuleMatch": value}


def expected(decision, *rules):
    value = {"matchedRules": list(rules)}
    if decision is not None:
        value["decision"] = decision
    return value


def fixtures_and_cases():
    fixtures = {
        "basic": 'prefix_rule(pattern=["git", "status"])\n',
        "strict": (
            'prefix_rule(pattern=["git"], decision="allow", justification="general command")\n'
            'prefix_rule(pattern=["git", "commit"], decision="prompt", justification="review change")\n'
            'prefix_rule(pattern=["git", "commit", "--amend"], decision="forbidden", justification="protect history")\n'
        ),
        "first": 'prefix_rule(pattern=["git"], decision="prompt")\n',
        "second": 'prefix_rule(pattern=["git", "commit"], decision="forbidden")\n',
        "aliases": 'prefix_rule(pattern=[["bash", "sh"], ["-c", "-l"]])\n',
        "tail": 'prefix_rule(pattern=["npm", ["i", "install"], ["--legacy-peer-deps", "--no-save"]])\n',
        "duplicates": 'prefix_rule(pattern=["git", "status"])\n' * 2,
        "unicode": 'prefix_rule(pattern=["工具", ["é", "é"], ""], decision="prompt", justification="检查工具")\n',
        "exact_unicode": 'prefix_rule(pattern=["é"])\n',
        "empty": "",
        "host": (
            'prefix_rule(pattern=["git", "status"], decision="prompt")\n'
            'host_executable(name="git", paths=["/usr/bin/git"])\n'
        ),
        "host_empty": (
            'prefix_rule(pattern=["git"], decision="prompt")\n'
            'host_executable(name="git", paths=[])\n'
        ),
        "host_fallback": 'prefix_rule(pattern=["git"], decision="prompt")\n',
        "host_exact": (
            'prefix_rule(pattern=["/usr/bin/git"], decision="allow")\n'
            'prefix_rule(pattern=["git"], decision="forbidden")\n'
            'host_executable(name="git", paths=["/usr/bin/git"])\n'
        ),
        "examples": (
            'prefix_rule(pattern=["git", "status"], match=[["git", "status"], "git status"], '
            'not_match=[["git", "commit"], "git --config color.status=always status"])\n'
        ),
        "invalid_pattern": 'prefix_rule(pattern=[])\n',
        "invalid_alternatives": 'prefix_rule(pattern=["git", []])\n',
        "invalid_decision": 'prefix_rule(pattern=["git"], decision="deny")\n',
        "invalid_justification": 'prefix_rule(pattern=["git"], justification="   ")\n',
        "invalid_example": 'prefix_rule(pattern=["git", "status"], match=["git commit"])\n',
        "invalid_negative_example": 'prefix_rule(pattern=["git"], not_match=["git status"])\n',
    }
    allow_git = rule(["git"], "allow", justification="general command")
    prompt_commit = rule(["git", "commit"], "prompt", justification="review change")
    forbid_amend = rule(["git", "commit", "--amend"], "forbidden", justification="protect history")
    cases = [
        {"name": "basic_allow", "rules": ["basic"], "command": ["git", "status", "--short"],
         "expected": expected("allow", rule(["git", "status"], "allow"))},
        {"name": "short_command", "rules": ["basic"], "command": ["git"], "expected": expected(None)},
        {"name": "token_not_string_prefix", "rules": ["basic"], "command": ["git", "statuses"], "expected": expected(None)},
        {"name": "case_sensitive_program", "rules": ["basic"], "command": ["Git", "status"], "expected": expected(None)},
        {"name": "strictest_allow", "rules": ["strict"], "command": ["git", "status"],
         "expected": expected("allow", allow_git)},
        {"name": "strictest_prompt", "rules": ["strict"], "command": ["git", "commit", "-m", "message"],
         "expected": expected("prompt", allow_git, prompt_commit)},
        {"name": "strictest_forbidden", "rules": ["strict"], "command": ["git", "commit", "--amend", "--no-edit"],
         "expected": expected("forbidden", allow_git, prompt_commit, forbid_amend)},
        {"name": "multiple_files", "rules": ["first", "second"], "command": ["git", "commit", "-m", "message"],
         "expected": expected("forbidden", rule(["git"], "prompt"), rule(["git", "commit"], "forbidden"))},
        {"name": "multiple_files_reversed", "rules": ["second", "first"], "command": ["git", "commit"],
         "expected": expected("forbidden", rule(["git", "commit"], "forbidden"), rule(["git"], "prompt"))},
        {"name": "first_alias", "rules": ["aliases"], "command": ["sh", "-l", "ignored"],
         "expected": expected("allow", rule(["sh", "-l"], "allow"))},
        {"name": "tail_alternatives", "rules": ["tail"], "command": ["npm", "install", "--no-save", "package"],
         "expected": expected("allow", rule(["npm", "install", "--no-save"], "allow"))},
        {"name": "tail_alternatives_mismatch", "rules": ["tail"], "command": ["npm", "install", "--no-save-extra"],
         "expected": expected(None)},
        {"name": "duplicate_rules_preserved", "rules": ["duplicates"], "command": ["git", "status"],
         "expected": expected("allow", rule(["git", "status"], "allow"), rule(["git", "status"], "allow"))},
        {"name": "unicode_empty_token", "rules": ["unicode"], "command": ["工具", "é", "", "尾部"],
         "expected": expected("prompt", rule(["工具", "é", ""], "prompt", justification="检查工具"))},
        {"name": "unicode_second_alternative", "rules": ["unicode"], "command": ["工具", "é", ""],
         "pretty": True, "expected": expected("prompt", rule(["工具", "é", ""], "prompt", justification="检查工具"))},
        {"name": "no_unicode_normalization", "rules": ["exact_unicode"], "command": ["é"], "expected": expected(None)},
        {"name": "empty_policy", "rules": ["empty"], "command": ["anything"], "expected": expected(None)},
        {"name": "host_resolution_disabled", "rules": ["host"], "command": ["/usr/bin/git", "status"],
         "expected": expected(None)},
        {"name": "allowed_host_basename", "rules": ["host"], "command": ["/usr/bin/git", "status"], "resolve": True,
         "expected": expected("prompt", rule(["git", "status"], "prompt", resolved="/usr/bin/git"))},
        {"name": "unlisted_host_path", "rules": ["host"], "command": ["/opt/codex-hia-test/bin/git", "status"],
         "resolve": True, "expected": expected(None)},
        {"name": "empty_host_allowlist", "rules": ["host_empty"], "command": ["/usr/bin/git", "status"],
         "resolve": True, "expected": expected(None)},
        {"name": "host_without_mapping", "rules": ["host_fallback"], "command": ["/usr/bin/git", "status"], "resolve": True,
         "expected": expected("prompt", rule(["git"], "prompt", resolved="/usr/bin/git"))},
        {"name": "exact_host_precedes_basename", "rules": ["host_exact"], "command": ["/usr/bin/git", "status"], "resolve": True,
         "expected": expected("allow", rule(["/usr/bin/git"], "allow"))},
        {"name": "original_example_validation", "rules": ["examples"], "command": ["git", "status"],
         "expected": expected("allow", rule(["git", "status"], "allow"))},
    ]
    for name, fragment in [
        ("invalid_pattern", "pattern cannot be empty"),
        ("invalid_alternatives", "pattern alternatives cannot be empty"),
        ("invalid_decision", "invalid decision: deny"),
        ("invalid_justification", "justification cannot be empty"),
        ("invalid_example", "expected every example to match at least one rule"),
        ("invalid_negative_example", "expected example to not match rule"),
    ]:
        cases.append({"name": name, "rules": [name], "command": ["git", "status"], "error_contains": fragment})
    fixtures["network_valid"] = (
        'network_rule(host="  API.Example.COM.:443  ", protocol="https", decision="allow")\n'
        'network_rule(host="[NOT:IP]:999999", protocol="socks5_tcp", decision="deny")\n'
        'network_rule(host="é.EXAMPLE", protocol="http", decision="prompt")\n'
        'prefix_rule(pattern=["git", "status"])\n'
    )
    fixtures["network_dot_space"] = (
        'network_rule(host="[ . ]", protocol="https", decision="allow")\n'
        'network_rule(host=":80", protocol="http", decision="allow")\n'
        'network_rule(host="host:abc", protocol="socks5_udp", decision="deny")\n'
    )
    cases += [
        {"name": "network_normalization_acceptance", "rules": ["network_valid"], "command": ["git", "status"],
         "expected": expected("allow", rule(["git", "status"], "allow"))},
        {"name": "network_original_dot_trim_and_port_acceptance", "rules": ["network_dot_space"], "command": ["git"],
         "expected": expected(None)},
    ]
    for name, host, fragment in [
        ("network_empty", " \t ", "network_rule host cannot be empty"),
        ("network_scheme_before_bracket", "https://[a", "network_rule host must be a hostname or IP literal (without scheme or path)"),
        ("network_bracket", "[abc", "network_rule host has an invalid bracketed IPv6 literal"),
        ("network_suffix_original_raw", "  [abc]x  ", "network_rule host contains an unsupported suffix:   [abc]x  "),
        ("network_normalized_empty", "...", "network_rule host cannot be empty"),
        ("network_wildcard_before_whitespace", "[a *]", "network_rule host must be a specific host; wildcards are not allowed"),
        ("network_internal_whitespace", "a\u2003b", "network_rule host cannot contain whitespace"),
    ]:
        fixtures[name] = f'network_rule(host={json.dumps(host, ensure_ascii=False)}, protocol="https", decision="allow")\n'
        cases.append({"name": name, "rules": [name], "command": ["git"], "error_contains": fragment})
    return fixtures, cases


def run_cases(binary, reference, work, environment, report, *, dispatch="standalone"):
    if dispatch not in ("standalone", "codex"):
        raise RuntimeError(f"unsupported execpolicy dispatch: {dispatch}")
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    rule_directory = work / "rules"
    rule_directory.mkdir()
    invocation_directory = work / "elsewhere"
    invocation_directory.mkdir()
    fixtures, cases = fixtures_and_cases()
    paths = {}
    fixture_hashes = {}
    for name, contents in fixtures.items():
        path = rule_directory / f"{name}.rules"
        path.write_text(contents, encoding="utf-8")
        paths[name] = path
        fixture_hashes[name] = sha256(path)
    report.setdefault("execpolicy_fixtures", []).append({
        "dispatch": dispatch, "files": {
            name: {"path": str(paths[name]), "sha256": fixture_hashes[name], "contents": contents}
            for name, contents in fixtures.items()
        },
    })
    prefix = ["check"] if dispatch == "standalone" else ["execpolicy", "check"]
    for spec in cases:
        arguments = prefix.copy()
        for name in spec["rules"]:
            arguments += ["--rules", str(paths[name])]
        if spec.get("pretty"):
            arguments.append("--pretty")
        if spec.get("resolve"):
            arguments.append("--resolve-host-executables")
        arguments += ["--", *spec["command"]]
        case = {"name": f"execpolicy_{spec['name']}", "dispatch": dispatch,
                "cwd": str(invocation_directory), "passed": False, "specification": spec, "processes": []}
        report.setdefault("cases", []).append(case)
        outputs = []
        for variant, executable in (("native", binary), ("reference", reference)):
            command = [str(executable), *arguments]
            started = time.monotonic()
            result = subprocess.run(command, capture_output=True, cwd=invocation_directory, env=environment, timeout=60)
            observed = {"variant": variant, "command": command, "returncode": result.returncode,
                        "elapsed_seconds": round(time.monotonic() - started, 6)}
            for stream in ("stdout", "stderr"):
                data = getattr(result, stream)
                observed[stream] = data.decode("utf-8", errors="replace")
                observed[f"{stream}_base64"] = base64.b64encode(data).decode("ascii")
                observed[f"{stream}_bytes"] = len(data)
                observed[f"{stream}_sha256"] = hashlib.sha256(data).hexdigest()
            case["processes"].append(observed)
            outputs.append((result.returncode, result.stdout, result.stderr))
        case["raw_process_results_equal"] = outputs[0] == outputs[1]
        if not case["raw_process_results_equal"]:
            raise RuntimeError(f"native/default CLI bytes or exit status differ: {case['name']}")
        status, stdout, stderr = outputs[0]
        if "error_contains" in spec:
            if status != 1 or stdout or spec["error_contains"].encode() not in stderr:
                raise RuntimeError(f"CLI did not preserve the expected rule error: {case['name']}")
        else:
            if status != 0:
                raise RuntimeError(f"CLI rejected a valid policy invocation: {case['name']}")
            actual = json.loads(stdout)
            case["actual_json"] = actual
            if actual != spec["expected"]:
                raise RuntimeError(f"CLI policy decision, prefix list or metadata is wrong: {case['name']}")
        case["passed"] = True
        print(f"PASS {case['name']}: actual {dispatch} CLI, exact original-Rust output")
    if any(sha256(paths[name]) != digest for name, digest in fixture_hashes.items()):
        raise RuntimeError("a CLI invocation modified an input rule file")
    report["execpolicy_rule_inputs_unchanged"] = True


def verify(args, report):
    binary = args.binary.resolve(strict=True)
    reference = args.reference_binary.resolve(strict=True)
    for path in (binary, reference):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"an executable production binary is required: {path}")
    report["binary"] = {"path": str(binary), "sha256": sha256(binary)}
    report["reference_binary"] = {"path": str(reference), "sha256": sha256(reference)}
    inspect_binary(binary, report["binary"], required_symbols=NATIVE_SYMBOLS)
    inspect_binary(reference, report["reference_binary"], native=False, required_symbols=NATIVE_SYMBOLS)
    environment = os.environ.copy()
    removed = ["CODEX_HIA_NATIVE_LIB_DIR", "LD_LIBRARY_PATH"]
    for name in removed:
        environment.pop(name, None)
    report["removed_child_environment_variables"] = removed
    with tempfile.TemporaryDirectory(prefix="codex-hia-installed-execpolicy-") as directory:
        temporary = Path(directory)
        installed = {}
        name = "codex-execpolicy" if args.dispatch == "standalone" else "codex"
        for variant, source in (("native", binary), ("reference", reference)):
            target = temporary / variant / "bin" / name
            target.parent.mkdir(parents=True)
            shutil.copy2(source, target)
            if sha256(target) != sha256(source):
                raise RuntimeError("a relocated executable differs from its inspected source")
            installed[variant] = target
        report["relocated_copies_match"] = True
        run_cases(installed["native"], installed["reference"], temporary / "cases", environment, report, dispatch=args.dispatch)
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--reference-binary", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--dispatch", choices=("standalone", "codex"), default="standalone")
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.report == ROOT or ROOT in args.report.parents:
        parser.error("reports must be outside the source checkout")
    report = {"schema": "codex.hia.installed-execpolicy.v1", "passed": False,
              "dispatch": args.dispatch, "cases": [], "skipped": 0, "whole_codex_rewritten": False}
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    report["cases_passed"] = sum(case["passed"] for case in report["cases"])
    report["processes_completed"] = sum(len(case["processes"]) for case in report["cases"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
