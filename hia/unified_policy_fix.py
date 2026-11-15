#!/usr/bin/env python3
"""Preserve Cargo fix's real Clippy compiler chain and arithmetic receipts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import unified_policy_ci as ci

CARGO_SHA = "a73b2c25573d251489101c0d8f19ad3702eb9761166de5ed8437b472b6c038ce"
OUTER = "hia/unified_policy_fix_outer.py"
WORKSPACE = "hia/unified_policy_fix_workspace.py"
CONTEXT_ENV = "CODEX_HIA_POLICY_FIX_CONTEXT"


def create(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def split_arguments(arguments):
    """Mirror pinned cargo-clippy ClippyCmd::new, then bind JSON transport."""
    cargo, clippy = ["--tests", "--allow-dirty"], []
    tail = iter(arguments)
    for argument in tail:
        if argument == "--":
            clippy.extend(tail)
            break
        if argument == "--fix":
            continue
        if argument == "--no-deps":
            clippy.append(argument)
        else:
            cargo.append(argument)
    if "--no-deps" not in clippy:
        clippy.append("--no-deps")
    ci.require(all("\0" not in argument and "__CLIPPY_HACKERY__" not in argument for argument in clippy),
               "invalid Clippy argument transport")
    result = []
    i = 0
    while i < len(cargo):
        argument = cargo[i]
        if argument == "--message-format":
            ci.require(i + 1 < len(cargo) and cargo[i + 1] == "json-render-diagnostics",
                       "fix qualification requires JSON Cargo artifact output")
            i += 2
            continue
        if argument == "--color":
            ci.require(i + 1 < len(cargo) and cargo[i + 1] in ("never", "auto"),
                       "fix qualification requires uncolored diagnostics")
            i += 2
            continue
        if argument.startswith("--color="):
            ci.require(argument in ("--color=never", "--color=auto"),
                       "fix qualification requires uncolored diagnostics")
            i += 1
            continue
        if argument.startswith("--message-format="):
            ci.require(argument == "--message-format=json-render-diagnostics",
                       "fix qualification requires JSON Cargo artifact output")
        else:
            result.append(argument)
        i += 1
    result.append("--message-format=json-render-diagnostics")
    result.append("--color=never")
    return result, "".join(argument + "__CLIPPY_HACKERY__" for argument in clippy)


def bridge(kind, arguments):
    """Use one admitted helper per compiler call, including fix primary units."""
    repo = Path(__file__).resolve().parents[1]
    context_path = Path(os.environ[CONTEXT_ENV]).resolve(strict=True)
    context = json.loads(context_path.read_text())
    ci.require(context["schema"] == "codex.hia.fix-compiler-context.v1", "unknown fix context")
    ci.require(not context_path.is_relative_to(repo), "fix context must be external")
    ci.require(context["repo"] == str(repo), "fix bridge checkout differs")
    for item in context["inputs"]:
        ci.require(ci.binding(item["path"]) == item, "fix compiler input changed: " + item["path"])
    rustc = Path(context["rustc"]).resolve(strict=True)
    ci.validate_configuration(repo, rustc, os.environ["CODEX_HIA_SIMILAR_POLICY_CONFIG"])
    ci.require(os.environ.get("RUSTC_WRAPPER") == str(repo / OUTER)
               and os.environ.get("RUSTC_WORKSPACE_WRAPPER") == str(repo / WORKSPACE),
               "unexpected fix wrapper arrangement")
    ci.require(os.environ.get("CLIPPY_ARGS") == context["clippy_args"], "fix lint arguments changed")
    ci.require(arguments, "missing fix compiler argument")
    first = Path(arguments[0]).resolve(strict=True)
    helper = ci.load_helper(repo)
    owner = helper.last_option(arguments, "--crate-name") == "codex_apply_patch"
    native = owner and 'feature="hia-native"' in helper.option_values(arguments, "--cfg")
    delegates = True
    if kind == "outer" and first == repo / WORKSPACE:
        ci.require(len(arguments) > 1 and Path(arguments[1]).resolve(strict=True) == rustc,
                   "unexpected nested fix workspace compiler")
        command = list(arguments)
        delegates = False
    else:
        ci.require(first == rustc, "fix bridge compiler is not the pinned rustc")
        ci.require(kind in ("outer", "workspace"), "unknown fix bridge entry")
        ci.require(not (kind == "outer" and native), "native owner must use the Clippy workspace bridge")
        prefix = [str(rustc)] if kind == "outer" else [context["clippy"], str(rustc)]
        helper.compiler_chain(prefix, {"rustc": str(rustc)})
        command = [sys.executable, str(repo / "hia/similar_policy.py"), *prefix, *arguments[1:]]
    result = subprocess.run(command, close_fds=False)
    record = {"kind": kind, "arguments": arguments, "command": command,
              "delegates_helper": delegates, "native_owner": native,
              "returncode": result.returncode, "context": ci.binding(context_path)}
    return result.returncode, record


def run_fix(arguments):
    requested = os.environ.get("CODEX_HIA_POLICY_FIX_REQUIRE_NATIVE", "0")
    ci.require(requested in ("0", "1"), "invalid native fix requirement")
    if not os.environ.get("CODEX_HIA_SIMILAR_POLICY_CONFIG"):
        ci.require(requested == "0", "native fix requires the admitted policy configuration")
        return subprocess.run(["cargo", "clippy", "--fix", "--tests", "--allow-dirty", *arguments],
                              close_fds=False).returncode
    repo = Path(__file__).resolve().parents[1]
    rustc = Path(os.environ["RUSTC"]).resolve(strict=True)
    env = os.environ.copy()
    ci.require(not env.get("RUSTC_WORKSPACE_WRAPPER"), "fix starts outside an existing workspace wrapper")
    admitted = ci.admit_environment(repo, rustc, env)
    ci.require(admitted is not None, "native fix requires the original admitted policy wrapper")
    cargo, clippy = rustc.parent / "cargo", rustc.parent / "clippy-driver"
    ci.require(ci.binding(cargo)["sha256"] == CARGO_SHA, "unqualified Cargo fix implementation")
    ci.require(ci.binding(clippy)["sha256"] == ci.CLIPPY_SHA, "unqualified Clippy implementation")
    if env.get("CARGO"):
        ci.require(Path(env["CARGO"]).resolve(strict=True) == cargo, "unqualified Cargo override")
    cargo_arguments, clippy_arguments = split_arguments(arguments)
    env["CLIPPY_ARGS"] = clippy_arguments
    env["CLIPPY_TERMINAL_WIDTH"] = "0"
    env["CARGO_TERM_COLOR"] = "never"
    # Reuse the frozen helper's lint-only Clippy argument validation. Restore
    # the process environment before launching Cargo; the child receives env.
    previous_clippy = os.environ.get("CLIPPY_ARGS")
    os.environ["CLIPPY_ARGS"] = clippy_arguments
    try:
        ci.load_helper(repo).compiler_chain([str(clippy), str(rustc)], {"rustc": str(rustc)})
    finally:
        if previous_clippy is None:
            os.environ.pop("CLIPPY_ARGS", None)
        else:
            os.environ["CLIPPY_ARGS"] = previous_clippy
    default = Path(admitted["receipt_root"]) / "fix-runs" / (str(time.time_ns()) + ".json")
    report_path = Path(env.get("CODEX_HIA_POLICY_FIX_REPORT", default)).resolve()
    ci.require(not report_path.is_relative_to(repo), "fix report must be outside the checkout")
    ci.require(not report_path.exists(), "refusing to replace a fix report")
    run = report_path.with_suffix("")
    ci.require(not run.exists(), "refusing to replace fix evidence")
    run.mkdir(parents=True)
    context = {"schema": "codex.hia.fix-compiler-context.v1", "repo": str(repo),
               "rustc": str(rustc), "clippy": str(clippy), "clippy_args": clippy_arguments,
               "inputs": admitted["source_inputs"] + [ci.binding(rustc), ci.binding(cargo), ci.binding(clippy),
                                                      admitted["config"]]}
    context_path = run / "context.json"
    create(context_path, context)
    env.update(RUSTC_WRAPPER=str(repo / OUTER), RUSTC_WORKSPACE_WRAPPER=str(repo / WORKSPACE),
               CODEX_HIA_POLICY_FIX_CONTEXT=str(context_path))
    command = [str(cargo), "fix", *cargo_arguments]
    report = {"schema": "codex.hia.actual-policy-fix.v1", "passed": False,
              "scope": "Actual Cargo fix with pinned Clippy and actual compiler artifact admission.",
              "arguments": arguments, "command": command, "configuration": admitted,
              "context": ci.binding(context_path), "require_native": requested == "1",
              "prior_clippy_args": os.environ.get("CLIPPY_ARGS"), "clippy_args": clippy_arguments}
    try:
        stdout, stderr = run / "cargo.jsonl", run / "cargo.stderr"
        with stdout.open("xb") as out, stderr.open("xb") as err:
            result = subprocess.run(command, env=env, stdout=out, stderr=err, close_fds=False)
        report.update(returncode=result.returncode, stdout=ci.binding(stdout), stderr=ci.binding(stderr))
        starts = {p.name.removesuffix(".begin.json"): p for p in run.glob("bridge-*.begin.json")}
        completions = {p.name.removesuffix(".end.json"): p for p in run.glob("bridge-*.end.json")}
        report["bridge_starts"] = [ci.binding(p) for p in sorted(starts.values())]
        report["bridge_completions"] = [ci.binding(p) for p in sorted(completions.values())]
        sys.stderr.buffer.write(stderr.read_bytes())
        ci.require(result.returncode == 0, "actual Cargo fix failed")
        ci.require(starts and starts.keys() == completions.keys(), "fix compiler call has no complete audit record")
        events = []
        for key, path in sorted(starts.items()):
            end = json.loads(completions[key].read_text())
            ci.require(end["start"] == ci.binding(path), "fix compiler audit pairing differs")
            ci.require(end["returncode"] == 0 and "exception" not in end,
                       "a fix bridge failed, even if Cargo returned zero")
            events.append(end["result"])
        report["all_subcompilers_succeeded"] = all(event["returncode"] == 0 for event in events)
        ci.require(report["all_subcompilers_succeeded"], "a real fix compiler invocation failed")
        ci.require(not any(line.startswith(("error:", "error[")) for line in stderr.read_text().splitlines()),
                   "Cargo fix reported an error despite its exit status")
        records = [json.loads(line) for line in stdout.read_text().splitlines()]
        ci.require(records and records[-1] == {"reason": "build-finished", "success": True},
                   "actual Cargo fix did not finish successfully")
        selected = [x for x in records if x.get("reason") == "compiler-artifact"
                    and x["target"]["name"].replace("-", "_") == "codex_apply_patch"
                    and "hia-native" in x["features"]]
        ci.require(selected or requested == "0", "actual Cargo fix produced no native owner")
        if selected:
            verified, errors = run / "policy-admission.json", run / "policy-admission.stderr"
            verify = [sys.executable, str(repo / "hia/similar_policy.py"), "--verify-cargo-log", str(stdout)]
            with verified.open("xb") as out, errors.open("xb") as err:
                checked = subprocess.run(verify, env=env, stdout=out, stderr=err, close_fds=False)
            report["admission"] = {"command": verify, "returncode": checked.returncode,
                                   "stdout": ci.binding(verified), "stderr": ci.binding(errors)}
            ci.require(checked.returncode == 0, "actual fix artifact receipt admission failed")
            record = json.loads(verified.read_text())
            ci.require(record["passed"] and record["cargo_log"] == ci.binding(stdout)
                       and record["consumer_artifacts"], "fix receipt result is incomplete")
            report["consumer_artifacts"] = record["consumer_artifacts"]
        else:
            report["consumer_artifacts"] = []
        owners = [event for event in events if event["native_owner"] and event["delegates_helper"]]
        ci.require(not selected or (owners and all(x["kind"] == "workspace" for x in owners)),
                   "native fix did not use the actual Clippy workspace bridge")
        report["actual_native_helper_calls"] = len(owners)
        report["source_inputs_unchanged"] = all(ci.binding(x["path"]) == x for x in admitted["source_inputs"])
        ci.require(report["source_inputs_unchanged"], "bound fix inputs changed")
        report["passed"] = True
    except Exception as error:
        report["exception"] = str(error)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    create(report_path, report)
    print(json.dumps({"passed": report["passed"], "report": ci.binding(report_path)}))
    return 0 if report["passed"] else 74


if __name__ == "__main__":
    try:
        raise SystemExit(run_fix(sys.argv[1:]))
    except Exception as error:
        print("HIA fix admission rejected: " + str(error), file=sys.stderr)
        raise SystemExit(74)
