#!/usr/bin/env python3
"""Pure local scope derivation. Never invokes Cargo, Git, Rust, fix, or fmt."""
import ast
import gzip
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

FROZEN = False
R31_JOB_ID = None
INPUT_PINS = None

HERE = Path(__file__).resolve().parent
T = PurePosixPath("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
CARGO_SHA = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_SHA = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
META_COMMAND = ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
WORKSPACE_COMMAND = ["just", "test", "--locked", "--retries", "0"]
PREFIX = "native-workspace-r31"
OWNER_NAMES = sorted([
    "codex-app-server", "codex-app-server-client", "codex-cli", "codex-core", "codex-exec-server",
    "codex-external-agent-migration", "codex-hepta-agent-protocol", "codex-hepta-agentd",
    "codex-hepta-automation", "codex-hepta-context-compiler", "codex-hepta-infer-worker-host",
    "codex-hepta-intelligence", "codex-hepta-learning-artifacts", "codex-hepta-memory",
    "codex-hepta-memory-extension", "codex-hepta-neuron", "codex-hepta-plasticity",
    "codex-hepta-runtime", "codex-hepta-supervisor", "codex-linux-sandbox", "codex-mcp",
    "codex-model-provider-info", "codex-network-proxy", "codex-shell-escalation", "codex-utils-pty",
    "core_test_support",
])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(name):
    require(name in INPUT_PINS, "unbound input: " + name)
    path = HERE / name
    require(path.is_file() and not path.is_symlink(), "not a regular input: " + name)
    raw = path.read_bytes()
    require(pin(raw) == INPUT_PINS[name], "input bytes changed: " + name)
    return raw


def load(name):
    return json.loads(read(name))


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()


def write(name, raw):
    with (HERE / name).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": name, **pin(raw)}


def record_pin(name, raw):
    return {"path": name, **pin(raw)}


def source_identity(value):
    require(value["source_commit"] == COMMIT and value["source_tree"] == TREE, "source identity differs")


def guard(value):
    require(value["source_commit"] == COMMIT and value["expected_tree"] == value["actual_tree"] == TREE,
            "source guard identity differs")
    require(value["pass"] is True and value["changed_file_count"] == 197 and value["native_head"] == HEAD,
            "source guard count/HEAD/failure")
    require(value["changed_path_set_matches"] is True and value["unstaged_paths"] == []
            and value["untracked_paths"] == [] and value["file_mismatches"] == [], "source guard mismatch")
    require(value["cargo_lock_sha256"] == CARGO_SHA and value["bazel_lock_sha256"] == BAZEL_SHA,
            "source guard dual locks differ")


def verify_fresh_metadata(source_raw):
    root = "input/r31-start/"
    evidence = root + "evidence/" + PREFIX
    metadata_raw = gzip.decompress(read("input/native-workspace-r31-metadata.json.gz"))
    metadata = json.loads(metadata_raw)
    scope_raw = read("input/native-workspace-r31-scope.json")
    scope = json.loads(scope_raw)
    raw_bytes = read(evidence + "-metadata-raw-process-result.json")
    post_bytes = read(evidence + "-metadata-source-post-verification.json")
    receipt_bytes = read(evidence + "-metadata-receipt.json")
    stderr = read(evidence + "-metadata-stderr.log")
    raw, post, receipt = map(json.loads, (raw_bytes, post_bytes, receipt_bytes))
    environment = load(evidence + "-environment.json")
    pre = load(evidence + "-preconditions.json")
    pre_bytes = read(evidence + "-source-pre-verification.json")
    initial_guard = json.loads(pre_bytes)
    for item in (receipt, raw, environment, pre, scope):
        source_identity(item)
    guard(post)
    guard(initial_guard)
    require(raw["schema"] == "hepta.native-raw-process-result.v1" and raw["phase"] == "workspace-metadata",
            "unexpected metadata raw schema/phase")
    require(receipt["schema"] == "hepta.native-metadata-receipt.v1", "unexpected metadata receipt")
    for item in (raw, receipt):
        require(item["command"] == META_COMMAND and item["cwd"] == str(S / "codex-rs")
                and item["exit_code"] == 0, "actual metadata invocation failed or differs")
    require(raw["start_unix"] == receipt["start_unix"] and raw["end_unix"] == receipt["end_unix"]
            and receipt["elapsed_seconds"] == raw["end_unix"] - raw["start_unix"], "metadata times differ")
    require(receipt["raw_process_result"] == record_pin(PREFIX + "-metadata-raw-process-result.json", raw_bytes)
            and receipt["source_postguard"] == record_pin(PREFIX + "-metadata-source-post-verification.json", post_bytes)
            and receipt["source_guards_pass"] is True, "receipt does not bind raw/postguard")
    require(receipt["stdout"] == pin(metadata_raw) and receipt["stderr"] == pin(stderr) and stderr == b"",
            "metadata stdout/stderr differs")
    require(raw["resources_not_collected_for_read_only_metadata"] is True,
            "metadata must not fabricate a time/resource receipt")
    require(pre["actual_changed_file_count"] == 197
            and pre["source_manifest"] == record_pin("native-candidate-r30-source.json", source_raw)
            and pre["initial_source_guard"] == record_pin(PREFIX + "-source-pre-verification.json", pre_bytes),
            "current preconditions do not bind source/guard")
    require(pre["workspace_test_command"] == WORKSPACE_COMMAND and pre["fix_fmt_executed"] is False
            and pre["historical_project_pass_substitutes_for_r30"] is False
            and pre["diagnostic_only"] is True and pre["behavior_repair_claimed"] is False,
            "precondition scope/diagnostic boundary changed")
    require(environment["source_manifest_sha256"] == pin(source_raw)["sha256"]
            and environment["fresh_current_source_metadata_required"] is True
            and environment["original_default_workspace_selection"] is True,
            "environment current source differs")

    mi = load(root + "transport/metadata_info-original.json")
    si = load(root + "transport/scope_info-original.json")
    for info, payload, name in ((mi, metadata_raw, "metadata"), (si, scope_raw, "scope")):
        require(info["path"] == str(T / "evidence" / (PREFIX + "-" + name + ".json"))
                and info["size"] == len(payload) and info["sha256"] == pin(payload)["sha256"]
                and bool(info["version"]), "actual native file_info mismatch: " + name)
    require(load("transport/scope-file-info-original.json") == si, "scope pinned version changed")
    transfer = load("TRANSFER-READBACK.json")
    require(transfer["scope_file_info"] == si and transfer["metadata_fresh_file_info"] == mi
            and transfer["metadata_uncompressed"] == pin(metadata_raw)
            and transfer["metadata_new_native_invocation_preserved"] is True
            and transfer["metadata_byte_cache_reuse_only"] is True
            and transfer["old_r29_invocation_not_relabelled"] is True, "transfer provenance differs")

    auth = load("input/ROOT-R31-EXECUTION-AUTHORIZATION.json")
    source_identity(auth)
    require(auth["fresh_current_metadata_command"] == META_COMMAND
            and auth["workspace_command"] == WORKSPACE_COMMAND and auth["fix_fmt_authorized"] is False,
            "root authorization differs")
    launch = load(root + "controller/launch-original.json")
    job = launch["job"]
    require(job["id"] == R31_JOB_ID and job["host"] == "pocket4"
            and job["idempotency_key"] == auth["unique_launch_key"]
            and job["executable"] == "/usr/bin/python3" and job["args"] == [auth["runner"]["native_path"]]
            and job["cwd"] == str(T) and launch["launch"]["ok"] is True,
            "actual launch does not match root authorization")
    runner_info = load(root + "transport/runner_info-original.json")
    require(runner_info["path"] == auth["runner"]["native_path"]
            and runner_info["size"] == auth["runner"]["bytes"]
            and runner_info["sha256"] == auth["runner"]["sha256"], "actual runner file_info differs")
    require(raw["start_unix"] * 1000 >= job["created_unix_ms"], "metadata predates current job")

    packages = {row["id"]: row for row in metadata["packages"]}
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    require(len(packages) == len(metadata["packages"]) == len(members) == len(defaults) == 193
            and len(set(members)) == len(set(defaults)) == 193 and set(packages) == set(members) == set(defaults),
            "actual 193 member/default identity set differs")
    expected_scope = {
        "schema": "hepta.source53-current-default-workspace-scope.v1", "source_tree": TREE, "source_commit": COMMIT,
        "metadata_command": META_COMMAND, "metadata": record_pin(PREFIX + "-metadata.json", metadata_raw),
        "metadata_generated_on_current_source": True, "old_metadata_reused_as_current": False,
        "workspace_root": metadata["workspace_root"], "target_directory": metadata["target_directory"],
        "workspace_member_count": 193, "workspace_default_member_count": 193,
        "workspace_members": [{"id": pid, "name": packages[pid]["name"], "manifest_path": packages[pid]["manifest_path"]} for pid in members],
        "workspace_default_members": [{"id": pid, "name": packages[pid]["name"]} for pid in defaults],
        "command": WORKSPACE_COMMAND, "features": "unchanged_defaults", "filters": "no_additions",
        "all_platforms_features_external_services_qualified": False, "diagnostic_only": True,
        "behavior_repair_claimed": False,
    }
    require(scope == expected_scope, "scope does not exactly match actual metadata producer, including original ordering")
    require(metadata["workspace_root"] == str(S / "codex-rs") and metadata["target_directory"] == str(T / "target"),
            "actual metadata paths differ")
    return metadata, metadata_raw, {"job_id": R31_JOB_ID, "metadata_exit_code": 0,
        "metadata_elapsed_seconds": receipt["elapsed_seconds"], "metadata": pin(metadata_raw),
        "scope": pin(scope_raw), "metadata_file_info": mi, "scope_file_info": si,
        "new_native_invocation_verified": True, "local_bytes_reused_from_equal_hash_cache": True,
        "workspace_terminal_status": None, "workspace_pass_claimed": False,
        "fix_fmt_authorized": False, "all_other_gate_claims_excluded": True}


def main():
    require(__debug__, "optimized Python is not allowed")
    require(FROZEN is True and R31_JOB_ID is not None and INPUT_PINS is not None,
            "inert template: actual closed input bindings are required")
    for name in INPUT_PINS:
        read(name)
    source_raw = read("input/native-candidate-r30-source.json")
    source = json.loads(source_raw)
    source_identity(source)
    rows = {row["path"]: row for row in source["changed_files"]}
    require(len(rows) == len(source["changed_files"]) == 197, "source row count or duplicate")
    require(source["cargo_lock_sha256"] == CARGO_SHA and source["bazel_lock_sha256"] == BAZEL_SHA,
            "manifest dual locks differ")
    previous = load("input/source52-parent-manifest.json")
    previous_rows = {row["path"]: row for row in previous["changed_files"]}
    require(len(previous_rows) == 195 and all(rows[path] == row for path, row in previous_rows.items()),
            "original 195 rows changed")
    require(set(rows) - set(previous_rows) == {
        "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
        "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"}, "source53 addition differs")
    metadata, metadata_raw, invocation = verify_fresh_metadata(source_raw)
    paths = sorted(rows)
    rust_paths = [path for path in paths if path.endswith(".rs")]
    require(len(rust_paths) == 183, "Rust count differs")
    python_paths = ["./" + path for path in paths if path.startswith(("scripts/", ".github/")) and path.endswith((".py", ".pyi"))]
    require(python_paths == ["./scripts/run-nextest.py", "./scripts/test_run_nextest_helpers.py"], "Python selection differs")
    require(not any(PurePosixPath(path).name in {"rustfmt.toml", ".rustfmt.toml", "pyproject.toml", "ruff.toml", ".ruff.toml"} for path in paths),
            "formatter configuration changed")
    require("justfile" not in rows and not any(
        PurePosixPath(path).name in {"BUILD", "WORKSPACE", "MODULE.bazel"}
        or PurePosixPath(path).name.startswith(("BUILD.", "WORKSPACE."))
        or path.endswith((".BUILD.bazel", ".MODULE.bazel", ".bzl", ".sky"))
        or ".bzl." in PurePosixPath(path).name or ".sky." in PurePosixPath(path).name for path in paths),
        "another default formatter group is selected")
    roots = {}
    defaults = set(metadata["workspace_default_members"])
    for package in metadata["packages"]:
        manifest = PurePosixPath(package["manifest_path"]).relative_to(S).as_posix()
        directory = PurePosixPath(manifest).parent.as_posix()
        require(directory not in roots and manifest.endswith("/Cargo.toml"), "ambiguous owning package")
        roots[directory] = {"package": package["name"], "package_id": package["id"],
            "package_directory": directory, "manifest_path": manifest, "edition": package["edition"],
            "default_workspace_member": package["id"] in defaults}
    owners = {}
    for path in rust_paths:
        matches = [root for root in roots if path.startswith(root + "/")]
        require(bool(matches), "missing owner: " + path)
        root = max(matches, key=lambda value: len(PurePosixPath(value).parts))
        package = roots[root]
        entry = owners.setdefault(package["package"], {**package, "rust_paths": []})
        require(entry["package_directory"] == root, "owner name collision")
        entry["rust_paths"].append(path)
    require(sorted(owners) == OWNER_NAMES and len(owners) == 26, "owner set differs")
    primary_raw = read("input/unchanged-PRIMARY-SOURCE-PINS.json")
    require(len(primary_raw) == 13098 and pin(primary_raw)["sha256"] == "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3",
            "primary source pin bytes changed")
    primary = json.loads(primary_raw)
    primary_by_path = {row["path"][len("original/"):]: row for row in primary}
    require(len(primary) == len(primary_by_path) == 34, "primary pin cardinality differs")
    for path, row in primary_by_path.items():
        actual = read("input/primary/original/" + path)
        require(pin(actual) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "primary input changed: " + path)
        if path in rows:
            require(pin(actual) == {key: rows[path][key] for key in ("bytes", "sha256", "git_blob")},
                    "primary input does not match current changed manifest: " + path)
    workspace_toml = tomllib.loads(read("input/primary/original/codex-rs/Cargo.toml").decode())
    for owner in owners.values():
        owner["rust_path_count"] = len(owner["rust_paths"])
        require(owner["edition"] == "2024" and owner["default_workspace_member"] is True,
                "owner edition/default scope differs")
        require(owner["manifest_path"] in primary_by_path, "owner not explicitly pinned")
        cargo = tomllib.loads(read("input/primary/original/" + owner["manifest_path"]).decode())
        require(cargo["package"]["name"] == owner["package"], "owner name differs from original TOML")
        edition = cargo["package"]["edition"]
        if isinstance(edition, dict):
            require(edition == {"workspace": True}, "unsupported inherited edition")
            edition = workspace_toml["workspace"]["package"]["edition"]
        require(str(edition) == owner["edition"], "original TOML edition differs from fresh metadata")
    workflow = read("input/hepta-cell-framework-native.yml")
    require(pin(workflow) == {key: rows[".github/workflows/hepta-cell-framework-native.yml"][key] for key in ("bytes", "sha256", "git_blob")},
            "workflow differs from source53")
    selectors = re.findall(r"(?<!\S)-p\s+([A-Za-z0-9_-]+)", workflow.decode())
    require(len(selectors) == len(set(selectors)) == 27
            and set(selectors) == set(owners) | {"codex-hepta-control-plane"}, "actual CI selector scope differs")
    formatter = read("input/primary/original/scripts/format.py").decode()
    functions = {node.name: ast.get_source_segment(formatter, node) for node in ast.parse(formatter).body if isinstance(node, ast.FunctionDef)}
    require('revision = "HEAD"' in functions["changed_paths"]
            and '"--no-renames"' in functions["changed_paths"] and '"--diff-filter=ACDMRT"' in functions["changed_paths"]
            and 'changed_paths(args.base)' in functions["main"], "original default formatter algorithm changed")
    require('imports_granularity=Item,skip_children=true' in functions["rust_file_command"]
            and '"uv"' in functions["python_scripts_formatter_group"]
            and '"--frozen"' in functions["python_scripts_formatter_group"], "formatter commands changed")
    justfile = read("input/primary/original/justfile").decode()
    require('fix *args:\n    cargo clippy --fix --tests --allow-dirty {args}' in justfile
            and 'fmt *args:\n    @{{ python }} ../scripts/format.py {args}' in justfile,
            "original just recipes changed")

    names = sorted(owners)
    args = [value for name in names for value in ("-p", name)]
    source_pin = record_pin("input/native-candidate-r30-source.json", source_raw)
    proposed = {"schema": "hepta.source53-final-fix-packages.v1",
        "status": "SCOPE_PREPARATION_ONLY_SAME_SOURCE_R31_TERMINAL_AND_TOOL_INVENTORY_PENDING",
        "source_commit": COMMIT, "source_tree": TREE, "source_manifest": source_pin,
        "fresh_metadata": pin(metadata_raw), "owners": names, "package_args": args,
        "command": ["just", "fix", "--locked", *args],
        "recipe_expansion": ["cargo", "clippy", "--fix", "--tests", "--allow-dirty", "--locked", *args],
        "cwd": str(S / "codex-rs"), "fix_executed": False, "same_source_workspace_pass_bound": False,
        "diagnostic_only": True, "behavior_repair_claimed": False}
    expected = {"schema": "hepta.source53-final-formatter-selection.v1", "status": "NOT_EXECUTED_PREPARATION_ONLY",
        "source_commit": COMMIT, "source_tree": TREE, "native_HEAD": HEAD,
        "native_created_commit_checkout_claimed": False, "source_manifest": source_pin,
        "changed_path_count": 197, "changed_paths": paths, "rust_count": 183, "rust_paths": rust_paths,
        "python_count": 2, "python_paths": python_paths, "formatting_configuration_changed_paths": [],
        "owner_count": 26, "owners": [owners[name] for name in names], "ci_selector_count": 27,
        "ci_selectors": selectors, "extra_ci_only_owner": ["codex-hepta-control-plane"],
        "workspace_members": 193, "workspace_default_members": 193,
        "fresh_source53_r31_metadata_verified": True, "default_formatter_command": ["just", "fmt"],
        "all_flag_used": False, "python_formatter_command": ["uv", "run", "--frozen", "--project", "scripts", "ruff", "format", *python_paths],
        "unselected_by_default_formatter": sorted(set(paths) - set(rust_paths) - {path[2:] for path in python_paths}),
        "final_scope_execution_authorized": False, "post_fix_selection_must_be_revalidated_before_fmt": True,
        "unexpected_scope_or_dependency_change_requires_stop_without_reset_or_test_rerun": True,
        "workspace_result": None, "diagnostic_only": True, "behavior_repair_claimed": False}
    commands = []
    for path in rust_paths:
        owner = next(row for row in owners.values() if path in row["rust_paths"])
        commands.append({"path": path, "owning_package": owner["package"], "manifest_path": owner["manifest_path"],
            "cwd": str(S / owner["package_directory"]), "command": ["rustfmt", "--edition", "2024", "--config",
                "imports_granularity=Item,skip_children=true", "--", str(S / path)]})
    require(len(expected["unselected_by_default_formatter"]) == 12 and len(commands) == 183, "remaining formatter counts differ")
    artifacts = {"EXPECTED-SELECTION.json": encode(expected), "PACKAGE-ARGS.json": encode(proposed),
                 "RUST-FILE-COMMANDS.json": encode(commands), "PRIMARY-SOURCE-PINS.json": primary_raw}
    require(not any((HERE / name).exists() for name in [*artifacts, "READ-ONLY-AUDIT.json"]), "create-only outputs already exist")
    outputs = [write(name, data) for name, data in artifacts.items()]
    report = {"schema": "hepta.source53-fresh-r31-final-scope-readback.v1",
        "result": "READ_ONLY_SCOPE_CLEAR_NOT_EXECUTION_AUTHORIZATION", "source_commit": COMMIT, "source_tree": TREE,
        "counts": {"changed": 197, "rust": 183, "other": 14, "python_formatter": 2, "owners": 26, "ci_selectors": 27,
                   "workspace_members": 193, "workspace_default_members": 193, "unselected_default_formatter": 12},
        "fresh_invocation": invocation, "outputs": outputs, "primary_source_pin_bytes_unchanged": True,
        "owner_algorithm": "Longest Cargo manifest parent from actual fresh R31 metadata; exact original TOML edition readback.",
        "formatter_algorithm": "Unchanged format.py default HEAD selection, no config widening; 183 Rust and 2 Python scripts.",
        "native_HEAD": HEAD, "HEAD_changed": False, "created_commit_checkout_claimed": False,
        "consumer": "source53-finalize-preparation/native-finalize-source53-template.py",
        "consumer_sha256": "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d",
        "consumer_not_imported_or_executed": True, "source_manifest_historical_fields_preserved": True,
        "workspace_terminal_status": None, "workspace_result": None, "workspace_PASS_claimed": False,
        "fresh_tool_inventory_bound": False, "fix_executed": False, "fmt_executed": False,
        "native_or_cargo_or_rust_commands_executed_by_generator": False,
        "required_before_finalizer": "Actual complete same-source R31 PASS and R30 PASS with independent source guards, fresh tool inventory, explicit finalizer authorization; recheck default HEAD selection before fmt.",
        "diagnostic_only": True, "behavior_repair_claimed": False}
    audit = write("READ-ONLY-AUDIT.json", encode(report))
    print(json.dumps({"audit": audit, "outputs": outputs, "counts": report["counts"]}))


if __name__ == "__main__":
    main()
