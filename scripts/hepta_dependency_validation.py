"""Data-only contracts for the isolated dependency validation workflow."""

import hashlib
import json
import re
import xml.etree.ElementTree as ET

BRANCH = "refs/heads/research/parameter-field-dependency-validation-20261028"
REGRESSION_PATH = "codex-rs/core-plugins/src/startup_sync_zip_tests.rs"
REGRESSION_NAME = (
    "startup_sync::zip_tests::"
    "extract_zipball_strips_privileged_modes_and_preserves_regular_permissions"
)
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
TLS = {
    "rustls": "0.23.46",
    "rustls-webpki": "0.103.16",
    "webpki-root-certs": "1.0.10",
    "webpki-roots": "1.0.10",
}
RUNNER_FILES = (
    "scripts/run_hepta_dependency_validation.py",
    "scripts/hepta_dependency_validation.py",
    "scripts/test_hepta_dependency_validation.py",
    "scripts/run_hepta_field_maintenance.py",
    "scripts/capture_cargo_deny_diagnostic.py",
)
NEXTEST_STORE_SOURCE = {
    "commit": "d2e7b879fb79975e8b47a8e3ce569b651e6381c0",
    "profile_store_blob": "98b92000c673b4baf061734b12d24c44279d72d8",
    "default_config_blob": "bb835297875869f0ec0c947a28dd07bea58dca6a",
    "junit_path_blob": "abc86ad3e82f605a7365427ab79f7466c06a48c9",
}


def junit_relative_path(config, justfile):
    """Accept the inspected 0.9.103 workspace/profile contract, not Cargo's target-dir."""
    profiles = config.get("profile", {})
    default, local = profiles.get("default", {}), profiles.get("local", {})
    if (
        config.get("store", {}) not in ({}, {"dir": "target/nextest"})
        or default.get("junit") != {"path": "junit.xml"}
        or local.get("inherits") != "default"
        or "junit" in local
        or any(
            "junit" in item
            for profile in (default, local)
            for item in profile.get("overrides", [])
        )
        or 'set working-directory := "codex-rs"' not in justfile
        or justfile.count("NEXTEST_PROFILE=local") != 1
    ):
        raise ValueError("unsupported nextest store/profile/just contract")
    return "codex-rs/target/nextest/local/junit.xml"


def receipt_bytes(rec, phase, status, timestamp, maximum):
    """Measure before writing; an overflow becomes an explicit bounded failure."""
    if rec.get("receipt_overflow"):
        status = "failed"
        rec.update(
            ready=False,
            qualification=False,
            validation_passed=False,
            dependency_graph_approved=False,
        )
    rec.update(phase=phase, status=status, updated_at_utc=timestamp)
    raw = (json.dumps(rec, indent=2) + "\n").encode()
    overflow = len(raw) > maximum
    if overflow:
        fields = (
            "schema_version",
            "mode",
            "source_head",
            "source_tree",
            "workflow_head",
            "baseline_head",
            "run_id",
            "run_attempt",
        )
        compact = {
            key: rec.get(key)
            for key in fields
            if rec.get(key) is None
            or isinstance(rec.get(key), (int, bool))
            or (isinstance(rec.get(key), str) and len(rec[key]) <= 256)
        }
        compact.update(
            phase=phase,
            status="failed",
            updated_at_utc=timestamp,
            ready=False,
            qualification=False,
            validation_passed=False,
            dependency_graph_approved=False,
            commands=[],
            tests=[],
            errors=[
                "Receipt metadata exceeded its bound; execution cannot be accepted."
            ],
            receipt_overflow={
                "encoded_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "full_metadata_written": False,
                "retained_evidence": "Existing payload files, including complete collected JUnit XML, remain unchanged.",
            },
        )
        rec.clear()
        rec.update(compact)
        raw = (json.dumps(rec, indent=2) + "\n").encode()
    if len(raw) > maximum:
        raise ValueError("receipt bound cannot hold the compact failure record")
    return raw, overflow


def group(label, package, *filters, targets=("--lib",), exact_count=None):
    return {
        "label": label,
        "package": package,
        "filters": filters,
        "targets": targets,
        "exact_count": exact_count,
    }


GROUPS = (
    group("zip_mode", "codex-core-plugins", "=" + REGRESSION_NAME, exact_count=1),
    group("zip_existing", "codex-core-plugins", "startup_sync::tests::"),
    group("rollout_zstd", "codex-rollout", "compression::tests::"),
    group("request_zstd", "codex-http-client", "request::tests::"),
    group("schema_zstd", "codex-app-server-protocol", "precomputed_exports_tests::"),
    group(
        "thread_store_zstd",
        "codex-thread-store",
        "=local::rollout_migration::tests::migration_preserves_compressed_rollouts_during_publish_and_recovery",
        "=local::rollout_migration::tests::migration_recovers_a_compressed_published_rollout",
        "=local::rollout_migration::tests::decompression_temporaries_are_owner_only",
        "=local::thread_history_materialization::tests::paginated_fork_materializes_compressed_source_and_ancestor",
    ),
    group(
        "yaml_plugins",
        "codex-core-plugins",
        "command_migration::tests::",
        "=script_attribution::tests::resolves_manifest_operation_for_exact_attributed_script",
        "=script_attribution::tests::allows_measurement_names_reused_across_operations",
        "=script_attribution::tests::invalid_manifest_disables_metrics_without_disabling_attribution",
    ),
    group(
        "yaml_migration",
        "codex-external-agent-migration",
        "tests::subagent_",
        "=tests::frontmatter_accepts_crlf_delimiters",
    ),
    group("yaml_skills", "codex-skills", "parser::tests::"),
    group(
        "yaml_skills_extension",
        "codex-skills-extension",
        "=loader::host::tests::loads_host_frontmatter_dependencies_and_policy",
        "=loader::host::tests::invalid_optional_metadata_fails_open",
        "=loader::host::tests::loads_host_interface_metadata_and_local_asset_paths",
        "=loader::environment::tests::direct_environment_loader_preserves_plugin_dependencies_and_product_policy",
        "=loader::environment::tests::executor_bundle_parser_matches_direct_environment_loader",
    ),
    group(
        "supervisor_integration",
        "codex-hepta-supervisor",
        "=unexpected_agent_crashes_back_off_and_stop_after_three_restarts",
        "=restart_budget_survives_repeated_supervisord_recovery",
        targets=("--test", "restart_budget", "--test", "restart_budget_recovery"),
        exact_count=2,
    ),
    group(
        "supervisor_lib",
        "codex-hepta-supervisor",
        "restart_budget::tests::",
        "=supervisor::tests::flapping_running_agent_stops_after_restart_budget_is_exhausted",
        "=supervisor::tests::unexpected_running_exit_uses_durable_restart_budget_and_backoff",
    ),
    group(
        "fleet_workspace",
        "codex-hepta-fleet",
        "=registry::tests::workspace_sweep_agrees_with_pairwise_oracle_for_nested_and_sibling_paths",
        exact_count=1,
    ),
)


def test_command(spec):
    return [
        "just",
        "test",
        "--locked",
        *spec["targets"],
        "-p",
        spec["package"],
        "--retries",
        "0",
        "--test-threads",
        "1" if spec["label"] == "zip_mode" else "2",
        "--no-tests=fail",
        "--failure-output",
        "immediate",
        "--success-output",
        "immediate",
        "-E",
        " | ".join(f"test({item})" for item in spec["filters"]),
    ]


def regression_contract(raw, expected_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("REGRESSION_SHA256 must identify the reviewed formatted test")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("regression source bytes differ from the workflow identity")
    lines = [
        index
        for index, line in enumerate(raw.decode("utf-8").splitlines(), 1)
        if line.strip() == "assert_eq!(actual, expected);"
    ]
    if len(lines) != 1:
        raise ValueError(
            "regression must have one exact final actual/expected assertion"
        )
    return {"path": REGRESSION_PATH, "sha256": expected_sha256, "assert_line": lines[0]}


def manifest_contract(document, extractor, mode):
    dependencies = document["workspace"]["dependencies"]
    wanted = (
        {"zip": "2.4.2", "zstd": "0.13", "serde_yaml": "0.9"}
        if mode == "baseline"
        else {
            "zip": "9.1.2",
            "zstd": "0.14.3",
            "serde_yaml": {"package": "serde_norway", "version": "0.9.42"},
        }
    )
    if {name: dependencies.get(name) for name in wanted} != wanted:
        raise ValueError("workspace dependency declarations do not match this arm")
    expression = (
        "Permissions::from_mode(mode)"
        if mode == "baseline"
        else "Permissions::from_mode(mode & 0o777)"
    )
    if extractor.count(expression) != 1:
        raise ValueError("extractor permission boundary does not match this arm")
    return wanted


def changed_scope(paths, mode):
    allowed = set(LOCKS) if mode == "candidate" else set()
    if not set(paths) <= allowed:
        raise ValueError("source changed outside the two permitted candidate lockfiles")


def package_map(document):
    result = {}
    for item in document["package"]:
        key = (item["name"], item["version"], item.get("source", ""))
        if key in result:
            raise ValueError("duplicate Cargo package identity")
        result[key] = item
    return result


def lock_delta(before, after):
    old, new = package_map(before), package_map(after)
    registry = "registry+https://github.com/rust-lang/crates.io-index"
    for name, version in TLS.items():
        key = (name, version, registry)
        if {k for k in old if k[0] == name} != {key} or {
            k for k in new if k[0] == name
        } != {key}:
            raise ValueError("protected TLS identity changed")
        if old[key].get("checksum") != new[key].get("checksum"):
            raise ValueError("protected TLS checksum changed")
    for name, version in {
        "zip": "9.1.2",
        "zstd": "0.14.3",
        "serde_norway": "0.9.42",
    }.items():
        if {k for k in new if k[0] == name} != {(name, version, registry)}:
            raise ValueError("candidate root package did not resolve exactly")
    if any(k[0] in {"serde_yaml", "unsafe-libyaml"} for k in new):
        raise ValueError("original YAML packages remain in the resolved lock")
    if not any(k[0] == "unsafe-libyaml-norway" for k in new):
        raise ValueError("the actual Norway parser package is absent")
    for key in old.keys() & new.keys():
        if old[key].get("checksum") != new[key].get("checksum"):
            raise ValueError("checksum changed for an unchanged package identity")
    return package_difference(before, after)


def package_difference(before, after):
    """Describe even a failed/partial resolver result without approving it."""
    old, new = package_map(before), package_map(after)
    return {
        "qualification": False,
        "dependency_graph_approved": False,
        "review_required": "Review every actual package, source, checksum, feature and dependency-edge delta; no dependency-name allowlist is applied.",
        "removed": [old[k] for k in sorted(old.keys() - new.keys())],
        "added": [new[k] for k in sorted(new.keys() - old.keys())],
        "changed": [
            {"before": old[k], "after": new[k]}
            for k in sorted(old.keys() & new.keys())
            if old[k] != new[k]
        ],
        "lock_metadata_before": {k: v for k, v in before.items() if k != "package"},
        "lock_metadata_after": {k: v for k, v in after.items() if k != "package"},
    }


def junit_result(raw, result, spec, regression, baseline=False):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations are not accepted in JUnit evidence")
    root = ET.fromstring(raw)
    if (
        root.tag != "testsuites"
        or not list(root)
        or any(c.tag != "testsuite" for c in root)
    ):
        raise ValueError("unexpected nextest JUnit root")
    if any(node.tag.lower().startswith(("rerun", "flaky")) for node in root.iter()):
        raise ValueError("retry/flaky evidence is incompatible with retries=0")
    cases = []
    for suite in root:
        entries = suite.findall("testcase")
        counts = {"tests": len(entries), "failures": 0, "errors": 0}
        for case in entries:
            if (
                not case.get("name")
                or not case.get("classname")
                or case.find("skipped") is not None
            ):
                raise ValueError("missing test identity or skipped testcase")
            failures, errors = case.findall("failure"), case.findall("error")
            if len(failures) + len(errors) > 1:
                raise ValueError("ambiguous testcase outcome")
            counts["failures"] += len(failures)
            counts["errors"] += len(errors)
            cases.append(case)
        for field, value in counts.items():
            if suite.get(field) != str(value):
                raise ValueError("JUnit suite counters disagree with actual cases")
    if not cases or len({(c.get("classname"), c.get("name")) for c in cases}) != len(
        cases
    ):
        raise ValueError("empty or duplicate executed testcase identity")
    failures = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    for field, value in {
        "tests": len(cases),
        "failures": failures,
        "errors": errors,
    }.items():
        if root.get(field) != str(value):
            raise ValueError("JUnit root counters disagree with actual cases")
    names = [c.get("name") for c in cases]
    if spec["exact_count"] is not None and len(cases) != spec["exact_count"]:
        raise ValueError("the exact registered testcase count was not executed")
    matches = lambda pattern, name: (
        name == pattern[1:] if pattern.startswith("=") else pattern in name
    )
    if any(not any(matches(p, name) for p in spec["filters"]) for name in names):
        raise ValueError("JUnit contains a testcase outside the registered filter")
    if any(not any(matches(p, name) for name in names) for p in spec["filters"]):
        raise ValueError("at least one registered filter matched no executed testcase")
    if result["timed_out"]:
        raise ValueError("test invocation timed out")
    if baseline:
        if (
            result["exit_code"] != 100
            or names != [REGRESSION_NAME]
            or (failures, errors) != (1, 0)
        ):
            raise ValueError(
                "baseline must be exactly one expected nextest test failure (100)"
            )
        text = re.sub(r"\x1b\[[0-9;]*m", "", "".join(cases[0].itertext()))
        location = rf"core-plugins[/\\]src[/\\]startup_sync_zip_tests\.rs:{regression['assert_line']}:\d+"
        if (
            not re.search(r"panicked at [^\n]*" + location, text)
            or "left == right" not in text
        ):
            raise ValueError(
                "baseline did not fail at the bound final mode/payload assertion"
            )
    elif result["exit_code"] != 0 or failures or errors:
        raise ValueError("candidate testcase execution did not pass")
    names_raw = json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "tests": len(cases),
        "failures": failures,
        "errors": errors,
        "names_sha256": hashlib.sha256(names_raw).hexdigest(),
        "names_encoding": "UTF-8 JSON array, ensure_ascii=false, separators=(',', ':'); full names remain in JUnit",
        "filter_matches": [
            {"filter": p, "executed_tests": sum(matches(p, n) for n in names)}
            for p in spec["filters"]
        ],
        "expected_regression_observed": baseline,
        "passed": True,
    }
