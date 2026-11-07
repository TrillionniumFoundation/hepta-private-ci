from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def pin(path):
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def main():
    source_inputs = json.loads((ROOT / "SOURCE-INPUT-PINS.json").read_text())
    for row in source_inputs["files"]:
        actual = pin(ROOT / "original" / row["path"])
        assert all(actual[key] == row[key] for key in ("bytes", "sha256", "git_blob")), row["path"]
    failure_index = json.loads((ROOT / "evidence/FAILURE-INDEX.json").read_text())
    failure = failure_index["failure"]
    failure_pin = pin(ROOT / "evidence/failure-1.txt")
    assert all(failure_pin[key] == failure[key] for key in ("bytes", "sha256", "git_blob"))
    assert failure["end_byte_offset"] - failure["start_byte_offset"] == failure_pin["bytes"]
    fixture = ROOT / "original/codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"
    native_pins = json.loads((ROOT / "evidence/NATIVE-SOURCE-PINS.json").read_text())
    native_fixture = native_pins["files"][0]
    assert all(pin(fixture)[key] == native_fixture[key] for key in ("bytes", "sha256", "git_blob"))
    guard = json.loads((ROOT / "evidence/native-workspace-r29-source-post-test-verification.json").read_text())
    assert guard["pass"] and guard["actual_tree"] == source_inputs["source_tree"]
    assert guard["gate_exit_code"] == 100 and guard["changed_file_count"] == 195
    report = {
        "schema": "hepta.bedrock-r29-initial-causal-readback.v1",
        "status": "READ_ONLY_CAUSAL_BOUNDARY_IDENTIFIED_ROOT_CAUSE_UNRESOLVED",
        "source_commit": source_inputs["source_commit"],
        "source_tree": source_inputs["source_tree"],
        "source_input_pin": pin(ROOT / "SOURCE-INPUT-PINS.json"),
        "native_fixture_matches_fixed_git_source": True,
        "source_copies_verified": len(source_inputs["files"]),
        "failure": failure,
        "failure_pin": failure_pin,
        "observed_facts": [
            "The original nextest record is FAIL, not TIMEOUT, lasting 10.643 seconds.",
            "Initialize response ID 0 was received, initialized notification sent, and first Profile setup request ID 1 sent.",
            "The response reader saw only remoteControl/status/changed before returning Error: deadline has elapsed.",
            "There is no handler-enter marker, await-stage marker, stack frame, outgoing response, DNS result, network syscall trace, or measured CPU scheduling evidence in this failure block.",
            "The failure occurs before the first response/config/dotenv assertion and before the second managed-credential server is constructed.",
        ],
        "source_chain": [
            {"path": "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs", "lines": [19, 54], "finding": "The original 60-second suite constant bounds initialization; the helper writes deterministic local profile/config files and disables EC2 metadata."},
            {"path": "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs", "lines": [143, 152], "finding": "The first request uses TestAppServer::request; whitespace in profile and region is intentional normalization coverage."},
            {"path": "codex-rs/app-server/tests/common/test_app_server.rs", "lines": [171, 174], "finding": "The existing non-Windows default request timeout is 10 seconds."},
            {"path": "codex-rs/app-server/tests/common/test_app_server.rs", "lines": [1546, 1559], "finding": "The typed request writes the request and wraps read_response in the original default timeout."},
            {"path": "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs", "lines": [68, 134], "finding": "Setup checks allowed login/config precedence, validates the selected profile, cancels any active login, persists provider settings, and returns an empty response. It does not call model refresh or authentication reload."},
            {"path": "codex-rs/aws-auth/src/discovery.rs", "lines": [46, 75], "finding": "Profile validation uses the explicit region and named ProfileFileCredentialsProvider; the DefaultRegionChain branch is not selected for this request."},
            {"path": "codex-rs/third_party/aws-config-1.12.0/src/profile/credentials/repr.rs", "lines": [128, 220], "finding": "With the exact fixture profile fields and no role ARN, the representation resolves one base provider and an empty assume-role chain."},
            {"path": "codex-rs/third_party/aws-config-1.12.0/src/profile/credentials/repr.rs", "lines": [258, 272], "finding": "The fixture has no credential_source, web identity, SSO, login session, or credential_process field, so its base resolves to static access keys."},
            {"path": "codex-rs/third_party/aws-config-1.12.0/src/profile/credentials/exec.rs", "lines": [88, 103], "finding": "The static AccessKey branch wraps the provided credentials rather than creating a network credential provider."},
            {"path": "codex-rs/app-server/src/request_processors/bedrock_auth.rs", "lines": [22, 70], "finding": "Provider configuration batches model_provider/profile/region edits and sets reload_user_config=false."},
            {"path": "codex-rs/app-server/src/config_manager_service.rs", "lines": [202, 466], "finding": "The manager applies edits through config-layer loading, local validation, and ConfigEditsBuilder persistence; no model-list/auth reload call is present in this method."},
            {"path": "codex-rs/core/src/config/edit.rs", "lines": [998, 1005], "finding": "Persistence awaits spawn_blocking of the existing local atomic file-update path."},
            {"path": "codex-rs/cloud-config/src/service.rs", "lines": [106, 115], "finding": "The cloud loader is cached via OnceCell and a short clone lock. This is a conditional external-capable dependency of config loading, not an observed failed HTTP request."},
        ],
        "limitations": [
            "Source analysis explains reachable boundaries; it does not prove which boundary actually stalled in the original run.",
            "Static-profile network exclusion is specific to the fixture's declared profile contents; it is not a statement that every account/setup configuration is network-free.",
            "No attribution is made to DNS, AWS endpoint delay, host load, filesystem latency, lock contention, or connection scheduling.",
            "The full workspace counts above are taken from the original runner review; this report independently verifies only this full failure excerpt and source pins, not the complete 2.5 MB log.",
            "Dispatch/initialized sequencing is delegated for a bounded independent review; its conclusion is not assumed here.",
        ],
        "repair_decision": {
            "behavior_candidate_created": False,
            "production_defect_proven": False,
            "fixture_external_mock_omission_proven": False,
            "reason": "The existing original record does not identify the awaited operation that failed to complete; changing behavior or isolating an unobserved network call would be speculative.",
            "minimal_next_evidence_if_dispatch_review_is_inconclusive": "An explicitly diagnostic-only candidate can record entry/exit stage labels around the existing setup awaits and the configuration persistence boundary, without raw credentials/profile contents, retries, extra RPCs, timeout changes, or assertion changes. Execution requires root/native coordination and would not itself be a repair or qualification.",
        },
        "source_mutated": False,
        "rust_or_tests_or_probes_executed": False,
        "finalizer_execution_authorized": False,
        "r29_failed_result_preserved": True,
    }
    output = ROOT / "INITIAL-CAUSAL-READBACK.json"
    data = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    with output.open("xb") as handle:
        handle.write(data)
    print(json.dumps(pin(output), indent=2))


if __name__ == "__main__":
    main()
