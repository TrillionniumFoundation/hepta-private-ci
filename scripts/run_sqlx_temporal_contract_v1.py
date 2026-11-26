"""Admit one SQLx compile-capability and scalar-storage engineering scope.

Inactive inputs dispatch nothing. Original negative compiler records remain
failed; their exact E0277 observation is classified separately. This is neither
Chrono removal nor product qualification.
"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import tomllib
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts/hepta_sqlx_temporal_contract_inputs_v1.json"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BRANCH = "research/sqlx-explicit-temporal-contract-20261125-7c9e"
TARGET = "aarch64-unknown-linux-gnu"
TOOLCHAIN = "+1.96.0"
NEXTEST_VERSION = "0.9.103"
PACKAGES = (
    "codex-cli",
    "codex-hepta-agentd",
    "codex-hepta-authbus",
    "codex-hepta-automation",
    "codex-hepta-evidence",
    "codex-hepta-matrix-store",
    "codex-hepta-memory",
    "codex-hepta-operations",
    "codex-hepta-runtime",
    "codex-hepta-shadow-qualification",
    "codex-state",
    "codex-thread-store",
)
DEFAULT = "qualification/sqlx_temporal_default_v1"
COMPATIBILITY = "qualification/sqlx_temporal_explicit_chrono_v1"
NEGATIVE_NAME = "chrono_default_refusal"
NEGATIVE_PACKAGE = "sqlx-temporal-default-contract-v1"
NEGATIVE_SOURCE = DEFAULT + "/chrono_default_refusal.rs"
NEGATIVE_LINE = "    require_sqlite_type::<DateTime<Utc>>();"
NEGATIVE_MESSAGES = frozenset(
    value.replace('"', "\x60")
    for value in (
        'the trait bound "DateTime<Utc>: sqlx::Type<Sqlite>" is not satisfied',
        'the trait bound "DateTime<Utc>: Type<Sqlite>" is not satisfied',
    )
)
NATIVE_CASES = (
    (
        "codex-state",
        "runtime::threads::tests::thread_updated_at_uses_unique_epoch_millis_and_reads_legacy_seconds",
    ),
    (
        "codex-state",
        "sqlite::pool_tests::refused_commit_keeps_reused_pool_readable_without_reopening_write_gate",
    ),
    (
        "codex-hepta-operations",
        "destination_dedupe::tests::domain_write_and_dedupe_receipt_commit_atomically",
    ),
    (
        "codex-hepta-operations",
        "destination_dedupe::tests::rollback_removes_domain_write_and_dedupe_together",
    ),
    (
        "codex-hepta-operations",
        "destination_dedupe::tests::semantic_identity_drift_conflicts",
    ),
    (
        "codex-hepta-operations",
        "durable_store::tests::prepare_is_atomic_and_survives_reopen",
    ),
    (
        "codex-hepta-operations",
        "durable_store::tests::migration_checksum_tamper_fails_reopen",
    ),
    (
        "codex-hepta-operations",
        "durable_store::tests::future_migration_lineage_blocks_old_binary_reopen",
    ),
    (
        "codex-hepta-operations::destination_recovery_binding",
        "valid_width_but_semantically_corrupt_receipts_fail_after_reopen",
    ),
    (
        "codex-thread-store",
        "local::thread_history_materialization::tests::event_timestamps_allow_invalid_rollout_timestamps",
    ),
    (
        "codex-state",
        "sqlx_temporal_contract_tests::scalar_sqlite_values_keep_types_nulls_and_reopen",
    ),
    (
        "codex-state",
        "sqlx_temporal_contract_tests::legacy_integer_rows_keep_original_conversion_and_refusal",
    ),
)
OWNER_SHA256 = "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba"
COLLECTOR_SHA256 = "cdb325f4a9266bc554fa266ee6a42dc1e1390b6b45d4bac47fa50aa9255cdeec"


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "input is not a regular file")
        require(0 <= before.st_size <= maximum, "input exceeds its byte bound")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        len(raw) <= maximum
        and len(raw) == before.st_size
        and all(getattr(before, key) == getattr(after, key) for key in fields),
        "input changed or exceeded its byte bound",
    )
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_path(relative):
    path = Path(relative)
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == relative,
        "input path is not a normalized repository path",
    )
    actual = ROOT / path
    require(actual.resolve().is_relative_to(ROOT), "input escaped the checkout")
    return actual


def check_pin(relative, pin):
    require(
        isinstance(pin, dict)
        and type(pin.get("bytes")) is int
        and 0 <= pin["bytes"] <= 64 * 1024 * 1024
        and re.fullmatch(r"[0-9a-f]{64}", pin.get("sha256", "")),
        "a required actual input pin is absent",
    )
    raw = read_regular(checked_path(relative), pin["bytes"] + 1)
    require(
        len(raw) == pin["bytes"] and digest(raw) == pin["sha256"],
        "actual bytes differ from the admitted source or generated lock: " + relative,
    )
    if "git_blob_sha1" in pin:
        require(
            hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            == pin["git_blob_sha1"],
            "input Git blob identity differs: " + relative,
        )
    return raw


def write_new(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"bytes": len(raw), "sha256": digest(raw)}


def load_module(name, path, expected_sha256):
    require(
        digest(read_regular(path, 1024 * 1024)) == expected_sha256,
        "original execution or collection owner changed",
    )
    description = importlib.util.spec_from_file_location(name, path)
    require(
        description is not None and description.loader is not None,
        "owner loader absent",
    )
    module = importlib.util.module_from_spec(description)
    description.loader.exec_module(module)
    return module


def normalized_patches(manifest, directory):
    result = {}
    for source, entries in manifest.get("patch", {}).items():
        normalized = {}
        for name, original in entries.items():
            item = dict(original)
            if "path" in item:
                actual = (directory / item["path"]).resolve()
                require(
                    actual.is_relative_to(ROOT), "fixture patch leaves accepted source"
                )
                item["path"] = actual.relative_to(ROOT).as_posix()
            normalized[name] = item
        result[source] = normalized
    return result


def check_fixture_declarations():
    workspace = tomllib.loads(
        read_regular(ROOT / "codex-rs/Cargo.toml", 1024 * 1024).decode()
    )
    original_patches = normalized_patches(workspace, ROOT / "codex-rs")
    require(
        "chrono" not in workspace["workspace"]["dependencies"]["sqlx"]["features"],
        "main workspace still requests the implicit SQLx Chrono codec",
    )
    for relative, expected_features in (
        (DEFAULT, ["sqlite-bundled"]),
        (COMPATIBILITY, ["chrono", "sqlite-bundled"]),
    ):
        directory = ROOT / relative
        manifest = tomllib.loads(
            read_regular(directory / "Cargo.toml", 1024 * 1024).decode()
        )
        require(
            manifest["workspace"] == {"resolver": "2"}
            and manifest["dependencies"]["sqlx"]
            == {
                "version": "=0.9.1",
                "default-features": False,
                "features": expected_features,
            }
            and manifest["dependencies"]["chrono"]
            == {"version": "=0.4.45", "default-features": False, "features": ["std"]}
            and normalized_patches(manifest, directory) == original_patches,
            "independent fixture SQLx capability or accepted workspace patches differ",
        )


def check_inputs(spec):
    require(
        spec.get("schema") == "hepta-sqlx-temporal-contract-inputs-v1"
        and spec.get("activated") is True
        and spec.get("activation_blockers") == [],
        "SQLx temporal scope is inactive",
    )
    require(
        spec["consumer_packages"] == list(PACKAGES)
        and spec["native_cases"] == [list(value) for value in NATIVE_CASES]
        and spec["original_native_count"] == 10
        and spec["new_native_count"] == 2,
        "the reviewed consumer or native roster changed",
    )
    require(
        spec["target"] == TARGET
        and spec["toolchain"] == "1.96.0"
        and spec["nextest_version"] == NEXTEST_VERSION
        and spec["compile_capability_cases"]
        == [
            "default_scalar_positive",
            "default_chrono_E0277",
            "explicit_chrono_positive",
        ],
        "the reviewed compile scope changed",
    )
    require(
        spec["qualification"] is False and spec["chrono_removed"] is False,
        "engineering observations cannot grant qualification or Chrono removal",
    )
    for key in ("parent_head", "parent_tree"):
        require(
            isinstance(spec["accepted_source"].get(key), str)
            and re.fullmatch(r"[0-9a-f]{40}", spec["accepted_source"][key]),
            "accepted source parent is not bound",
        )
    require(
        isinstance(spec.get("accepted_consumer_targets_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", spec["accepted_consumer_targets_sha256"]),
        "the actual complete twelve-consumer target roster is not bound",
    )
    for key, pattern in (
        ("acceptance_sha256", r"[0-9a-f]{64}"),
        ("generation_source", r"[0-9a-f]{40}"),
        ("original_artifact_sha256", r"[0-9a-f]{64}"),
        ("generation_run_id", r"[0-9]+"),
    ):
        value = spec["accepted_generation"].get(key)
        require(
            isinstance(value, str) and re.fullmatch(pattern, value),
            "actual generation acceptance is absent: " + key,
        )
    require(
        set(spec["accepted_locks"])
        == {
            "codex-rs/Cargo.lock",
            "MODULE.bazel.lock",
            DEFAULT + "/Cargo.lock",
            COMPATIBILITY + "/Cargo.lock",
        },
        "four accepted lock originals are required",
    )
    require(
        set(spec["expected_fixture_graph_sha256"]) == {"default", "compatibility"}
        and all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in spec["expected_fixture_graph_sha256"].values()
        ),
        "both independent fixture graphs must be accepted",
    )
    budget = spec["budget"]
    require(
        isinstance(budget, dict)
        and set(budget)
        == {"scope_seconds", "metadata_seconds", "compile_seconds", "native_seconds"}
        and all(
            type(value) in (int, float) and math.isfinite(value) and value > 1
            for value in budget.values()
        )
        and budget["scope_seconds"] <= 3600
        and all(value <= budget["scope_seconds"] for value in budget.values()),
        "a separate bounded engineering budget must be admitted",
    )
    require(
        {
            "scripts/run_sqlx_temporal_contract_v1.py",
            "scripts/hepta_ci_exec.py",
            "scripts/hepta_ci_junit.py",
            "codex-rs/Cargo.toml",
            "codex-rs/state/src/lib.rs",
            "codex-rs/state/src/sqlx_temporal_contract_tests.rs",
            DEFAULT + "/Cargo.toml",
            DEFAULT + "/scalar_public.rs",
            NEGATIVE_SOURCE,
            COMPATIBILITY + "/Cargo.toml",
            COMPATIBILITY + "/chrono_explicit.rs",
        }.issubset(spec["source_pins"]),
        "required owner or fixture sources are not pinned",
    )
    for relative, pin in spec["source_pins"].items():
        check_pin(relative, pin)
    for relative, pin in spec["accepted_locks"].items():
        check_pin(relative, pin)
    check_fixture_declarations()


def check_admission(spec, acceptance_path):
    require(sys.platform == "linux", "this new owner scope is Linux only")
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("HEPTA_CI_LANE") == "source-head",
        "only the first owned source-head pull-request scope is admitted",
    )
    event = strict_json(
        read_regular(Path(os.environ["GITHUB_EVENT_PATH"]), 4 * 1024 * 1024)
    )
    pull = event["pull_request"]
    require(
        event["action"] == "opened"
        and pull["draft"] is True
        and pull["state"] == "open"
        and pull["user"]["login"] == "ProfHepta"
        and pull["head"]["repo"]["full_name"] == REPOSITORY
        and pull["base"]["repo"]["full_name"] == REPOSITORY
        and pull["head"]["ref"] == BRANCH
        and pull["head"]["sha"] == os.environ.get("SOURCE_SHA")
        and os.environ.get("SOURCE_SHA") == os.environ.get("TESTED_SHA"),
        "the owned Draft source identity or first-open event differs",
    )
    raw = read_regular(acceptance_path, 4 * 1024 * 1024)
    require(
        digest(raw) == spec["accepted_generation"]["acceptance_sha256"],
        "generation acceptance bytes differ",
    )
    acceptance = strict_json(raw)
    require(
        acceptance["schema"] == "sqlx-temporal-lock-acceptance-v1"
        and acceptance["accepted"] is True
        and acceptance["accepted_source"] == spec["accepted_source"]
        and acceptance["locks"] == spec["accepted_locks"]
        and acceptance["fixture_graph_sha256"] == spec["expected_fixture_graph_sha256"]
        and acceptance["consumer_targets_sha256"]
        == spec["accepted_consumer_targets_sha256"]
        and acceptance["generation_source"]
        == spec["accepted_generation"]["generation_source"]
        and acceptance["generation_run_id"]
        == spec["accepted_generation"]["generation_run_id"]
        and acceptance["original_artifact_sha256"]
        == spec["accepted_generation"]["original_artifact_sha256"],
        "accepted locks, graph, source and generation are not the same observation",
    )
    return {
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": "1",
        "pull_number": event["number"],
        "source_sha": pull["head"]["sha"],
        "acceptance_sha256": digest(raw),
    }


def metadata_from_log(raw):
    values = []
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if line.startswith("{"):
            value = strict_json(line)
            if (
                value.get("version") == 1
                and "packages" in value
                and "workspace_members" in value
            ):
                values.append(value)
    require(len(values) == 1, "expected one complete original Cargo metadata document")
    return values[0]


def normalized_fixture_graph(metadata):
    packages = {row["id"]: row for row in metadata["packages"]}
    nodes = {row["id"]: row for row in metadata["resolve"]["nodes"]}
    require(
        len(packages) == len(metadata["packages"])
        and len(nodes) == len(metadata["resolve"]["nodes"])
        and packages.keys() == nodes.keys(),
        "fixture metadata package and resolved-node rosters differ",
    )

    def identity(package_id):
        package = packages[package_id]
        manifest = None
        if package["source"] is None:
            manifest = Path(package["manifest_path"]).relative_to(ROOT).as_posix()
        return {
            "name": package["name"],
            "version": package["version"],
            "source": package["source"],
            "manifest": manifest,
        }

    normalized = []
    for package_id, package in packages.items():
        node = nodes[package_id]
        target_root = (
            ROOT if package["source"] is None else Path(package["manifest_path"]).parent
        )
        targets = []
        for original in package["targets"]:
            target = dict(original)
            target["src_path"] = (
                Path(target["src_path"]).relative_to(target_root).as_posix()
            )
            targets.append(target)
        normalized.append(
            {
                "identity": identity(package_id),
                "links": package.get("links"),
                "features": sorted(node["features"]),
                "targets": sorted(targets, key=canonical),
                "deps": sorted(
                    (
                        {
                            "name": edge["name"],
                            "dependency": identity(edge["pkg"]),
                            "dep_kinds": sorted(edge["dep_kinds"], key=canonical),
                        }
                        for edge in node["deps"]
                    ),
                    key=canonical,
                ),
            }
        )
    return {
        "packages": sorted(normalized, key=canonical),
        "workspace_members": sorted(
            (identity(value) for value in metadata["workspace_members"]), key=canonical
        ),
        "workspace_default_members": sorted(
            (identity(value) for value in metadata["workspace_default_members"]),
            key=canonical,
        ),
        "resolve_root": identity(metadata["resolve"]["root"]),
    }


def check_fixture_graph(raw, expected_sha256, compatibility):
    metadata = metadata_from_log(raw)
    normalized = normalized_fixture_graph(metadata)
    require(
        digest(canonical(normalized)) == expected_sha256,
        "fixture graph differs from the independently accepted original",
    )
    packages = normalized["packages"]
    codecs = [
        row
        for row in packages
        if row["identity"]["name"] in ("sqlx", "sqlx-core", "sqlx-sqlite")
    ]
    require(
        len(codecs) == 3
        and all(row["identity"]["version"] == "0.9.1" for row in codecs)
        and all(("chrono" in row["features"]) is compatibility for row in codecs),
        "fixture graph does not have the intended SQLx Chrono capability",
    )
    require(
        all(
            "chrono" not in row["features"]
            for row in packages
            if not compatibility and row["identity"]["name"].startswith("sqlx")
        ),
        "default fixture gained an indirect SQLx Chrono feature",
    )
    expected_name = (
        "sqlx-temporal-explicit-chrono-contract-v1"
        if compatibility
        else NEGATIVE_PACKAGE
    )
    require(
        normalized["resolve_root"]["name"] == expected_name
        and normalized["resolve_root"]["manifest"]
        == (COMPATIBILITY if compatibility else DEFAULT) + "/Cargo.toml",
        "fixture root is not its separate admitted workspace",
    )
    return {
        "normalized_graph_sha256": digest(canonical(normalized)),
        "package_count": len(packages),
        "sqlx_chrono_opt_in": compatibility,
        "chrono_dependency_retained": True,
        "root_package_id": metadata["resolve"]["root"],
    }


def check_exact_refusal(record, raw, expected_package_id):
    require(
        record["status"] == "failed"
        and record["command_exit_code"] == 101
        and record["exit_code"] == 101
        and record["timed_out"] is False
        and record["output_limit_exceeded"] is False,
        "the negative must be a real, terminal Rust compiler failure",
    )
    errors, finished, terminal_lines = [], [], []
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", errors="strict"))
    for line in text.splitlines():
        if line.startswith("{"):
            item = strict_json(line)
            if (
                item.get("reason") == "compiler-message"
                and item["message"].get("level") == "error"
            ):
                errors.append(item)
            elif item.get("reason") == "build-finished":
                finished.append(item)
        elif re.match(r"error(?:\[[A-Z][0-9]+\])?:", line):
            terminal_lines.append(line)
    require(
        len(errors) == 1 and len(finished) == 1 and finished[0]["success"] is False,
        "the negative has an absent, extra, or unrelated compiler error",
    )
    error = errors[0]
    target = error["target"]
    message = error["message"]
    source_path = checked_path(NEGATIVE_SOURCE).resolve()
    require(
        target["name"] == NEGATIVE_NAME
        and target["kind"] == ["bin"]
        and Path(target["src_path"]).resolve() == source_path
        and error["package_id"] == expected_package_id,
        "the compiler error is not from the exact negative fixture target",
    )
    require(
        message.get("code", {}).get("code") == "E0277"
        and message["message"] in NEGATIVE_MESSAGES,
        "the compiler refused a different trait obligation",
    )
    primary = [span for span in message["spans"] if span["is_primary"]]
    require(len(primary) == 1, "the exact refusal must have one primary source span")
    supplied_path = Path(primary[0]["file_name"])
    candidates = (
        [supplied_path.resolve()]
        if supplied_path.is_absolute()
        else [
            (directory / supplied_path).resolve()
            for directory in (ROOT, ROOT / "codex-rs", ROOT / DEFAULT)
        ]
    )
    require(
        source_path in candidates
        and primary[0]["line_start"] == primary[0]["line_end"] == 7
        and [line["text"] for line in primary[0]["text"]] == [NEGATIVE_LINE],
        "E0277 is not at the pinned Chrono Type<Sqlite> expression",
    )
    terminal = (
        'error: could not compile "'
        + NEGATIVE_PACKAGE
        + '" (bin "'
        + NEGATIVE_NAME
        + '") due to 1 previous error'
    ).replace('"', "\x60")
    require(
        terminal_lines in ([], [terminal]),
        "the negative includes an unrelated Cargo failure",
    )
    return {
        "observation": "expected_exact_trait_refusal",
        "compiler_code": "E0277",
        "obligation": "chrono::DateTime<chrono::Utc>: sqlx::Type<sqlx::Sqlite>",
        "source": NEGATIVE_SOURCE,
        "line": 7,
        "original_command_status": "failed",
        "original_command_exit_code": 101,
        "qualification": False,
    }


def check_native_xml(xml, raw_stdout, collector):
    root = ET.fromstring(
        xml, parser=ET.XMLParser(target=collector.NoDoctypeTreeBuilder())
    )
    cases = list(root.iter("testcase"))
    expected = Counter(NATIVE_CASES)
    actual = Counter((case.get("classname"), case.get("name")) for case in cases)
    require(
        actual == expected
        and len(cases) == 12
        and all(
            case.find(name) is None
            for case in cases
            for name in ("failure", "error", "skipped", "rerunFailure", "flakyFailure")
        ),
        "native JUnit has a missing, skipped, repeated, extra, or failed case",
    )
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw_stdout.decode("utf-8", errors="strict"))
    passes = Counter(
        re.findall(r"^\s*PASS\s+\[[^\]\r\n]+\]\s+(\S+)\s+(\S+)\s*$", text, flags=re.M)
    )
    require(
        passes == expected,
        "original native stdout does not have exactly the same twelve passes",
    )
    return {
        "native_cases": [list(value) for value in NATIVE_CASES],
        "new": 2,
        "retained": 10,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    result = {
        "schema": "sqlx-temporal-contract-observation-v1",
        "status": "rejected",
        "commands": [],
        "qualification": False,
        "chrono_removed": False,
        "old_E1_E6_executions": 0,
    }
    artifacts = before = owner = spec = deadline = None
    exit_code = 2
    previous_cwd = Path.cwd()
    previous_target = os.environ.get("CARGO_TARGET_DIR")
    previous_toolchain = os.environ.get("RUSTUP_TOOLCHAIN")
    previous_handler = None
    try:
        spec = strict_json(read_regular(SPEC, 4 * 1024 * 1024))
        check_inputs(spec)
        admission = check_admission(spec, args.acceptance)
        require(
            args.artifacts.is_absolute()
            and not args.artifacts.resolve().is_relative_to(ROOT),
            "artifacts must be in a new directory outside the checkout",
        )
        args.artifacts.mkdir(mode=0o700, parents=False, exist_ok=False)
        artifacts = args.artifacts
        write_new(
            artifacts / "STARTED.json", {"admission": admission, "status": "running"}
        )
        result["admission"] = admission
        deadline = started + spec["budget"]["scope_seconds"]
        owner = load_module(
            "hepta_sqlx_original_exec", ROOT / "scripts/hepta_ci_exec.py", OWNER_SHA256
        )
        collector = load_module(
            "hepta_sqlx_original_junit",
            ROOT / "scripts/hepta_ci_junit.py",
            COLLECTOR_SHA256,
        )
        os.environ["RUSTUP_TOOLCHAIN"] = "1.96.0"
        os.chdir(ROOT / "codex-rs")
        before = owner.identity()
        require(
            before["dirty"] is False
            and before["commit"] == admission["source_sha"]
            and before["parents"] == [spec["accepted_source"]["parent_head"]]
            and owner.git(
                "rev-parse", spec["accepted_source"]["parent_head"] + "^{tree}"
            )
            == spec["accepted_source"]["parent_tree"],
            "candidate is not the clean child of the accepted generated-lock source",
        )
        result["before"] = before

        def cancelled(_signum, _frame):
            raise KeyboardInterrupt("engineering scope was cancelled")

        previous_handler = signal.signal(signal.SIGTERM, cancelled)

        def invoke(
            name, command, cap, minimum=0, allow_failed=False, target_directory="main"
        ):
            remaining = min(cap, deadline - time.monotonic() - 1)
            require(
                remaining > 0,
                "shared engineering deadline exhausted before command admission",
            )
            os.environ["CARGO_TARGET_DIR"] = str(
                artifacts / ("cargo-" + target_directory)
            )
            output = artifacts / (name + ".json")
            code = owner.run(
                output, command, minimum_tests=minimum, timeout_seconds=remaining
            )
            record_raw = read_regular(output, 1024 * 1024)
            record = strict_json(record_raw)
            result["commands"].append(
                {
                    "name": name,
                    "record": output.name,
                    "sha256": digest(record_raw),
                    "owner_exit_code": code,
                }
            )
            require(
                record["before"] == before == record.get("after")
                and record["command"] == command
                and record["source_sha"] == admission["source_sha"]
                and record["tested_sha"] == admission["source_sha"]
                and record["lane"] == "source-head",
                "command did not retain the exact clean source and argument vector",
            )
            log_name = record["log_file"]
            require(
                Path(log_name).name == log_name,
                "raw log left its original artifact owner",
            )
            raw = read_regular(artifacts / log_name, 64 * 1024 * 1024)
            require(
                digest(raw) == record["log_sha256"] and len(raw) == record["log_bytes"],
                "original command log bytes differ",
            )
            require(
                record["timed_out"] is False
                and record["output_limit_exceeded"] is False
                and time.monotonic() <= deadline,
                "command timeout, output refusal, cleanup cost, or shared deadline exceeded",
            )
            if not allow_failed:
                require(
                    code == 0
                    and record["status"] == "passed"
                    and record["command_exit_code"] == 0,
                    "required engineering command did not pass",
                )
            return record, raw, output

        budget = spec["budget"]
        _, cargo_version, _ = invoke(
            "cargo-version",
            ["cargo", TOOLCHAIN, "--version"],
            budget["metadata_seconds"],
        )
        _, rust_version, _ = invoke(
            "rustc-version",
            ["rustc", TOOLCHAIN, "--version", "--verbose"],
            budget["metadata_seconds"],
        )
        require(
            cargo_version.decode().startswith("cargo 1.96.0 ")
            and rust_version.decode().startswith("rustc 1.96.0 ")
            and "\nhost: " + TARGET + "\n" in rust_version.decode(),
            "the admitted exact native compiler or host differs",
        )
        _, nextest_version, _ = invoke(
            "nextest-version",
            ["cargo", TOOLCHAIN, "nextest", "--version"],
            budget["metadata_seconds"],
        )
        require(
            nextest_version.decode().split()[:2] == ["cargo-nextest", NEXTEST_VERSION],
            "the actual nextest version differs from the admitted source",
        )
        result["verified_tool_selection"] = {
            "rustup_toolchain_for_just": os.environ["RUSTUP_TOOLCHAIN"],
            "nextest_version": NEXTEST_VERSION,
            "nextest_version_observation_command": "nextest-version",
        }
        _, root_meta, _ = invoke(
            "consumer-target-roster",
            [
                "cargo",
                TOOLCHAIN,
                "metadata",
                "--locked",
                "--no-deps",
                "--format-version=1",
            ],
            budget["metadata_seconds"],
        )
        metadata = metadata_from_log(root_meta)
        selected = [row for row in metadata["packages"] if row["name"] in PACKAGES]
        found = {row["name"]: row for row in selected}
        require(
            len(selected) == len(found) == 12 and set(found) == set(PACKAGES),
            "the exact twelve consumers are not present once",
        )
        observed_targets = {}
        for name, package in found.items():
            targets = []
            for original in package["targets"]:
                target = dict(original)
                target["src_path"] = (
                    Path(target["src_path"]).relative_to(ROOT).as_posix()
                )
                targets.append(target)
            observed_targets[name] = sorted(targets, key=canonical)
        require(
            digest(canonical(observed_targets))
            == spec["accepted_consumer_targets_sha256"],
            "full target declarations differ from the accepted twelve-consumer source",
        )
        result["declared_targets"] = observed_targets
        result["declared_targets_are_not_test_counts"] = True
        result["qualification_features_requested"] = []
        result["required_feature_declarations_are_not_claimed_compiled"] = [
            {
                "package": name,
                "target": target["name"],
                "features": target["required-features"],
            }
            for name, targets in observed_targets.items()
            for target in targets
            if target.get("required-features")
        ]
        package_args = [value for name in PACKAGES for value in ("-p", name)]
        invoke(
            "twelve-consumer-compile",
            [
                "cargo",
                TOOLCHAIN,
                "check",
                "--locked",
                "--all-targets",
                "--target",
                TARGET,
                *package_args,
            ],
            budget["compile_seconds"],
        )
        result["consumer_compile"] = {"packages": list(PACKAGES), "status": "passed"}

        for label, relative, compatibility in (
            ("default", DEFAULT, False),
            ("compatibility", COMPATIBILITY, True),
        ):
            _, raw, _ = invoke(
                label + "-graph",
                [
                    "cargo",
                    TOOLCHAIN,
                    "metadata",
                    "--locked",
                    "--format-version=1",
                    "--filter-platform",
                    TARGET,
                    "--manifest-path",
                    str(ROOT / relative / "Cargo.toml"),
                ],
                budget["metadata_seconds"],
                target_directory=label,
            )
            result[label + "_graph"] = check_fixture_graph(
                raw, spec["expected_fixture_graph_sha256"][label], compatibility
            )
        invoke(
            "default-scalar-positive",
            [
                "cargo",
                TOOLCHAIN,
                "check",
                "--locked",
                "--target",
                TARGET,
                "--manifest-path",
                str(ROOT / DEFAULT / "Cargo.toml"),
                "--bin",
                "scalar_public",
                "--message-format=json",
            ],
            budget["compile_seconds"],
            target_directory="default",
        )
        negative_record, negative_stdout, _ = invoke(
            "default-chrono-refusal",
            [
                "cargo",
                TOOLCHAIN,
                "check",
                "--locked",
                "--target",
                TARGET,
                "--manifest-path",
                str(ROOT / DEFAULT / "Cargo.toml"),
                "--bin",
                NEGATIVE_NAME,
                "--message-format=json",
            ],
            budget["compile_seconds"],
            allow_failed=True,
            target_directory="default",
        )
        result["negative_interpretation"] = check_exact_refusal(
            negative_record, negative_stdout, result["default_graph"]["root_package_id"]
        )
        invoke(
            "explicit-chrono-positive",
            [
                "cargo",
                TOOLCHAIN,
                "check",
                "--locked",
                "--target",
                TARGET,
                "--manifest-path",
                str(ROOT / COMPATIBILITY / "Cargo.toml"),
                "--bin",
                "chrono_explicit",
                "--message-format=json",
            ],
            budget["compile_seconds"],
            target_directory="compatibility",
        )
        result["explicit_opt_in_retains_chrono"] = True

        expression = " | ".join(
            "(binary_id(=" + binary + ") & test(=" + name + "))"
            for binary, name in NATIVE_CASES
        )
        command = [
            "just",
            "test",
            "--locked",
            "--target",
            TARGET,
            "-p",
            "codex-state",
            "-p",
            "codex-hepta-operations",
            "-p",
            "codex-thread-store",
            "--lib",
            "--test",
            "destination_recovery_binding",
            "--retries",
            "0",
            "--test-threads",
            "1",
            "--status-level",
            "pass",
            "--final-status-level",
            "fail",
            "-E",
            expression,
        ]
        record, stdout, execution_path = invoke(
            "native-twelve",
            command,
            budget["native_seconds"],
            minimum=12,
            allow_failed=True,
        )
        original_junit = ROOT / "codex-rs/target/nextest/local/junit.xml"
        retained_junit = artifacts / "native-twelve.junit.xml"
        collected = collector.collect(execution_path, original_junit, retained_junit)
        summary_raw = read_regular(
            retained_junit.with_suffix(".summary.json"), 1024 * 1024
        )
        summary = strict_json(summary_raw)
        result["native_junit_collection"] = {
            "collector_exit": collected,
            "summary_sha256": digest(summary_raw),
            "status": summary["status"],
        }
        require(
            record["status"] == "passed"
            and record["command_exit_code"] == 0
            and record["exit_code"] == 0
            and collected == 0
            and record["observed_passed_tests"] == 12
            and record["observed_failed_tests"] == 0,
            "original native execution or fresh JUnit collection did not pass",
        )
        xml = read_regular(retained_junit, 64 * 1024 * 1024)
        require(
            digest(xml) == summary["junit_sha256"]
            and summary["execution_sha256"]
            == digest(read_regular(execution_path, 1024 * 1024)),
            "retained native XML no longer binds the original execution record",
        )
        result["native"] = check_native_xml(xml, stdout, collector)
        result["junit_collection_is_not_another_execution"] = True
        result["status"] = "passed"
        exit_code = 0
    except KeyboardInterrupt as error:
        result["status"] = "interrupted"
        result["error"] = str(error)
        exit_code = 130
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result["status"] = "failed" if artifacts is not None else "rejected"
        exit_code = 2
    finally:
        if owner is not None and before is not None:
            try:
                result["after"] = owner.identity()
                if result["after"] != before:
                    result["status"] = "failed"
                    result["source_changed"] = True
                    exit_code = 2
                if spec is not None:
                    check_inputs(spec)
            except Exception as error:
                result["postcheck_error"] = f"{type(error).__name__}: {error}"
                result["status"] = "failed"
                exit_code = 2
        if deadline is not None and time.monotonic() > deadline:
            result["status"] = "failed"
            result["deadline_exceeded_after_postcheck"] = True
            exit_code = 124
        result["elapsed_seconds"] = time.monotonic() - started
        result["exit_code"] = exit_code
        result["scope_cost_includes_commands_and_collection"] = True
        result["os_spawn_io_signal_and_final_reap_are_not_hard_real_time"] = True
        if artifacts is not None:
            write_new(artifacts / "RESULT.json", result)
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
        if previous_target is None:
            os.environ.pop("CARGO_TARGET_DIR", None)
        else:
            os.environ["CARGO_TARGET_DIR"] = previous_target
        if previous_toolchain is None:
            os.environ.pop("RUSTUP_TOOLCHAIN", None)
        else:
            os.environ["RUSTUP_TOOLCHAIN"] = previous_toolchain
        os.chdir(previous_cwd)
        print(json.dumps(result, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
