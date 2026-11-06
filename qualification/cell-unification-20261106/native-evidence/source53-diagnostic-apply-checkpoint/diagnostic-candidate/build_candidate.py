from pathlib import Path
import difflib
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
INPUT = ROOT.parent / "app-server-bedrock-r29-investigation"
COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
HANDLER = "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs"
FIXTURE = "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"
EXPECTED = {
    HANDLER: "af9ceab5047c7ee06bba84d47684748b38bfbb32e287db4a6fca84b2b45fa6fa",
    FIXTURE: "25c5036f352b673af21adfd37930f3f1762359b7422084c6e4eaaa9c1f513d55",
}


def pin(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def create(relative, data):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def emit(stage, indent="        "):
    return (
        indent + "tracing::info!(\n"
        + indent + '    target: "bedrock_setup_diagnostic",\n'
        + indent + f'    stage = "{stage}",\n'
        + indent + '    "diagnostic-only Bedrock setup boundary"\n'
        + indent + ");\n"
    )


def main():
    originals = {path: (INPUT / "original" / path).read_bytes() for path in EXPECTED}
    for path, data in originals.items():
        assert pin(data)["sha256"] == EXPECTED[path]
    handler = originals[HANDLER].decode()
    fixture = originals[FIXTURE].decode()
    operations = []

    def replace(path, text, old, new, label):
        assert text.count(old) == 1, (path, label, text.count(old))
        operations.append({"path": path, "label": label, "before": old, "after": new})
        return text.replace(old, new, 1)

    entry = (
        "    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {\n"
        "        self.ensure_bedrock_login_allowed()?;\n"
        "        ensure_user_model_provider_can_be_bedrock(&self.config_manager).await?;\n"
    )
    handler = replace(
        HANDLER, handler, entry,
        "    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {\n"
        + emit("handler_entered")
        + "        self.ensure_bedrock_login_allowed()?;\n"
        + emit("config_precedence_start")
        + "        ensure_user_model_provider_can_be_bedrock(&self.config_manager).await?;\n"
        + emit("config_precedence_complete"),
        "entry-and-config-precedence-await",
    )
    start = "                codex_aws_auth::validate_aws_profile(profile, region)\n"
    handler = replace(HANDLER, handler, start, emit("profile_validation_start", "                ") + start, "profile-validation-start")
    end = "                    })?;\n                Some(profile.to_string())\n"
    handler = replace(HANDLER, handler, end, "                    })?;\n" + emit("profile_validation_complete", "                ") + "                Some(profile.to_string())\n", "profile-validation-complete")
    cancel = "        self.cancel_active_login().await;\n"
    handler = replace(HANDLER, handler, cancel, emit("login_cancel_start") + cancel + emit("login_cancel_complete"), "original-login-cancel-await")
    configure = "        configure_bedrock_provider(\n"
    handler = replace(HANDLER, handler, configure, emit("provider_config_start") + configure, "provider-config-start")
    response = "        .await?;\n\n        Ok(Some(BedrockSetupResponse {}.into()))\n"
    handler = replace(HANDLER, handler, response, "        .await?;\n" + emit("provider_config_complete") + "\n        Ok(Some(BedrockSetupResponse {}.into()))\n", "provider-config-complete")

    environment = '            ("AWS_DEFAULT_REGION", Some("us-east-1")),\n'
    log_filter = "warn,codex_app_server::app_server_tracing=info,codex_app_server::request_serialization=debug,bedrock_setup_diagnostic=info"
    fixture = replace(
        FIXTURE, fixture, environment,
        environment
        + "            (\n"
        + '                "RUST_LOG",\n'
        + f'                Some("{log_filter}"),\n'
        + "            ),\n",
        "only-original-failed-test-first-child-log-filter",
    )
    candidates = {HANDLER: handler.encode(), FIXTURE: fixture.encode()}
    for path, after in candidates.items():
        reverted = after.decode()
        for operation in reversed(operations):
            if operation["path"] == path:
                assert reverted.count(operation["after"]) == 1
                reverted = reverted.replace(operation["after"], operation["before"], 1)
        assert reverted.encode() == originals[path], path
    fixture_before = originals[FIXTURE].decode()
    assert fixture_before.count(".await") == fixture.count(".await")
    assert fixture_before.count(".request(") == fixture.count(".request(")
    assert originals[HANDLER].decode().count(".await") == handler.count(".await")
    assert re.findall(r"(?m)^\s*#\[.*$", fixture_before) == re.findall(r"(?m)^\s*#\[.*$", fixture)
    assertion_lines_before = re.findall(r"(?m)^\s*assert(?:_eq|_ne)?!.*$", fixture_before)
    assert assertion_lines_before == re.findall(r"(?m)^\s*assert(?:_eq|_ne)?!.*$", fixture)
    assert 'Duration::from_secs(/*secs*/ 60)' in fixture
    assert 'DEFAULT_REQUEST_TIMEOUT' not in fixture
    assert handler.count('target: "bedrock_setup_diagnostic"') == 9
    stage_fields = re.findall(r'stage = "([a-z_]+)"', handler)
    assert len(stage_fields) == len(set(stage_fields)) == 9
    patch = "".join(
        "".join(difflib.unified_diff(originals[path].decode().splitlines(keepends=True), candidates[path].decode().splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
        for path in sorted(candidates)
    ).encode()
    rows = []
    for path in sorted(candidates):
        create("original/" + path, originals[path])
        create("source/" + path, candidates[path])
        rows.append({"path": path, "mode": "100644", "before": pin(originals[path]), "after": pin(candidates[path])})
    create("diagnostic.patch", patch)
    create("edit-operations.json", (json.dumps(operations, indent=2) + "\n").encode())
    manifest = {
        "schema": "hepta.bedrock-r29-diagnostic-candidate.v1",
        "classification": "DIAGNOSTIC_ONLY_NOT_A_REPAIR_OR_QUALIFICATION",
        "source_before_commit": COMMIT,
        "source_before_tree": TREE,
        "candidate_git_commit": None,
        "candidate_git_tree": None,
        "execution_authorized": False,
        "execution_performed": False,
        "files": rows,
        "patch": {"path": "diagnostic.patch", **pin(patch)},
        "stage_labels": stage_fields,
        "log_filter": log_filter,
        "log_filter_scope": "Only first child of original setup_bedrock_profile_and_environment case; parent process and second managed child remain unchanged.",
        "new_logged_values": "Nine fixed stage strings and one fixed message. No profile, region, credentials, request payload, filesystem path, or environmental value added.",
        "existing_span_values": "Existing app_server.request method/request ID/connection ID/client info, plus static account-auth queue scope; no new params logging enabled.",
        "await_count_before_after": {path: [originals[path].decode().count('.await'), candidates[path].decode().count('.await')] for path in candidates},
        "fixture_assertion_macros_retained": len(assertion_lines_before),
        "original_request_and_initialization_timeouts_unchanged": True,
        "original_test_attributes_requests_responses_and_oracles_unchanged": True,
        "inverse_whole_file_bytes_exact": True,
        "parent_environment_mutated": False,
        "production_behavior_fix_claimed": False,
        "r29_failed_100_preserved": True,
        "rust_or_tests_run": False,
    }
    data = (json.dumps(manifest, indent=2) + "\n").encode()
    create("source-manifest.json", data)
    print(json.dumps({"manifest": pin(data), "patch": pin(patch), "files": rows, "stage_count": len(stage_fields)}, indent=2))


if __name__ == "__main__":
    main()
