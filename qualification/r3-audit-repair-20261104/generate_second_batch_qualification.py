#!/usr/bin/env python3
"""Build a reviewable qualification summary from retained, complete evidence.

This program reads files and writes summaries only. It never runs Cargo, Bazel,
tests, GitHub actions, or a product. Run with the audit workspace as --audit-root;
the resulting documents contain relative artifact names and hashes, not local
home paths or raw test output. Original receipts remain separate evidence.
"""

import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


BASE = "e729e6c2becb528e3a6b49c9e5bbea57bd26637a"
D12 = "d12e1f208276f8986a5dcb641182ec20316ac4c8"
NATIVE = "ci-audit/native-evidence/"
STATUS_FILES = [
    "core-production-v2-status.json",
    "core-final-oracles-results.json",
    "agentd-lease-original-status.json",
    "queue-claim-originals-status.json",
    "tui-canonical-original-status.json",
    "rt-causal-results-v3.json",
    "rt-fixture-final-results.json",
    "rt-v2-close-results.json",
    "app-remote-original-negative-status.json",
    "app-native-results.json",
    "pty-tui-results.json",
    "app-signal-results.json",
]
NEGATIVE_MESSAGES = {
    "rt-causal-original-negative-v3": [
        "failed to submit turn input: NotIdle",
        "Some(BadRequest)",
        "pending_owner=true; physical_model_requests=1",
    ],
    "rt-causal-sync-audio-negative-v3": [
        "realtime audio blocked by terminalizing handoff beyond 500ms",
        "pending_owner=true; physical_model_requests=1",
    ],
    "app-remote-original-negative": [
        'WebSocket protocol error: No "Connection: upgrade" header',
    ],
    "pty-readiness-original-negative": [
        "PTY input echo satisfied readiness before Python could execute the probe",
    ],
    "tui-interrupt-old-predicate-negative": [
        "TurnStarted must not make a failed shell start ready for interrupt",
    ],
}
EXPECTED_COUNTS = {
    "core-ws-mailbox-boundary-units-v2": (8, 8, 0),
    "core-ws-production-originals-v2": (8, 7, 1),
    "core-mailbox-production-originals-v2": (8, 7, 1),
    "core-macos-oracle-lifecycle-originals-v2": (3, 3, 0),
    "core-hooks-after-lifecycle-v2": (22, 22, 0),
    "core-startup-and-compact-final-oracles": (2, 2, 0),
    "agentd-lease-original": (1, 1, 0),
    "queue-claim-originals": (4, 4, 0),
    "tui-canonical-original": (1, 1, 0),
    "rt-causal-original-negative-v3": (1, 0, 1),
    "rt-causal-sync-audio-negative-v3": (1, 0, 1),
    "rt-causal-worker-positive-v3": (3, 1, 2),
    "rt-originals-and-final-oracles-v3": (20, 20, 0),
    "ws-identity-after-realtime-v3": (2, 2, 0),
    "rt-worker-final-four-controls": (4, 3, 1),
    "rt-v2-requested-close-original": (1, 1, 0),
    "app-remote-original-negative": (2, 1, 1),
    "app-remote-fixed-originals": (19, 19, 0),
    "app-lifecycle-and-executor-originals": (14, 14, 0),
    "pty-readiness-original-negative": (1, 0, 1),
    "pty-readiness-fixed-all-originals": (28, 28, 0),
    "tui-interrupt-old-predicate-negative": (1, 0, 1),
    "tui-interrupt-fixed-all-originals": (12, 12, 0),
    "app-signal-original-negative": (5, 2, 3),
    "app-signal-fixed-parents-and-drain": (5, 5, 0),
}
SIGNAL_NAMES = {
    "shutdown_signals::tests::first_sigterm_survives_cancelled_receive",
    "shutdown_signals::tests::first_sighup_survives_cancelled_receive",
    "shutdown_signals::tests::first_sigint_survives_cancelled_receive",
    "drain_handle_tests::repeated_drain_requests_preserve_the_real_completion_acknowledgement",
    "drain_handle_tests::requesting_drain_does_not_acknowledge_outstanding_turns",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--disposition-snapshot",
        default="architecture-audit/original-failure-disposition.json",
        help="Audit-relative retained disposition snapshot; the current mapping is recorded separately.",
    )
    parser.add_argument(
        "--extra-status", action="append", default=[],
        help="Additional audit-relative native status JSON, added only with full JUnit files.",
    )
    args = parser.parse_args()
    root = args.audit_root.resolve()
    output = args.output.resolve()
    inventory = {}

    def data(relative):
        path = root / relative
        raw = path.read_bytes()
        inventory[relative] = {"artifact": relative, "bytes": len(raw), "sha256": sha(raw)}
        return raw

    def load(relative):
        return json.loads(data(relative))

    def reference(relative):
        data(relative)
        return inventory[relative]

    # This is a deliberately retained disposition snapshot. Additional native
    # reports may arrive after it; their exact original matches are listed apart.
    disposition_path = args.disposition_snapshot
    disposition = load(disposition_path)
    current_disposition_path = "architecture-audit/original-failure-disposition.json"
    current_disposition = load(current_disposition_path)
    union_path = "evidence/candidate-original-failure-union.json"
    union = load(union_path)
    require(union["count"] == len(union["tests"]) == 48, "Original union must contain48 names")
    require({x["test"] for x in disposition["entries"]} == {x["test"] for x in union["tests"]}, "Disposition and original union differ")
    require(disposition["summary"]["original_platform_gates_closed"] == 0, "This draft does not infer original-platform closure")
    original_names = {x["test"] for x in union["tests"]}
    snapshot_passes = {
        x["test"] for x in disposition["entries"]
        if x["status"] == "EXACT_NATIVE_PASS_ORIGINAL_PLATFORM_QUALIFICATION_PENDING"
    }

    source_manifests = {}
    candidates = [root / "ci-audit/core-production-v2-manifest.json"]
    candidates.extend(sorted((root / NATIVE).glob("*manifest.json")))
    for path in candidates:
        if not path.exists():
            continue
        relative = str(path.relative_to(root))
        value = load(relative)
        if not isinstance(value, dict):
            continue
        tree = value.get("source_tree", value.get("candidate_tree"))
        if tree and isinstance(value.get("files"), list):
            source_manifests.setdefault(tree, []).append({
                "receipt": inventory[relative],
                "base_commit": value.get("base_commit"),
                "source_tree": tree,
                "reported_file_count": len(value["files"]),
                "postimages": [
                    {key: item[key] for key in ("path", "bytes", "sha256", "git_blob") if key in item}
                    for item in value["files"]
                ],
                "six_line_observer_present": value.get("six_line_observer_present"),
            })

    phases = []
    missing = []
    seen = {}
    status_paths = [NATIVE + name for name in STATUS_FILES] + args.extra_status
    for status_path in status_paths:
        if not (root / status_path).exists():
            missing.append({"artifact": status_path, "state": "NO_STATUS_AVAILABLE_NOT_QUALIFIED"})
            continue
        statuses = load(status_path)
        statuses = statuses if isinstance(statuses, list) else [statuses]
        for status in statuses:
            phase = status["phase"]
            if phase in seen:
                require(seen[phase] == status, f"Conflicting duplicate native phase:{phase}")
                for qualified in phases:
                    if qualified["phase"] == phase:
                        qualified.setdefault("additional_status_receipts", []).append(inventory[status_path])
                continue
            seen[phase] = status
            junit_path = NATIVE + phase + ".junit.xml"
            if not (root / junit_path).exists():
                missing.append({"artifact": junit_path, "state": "FULL_JUNIT_NOT_AVAILABLE_NOT_QUALIFIED"})
                continue
            raw = data(junit_path)
            require(sha(raw) == status["junit_sha256"], f"JUnit hash mismatch:{phase}")
            xml = ET.fromstring(raw)
            source_tree = status.get("source_tree", status.get("source_tree_with_diagnostics"))
            require(isinstance(source_tree, str) and re.fullmatch(r"[0-9a-f]{40}", source_tree), f"Missing immutable tree:{phase}")
            source_unchanged = status.get("source_unchanged")
            source_recheck = None
            if source_unchanged is None and source_tree == D12:
                source_recheck = NATIVE + "core-production-v2-source-recheck.json"
                check = load(source_recheck)
                require(check["source_tree"] == source_tree, "d12 recheck source mismatch")
                source_unchanged = check["source_unchanged"]
            require(source_unchanged is True, f"Missing source unchanged proof:{phase}")
            require(status.get("selection_complete") is True, f"Incomplete native selection:{phase}")
            command = status["command"]
            require("--retries" in command and command[command.index("--retries") + 1] == "0", f"Retries not zero:{phase}")
            cases = []
            for case in xml.iter("testcase"):
                result = "FAIL" if case.find("failure") is not None or case.find("error") is not None else "SKIP" if case.find("skipped") is not None else "PASS"
                cases.append({"test": case.attrib["name"], "binary": case.attrib.get("classname"), "result": result, "seconds": float(case.attrib.get("time", "0")), "in_original_failure_union": case.attrib["name"] in original_names})
            require(len(cases) == int(xml.attrib["tests"]), f"JUnit selected count differs:{phase}")
            require({x["test"] for x in cases} == {x["name"] for x in status["testcases"]}, f"JUnit/status roster differs:{phase}")
            counts = collections.Counter(x["result"] for x in cases)
            if status["exit_code"] == 0:
                require(counts["FAIL"] == 0, f"Successful phase has failing case:{phase}")
            if phase in NEGATIVE_MESSAGES:
                text = "\n".join(node.text or "" for node in xml.iter() if node.tag in {"failure", "error", "system-err", "system-out"})
                require(all(message in text for message in NEGATIVE_MESSAGES[phase]), f"Targeted causal observation missing:{phase}")
            if phase.startswith("app-signal-"):
                require({case["test"] for case in cases} == SIGNAL_NAMES, "Signal roster must be the exact five parent/drain cases")
            if phase == "app-signal-original-negative":
                native_source = data(NATIVE + "app-signal-native-shutdown-signals-tests.rs")
                require(sha(native_source) == "c664383fe6d0943e9df9be1ca8acc21b3c9b16e2926e5cb42bf13bb7625d4537", "Signal source differs from reviewed fixture")
                source_lines = native_source.decode().splitlines()
                require("delivered.recv()" in source_lines[114] and "retained.recv()" in source_lines[115], "Signal causal source-order mismatch")
                failed_signal_names = set()
                for case in xml.iter("testcase"):
                    if case.find("failure") is not None or case.find("error") is not None:
                        text = "\n".join(case.itertext())
                        require("deadline has elapsed" in text and "./src/shutdown_signals_tests.rs:116:16" in text, "Signal failure is not the retained receive after confirmed delivery")
                        failed_signal_names.add(case.attrib["name"])
                require(failed_signal_names == {name for name in SIGNAL_NAMES if name.startswith("shutdown_signals::tests::")}, "Unexpected signal negative-control failure set")
            phases.append({
                "phase": phase, "source_tree": source_tree,
                "source_stage": status.get("source_stage"),
                "status_receipt": inventory[status_path], "junit": inventory[junit_path],
                "source_recheck": inventory.get(source_recheck),
                "source_manifest_receipts": [m["receipt"] for m in source_manifests.get(source_tree, [])],
                "source_manifest_limit": None if source_tree in source_manifests else "No separate full file manifest is attached for this stage; the exact tree and unchanged-source status are retained.",
                "command": command, "exit_code": status["exit_code"],
                "uuid": xml.attrib.get("uuid"), "timestamp": xml.attrib.get("timestamp"),
                "selected": len(cases), "passed": counts["PASS"], "failed": counts["FAIL"], "skipped": counts["SKIP"],
                "whole_phase_elapsed_seconds": status.get("elapsed_seconds"),
                "junit_elapsed_seconds": float(xml.attrib.get("time", "0")),
                "selection_complete": True, "source_unchanged": True, "retries": 0,
                "targeted_negative_observations": NEGATIVE_MESSAGES.get(phase, []),
                "cases": cases,
                "scope": "Only this exact native source stage and selected roster; no final combined-source or original-platform qualification is inferred.",
            })

    phase_index = {phase["phase"]: phase for phase in phases}
    for name, counts in EXPECTED_COUNTS.items():
        require(name in phase_index, f"Missing complete receipt for a documented historical phase: {name}")
        phase = phase_index[name]
        require(tuple(phase[key] for key in ("selected", "passed", "failed")) == counts, f"Retained historical phase outcome changed: {name}")
        require(phase["skipped"] == 0, f"Documented phase unexpectedly contains skips: {name}")

    lane_path = NATIVE + "native-host-toolchain-receipt.json"
    lane = load(lane_path)
    lane_summary = {
        "receipt": inventory[lane_path], "captured_unix": lane["captured_unix"],
        "source_tree_at_capture": lane["source_tree"],
        "os": lane["uname"]["system"], "architecture": lane["uname"]["machine"],
        "kernel_release": lane["uname"]["release"], "rustc_vV": lane["rustc_vV"],
        "active_toolchain": lane["active_toolchain"].split()[0],
        "repository_toolchain_sha256": lane["rust_toolchain_sha256"],
        "scope": "Direct Linux x86_64 lane observation at AppServer startup on tree 8940; not a separately captured OS/toolchain receipt for each earlier run.",
    }

    helpers = []
    for run_id, expected_count, scope in [
        (41851347278, 805, "Four reviewed Exec Server helper source postimages"),
        (41865994466, 806, "Combined four Exec Server and two CLI helper source postimages"),
    ]:
        prefix = f"websocket-audit/bazel-lock-workflow/run-{run_id}/"
        receipt_path = prefix + "artifact/generated/receipt.json"
        if not (root / receipt_path).exists():
            helpers.append({"run_id": run_id, "scope": scope, "state": "NO_GENERATED_RECEIPT_AVAILABLE"})
            continue
        receipt = load(receipt_path)
        generated = prefix + "artifact/generated/"
        inputs = load(generated + "source-inputs.json")
        require(len(inputs) == expected_count, "Unexpected helper source-input inventory")
        require(data(generated + "source-inputs.json") == data(generated + "source-inputs-after.json"), "Helper input drift")
        expected_steps = [("original-lock-update", ["just", "bazel-lock-update"], 0), ("original-lock-check", ["just", "bazel-lock-check"], 0)]
        require([(x["name"], x["command"], x["exit_code"]) for x in receipt["steps"]] == expected_steps, "Original lock recipes did not both succeed")
        for name, claimed in receipt["outputs"].items():
            observed = reference(generated + name)
            require({k: observed[k] for k in ("bytes", "sha256")} == claimed, f"Generator output hash differs:{name}")
        lock = reference(generated + "MODULE.bazel.lock")
        require(lock["sha256"] == receipt["generated_lock_sha256"] and lock["bytes"] == receipt["generated_lock_bytes"], "Generated lock identity mismatch")
        verification_path = prefix + "verification.json"
        verification = load(verification_path) if (root / verification_path).exists() else None
        api = load(prefix + "run-final.json") if (root / (prefix + "run-final.json")).exists() else None
        terminal = bool(api and api["status"] == "completed" and api["conclusion"] == "success" and api["head_sha"] == receipt["commit"])
        fully_verified = bool(verification and terminal and verification["source_commit"] == receipt["commit"])
        helpers.append({
            "run_id": run_id, "run_url": f"https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/{run_id}",
            "scope": scope, "source_commit": receipt["commit"], "parent": receipt["parent"],
            "source_base": receipt.get("source_base", receipt["parent"]),
            "source_input_count": len(inputs), "source_inputs": inventory[generated + "source-inputs.json"],
            "source_inputs_after": inventory[generated + "source-inputs-after.json"],
            "input_bytes_unchanged": True, "generated_receipt": inventory[receipt_path],
            "steps": receipt["steps"], "module_lock": lock,
            "committed_lock_matches": receipt["committed_lock_matches"],
            "state": verification["status"] if fully_verified else "ORIGINAL_COMMANDS_EXIT0_ARTIFACT_RECEIPT_PRESENT_FULL_API_TERMINAL_VERIFICATION_PENDING",
            "api_terminal_success_verified": terminal,
            "full_artifact_verification": inventory.get(verification_path),
            "product_qualification": False,
        })

    all_passes = {case["test"] for phase in phases for case in phase["cases"] if case["result"] == "PASS" and case["in_original_failure_union"]}
    pending = [
        "Final product commit/tree and full original CI matrix have not been certified by this document.",
        "Windows token/legacy outside-delete production failures remain open; helper layout does not change or qualify the restricted production boundary.",
        "Windows Code Mode approval-path timing remains diagnostic; no cause is closed by native results from a different platform.",
        "Windows private-state acquisition original positives and two real negative controls remain independent gates.",
        "macOS Intel PTY drain root cause remains unproved despite the unchanged-budget Linux case passing.",
        "Additional native reports require complete matching JUnit/status/source receipts before inclusion; no process is polled or started by this generator.",
    ]
    roster_path = "architecture-audit/pty-diagnosis/platform-roster-correction.json"
    roster = load(roster_path) if (root / roster_path).exists() else None
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repository": "TrillionniumFoundation/hepta-private-ci", "original_product_head": BASE,
        "scope": "Second-batch evidence summary across explicitly different exact source trees. This is neither a final combined-tree all-pass claim nor original-platform closure.",
        "original_failure_snapshot": {
            "source": inventory[disposition_path], "snapshot_generated_at_utc": disposition["generated_at_utc"],
            "union": inventory[union_path], "unique_names": 48,
            "names_are_not_root_causes": True,
            "exact_native_pass_names_at_snapshot": len(snapshot_passes),
            "original_platform_gates_closed": 0,
            "status_counts": disposition["summary"]["status_counts"],
            "new_exact_original_pass_names_in_later_attached_reports": sorted(all_passes - snapshot_passes),
            "entries": [{
                "test": x["test"], "status_at_snapshot": x["status"],
                "workstream": x["workstream"], "patch_refs": x["patch_refs"],
                "original_platforms": [p["platform"] for p in x["original_occurrences"]],
                "original_platform_gate": "PENDING", "closed": False,
            } for x in disposition["entries"]],
        },
        "retained_previous_parser_union": {
            "count": 47,
            "evidence": reference("evidence/candidate-original-failure-union-before-ansi-fix.json"),
            "interpretation": "Superseded only by the ANSI-corrected 48-name inventory; the previous artifact is retained.",
        },
        "current_failure_mapping": {
            "source": inventory[current_disposition_path],
            "generated_at_utc": current_disposition["generated_at_utc"],
            "status_counts": current_disposition["summary"]["status_counts"],
            "exact_original_cases_with_latest_native_pass": current_disposition["summary"].get("exact_original_cases_with_latest_native_pass"),
            "native_pass_with_root_cause_still_open": current_disposition["summary"].get("native_pass_with_root_cause_still_open", []),
            "original_platform_gates_closed": current_disposition["summary"]["original_platform_gates_closed"],
            "interpretation": "A latest native PASS is evidence of that execution. It does not establish the cause or repair of an original failure on another platform; PTY drain remains OPEN_DIAGNOSTIC_ONLY.",
        },
        "native_lane": lane_summary, "native_phases": phases,
        "source_manifests": source_manifests,
        "realtime_interpretation": {
            "baseline_scope": "Combined prior repairs with original RT production/session input, not otherwise-unmodified e729.",
            "causal_negative": "Actual NotIdle under pending ownership; the six-line synchronous observer separately fails the 500 ms audio budget.",
            "historical_fixture_failures_retained": "Worker tree 36e6 passed 1/3 because two new negative fixtures incorrectly expected 2 requests. Corrected tree 8940 passed three V1 controls, while V2 failed at the peer reset after explicit close. The narrow requested-close fixture correction passed the exact V2 case on tree 3b5.",
            "all_four_same_execution_claimed": False,
            "six_line_observer_admitted_to_product": False,
            "protocol_limit": "No universal one-handoff-ID/one-turn invariant or atomic post-close generation exclusion is inferred.",
        },
        "appserver_interpretation": "The original handshake baseline fails when its models GET reaches the WebSocket handshake; the companion non-upgrade control passes. The fixed remote group passes 19/19 and the lifecycle/executor group passes 14/14 on tree 98e7. These 33 selected cases include 11 names in the original 48-failure union.",
        "pty_platform_roster": None if roster is None else {
            "evidence": inventory[roster_path], "linux": 28, "macos": 30,
            "reason": "Two process_group tests are compiled only for macOS. Linux has 27 original cases plus 1 new gate; macOS has 29 original cases plus 1 new gate.",
            "preserved_runner_failure": "The initial runner stopped after Linux 28/28 passed because its count assertion incorrectly expected 30. The original runner failure remains retained separately from the passing product cases; those 28 cases are not rerun merely to change the count.",
            "original_intel_qualification": "PENDING",
        },
        "helper_lock_generation": helpers,
        "additional_workstreams_outside_original_failure_union": [{
            "id": "B23",
            "name": "AppServer retained shutdown-signal subscription lifetime",
            "in_original_48_name_count": False,
            "native_phase_refs": [p["phase"] for p in phases if any(c["test"].startswith("shutdown_signals::tests::") for c in p["cases"])],
            "state": "REAL_CANCELLED_RECEIVE_CAUSAL_NEGATIVE_AND_FIXED_FIVE_CASE_NATIVE_PASS_ORIGINAL_PLATFORM_PENDING",
            "negative_cause": "Each failed TERM/HUP/INT parent's complete child backtrace identifies source line116 retained.recv timeout. The byte-identical native fixture confirms line115 already awaited independent delivered.recv and asserted Some(()).",
            "native_source": inventory[NATIVE + "app-signal-native-shutdown-signals-tests.rs"],
            "source_lines": {"115": "Independent delivery is observed and asserted", "116": "Retained receive times out in all three original-control children"},
            "fixed_source_tree": phase_index["app-signal-fixed-parents-and-drain"]["source_tree"],
            "fixed_selected_parent_and_original_cases": 5,
            "ignored_owned_child_counted_as_pass": False,
            "intentional_startup_change": "Configured signal registration failure now propagates before opening acceptors; drain and second-signal rules remain unchanged.",
            "qualification_rule": "These are actual candidate executions, not inherited donor results. Final composed-source and original-platform CI remain independent gates.",
        }],
        "remaining_gates": pending,
        "incomplete_or_absent_native_inputs": missing,
        "evidence_inventory": list(inventory.values()),
        "generator_boundary": "Read-only evidence parsing and summary generation. No Cargo/Bazel/native execution, workflow dispatch, publication, secret data or local-home paths in this output.",
    }
    json_text = json.dumps(report, indent=2) + "\n"
    document = render_markdown(report)
    reject = re.compile(r"(?i)/home/|/Users/|[A-Z]:\\\\Users\\\\|X-Amz-|(?:[?&](?:sig|token|access_token)=)|Authorization:\s*Bearer|-----BEGIN .*PRIVATE KEY")
    require(not reject.search(json_text + document), "Output contains a prohibited local-home path or credential-shaped value")
    output.mkdir(parents=True, exist_ok=True)
    (output / "second-batch-qualification.json").write_text(json_text)
    (output / "SECOND_BATCH_QUALIFICATION.md").write_text(document)
    print(json.dumps({
        "native_phases": len(phases),
        "snapshot_original_names": 48, "snapshot_exact_native_pass_names": len(snapshot_passes),
        "later_original_pass_names": sorted(all_passes - snapshot_passes),
        "original_platform_gates_closed": 0,
        "outputs": {name: {"bytes": (output / name).stat().st_size, "sha256": sha((output / name).read_bytes())} for name in ["second-batch-qualification.json", "SECOND_BATCH_QUALIFICATION.md"]},
    }, indent=2))


def render_markdown(report):
    snapshot = report["original_failure_snapshot"]
    current = report["current_failure_mapping"]
    classified = current["status_counts"].get("EXACT_NATIVE_PASS_ORIGINAL_PLATFORM_QUALIFICATION_PENDING", 0)
    lines = [
        "# Second-batch qualification evidence",
        "",
        f"Generated: {report['generated_at_utc']}",
        "",
        "This package records actual native runs on different fixed source trees. **It does not certify a final combined product tree or close the original macOS/Windows/Linux CI gates.** Original JUnit, status and source-manifest identities are retained in `second-batch-qualification.json`; no raw test-output prompt or local runtime path is reproduced here.",
        "",
        "## Original failure accounting",
        "",
        f"The current mapping at `{current['generated_at_utc']}` classifies **{classified} of the 48 original names** as native-pass/awaiting-platform. It separately records **{current['exact_original_cases_with_latest_native_pass']}** names with a latest native PASS. The difference is the PTY drain case, which remains `OPEN_DIAGNOSTIC_ONLY`: its Linux success does not prove that the original Intel cause was repaired. Original-platform closures remain **0**.",
        "",
        f"The ANSI-corrected original union contains **48 distinct failing test names**. The retained disposition snapshot at `{snapshot['snapshot_generated_at_utc']}` has **{snapshot['exact_native_pass_names_at_snapshot']} exact native original-case passes** and **0 original-platform closures**. Names are not a root-cause count. The earlier 47-name parser result and failed attempts remain historical evidence.",
        "",
        "The 48-name snapshot remains distinct from later reports attached to this package. Newly passing original names received after that snapshot are listed below and are not silently substituted into the frozen snapshot count:",
        "",
    ]
    additions = snapshot["new_exact_original_pass_names_in_later_attached_reports"]
    lines.extend([f"- `{name}`" for name in additions] or ["- None."])
    lines.extend([
        "", "## Native executions", "",
        "Each row has a complete JUnit matching its retained status hash, an exact source tree, unchanged-source proof, complete selection and zero retries. A negative-control failure is intentional only where its targeted observation was independently found in the complete output. The whole phase status remains visible.",
        "", "| Phase | Source tree | Selected | Pass | Fail | Skip | Phase exit |", "|---|---|---:|---:|---:|---:|---:|",
    ])
    for p in report["native_phases"]:
        lines.append(f"| `{p['phase']}` | `{p['source_tree']}` | {p['selected']} | {p['passed']} | {p['failed']} | {p['skipped']} | {p['exit_code']} |")
    lines.extend([
        "", "### Interpretation of the retained failures", "",
        "- **Core d12:** 49 selected, 47 passed and 2 failed. These two failures are preserved. The later exact startup/compact oracle run passed 2/2 on tree 7ff; it does not erase the d12 results.",
        "- **Realtime baseline:** the combined repair base with original realtime production rejects the second handoff with `NotIdle/BadRequest` while the owner is pending and only one physical model request exists. The six-line synchronous observer separately blocks audio beyond the unchanged 500 ms budget and is excluded from the product.",
        "- **Realtime worker:** the 36e6 three-control attempt passed 1 and failed 2 because its new negative fixture expected two requests while asserting one. Correcting only that internal fixture contradiction yielded three V1 passes on tree 8940. The V2 test's later explicit-close reset failure is retained; the narrow requested-close correction passes the exact V2 case on tree 3b5. There is no all-four-in-one-execution claim. The original realtime/final-oracle 20/20 and identity 2/2 reports are separate.",
        "- **AppServer:** the original handshake baseline records 1 failure and 1 companion-control pass. The failure is the models request reaching the WebSocket handshake without its upgrade header. The fixed original remote group passes 19/19 and the lifecycle/executor group passes 14/14 on tree 98e7. Those 33 selected cases include 11 names in the original 48-name union.",
        "- **PTY:** complete JUnit and status receipts verify the echo-before-execution baseline failure and the repaired Linux 28/28 result on tree a3a25267. The previous expected-30 runner check was wrong for Linux: two original process-group cases are macOS-only. That runner failure, all original budgets and the original Intel gate remain visible. The diagnostic drain case's Linux pass does not establish the original Intel cause or its repair.",
        "- **TUI interrupt/shutdown:** the extracted old readiness predicate fails the real failed-start control with the expected `TurnStarted must not make a failed shell start ready for interrupt` diagnostic. The repaired group passes 12/12 on tree 7c437033, including all 11 original cases and the new failed-start control. The original Windows gate remains open.",
        "- **Signal follow-up (B23):** the baseline has three failed TERM/HUP/INT parents and two passing original drain cases. Each complete child backtrace identifies the timeout at source line 116 (`retained.recv`), after line 115 confirmed independent delivery. The actual native fixture is byte-identical to the reviewed source. The fixed five-case roster passes 5/5 on tree 57b8d270 in 0.089 seconds. This new issue remains outside the original 48-name union. The ignored helper is executed inside each owned child and acknowledged privately; it is not counted as an extra parent pass. Signal registration failure now intentionally propagates before acceptors open. Final product/platform CI remains pending.",
        "", "## Native platform scope", "",
        "The directly retained lane receipt observes Linux x86_64 with Rust 1.95.0 at AppServer startup on tree 8940. It is a current same-lane observation, not an independently captured platform receipt for every earlier JUnit. No macOS, Windows, Wine or final Bazel product qualification is inferred.",
        "", "## Helper dependency generation", "",
        "| Hosted run | Exact source | Actual inputs | Scope | State |", "|---|---|---:|---|---|",
    ])
    for h in report["helper_lock_generation"]:
        lines.append(f"| {h['run_id']} | `{h.get('source_commit', 'unavailable')}` | {h.get('source_input_count', 'unavailable')} | {h['scope']} | `{h['state']}` |")
    lines.extend([
        "",
        "The first 805-input run covers the four Exec Server helper postimages. The combined 806-input run additionally covers the two reviewed CLI files; the added inventory entry is the CLI test source because its BUILD file was already tracked in the original 805 inputs. Both use the real original `just bazel-lock-update` and `just bazel-lock-check` commands. Their exact step durations, API terminal states and artifact-verification receipts are recorded separately in the JSON. Neither artifact branch is product qualification.",
        "", "## Gates still open", "",
    ])
    helpers = report["helper_lock_generation"]
    if helpers and all(h.get("api_terminal_success_verified") and h.get("full_artifact_verification") for h in helpers):
        conclusion = "Both hosted runs have terminal-success API evidence and complete artifact verification."
        lock_hashes = {h["module_lock"]["sha256"] for h in helpers}
        if len(lock_hashes) == 1 and all(h["committed_lock_matches"] for h in helpers):
            conclusion += f" Both actual generated locks remain byte-identical to the committed source lock: SHA-256 `{next(iter(lock_hashes))}`. No lock diff was manufactured."
        else:
            conclusion += " Their actual lock changes and byte identities remain recorded per run; no no-drift result is inferred."
        lines.insert(lines.index("## Gates still open"), conclusion + "\n")
    lines.extend(f"- {item}" for item in report["remaining_gates"])
    lines.extend([
        "", "## Reproduce this summary", "",
        "```sh",
        "python3 generate_second_batch_qualification.py --audit-root AUDIT_EVIDENCE_DIRECTORY --output OUTPUT_DIRECTORY",
        "```", "",
        "The generator only parses retained evidence. Use `--disposition-snapshot AUDIT_RELATIVE_SNAPSHOT_JSON` to retain a historical count while also reporting the current mapping. Additional signal/TUI result files can be supplied with `--extra-status AUDIT_RELATIVE_STATUS_JSON`; their complete JUnit must be present and hash-identical before inclusion. Run failures, source changes or missing evidence cause a validation error or an explicit pending entry. The enclosing publication should retain the referenced original receipts and the final composed source manifest alongside this summary.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
