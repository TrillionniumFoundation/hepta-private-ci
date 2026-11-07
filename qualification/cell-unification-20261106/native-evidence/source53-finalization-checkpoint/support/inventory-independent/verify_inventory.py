"""Verify closed inventory evidence using local bytes and AST only; execute no toolchain."""
from pathlib import Path, PurePosixPath
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
INPUT = ROOT / "native-validation-results/source53-formatter-tool-inventory-closed"
T = "/home/alex/work/hepta-cell-unified-20261106-a"
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def plain(raw):
    return {k: v for k, v in pin(raw).items() if k != "git_blob"}


def put(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with (OUT / name).open("xb") as stream:
        stream.write(raw)
    return pin(raw)


def main():
    local_raw = (INPUT / "LOCAL-READBACK.json").read_bytes()
    assert len(local_raw) == 12006 and pin(local_raw)["sha256"] == "316b4fe98ac78ee34fb62d415b32e24bbc8f351f013e2ea3eff1941869cc0632"
    declared = json.loads(local_raw)["files"]
    assert len(declared) == 42 and len({r["path"] for r in declared}) == 42
    names = {str(p.relative_to(INPUT)) for p in INPUT.rglob("*") if p.is_file()}
    assert names == {r["path"] for r in declared} | {"LOCAL-READBACK.json"}
    raw_files = {}
    for row in declared:
        path = INPUT / row["path"]
        assert not path.is_symlink()
        raw = path.read_bytes()
        assert pin(raw) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        raw_files[row["path"]] = raw
    def raw(name): return raw_files[name]
    def obj(name): return json.loads(raw(name))
    inventory_raw = raw("evidence/inventory.json")
    assert pin(inventory_raw)["sha256"] == "2b5e16723c8b91d9f7e784c5063f6dda5226c47ec4cca5f176fa448bb9899ed8"
    inventory = json.loads(inventory_raw)
    assert len(inventory_raw) == 8480

    transported = {}
    for name in ("transport/batch0-original.json", "transport/batch1-original.json"):
        batch = obj(name)
        assert batch["encoding"] == "utf-8" and batch["truncated"] is False
        for entry in batch["files"]:
            assert entry["path"].startswith(T + "/evidence/source53-formatter-tool-inventory/")
            basename = entry["path"].rsplit("/", 1)[1]
            assert basename not in transported and entry["eof"] is True and entry["version"]
            data = entry["text"].encode()
            assert plain(data) == {"bytes": entry["size"], "sha256": entry["sha256"]}
            assert data == raw("evidence/" + basename)
            transported[basename] = {"path": entry["path"], "version": entry["version"], **pin(data)}
    assert len(transported) == 29 and {"evidence/" + k for k in transported} == {n for n in names if n.startswith("evidence/")}

    consumer_path = ROOT / "source53-finalize-preparation/native-finalize-source53-template.py"
    consumer_raw = consumer_path.read_bytes()
    assert len(consumer_raw) == 174038 and pin(consumer_raw)["sha256"] == "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d"
    consumer_tree = ast.parse(consumer_raw)
    fn = next(n for n in consumer_tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify_tools")
    versions_node = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign) and len(n.targets) == 1
                         and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "expected_versions")
    expected_versions = ast.literal_eval(versions_node.value)
    consumer_segment = ast.get_source_segment(consumer_raw.decode(), fn).encode()
    assert set(inventory["tools"]) == set(expected_versions) and len(expected_versions) == 5
    assert inventory["schema"] == "hepta.source53-formatter-readonly-inventory.v1"
    assert inventory["source_commit"] == COMMIT and inventory["source_tree"] == TREE
    assert inventory["source_manifest"] == {"bytes": 56747, "sha256": "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda"}
    assert inventory["inventory_complete"] is True and inventory["source_guard_pass"] is True and inventory["issues"] == []
    for key in ("formatter_commands_executed", "sync_install_compile_fix_executed", "active_rust_environment_modified", "behavior_repair_claimed"):
        assert inventory[key] is False
    assert inventory["diagnostic_only"] is True
    formatter = obj("evidence/formatter-env-original.json")
    assert formatter == {"UV_PROJECT_ENVIRONMENT": T + "/tools/python-scripts-env", "UV_CACHE_DIR": T + "/tools/uv-cache", "UV_PYTHON_DOWNLOADS": "never"}
    assert inventory["formatter_env"] == plain(raw("evidence/formatter-env-original.json"))
    assert inventory["toolchain"] == "1.96.0" and inventory["effective_path"].startswith(T + "/bin:/home/alex/.cargo/bin:")
    assert inventory["project_environment_exists"] is True and inventory["uv_cache_exists"] is True
    assert inventory["pyvenv_cfg"] == plain(raw("evidence/pyvenv.cfg"))

    version_receipts = {}
    for name in ("just", "python3", "uv", "rustfmt-path", "rustfmt", "ruff"):
        process = obj("evidence/" + name + "-raw-process-result.json")
        receipt = obj("evidence/" + name + "-receipt.json")
        assert process["exit_code"] == receipt["exit_code"] == 0
        assert process == {k: v for k, v in receipt.items() if k not in ("stdout", "stderr")}
        assert receipt["name"] == name and receipt["end_unix"] >= receipt["start_unix"]
        for stream in ("stdout", "stderr"):
            assert receipt[stream] == plain(raw("evidence/" + name + "." + stream))
        assert raw("evidence/" + name + ".stderr") == b""
        version_receipts[name] = receipt
    for name, expected in expected_versions.items():
        tool = inventory["tools"][name]
        identity = tool["identity"]
        assert identity["found"] is True and PurePosixPath(identity["requested"]).is_absolute() and PurePosixPath(identity["resolved"]).is_absolute()
        assert identity["bytes"] > 0 and re.fullmatch("[0-9a-f]{64}", identity["sha256"])
        assert int(identity["mode"], 8) & 0o111
        assert isinstance(identity["requested_is_symlink"], bool)
        receipt_name = "rustfmt" if name == "rustfmt-1.96.0" else name
        receipt = version_receipts[receipt_name]
        assert tool["version"] == receipt
        assert tool["version_stdout"] == expected and tool["version_stderr"] == ""
        assert raw("evidence/" + receipt_name + ".stdout") == expected.encode()
        assert receipt["command"] == [identity["requested"], "--version"]
        assert receipt["cwd"] == T + ("/source" if name == "ruff" else "/source/codex-rs")
    assert inventory["tools"]["ruff"]["matches_locked_version"] is True and inventory["tools"]["ruff"]["locked_version"] == "0.15.13"
    resolver = inventory["rustup_resolver_identity"]
    assert resolver["found"] is True and PurePosixPath(resolver["requested"]).is_absolute()
    assert resolver["bytes"] > 0 and re.fullmatch("[0-9a-f]{64}", resolver["sha256"]) and int(resolver["mode"], 8) & 0o111
    query = version_receipts["rustfmt-path"]
    assert query == inventory["rustfmt_path_query"] and query["cwd"] == T + "/source"
    assert query["command"] == [resolver["requested"], "which", "--toolchain", "1.96.0", "rustfmt"]
    target = inventory["tools"]["rustfmt-1.96.0"]["identity"]["requested"]
    assert raw("evidence/rustfmt-path.stdout") == (target + "\n").encode()

    script = raw("input/inventory-executed.py")
    assert len(script) == 13210 and pin(script)["sha256"] == "8abb380ae59ad6fd0ee18de3e0987cb6303c810af0ec34a5b7f20a79c8522806"
    script_ast = ast.parse(script)
    constants = {}
    for node in script_ast.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try: constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError): pass
    assert constants["FROZEN"] is True and constants["EXPECTED_SOURCE_COMMIT"] == COMMIT and constants["EXPECTED_SOURCE_TREE"] == TREE
    assert raw("evidence/source-before.json") == raw("evidence/source-after.json")
    guard = obj("evidence/source-before.json")
    assert guard["pass"] is True and guard["source_commit"] == COMMIT and guard["expected_source_tree"] == TREE
    assert guard["native_head"] == HEAD and guard["changed_file_count"] == 197 and guard["index_and_source_rows_equal"] is True
    assert {k: v["sha256"] for k, v in guard["locks"].items()} == constants["LOCKS"]
    assert {k: v["sha256"] for k, v in guard["support"].items()} == constants["SUPPORT"]
    manifest_path = ROOT / "source53-final-scope-preparation/input/native-candidate-r30-source.json"
    manifest_raw = manifest_path.read_bytes()
    assert plain(manifest_raw) == inventory["source_manifest"]
    manifest = json.loads(manifest_raw)
    assert len(manifest["changed_files"]) == 197 and manifest["source_commit"] == COMMIT and manifest["source_tree"] == TREE
    support_pins = []
    for relative, expected in guard["support"].items():
        support = ROOT / "source53-final-scope-preparation/input/primary/original" / relative
        assert plain(support.read_bytes()) == expected
        support_pins.append({"path": str(support.relative_to(ROOT)), **pin(support.read_bytes())})

    prerequisite = obj("input/native-workspace-r31-terminal-process-status.json")
    prerequisite_pin = plain(raw("input/native-workspace-r31-terminal-process-status.json"))
    assert prerequisite_pin == {"bytes": 731, "sha256": "56e8d10b8a04bb14fd5ec432610878f9d648ca724d4fe860f644d7831f93047e"}
    assert inventory["workspace_terminal_observed"] == {"path": "native-workspace-r31-terminal-process-status.json", **prerequisite_pin}
    assert prerequisite["job_id"] == "1a1b275ba33-fc05-7e17" and prerequisite["state"] == "succeeded" and prerequisite["exit_code"] == 0
    assert inventory["workspace_original_exit_code"] == 0 and inventory["workspace_terminal_state"] == "succeeded"
    assert inventory["workspace_pass_not_implied_by_inventory"] is True

    auth = obj("input/ROOT-EXECUTION-AUTHORIZATION.json")
    assert auth["authorized"] is True and {k: auth["script"][k] for k in ("bytes", "sha256", "git_blob")} == pin(script)
    assert auth["source_commit"] == COMMIT and auth["source_tree"] == TREE and auth["source_count"] == 197
    assert auth["Rust_tests_metadata_fix_fmt_install_source_mutation_authorized"] is False
    assert {k: auth["actual_R31_natural_terminal"][k] for k in ("bytes", "sha256", "git_blob")} == pin(raw("input/native-workspace-r31-terminal-process-status.json"))
    upload, info = obj("transport/upload-original.json"), obj("transport/file_info-original.json")
    assert upload["written"] == upload["size"] == info["size"] == len(script)
    assert upload["sha256"] == info["sha256"] == pin(script)["sha256"] and upload["version"] == info["version"]
    assert info["path"] == auth["native_path"]
    launch_args, launch = obj("controller/launch_args-original.json"), obj("controller/launch-original.json")
    job = launch["job"]
    assert launch["launch"]["ok"] is True and launch["reused"] is False and job["launch_error"] is None
    assert job["id"] == "1a1b29af2e2-fc05-7ee3"
    for key in ("executable", "args", "cwd", "idempotency_key"):
        assert launch_args[key] == job[key] == auth[key]
    assert launch_args["timeout_seconds"] == auth["outer_timeout_seconds"] == 120
    assert job["env_keys"] == auth["env_keys"] == []
    assert job["executable"] == "/usr/bin/python3" and len(job["args"]) == 1 and job["args"][0] == info["path"]
    terminal, readback = obj("controller/terminal-original.json"), obj("controller/read-original.json")
    assert terminal["job_id"] == readback["job_id"] == job["id"]
    for term in (terminal, prerequisite):
        assert term["state"] == "succeeded" and term["exit_code"] == 0 and term["output_complete"] is term["output_durable"] is term["terminal_publication_confirmed"] is True
        assert term["automatic_retry"] is term["timed_out"] is term["cancelled"] is False
        for stream in ("stdout", "stderr"):
            assert term["log_bytes"][stream]["seen"] == term["log_bytes"][stream]["stored"]
            assert term["log_truncated"][stream] is False and term["log_synced"][stream] is True and term["log_errors"][stream] is None
    assert prerequisite["at_unix_ms"] < job["created_unix_ms"] < terminal["at_unix_ms"]
    for stream in ("stdout", "stderr"):
        value = readback[stream]
        content = raw("controller/original-" + stream + ".log")
        assert value["eof"] is True and value["offset"] == 0 and value["next_offset"] == value["size"] == len(content)
        assert bytes.fromhex(value["bytes_hex"]) == value["text"].encode() == content
        assert terminal["log_bytes"][stream]["stored"] == len(content)
    assert len(raw("controller/original-stdout.log")) == 161 and raw("controller/original-stderr.log") == b""
    assert json.loads(raw("controller/original-stdout.log")) == {"directory": T + "/evidence/source53-formatter-tool-inventory", "inventory_complete": True, "source_guard_pass": True}
    for receipt in version_receipts.values():
        assert job["created_unix_ms"] / 1000 <= receipt["start_unix"] <= receipt["end_unix"] <= terminal["at_unix_ms"] / 1000

    input_pins = [{"path": str((INPUT / name).relative_to(ROOT)), **pin(data)} for name, data in raw_files.items()]
    input_pins += [{"path": str((INPUT / "LOCAL-READBACK.json").relative_to(ROOT)), **pin(local_raw)},
                   {"path": str(consumer_path.relative_to(ROOT)), **pin(consumer_raw)},
                   {"path": str(manifest_path.relative_to(ROOT)), **pin(manifest_raw)}]
    input_pins += support_pins
    report = {"schema": "hepta.source53-formatter-inventory-actual-independent-readback.v1",
              "result": "ACTUAL_CLOSED_INVENTORY_CLEAR_FOR_ROOT_BINDING_NOT_FINALIZER_AUTHORIZATION",
              "native_original_file_count": 29, "controller_transport_authorization_script_file_count": 13,
              "all42_raw_sha256_git_blob_and_exact_set_verified": True,
              "both_original_transport_batches_reconstruct_all29_files_exactly": True,
              "inventory": {"path": "source53-formatter-tool-inventory/inventory.json", **pin(inventory_raw)},
              "source_commit": COMMIT, "source_tree": TREE, "source_manifest": inventory["source_manifest"],
              "source_before_after_full_bytes_identical": pin(raw("evidence/source-before.json")),
              "native_recorded_guard": guard,
              "source_rows_and_actual_executable_bytes_not_reprobed_from_local_reader": True,
              "actual_native_guard_per197_file_algorithm_reviewed_in_exact_executed_script": True,
              "query_count": 6, "all_original_query_raw_and_receipt_exit_codes": [0] * 6,
              "queries": list(version_receipts.values()), "expected_and_observed_versions": expected_versions,
              "actual_finalizer_consumer": {"path": str(consumer_path.relative_to(ROOT)), **pin(consumer_raw), "verify_tools_function": pin(consumer_segment)},
              "source_schema_manifest_env_versions_streams_Ruff_lock_and_target_query_match_consumer": True,
              "formatter_env_exact_original_three_keys": formatter,
              "tool_identities_are_native_observations_not_new_local_binary_reads": {name: tool["identity"] for name, tool in inventory["tools"].items()},
              "runtime_checks_still_required": [
                  "Current PATH, executable resolution/mode/symlink and full executable bytes before each finalization command.",
                  "PATH rustfmt shim must match recorded rustup resolver; this inventory did not independently record the shim.",
                  "Prepared venv/cache/pyvenv.cfg and absence of source-local .venv are rechecked by the finalizer.",
                  "Same-source complete workspace/project proofs, root authorization and full source/scope guards remain separate prerequisites."],
              "R31_original_terminal_pin": pin(raw("input/native-workspace-r31-terminal-process-status.json")),
              "R31_full_log_test_counts_not_reviewed_in_this_inventory_readback": True,
              "inventory_natural_outer": terminal,
              "execution_after_R31_natural_terminal_verified": True,
              "local_reader_ran_versions_or_Rust_or_metadata_or_finalizer": False,
              "native_inventory_ran_format_sync_install_compile_fix": False,
              "new_authorization_granted": False, "diagnostic_only": True, "behavior_repair_claimed": False,
              "science": "HOLD", "authority": "DENY_ALL"}
    bindings = {"TOOL_INVENTORY_NAME": "source53-formatter-tool-inventory/inventory.json",
                "TOOL_INVENTORY_BYTES": len(inventory_raw), "TOOL_INVENTORY_SHA256": pin(inventory_raw)["sha256"],
                "TOOL_INVENTORY_SCHEMA": inventory["schema"], "TOOL_INVENTORY_SOURCE_COMMIT": COMMIT,
                "TOOL_INVENTORY_SOURCE_TREE": TREE, "TOOL_INVENTORY_SOURCE_MANIFEST": inventory["source_manifest"]}
    report_pin = put("INDEPENDENT-READBACK.json", report)
    put("PROPOSED-TOOL-BINDINGS.json", {"schema": "hepta.proposed-tool-binding-only.v1", "bindings": bindings,
        "finalizer_not_modified": True, "execution_not_authorized": True})
    put("INPUT-PINS.json", {"schema": "hepta.inventory-actual-readback-input-pins.v1", "files": input_pins})
    files = [{"path": p.name, **pin(p.read_bytes())} for p in sorted(OUT.iterdir()) if p.is_file()]
    handoff_pin = put("HANDOFF-MANIFEST.json", {"schema": "hepta.inventory-actual-independent-handoff.v1", "files": files,
        "readback_result": report["result"], "native_execution_by_reader": False})
    print(json.dumps({"readback": report_pin, "handoff": handoff_pin, "result": report["result"]}))


if __name__ == "__main__":
    main()
