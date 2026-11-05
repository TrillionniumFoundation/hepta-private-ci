#!/usr/bin/env python3
"""Run one explicitly addressed second-wave native phase; never auto-launch.

All red controls preserve tests and restore the exact positive bytes in finally.
Named test failures remain review-required, never an automatic behavioral pass.
The explicit HEAD/tree may advance after a separately reviewed repair; the 14
sealed-ingress source identities and original entry contracts remain fixed.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


TASK = Path("/home/qq/work/hepta-convergence-20261105-0c901b")
SOURCE = TASK / "source-next"
PHASES = ("red-q-decision", "red-q-agentd", "red-q-plasticity", "red-q-selector")
CONTRACTS = {
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "codex-rs/.config/nextest.toml": "5e43111fc8a7a79848f00c1838582edde60bd680",
    "AGENTS.md": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a",
}
MUTATIONS = {
    "red-q-decision": (
        "codex-rs/hepta-intelligence-eval/src/product_qualification_use.rs",
        "73dd589ff130e162de3209c67246bfbbbccec4e09d1b08e85e5cea11ddddb7bd",
    ),
    "red-q-agentd": (
        "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        "1094002c9a97ae4485e69487e5a9406c5e0e1ac91e53cabb19b57491d9c9fe90",
    ),
    "red-q-plasticity": (
        "codex-rs/hepta-intelligence/src/plasticity_product.rs",
        "4d21e5f1eabe993427850ea83dab628ed8ecdf07454f88ef8d72cfd19cd988b5",
    ),
    "red-q-selector": (
        "codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs",
        "e74af6899e6941ee81ba944664153fb67157398220b0cc395847feb5c5ef95a0",
    ),
}
PACKAGES = (
    "codex-hepta-intelligence-eval",
    "codex-hepta-agentd",
    "codex-hepta-intelligence",
)
FIX_PREFIXES = tuple("codex-rs/" + p.removeprefix("codex-") + "/" for p in PACKAGES)
TRUST_WITNESS = "reissued current trust must not rebind a published qualification"
DESKTOP_TEST = "desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def checked_json(path, expected_sha=None):
    data = path.read_bytes()
    if expected_sha is not None and sha(data) != expected_sha:
        raise RuntimeError("artifact digest mismatch: " + str(path))
    return json.loads(data)


def summary_and_failures(output, required):
    """Use the final nextest summary, not retry lines before that summary."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    summaries = list(re.finditer(r"Summary\s+\[[^\n]+?\]\s+(\d+) tests? run:([^\n]+)", clean))
    if not summaries:
        return {"summary": None, "observed_named_failures": [], "complete_named_red": False}
    final = summaries[-1]
    counts = final.group(2)
    failed = re.search(r"\b(\d+) failed\b", counts)
    passed = re.search(r"\b(\d+) passed\b", counts)
    failure_lines = [
        line for line in clean[final.end():].splitlines()
        if re.match(r"^\s*(?:TRY \d+ )?FAIL\s+\[", line)
    ]
    observed = [
        name for name in required
        if any(re.search(r"(?:\s|::)" + re.escape(name) + r"\s*$", line) for line in failure_lines)
    ]
    run_count = int(final.group(1))
    failed_count = int(failed.group(1)) if failed else 0
    passed_count = int(passed.group(1)) if passed else 0
    return {
        "summary": final.group(0),
        "run_count": run_count,
        "failed_count": failed_count,
        "passed_count": passed_count,
        "observed_named_failures": observed,
        "final_failure_lines": failure_lines,
        "complete_named_red": (
            bool(required) and set(observed) == set(required)
            and run_count == len(required) and failed_count == len(required)
            and passed_count == 0
        ),
        "trust_witness_present": TRUST_WITNESS in clean,
    }


def native_environment():
    """Reuse the already verified first-wave toolchain and standard headers."""
    env = os.environ.copy()
    tools_path = TASK / "evidence/ai395-tools-attempt-1/receipt.json"
    tools = checked_json(tools_path)
    if tools.get("state") != "ready-exact-native-tools":
        raise RuntimeError("exact native toolchain is not ready")
    env["RUSTUP_HOME"] = tools["selected_rustup_home"]
    env["RUSTUP_TOOLCHAIN"] = "1.96.0"
    env["PATH"] = str(TASK / "tools/bin") + ":/home/qq/.cargo/bin:" + env.get("PATH", "/usr/bin:/bin")
    env["CARGO_BUILD_JOBS"] = "2"
    env["CARGO_TARGET_DIR"] = str(TASK / "target")
    env["GIT_TERMINAL_PROMPT"] = "0"
    clang_path = TASK / "evidence/clang-headers-attempt-1/receipt.json"
    clang = checked_json(clang_path)
    if clang.get("state") != "ready-task-local-clang-resource-headers":
        raise RuntimeError("verified task-local Clang headers are required")
    if sha(Path(clang["stddef_header"]).read_bytes()) != clang["stddef_header_sha256"]:
        raise RuntimeError("task-local Clang header identity changed")
    clang_args = clang["environment"]["BINDGEN_EXTRA_CLANG_ARGS"]
    if env.get("BINDGEN_EXTRA_CLANG_ARGS") not in {None, "", clang_args}:
        raise RuntimeError("inherited bindgen arguments differ from the verified repair")
    env["BINDGEN_EXTRA_CLANG_ARGS"] = clang_args
    openssl_path = TASK / "evidence/openssl-dev-attempt-1/receipt.json"
    openssl = checked_json(openssl_path)
    if openssl.get("state") != "ready-task-local-matched-openssl-development-prefix":
        raise RuntimeError("verified matched OpenSSL development prefix is required")
    for library in openssl["runtime_library_identity"]:
        actual = Path(openssl["environment"]["OPENSSL_LIB_DIR"]) / library["name"]
        if sha(actual.read_bytes()) != library["sha256"]:
            raise RuntimeError("task-local OpenSSL library identity changed")
    for key, value in openssl["environment"].items():
        if env.get(key) not in {None, "", value}:
            raise RuntimeError("inherited OpenSSL environment differs from repair: " + key)
        env[key] = value
    return env, {
        "toolchain_receipt_sha256": sha(tools_path.read_bytes()),
        "clang_receipt_sha256": sha(clang_path.read_bytes()),
        "openssl_receipt_sha256": sha(openssl_path.read_bytes()),
        "environment": {key: env[key] for key in (
            "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "CARGO_BUILD_JOBS", "CARGO_TARGET_DIR",
            "BINDGEN_EXTRA_CLANG_ARGS", "OPENSSL_LIB_DIR", "OPENSSL_INCLUDE_DIR", "CPATH",
        )},
        "inherited_compile_options": {
            key: value for key, value in env.items()
            if key in {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"}
            or key.startswith("CARGO_PROFILE_")
        },
        "repository_features_profiles_budgets_or_backend_changed": False,
    }


def main(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.head) or not re.fullmatch(r"[0-9a-f]{40}", args.tree):
        raise RuntimeError("explicit full HEAD and tree IDs are required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.first_wave_head):
        raise RuntimeError("explicit repaired first-wave HEAD is required")
    if args.attempt < 1:
        raise RuntimeError("attempt must be positive")
    bundle = args.bundle.resolve()
    plan = checked_json(bundle / "plan.json", args.plan_sha256)
    if args.head != plan["execution_head"] or args.tree != plan["execution_tree"]:
        raise RuntimeError("explicit HEAD/tree differ from the reviewed plan")
    if args.first_wave_head != plan["first_wave_expected_implementation_commit"]:
        raise RuntimeError("explicit repaired first-wave HEAD differs from the reviewed plan")
    positive = checked_json(bundle / "final-positive-manifest.json", args.positive_manifest_sha256)
    expected = {item["path"]: item for item in positive["files"]}
    if len(expected) != 14:
        raise RuntimeError("exactly fourteen controlled positive source files are required")
    controls = {item["phase"]: item for item in plan["controls"]}
    if set(controls) != set(PHASES):
        raise RuntimeError("native plan has the wrong control set")
    for phase, (path, patch_sha) in MUTATIONS.items():
        case = controls[phase]
        if case["production_path"] != path or case["patch_sha256"] != patch_sha:
            raise RuntimeError("mutation changed from the independently reviewed deletion")
        if case["positive_production_git_blob"] != expected[path]["git_blob"]:
            raise RuntimeError("mutation base does not match the positive source manifest")
        if case["command"][:3] != ["just", "test", "--locked"]:
            raise RuntimeError("negative command changed the original test entry")
        patch_path = (bundle / case["patch_path"]).resolve()
        if not patch_path.is_relative_to(bundle) or sha(patch_path.read_bytes()) != patch_sha:
            raise RuntimeError("negative patch path or bytes changed")

    evidence = TASK / "evidence" / f"native-sealed-{args.phase}-v{args.attempt}"
    evidence.mkdir(exist_ok=False)
    receipt = {
        "schema": "hepta.sealed-ingress-native-phase.v1",
        "phase": args.phase, "attempt": args.attempt,
        "source": str(SOURCE), "execution_head": args.head, "execution_tree": args.tree,
        "plan_execution_head": plan["execution_head"],
        "head_was_explicitly_supplied": True,
        "plan_sha256": args.plan_sha256,
        "positive_manifest_sha256": args.positive_manifest_sha256,
        "state": "preflight", "steps": [], "source_expected": positive["files"],
        "native_runner_sha256": sha(Path(__file__).read_bytes()),
        "behavioral_failure_review_required": args.phase in PHASES,
    }

    def save():
        temporary = evidence / "receipt.json.tmp"
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(evidence / "receipt.json")

    save()
    env = None

    def run(name, argv, required=True, stdin=None):
        out, err = evidence / f"{name}.stdout", evidence / f"{name}.stderr"
        started = time.time()
        print(json.dumps({"stage": "start", "name": name, "argv": argv}), flush=True)
        with out.open("wb") as stdout, err.open("wb") as stderr:
            done = subprocess.run(argv, cwd=SOURCE, env=env, input=stdin, stdout=stdout, stderr=stderr)
        stdout, stderr = out.read_bytes(), err.read_bytes()
        receipt["steps"].append({
            "name": name, "argv": argv, "exit_code": done.returncode,
            "elapsed_seconds": time.time() - started,
            "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr),
        })
        save()
        if required and done.returncode:
            raise RuntimeError(f"{name} failed with exit {done.returncode}")
        return done.returncode, stdout, stderr

    def snapshot():
        return [{"path": path, "sha256": sha((SOURCE / path).read_bytes()),
                 "git_blob": git_blob((SOURCE / path).read_bytes())} for path in expected]

    def check_positive():
        actual = snapshot()
        for item in actual:
            if item["sha256"] != expected[item["path"]]["sha256"] or item["git_blob"] != expected[item["path"]]["git_blob"]:
                raise RuntimeError("positive source/fixture drift: " + item["path"])
        return actual

    def prior_phase(phase, state):
        matches = []
        for path in (TASK / "evidence").glob(f"native-sealed-{phase}-v*/receipt.json"):
            prior = checked_json(path)
            if (prior.get("execution_head") == args.head
                    and prior.get("execution_tree") == args.tree
                    and prior.get("positive_manifest_sha256") == args.positive_manifest_sha256
                    and prior.get("plan_sha256") == args.plan_sha256
                    and prior.get("state") == state and prior.get("exit_code") == 0):
                matches.append((prior.get("attempt", 0), path))
        if not matches:
            raise RuntimeError("required earlier phase evidence is absent: " + phase)
        path = max(matches)[1]
        return {"phase": phase, "path": str(path), "sha256": sha(path.read_bytes())}

    backup = None
    production = None
    permitted_mutated_blob = None
    lock_bytes = None
    native_lock = None
    result = 1
    try:
        # These paths and identities are explicit, reviewed inputs. A later
        # attempt requires a newly reviewed plan; failed or stale receipts do
        # not open the gate, and the original failing evidence is preserved.
        first_gates = []
        first_source = Path(plan["first_wave_completion_gates"]["source"])
        for label, path in [
            ("desktop_regression", args.first_wave_desktop_receipt),
            ("green", args.first_wave_green_receipt),
            ("fix", args.first_wave_fix_receipt),
        ]:
            gate = plan["first_wave_completion_gates"][label]
            if path.resolve() != Path(gate["receipt"]).resolve():
                raise RuntimeError("first-wave receipt path differs from the reviewed plan: " + label)
            prior = checked_json(path)
            if (prior.get("state") != gate["state"] or prior.get("phase") != gate["phase"]
                    or prior.get("exit_code") != 0 or prior.get("command_exit_code") != 0):
                raise RuntimeError("all three repaired first-wave phases must have completed: " + str(path))
            if prior.get("implementation_commit") != args.first_wave_head:
                raise RuntimeError("first-wave completion receipt is not for the explicit repaired HEAD")
            if prior.get("source") != str(first_source):
                raise RuntimeError("first-wave completion receipt has the wrong source checkout")
            if label == "fix":
                if (prior.get("source_changed_by_fix") is not False
                        or prior.get("unexpected_changed_paths") != []):
                    raise RuntimeError("first-wave fix changed source; publish and review its identity before proceeding")
            else:
                observed = prior.get("positive_observation", {})
                required = observed.get("required_tests", [])
                passed = observed.get("observed_passes", [])
                summary = summary_and_failures(observed.get("summary") or "", [])
                if (not required or set(passed) != set(required) or DESKTOP_TEST not in required
                        or observed.get("run_count", 0) < len(required)
                        or summary.get("run_count") != observed.get("run_count")
                        or summary.get("failed_count") != 0):
                    raise RuntimeError("first-wave positive receipt lacks its actual passing test observations")
                if label == "desktop_regression" and (observed["run_count"] != 1 or required != [DESKTOP_TEST]):
                    raise RuntimeError("first-wave named desktop regression must execute exactly the original test")
            first_gates.append({"path": str(path), "sha256": sha(path.read_bytes()), "state": gate["state"],
                                "phase": gate["phase"],
                                "implementation_commit": prior["implementation_commit"]})
        receipt["first_wave_completion"] = first_gates
        receipt["first_wave_implementation_commit"] = args.first_wave_head
        native_lock = (TASK / "evidence/native-sealed-validation.lock").open("a+b")
        fcntl.flock(native_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env, repair = native_environment()
        receipt["verified_environment"] = repair
        # Read-only first-checkout checks: never reset, restore or write there.
        _, first_head, _ = run("first-wave-head", ["git", "--no-optional-locks", "-C", str(first_source),
                                                   "rev-parse", "HEAD"])
        _, first_status, _ = run("first-wave-clean", ["git", "--no-optional-locks", "-C", str(first_source),
                                                       "status", "--porcelain=v1", "--untracked-files=all"])
        if first_head.decode().strip() != args.first_wave_head or first_status:
            raise RuntimeError("repaired first-wave source must retain its explicit HEAD and clean state")
        receipt["first_wave_source_readonly_verified"] = {"head": args.first_wave_head, "clean": True}
        _, head, _ = run("head", ["git", "rev-parse", "HEAD"])
        _, tree, _ = run("tree", ["git", "rev-parse", "HEAD^{tree}"])
        if head.decode().strip() != args.head or tree.decode().strip() != args.tree:
            raise RuntimeError("worktree is not the explicitly authorized HEAD/tree")
        _, status, _ = run("clean-before", ["git", "status", "--porcelain=v1", "--untracked-files=all"])
        if status:
            raise RuntimeError("second worktree must be clean before the phase")
        receipt["source_before"] = check_positive()
        for path, expected_blob in CONTRACTS.items():
            if git_blob((SOURCE / path).read_bytes()) != expected_blob:
                raise RuntimeError("original entry/profile contract changed: " + path)
        lock_path = SOURCE / "codex-rs/Cargo.lock"
        lock_bytes = lock_path.read_bytes()
        _, committed_lock_blob, _ = run("committed-lock", ["git", "rev-parse", args.head + ":codex-rs/Cargo.lock"])
        if git_blob(lock_bytes) != committed_lock_blob.decode().strip():
            raise RuntimeError("Cargo.lock differs from the explicit committed HEAD")
        receipt["cargo_lock_sha256"] = sha(lock_bytes)
        receipt["cargo_lock_git_blob"] = git_blob(lock_bytes)
        _, rustc, _ = run("rustc", ["rustc", "-Vv"])
        _, cargo, _ = run("cargo", ["cargo", "-V"])
        if not rustc.startswith(b"rustc 1.96.0 ") or not cargo.startswith(b"cargo 1.96.0 "):
            raise RuntimeError("native invocation did not select exact Rust/Cargo 1.96.0")
        receipt["versions"] = {"rustc": rustc.decode().strip(), "cargo": cargo.decode().strip()}
        # A completed final fix ends testing for this source identity.
        if args.phase != "fix":
            for path in (TASK / "evidence").glob("native-sealed-fix-v*/receipt.json"):
                prior = checked_json(path)
                if prior.get("execution_head") == args.head and prior.get("state") == "fix-complete":
                    raise RuntimeError("tests may not rerun after the final scoped fix")
        prior = []
        required = PHASES[:PHASES.index(args.phase)] if args.phase in PHASES else PHASES
        for phase in required:
            prior.append(prior_phase(phase, "named-test-failures-observed-review-required"))
        if args.phase == "fix":
            prior.append(prior_phase("green", "green-complete"))
        receipt["prior_phases"] = prior

        if args.phase in PHASES:
            case = controls[args.phase]
            production = SOURCE / case["production_path"]
            backup = production.read_bytes()
            permitted_mutated_blob = case["mutated_production_git_blob"]
            (evidence / "production-before.rs").write_bytes(backup)
            patch = (bundle / case["patch_path"]).read_bytes()
            (evidence / "negative.patch").write_bytes(patch)
            receipt.update(state="preparing-negative-control", production_path=case["production_path"],
                           negative_patch_sha256=sha(patch), expected_mutated_blob=permitted_mutated_blob)
            save()
            run("negative-apply-check", ["git", "apply", "--check", "-"], stdin=patch)
            run("negative-apply", ["git", "apply", "-"], stdin=patch)
            mutated = production.read_bytes()
            if git_blob(mutated) != permitted_mutated_blob:
                raise RuntimeError("negative production differs from the reviewed mutation")
            if b"#[cfg(test)]" in backup and backup.split(b"#[cfg(test)]", 1)[1] != mutated.split(b"#[cfg(test)]", 1)[1]:
                raise RuntimeError("negative mutation changed inline tests")
            for item in snapshot():
                if item["path"] != case["production_path"] and item["sha256"] != expected[item["path"]]["sha256"]:
                    raise RuntimeError("negative changed another source or fixture: " + item["path"])
            _, changed, _ = run("negative-changed-paths", ["git", "diff", "--name-only", "-z", "HEAD"])
            if set(changed.decode().split("\0")) - {""} != {case["production_path"]}:
                raise RuntimeError("negative mutation changed an unexpected tracked path")
            receipt.update(state="negative-control-running", requested_tests=case["required_named_failures"])
            save()
            code, stdout, stderr = run("just-test", case["command"], required=False)
            observed = summary_and_failures((stdout + b"\n" + stderr).decode(errors="replace"), case["required_named_failures"])
            if args.phase == "red-q-decision" and not observed.get("trust_witness_present"):
                observed["complete_named_red"] = False
            receipt.update(test_exit_code=code, failure_observation=observed)
            successful_observation = code > 0 and observed["complete_named_red"]
            receipt["state"] = ("named-test-failures-observed-review-required" if successful_observation
                                else "negative-control-did-not-prove-required-test-failures")
            result = 0 if successful_observation else 1
        else:
            command = ["just", "fix" if args.phase == "fix" else "test", "--locked"]
            for package in PACKAGES:
                command.extend(["-p", package])
            receipt["state"] = "running-" + args.phase
            save()
            code, stdout, stderr = run("just-" + args.phase, command, required=False)
            receipt["command_exit_code"] = code
            if args.phase == "green":
                output = (stdout + b"\n" + stderr).decode(errors="replace")
                observed = summary_and_failures(output, [])
                clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
                critical = {name for case in controls.values() for name in case["required_named_failures"]}
                successes = [line for line in clean.splitlines()
                             if re.match(r"^\s*(?:TRY \d+ )?(?:PASS|FLAKY)\b", line)]
                observed["critical_passes"] = sorted(
                    name for name in critical
                    if any(re.search(r"(?:\s|::)" + re.escape(name) + r"\s*$", line) for line in successes)
                )
                receipt["test_summary"] = observed
                check_positive()
                passed = (code == 0 and observed.get("run_count", 0) > 0
                          and observed.get("failed_count", 0) == 0
                          and set(observed["critical_passes"]) == critical)
                receipt["state"] = "green-complete" if passed else "green-failed"
                result = 0 if passed else 1
            else:
                run("format-after-fix", plan["commands"]["format"])
                _, changed, _ = run("changed-after-fix", ["git", "diff", "--name-only", "-z", "HEAD"])
                paths = set(changed.decode().split("\0")) - {""}
                unexpected = sorted(p for p in paths if not p.startswith(FIX_PREFIXES) or not p.endswith(".rs"))
                _, patch, _ = run("fix-patch", ["git", "diff", "--binary", "--no-ext-diff", "HEAD"])
                (evidence / "native-fix.patch").write_bytes(patch)
                receipt.update(after=snapshot(), changed_paths=sorted(paths), unexpected_changed_paths=unexpected,
                               post_fix_source_changed=bool(paths), tests_rerun_after_fix=False,
                               post_fix_diff_sha256=sha(patch))
                receipt["state"] = "fix-complete" if code == 0 and not unexpected else "fix-blocked"
                result = 0 if receipt["state"] == "fix-complete" else 1
        if lock_path.read_bytes() != lock_bytes:
            raise RuntimeError("Cargo.lock changed during the native phase")
        receipt["exit_code"] = result
    except Exception as error:
        receipt.update(state="native-phase-blocked", error=str(error), exit_code=1)
        result = 1
    finally:
        try:
            if backup is not None:
                current = production.read_bytes()
                if git_blob(current) not in {git_blob(backup), permitted_mutated_blob}:
                    raise RuntimeError("refusing to overwrite an unexpected production change during restore")
                production.write_bytes(backup)
                receipt["restored_positive"] = check_positive()
                receipt["restored_candidate"] = True
            if lock_bytes is not None and (SOURCE / "codex-rs/Cargo.lock").read_bytes() != lock_bytes:
                raise RuntimeError("Cargo.lock differs at phase completion")
            if env is not None and receipt.get("versions") and args.phase != "fix":
                _, status, _ = run("clean-after", ["git", "status", "--porcelain=v1", "--untracked-files=all"])
                if status:
                    raise RuntimeError("worktree is not clean after restoration/test")
                check_positive()
            if env is not None and receipt.get("versions"):
                _, final_head, _ = run("head-after", ["git", "rev-parse", "HEAD"])
                _, final_tree, _ = run("tree-after", ["git", "rev-parse", "HEAD^{tree}"])
                if final_head.decode().strip() != args.head or final_tree.decode().strip() != args.tree:
                    raise RuntimeError("explicit HEAD/tree changed during the native phase")
        except Exception as restore_error:
            receipt.update(state="native-phase-restore-or-integrity-blocked", restore_error=str(restore_error),
                           restored_candidate=False, exit_code=1)
            result = 1
        if native_lock is not None:
            native_lock.close()
        receipt["exit_code"] = result
        save()
        print(json.dumps({"phase": args.phase, "state": receipt["state"], "exit_code": result,
                          "receipt": str(evidence / "receipt.json")}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=(*PHASES, "green", "fix"))
    parser.add_argument("--head", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--positive-manifest-sha256", required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--first-wave-head", required=True)
    parser.add_argument("--first-wave-desktop-receipt", required=True, type=Path)
    parser.add_argument("--first-wave-green-receipt", required=True, type=Path)
    parser.add_argument("--first-wave-fix-receipt", required=True, type=Path)
    sys.exit(main(parser.parse_args()))
