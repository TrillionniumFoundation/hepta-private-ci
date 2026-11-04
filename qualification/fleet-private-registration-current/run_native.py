#!/usr/bin/env python3
"""Run explicit complete native library groups on the composed source."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import subprocess
import time
import xml.etree.ElementTree as ET

from common import ROOT, WORKSPACE, HERE, NATIVE_GROUPS, digest, require, snapshot
from common import memory_ignored_cases, require_memory_process_cases

WINDOWS_REQUIRED = {
    "codex-utils-path": {
        "existing_only_directory_does_not_create_or_repair_a_missing_source",
        "frozen_private_child_retains_bytes_and_refuses_write_and_delete_handles",
        "frozen_child_rejects_missing_alias_and_hard_link_without_creation",
        "fresh_materialization_never_opens_an_occupied_name",
    },
    "codex-state": {
        "windows_guard_never_creates_missing_sources_and_rejects_live_writers",
        "windows_sidecar_appearance_refuses_before_any_candidate_is_created",
        "windows_retains_each_sidecar_and_rejects_hard_links_for_every_role",
        "windows_cold_image_is_read_only_and_reconnects_from_the_retained_copy",
        "windows_materializes_only_fresh_private_bytes_and_never_copies_shm",
        "windows_native_and_verbatim_homes_bind_without_admitting_another_directory",
        "windows_home_spelling_reconciliation_rejects_other_roots_and_namespaces",
    },
    "codex-hepta-memory": {
        "bootstrap_creates_private_source_and_preserves_existing_bytes",
        "bootstrap_refuses_existing_hard_link_without_adopting_or_changing_it",
        "pointer_stage_collision_preserves_the_original_private_file",
        "exact_current_cut_recovers_both_native_and_verbatim_root_spellings",
        "exact_current_cut_recovers_writable_generation_and_persists_activation",
        "post_rename_publication_failure_is_indeterminate_and_retains_candidate",
        "predecessor_witness_is_rejected_and_current_witness_recovers",
        "revoked_owner_profile_and_witness_checks_precede_recovery_admission",
        "writable_recovery_requires_exclusive_store_fence",
    },
}


WINDOWS_FULL_REQUIRED = {
    "codex-utils-path": {
        "private_state_windows::security_tests::create_new_directory_refuses_existing_private_state_without_mutation",
        "private_state_windows::security_tests::create_new_directory_does_not_repair_existing_restricted_security",
        "private_state_windows::directory::tests::create_new_rejects_junction_without_creating_redirected_leaf",
    },
    "codex-hepta-fleet": {
        "registry::tests::fresh_agent_roots_satisfy_private_owner_contract",
    },
    "codex-hepta-agentd": {
        "automation::service_tests::cancellation_preserves_in_flight_queue_ack_before_scheduler_exit",
        "cognitive_ranker::tests::running_socket_uses_launch_bound_model_and_isolates_ranker_revocation",
        "runtime::tests::drain_runtime_keeps_control_reconciliation_live_until_terminal_observation",
        "runtime::tests::duplicate_automation_attachment_does_not_replace_the_live_store",
        "runtime::tests::runtime_automation_store_failure_stops_only_the_scheduler_plane",
    },
}


def require_windows_cases(listed, package):
    names = set(listed["expected"])
    suffixes = {name.rsplit("::", 1)[-1] for name in names}
    require(WINDOWS_REQUIRED.get(package, set()) <= suffixes,
            "required Windows controls not compiled")
    require(WINDOWS_FULL_REQUIRED.get(package, set()) <= names,
            "required full Windows case identities not compiled")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def inventory(raw, package, allowed_ignored):
    data = json.loads(raw, object_pairs_hook=unique_object)
    suites = data["rust-suites"]
    require(len(suites) == 1, "expected exactly the selected library binary")
    suite_id, suite = next(iter(suites.items()))
    require(suite["package-name"] == package and suite["kind"] == "lib"
            and suite["status"] == "listed", "wrong or unlisted library")
    cases = suite["testcases"]
    require(cases and data["test-count"] == len(cases), "empty or inconsistent inventory")
    ignored = {name for name, case in cases.items() if case["ignored"] is True}
    require(ignored == set(allowed_ignored), "original ignored set changed")
    expected = set(cases) - ignored
    require(expected, "no executable library cases")
    for name, case in cases.items():
        require(type(case["ignored"]) is bool and case.get("kind") in (None, "test"),
                "unexpected test kind or ignored marker")
        wanted = {"status": "mismatch", "reason": "ignored"} if name in ignored else {"status": "matches"}
        require(case["filter-match"] == wanted, "unexpected library case filter: " + name)
    return {"suite": suite_id, "binary": suite["binary-path"],
            "all_cases": sorted(cases), "expected": sorted(expected),
            "original_ignored": sorted(ignored)}


def validate_junit(raw, listed):
    root = ET.fromstring(raw)
    suites = list(root.iter("testsuite"))
    require(suites, "missing JUnit suite")
    bad = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
    require(not any(element.tag in bad for element in root.iter()), "failed, skipped or retried case")
    cases = list(root.iter("testcase"))
    names = [case.get("name") for case in cases]
    require(len(names) == len(set(names)) and set(names) == set(listed["expected"]),
            "JUnit does not cover every nonignored library case exactly once")
    require(sum(int(s.get("tests", "-1")) for s in suites) == len(names),
            "JUnit test counters do not match executed cases")
    for suite in suites:
        require(all(int(suite.get(key, "0")) == 0 for key in ("failures", "errors", "skipped")),
                "nonzero JUnit failure or skip counter")
    return {"passed": len(names), "failed": 0, "errors": 0, "skipped": 0, "retried": 0,
            "executed": names, "original_ignored": listed["original_ignored"]}



def junit_failure_details(raw):
    """Make original failures visible without changing their acceptance."""
    root = ET.fromstring(raw)
    bad = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
    failures = []
    remaining = 65536
    for case in root.iter("testcase"):
        if not any(child.tag in bad for child in case):
            continue
        details = []
        for child in case:
            if child.tag in bad or child.tag in {"system-out", "system-err"}:
                text = (child.text or "")[:min(8192, remaining)]
                remaining -= len(text)
                details.append({"kind": child.tag, "attributes": child.attrib, "text": text})
        failures.append({"name": case.get("name"), "details": details})
    return failures


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=tuple(NATIVE_GROUPS), required=True)
    args = parser.parse_args()
    packages = NATIVE_GROUPS[args.group]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((HERE / "scope.json").read_bytes())
    before = snapshot(verify_index=True)
    head = subprocess.check_output(["git", "--no-replace-objects", "rev-parse", "HEAD"],
                                   cwd=ROOT, text=True).strip()
    receipt = {"source_commit": head, "group": args.group, "packages": list(packages),
               "status": "failed", "run_id": os.environ["GITHUB_RUN_ID"],
               "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "host": platform.platform(),
               "machine": platform.machine(), "commands": [], "libraries": {}, "problems": [],
               "scope": "Complete original native library tests and scoped original Clippy; no production admission."}
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    report = WORKSPACE / "target/nextest/local/junit.xml"
    pinned_client = None
    pinned_files = {}

    def run(name, argv, cwd=ROOT):
        started = time.monotonic()
        stdout, stderr = output / (name + ".stdout"), output / (name + ".stderr")
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err)
        row = {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": process.returncode,
               "seconds": time.monotonic() - started}
        receipt["commands"].append(row)
        print(json.dumps(row), flush=True)
        if process.returncode:
            print(stdout.read_text(encoding="utf-8", errors="replace")[-15000:], flush=True)
            print(stderr.read_text(encoding="utf-8", errors="replace")[-15000:], flush=True)
        return process.returncode

    try:
        require(head == os.environ["HEPTA_EXPECTED_COMMIT"], "unexpected source head")
        require(run("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]) == 0,
                "dirty initial source")
        require(run("rustc-version", ["rustc", "-Vv"]) == 0, "rustc version failed")
        require((output / "rustc-version.stdout").read_text().startswith("rustc 1.96.0 "),
                "not the committed Rust 1.96 toolchain")
        require(run("nextest-version", ["cargo", "nextest", "--version"], WORKSPACE) == 0,
                "nextest version failed")
        require((output / "nextest-version.stdout").read_text().startswith("cargo-nextest 0.9.151 "),
                "unexpected nextest version")
        if platform.system() == "Linux" and args.group == "agentd":
            # Preserve the same pinned native D-Bus provider used by the
            # maintained keyring and YAML consumer qualifications.
            pinned_client = output.parent / ("pinned-dbus-" + args.group)
            try:
                require(run("pinned-dbus-client", [
                    sys.executable, str(ROOT / "qualification/keyring-sync-provider/build_pinned_client.py"),
                    "--output", str(pinned_client),
                ]) == 0, "pinned D-Bus client qualification failed")
            finally:
                if (pinned_client / "receipt.json").is_file():
                    shutil.copyfile(pinned_client / "receipt.json",
                                    output / "pinned-dbus-client-receipt.json")
            for relative in ("lib/libdbus-1.a", "lib/pkgconfig/dbus-1.pc", "native-identity"):
                pinned_files[relative] = digest((pinned_client / relative).read_bytes())
            provider = json.loads((pinned_client / "receipt.json").read_bytes())
            require(provider["status"] == "PASS"
                    and provider["static_sha256"] == pinned_files["lib/libdbus-1.a"]
                    and provider["identity_sha256"] == pinned_files["native-identity"],
                    "pinned D-Bus products differ from their executed receipt")
            os.environ["PKG_CONFIG_PATH"] = str(pinned_client / "lib/pkgconfig")
            receipt["pinned_dbus"] = {"path": str(pinned_client), "before": pinned_files}
        receipt["environment"] = {name: os.environ.get(name) for name in (
            "RUSTUP_TOOLCHAIN", "RUST_MIN_STACK", "NEXTEST_PROFILE", "CARGO_INCREMENTAL",
            "CARGO_BUILD_JOBS", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG",
            "CARGO_TARGET_DIR", "PKG_CONFIG_PATH",
        )}
        for package in packages:
            item = {"status": "failed"}
            receipt["libraries"][package] = item
            try:
                require(run(package + "-inventory", ["cargo", "nextest", "list", "--locked",
                        "-p", package, "--lib", "--message-format=json"], WORKSPACE) == 0,
                        "library inventory failed")
                ignored = memory_ignored_cases(config, platform.system()) if package == "codex-hepta-memory" else []
                listed = inventory((output / (package + "-inventory.stdout")).read_bytes(), package, ignored)
                item["inventory"] = listed
                if package == "codex-hepta-memory":
                    require_memory_process_cases(listed["all_cases"], listed["expected"], platform.system())
                if os.name == "nt":
                    require_windows_cases(listed, package)
                binary = Path(listed["binary"])
                item["binary_sha256_before"] = digest(binary.read_bytes())
                if report.exists():
                    report.unlink()
                require(not report.exists(), "stale JUnit report")
                code = run(package + "-original-tests", ["just", "test", "--locked", "-p", package,
                           "--lib", "--no-tests=fail", "--retries", "0", "--success-output=final"])
                if report.is_file():
                    shutil.copyfile(report, output / (package + "-junit.xml"))
                    details = junit_failure_details(report.read_bytes())
                    if details:
                        print("ORIGINAL_JUNIT_FAILURES=" + json.dumps({"package": package, "cases": details}), flush=True)
                require(code == 0, "original library tests failed")
                require(report.is_file(), "successful process produced no fresh JUnit")
                log = b"".join((output / (package + "-original-tests." + suffix)).read_bytes()
                               for suffix in ("stdout", "stderr"))
                require(b"skipping test:" not in log.lower(), "test reported an early-return skip")
                item["result"] = validate_junit(report.read_bytes(), listed)
                item["binary_sha256_after"] = digest(binary.read_bytes())
                require(item["binary_sha256_before"] == item["binary_sha256_after"],
                        "test binary changed during execution")
                item["status"] = "passed"
            except Exception as error:
                item["error"] = str(error)
                receipt["problems"].append(package + ": " + str(error))
        fix = ["just", "fix", "--locked"]
        for package in packages:
            fix.extend(["-p", package])
        fix.append("--no-deps")
        if run("original-scoped-clippy", fix):
            receipt["problems"].append("original scoped Clippy failed")
        if run("final-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]):
            receipt["problems"].append("qualification changed tracked source")
        if snapshot() != before:
            receipt["problems"].append("source input hashes changed")
        if pinned_client is not None and pinned_files:
            after_provider = {
                relative: digest((pinned_client / relative).read_bytes())
                for relative in pinned_files
            }
            receipt["pinned_dbus"]["after"] = after_provider
            if after_provider != pinned_files:
                receipt["problems"].append("pinned native provider changed during qualification")
        require(not receipt["problems"], "; ".join(receipt["problems"]))
        receipt["status"] = "passed"
    finally:
        after = snapshot()
        receipt["source_after"] = after
        receipt["source_inputs_unchanged"] = after == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("NATIVE_QUALIFICATION_RESULT=" + json.dumps({
            key: value for key, value in receipt.items() if key not in {"source_after", "outputs"}
        }), flush=True)


if __name__ == "__main__":
    main()
