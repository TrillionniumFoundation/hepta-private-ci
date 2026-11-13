"""Pure-data/AST preparation of an unexecutable qualification binding HOLD.

This program never imports a project, producer, admission or gate module. It
reads fixed local copies of complete Git GET responses and immutable evidence,
checks their identities, and writes only this isolated preparation directory.
It does not observe H, a source checkout, live Git metadata or runtime state.
"""
from pathlib import Path, PurePosixPath
import ast
import copy
import hashlib
import json
import os
import stat

ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
PIN_KEYS = ("bytes", "sha256", "git_blob")
HISTORICAL = "/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1"
DONOR = "/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1"
CURRENT = "/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1"
EVIDENCE = "/home/qian-qi/hepta-utility-36fa-evidence"
MATERIALIZATION_CONTROL = EVIDENCE + "/provider-coordinator-a489-isolated-materialization-v1"
MAINTENANCE_CONTROL = EVIDENCE + "/provider-coordinator-a489-maintenance-v1"
FINAL_FORMAT_CONTROL = EVIDENCE + "/provider-coordinator-a489-final-nonrust-format-v1"
CANONICAL_CONTROL = EVIDENCE + "/provider-coordinator-a489-final-canonical-alignment-v1"
SUBJECT = {
    "commit": "d25675445c39f76db69a7bd8e71a1a72e1cd5b9f",
    "tree": "a489b394666b8141840275128a780605b024cde0",
    "parents": ["cc57c7198db6293ccca562253c42fffbe2a04633"],
}
WORKFLOW = ".github/workflows/hepta-daemon-learning-native.yml"
FORMAT_BASE = "c0f78493f815780f68b9bf5e390a21314d79311f"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def pin3(value):
    return {key: value[key] for key in PIN_KEYS}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write(name, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, ("immutable output differs", name)
    else:
        path.write_bytes(raw)
    return {"name": name, **identity(raw)}


def read(name):
    return json.loads((INPUTS / name).read_bytes())


def spans(name):
    raw = (INPUTS / name).read_bytes()
    lines = raw.decode().splitlines(keepends=True)
    result = {}
    def walk(nodes, parent=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = parent + node.name
                first = min([node.lineno] + [item.lineno for item in node.decorator_list])
                body = "".join(lines[first - 1:node.end_lineno]).encode()
                result[key] = {"first_line": first, "last_line": node.end_lineno,
                               "source": identity(body),
                               "ast_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()}
            elif isinstance(node, ast.ClassDef):
                walk(node.body, parent + node.name + ".")
    walk(ast.parse(raw).body)
    return result


def normal(name, expected_job):
    outer = read(name)
    assert ("resultType" not in outer or outer["resultType"] == "complete")
    assert outer.get("isError") is False and len(outer.get("content", [])) == 1
    assert outer["content"][0].get("type") == "text"
    value = json.loads(outer["content"][0]["text"])
    assert value["job_id"] == expected_job
    assert value.get("state") == "succeeded" and value.get("exit_code") == 0
    for key in ("timed_out", "cancelled", "automatic_retry"):
        assert value.get(key) is False, key
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        assert value.get(key) is True, key
    assert not any(value.get("log_truncated", {}).values())
    return {"job_id": expected_job, "normal_zero_complete": True,
            "original": identity((INPUTS / name).read_bytes())}


def canonical_to_v5_projection(canonical):
    """Pure proposed schema bridge; this run has no final canonical input.

    Ownership is intentionally NOT verified by this lossy projection. A future
    admission must retain the entire canonical input and compare a fresh full
    uid/gid-bearing observation to it both before and after the original gate.
    This function only reconstructs the additional original V5 byte envelope.
    """
    assert set(canonical) == {"root", "files"}
    common = {"path", "kind", "mode", "uid", "gid", "device", "inode",
              "nlink", "mtime_ns", "ctime_ns"}
    rows = canonical["files"]
    assert isinstance(rows, list)
    assert rows == sorted(rows, key=lambda item: os.fsencode(item["path"]))
    indexed = {}
    children = {}
    for row in rows:
        path = row["path"]
        parts = PurePosixPath(path).parts
        assert isinstance(path, str) and parts and not path.startswith("/")
        assert all(part not in ("", ".", "..") for part in parts)
        assert "/".join(parts) == path and path not in indexed
        assert row["kind"] in ("file", "directory")
        assert set(row) == common | ({"bytes", "sha256"} if row["kind"] == "file" else set())
        for key in ("mode", "uid", "gid", "device", "inode", "nlink", "mtime_ns", "ctime_ns"):
            assert type(row[key]) is int
        indexed[path] = row
        parent = "/".join(parts[:-1])
        children.setdefault(parent, []).append(path)
    for path in indexed:
        parent = str(PurePosixPath(path).parent)
        if parent != ".":
            assert parent in indexed and indexed[parent]["kind"] == "directory"
    result = []
    def visit(parent):
        for path in sorted(children.get(parent, []), key=lambda item: os.fsencode(PurePosixPath(item).name)):
            row = indexed[path]
            result.append({key: value for key, value in row.items() if key not in ("uid", "gid")})
            if row["kind"] == "directory":
                visit(path)
    visit("")
    assert len(result) == len(rows)
    value = {"format": "hepta-source-git-metadata-inventory-v1", "root": canonical["root"], "files": result}
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main():
    original_rows = json.loads((ROOT / "ORIGINAL_INPUTS_FULL_GET.json").read_bytes())
    if isinstance(original_rows, dict):
        original_rows = original_rows["entries"]
    producer_rows = json.loads((ROOT / "PRODUCER_INPUTS_FULL_GET.v2.json").read_bytes())["entries"]
    all_rows = original_rows + producer_rows
    names = [row["name"] for row in all_rows]
    assert len(names) == len(set(names)) == 44
    checked = []
    for row in all_rows:
        raw = (INPUTS / row["name"]).read_bytes()
        assert identity(raw) == pin3(row), row["name"]
        sdk = ROOT / "github" / (row["name"] + ".GET.original.json")
        response = json.loads(sdk.read_bytes())
        assert response["structuredContent"]["content"].encode() == raw
        checked.append({"name": row["name"], **identity(raw), "actual_full_get_equal": True,
                        "get_sdk": {"name": sdk.relative_to(ROOT).as_posix(), **identity(sdk.read_bytes())}})
    index = {row["name"]: row for row in checked}
    def input_pin(name):
        return pin3(index[name])

    materialized = read("MATERIALIZATION_3BB_RESULT.json")
    materialization_packet = read("MATERIALIZATION_3BB_PACKET.json")
    maintenance = read("MAINTENANCE_41E_RESULT.json")
    maintenance_cfg = read("MAINTENANCE_41E_CONFIG.json")
    archive = read("ARCHIVE_V3_RESULT.json")
    archive_readback = read("ARCHIVE_V3_READBACK.json")
    old_environment = read("HISTORICAL_ENVIRONMENT_READY.json")
    final_format_cfg = read("FINAL_NONRUST_CONFIG.execution-candidate.json")
    canonical_cfg = read("CANONICAL_WAITING_CONFIG.HOLD.json")
    plan = read("PLAN_3AEF.json")
    bindings = read("STATIC_TEMPLATE_BINDINGS.json")
    old_qualification = json.loads((INPUTS / "historical-source-layout/APPROVED_QUALIFICATION_INPUT.json").read_bytes())
    old_source_cfg = json.loads((INPUTS / "historical-source-layout/APPROVED_SOURCE_GATES_CONFIG.json").read_bytes())
    normals = [normal("MATERIALIZATION_3BB_NORMAL.json", "1a1d468462a-392-3bb"),
               normal("MAINTENANCE_41E_NORMAL.json", "1a1d47cebc8-392-41e"),
               normal("ARCHIVE_V3_NORMAL.json", "1a1d38b82e9-392-160"),
               normal("HISTORICAL_RUNTIME_NORMAL.json", "1a1d0fcb212-2564-1bf4")]

    assert materialized["format"] == "hepta-complete-candidate-materialization-result-v1"
    assert materialized["status"] == "MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY"
    assert materialized["source_repo"] == DONOR and materialized["destination_repo"] == CURRENT
    assert {"commit": materialized["source_commit"], "tree": materialized["source_tree"], "parents": materialized["parents"]} == SUBJECT
    assert materialized["current_source_before"] == materialized["current_source_after"]
    clean_start = materialized["current_source_after"]
    assert clean_start["head"] == SUBJECT["commit"] and clean_start["tree"] == SUBJECT["tree"]
    assert clean_start["parents"] == SUBJECT["parents"] and clean_start["status"] == ""
    assert pin3(clean_start["inventory"]) == materialization_packet["current"]["inventory"]
    assert clean_start["native_inventory"] == materialization_packet["current"]["native_inventory"]
    assert materialized["physical_leaves_created"] == materialization_packet["current"]["leaves"] == 15243
    for key in ("new_repo_created", "action_completed", "new_files_and_directories_synced", "donor_physical_and_git_file_state_unchanged", "input_identities_unchanged"):
        assert materialized[key] is True
    for key in ("qualification", "old_source_writes", "remote_ref_updates", "cargo_or_formatter_started", "dependency_installation_started", "automatic_retry", "rollback"):
        assert materialized[key] is False
    assert materialized["test_commands_dispatched"] == 0 and materialized["cleanup_errors"] == []
    assert not any(key in materialized for key in ("error", "retention_error"))
    assert {item["check"]: item["status"] for item in materialized["final_audits"]} == {
        "donor_physical_source_and_git_files": "verified", "new_source_and_git": "verified", "inputs_and_coordination": "verified"}
    assert materialized["new_objects_fully_verified"] == 16661 and materialized["donor_objects_fully_verified"] == 16449
    assert materialized["object_scope"] == {**materialization_packet["object_scope"], "complete_ancestry": False,
                                           "donor_objects_must_be_read_from_git_bodies": 16449,
                                           "format_base_leaf_identities_verified": True}
    assert materialized["donor_source_before"] == materialized["donor_source_after"]
    assert materialized["donor_git_state_before"] == materialized["donor_git_state_after"]
    donor_actual = materialized["donor_git_state_after"]
    assert {key: donor_actual[key] for key in materialization_packet["donor_git"]} == materialization_packet["donor_git"]
    assert set(donor_actual) == set(materialization_packet["donor_git"]) | {"git_state", "refs"}
    assert donor_actual["git_state"]["head"] == materialization_packet["donor"]["commit"]
    assert donor_actual["git_state"]["tree"] == materialization_packet["donor"]["tree"]
    assert donor_actual["refs"] == identity(b"") and donor_actual["refs_base64"] == ""
    assert materialized["current_git_state_before"] == materialized["current_git_state_after"]
    for key, filename in (("command_records", "MATERIALIZATION_3BB_COMMANDS.json"),
                          ("mutation_records", "MATERIALIZATION_3BB_MUTATION_INTENTS.json"),
                          ("input_records", "MATERIALIZATION_3BB_INPUT_IDENTITIES.json"),
                          ("artifact_records", "MATERIALIZATION_3BB_ARTIFACTS.json")):
        assert pin3(materialized[key]) == input_pin(filename)
    commands = read("MATERIALIZATION_3BB_COMMANDS.json")
    assert commands and all(row.get("actual_terminal") == "observed" and row.get("returncode") == 0 and row.get("timed_out") is False for row in commands)
    intents = read("MATERIALIZATION_3BB_MUTATION_INTENTS.json")
    assert [row["kind"] for row in intents] == ["create_new_repository", "write_exact_new_physical_source_and_standard_pack", "import_independent_standard_pack", "new_index_and_detached_head"]
    assert all(row["actual_terminal"] == "observed" for row in intents)
    materialized_inputs = read("MATERIALIZATION_3BB_INPUT_IDENTITIES.json")
    for basename, name in (("driver.py", "MATERIALIZER_3BB.original.py"), ("MATERIALIZATION_PACKET.json", "MATERIALIZATION_3BB_PACKET.json"), ("APPROVED_CONFIG.json", "MATERIALIZATION_3BB_CONFIG.json")):
        assert materialized_inputs[MATERIALIZATION_CONTROL + "/" + basename] == input_pin(name)

    assert maintenance["format"] == "hepta-original-scoped-maintenance-result-v1"
    assert maintenance["status"] == "MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED"
    assert maintenance["source_repo"] == CURRENT
    assert {"commit": maintenance["source_commit"], "tree": maintenance["source_tree"], "parents": maintenance["parents"]} == SUBJECT
    assert maintenance["source_initial_inventory"] == clean_start["inventory"]
    assert maintenance["actual_materialization_result"] == input_pin("MATERIALIZATION_3BB_RESULT.json")
    assert maintenance["actual_materialization_job"] == normals[0]["job_id"]
    assert maintenance["attempted_commands"] == ["fix", "fmt"] and maintenance["not_run_commands"] == []
    assert maintenance["qualification"] is False and maintenance["test_commands_dispatched"] == 0
    assert maintenance["source_ref_updates"] is False and maintenance["automatic_retry"] is False
    assert maintenance["git_metadata_unchanged"] is True and maintenance["source_preflight_complete"] is True
    assert len(maintenance["stages"]) == 2
    expected_commands = [("fix", ["just", "fix", "-p", "codex-hepta-intelligence-eval", "-p", "codex-hepta-agentd", "-p", "codex-hepta-learning-ledger"], 7200),
                         ("fmt", ["just", "fmt", "--base", FORMAT_BASE], 900)]
    for stage, (name, argv, seconds) in zip(maintenance["stages"], expected_commands):
        assert stage["name"] == name and stage["argv"] == argv and stage["timeout_seconds"] == seconds
        assert stage["status"] == "completed_review_required" and stage["working_directory"] == CURRENT
        assert stage["maximum_log_bytes"] == 67108864 and stage["test_command"] is False
        assert stage["command_returned"] is True and stage["execution_outcome"] == "completed"
        assert stage["execution"]["returncode"] == 0 and stage["execution"]["timed_out"] is False
        assert stage["execution"]["output_limit_exceeded"] is False and stage["raw_log_retained"] is True
        assert stage["retention"]["complete"] is True
    assert {item["check"]: item["status"] for item in maintenance["final_audits"]} == {"actual_complete_source_and_git": "verified", "original_inputs": "verified"}
    assert len(read("MAINTENANCE_41E_INPUT_IDENTITIES.json")) == 24
    assert maintenance["materialization_current_git_metadata_verified"] == input_pin("MATERIALIZATION_3BB_GIT_METADATA.json")
    assert maintenance["materialization_current_index_verified"] == materialized["current_index"]
    assert read("MAINTENANCE_41E_GIT_STATE.json") == materialized["current_git_state_after"]
    assert maintenance["actual_archive_restoration_result"] == input_pin("ARCHIVE_V3_RESULT.json")
    assert maintenance["actual_archive_restoration_job"] == normals[2]["job_id"]
    assert maintenance["actual_archive_restoration_readback"] == input_pin("ARCHIVE_V3_READBACK.json")
    assert maintenance["actual_runtime_restoration_result"] == input_pin("HISTORICAL_RUNTIME_RESULT.json")
    assert maintenance["actual_runtime_environment"] == input_pin("HISTORICAL_ENVIRONMENT_READY.json")
    assert maintenance_cfg["runtime_restoration"] == old_qualification["runtime_guard"]["runtime_restoration"]
    for key in old_qualification["runtime_guard"]:
        assert maintenance_cfg[key] == old_qualification["runtime_guard"][key], key

    materialized_metadata = read("MATERIALIZATION_3BB_GIT_METADATA.json")
    maintenance_metadata = read("MAINTENANCE_41E_GIT_METADATA.json")
    assert maintenance_metadata["root"] == CURRENT + "/.git"
    metadata_files = {row["path"]: row for row in maintenance_metadata["files"] if row["kind"] == "file"}
    assert len(metadata_files) == len(materialized_metadata) == 6
    mappings = {"device": "st_dev", "inode": "st_ino", "nlink": "st_nlink", "mtime_ns": "st_mtime_ns", "ctime_ns": "st_ctime_ns"}
    for row in materialized_metadata:
        target = metadata_files[row["path"]]
        assert target["bytes"] == row["bytes"] and target["sha256"] == row["sha256"]
        assert target["mode"] == stat.S_IMODE(row["stat"]["st_mode"])
        assert all(target[key] == row["stat"][value] for key, value in mappings.items())
        assert row["stat"]["st_size"] == row["bytes"]
    assert archive_readback == maintenance_cfg["archive_restoration"]["archive_actual"]
    projection = {"path": archive_readback["path"], "resolved": archive_readback["path"],
                  "bytes": archive_readback["identity"]["bytes"], "sha256": archive_readback["identity"]["sha256"],
                  "mode": stat.S_IMODE(archive_readback["stat"]["st_mode"])}
    assert projection == maintenance_cfg["v8_files"]["RUSTY_V8_ARCHIVE"]
    assert archive["format"] == "hepta-v8-single-archive-restoration-result-v1"
    assert archive["status"] == "ARCHIVE_RESTORED_FOR_REVIEW_ONLY"
    assert archive["source_repo"] == DONOR
    assert archive_readback["stat"]["st_ino"] == 26738823
    old_archive = old_environment["tool_and_material_files"]["v8-sandbox-archive"]
    assert {key: old_archive[key] for key in projection} == projection

    assert final_format_cfg["actual_prior_maintenance"]["result"] == input_pin("MAINTENANCE_41E_RESULT.json")
    assert final_format_cfg["actual_prior_maintenance"]["supervisor"] == input_pin("MAINTENANCE_41E_NORMAL.json")
    assert final_format_cfg["baseline_inventory"] == maintenance["actual_final_source"]["inventory"]
    assert final_format_cfg["baseline_physical_tree"] == maintenance["actual_final_source"]["postimages"]["all_actual_physical_tree"]
    assert final_format_cfg["actual_prior_maintenance"]["complete_git_metadata"] == input_pin("MAINTENANCE_41E_GIT_METADATA.json")
    assert canonical_cfg["before_commit"] == SUBJECT["commit"] and canonical_cfg["before_tree"] == SUBJECT["tree"]
    assert canonical_cfg["before_parents"] == SUBJECT["parents"]
    for key in ("after_commit", "after_tree", "after_parents", "after_inventory", "before_inventory", "expected_before_git_state", "canonical_packet", "canonical_object_count"):
        assert canonical_cfg[key] is None

    recovered = Path("/tmp/hepta-36fa-a489-maintenance-actual-inventory-recovery-v1/final.inventory.exact_recovered.json")
    recovered_raw = recovered.read_bytes()
    assert identity(recovered_raw) == maintenance["actual_final_source"]["inventory"]
    source_rows = {row["path"]: row for row in json.loads(recovered_raw)["files"]}
    controls = []
    for item in plan["unchanged_original_controls"]["reviewed_source_pins"]["files"]:
        row = source_rows[item["path"]]
        actual = {"bytes": row["bytes"], "sha256": row["sha256"], "git_blob": row["working_blob"]}
        expected = input_pin("WORKFLOW_D256.yml") if item["path"] == WORKFLOW else pin3(item)
        assert actual == expected
        controls.append({"path": item["path"], "original_plan_pin": pin3(item), "actual_41e_pin": actual,
                         "status": "one_explicit_reviewed_workflow_successor_required" if item["path"] == WORKFLOW else "original_pin_unchanged"})
    assert len(controls) == 12 and sum(row["status"] != "original_pin_unchanged" for row in controls) == 1

    qualification = copy.deepcopy(old_qualification)
    for key in ("source", "tree", "parents", "expected_inventory_sha256", "full_physical_inventory", "admission_path", "admission_pin", "source_gates_config_path", "source_gates_config_pin", "native_driver_path", "plan_path", "records", "root_parent", "run_identity", "source_gates_handoff_records"):
        qualification[key] = None
    qualification.update({"state": "HOLD_FOR_ACTUAL_FINAL_SOURCE_BINDINGS", "root_execution_approved": False,
                          "repo": CURRENT, "historical_source_repo": HISTORICAL, "provenance_donor_repo": DONOR,
                          "expected_file_count": 15243, "actual_final_format_postimages_reviewed": False,
                          "reviewed_formatter_changed_paths": None,
                          "isolated_materialization": copy.deepcopy(maintenance_cfg["materialization"]),
                          "materialized_subject": SUBJECT,
                          "archive_restoration": copy.deepcopy(maintenance_cfg["archive_restoration"]),
                          "current_final_git_state": None, "canonical_complete_git_metadata": None,
                          "canonical_original_index": None, "full_native_inventory": None,
                          "actual_final_fences_reviewed": False,
                          "source_control_pin_overrides": [{"path": WORKFLOW, "original_plan_pin": controls[8]["original_plan_pin"],
                                                            "reviewed_current_pin": input_pin("WORKFLOW_D256.yml"),
                                                            "final_actual_confirmed": False}],
                          "normal_native_and_source_results": None,
                          "qualification_execution_dispatched": False})
    qualification["actual_maintenance"] = {"job_id": normals[1]["job_id"],
        "result_path": MAINTENANCE_CONTROL + "/run/RESULT.json", "result": input_pin("MAINTENANCE_41E_RESULT.json"),
        "supervisor_path": FINAL_FORMAT_CONTROL + "/MAINTENANCE_NORMAL.original.json", "supervisor": input_pin("MAINTENANCE_41E_NORMAL.json"),
        "final_inventory": maintenance["actual_final_source"]["inventory"],
        "final_physical_tree": maintenance["actual_final_source"]["postimages"]["all_actual_physical_tree"],
        "git_state": input_pin("MAINTENANCE_41E_GIT_STATE.json"), "complete_git_metadata": input_pin("MAINTENANCE_41E_GIT_METADATA.json"),
        "artifacts": input_pin("MAINTENANCE_41E_ARTIFACTS.json"), "original_input_map": input_pin("MAINTENANCE_41E_INPUT_IDENTITIES.json")}
    qualification["final_format"] = {"job_id": None, "result": None, "supervisor": None,
        "result_path": FINAL_FORMAT_CONTROL + "/run/RESULT.json", "supervisor_path": None,
        "git_state_path": FINAL_FORMAT_CONTROL + "/run/final.git-state.json", "git_state": None,
        "complete_git_metadata": None, "final_inventory": None, "actual_physical_tree": None}
    qualification["canonical_alignment"] = {"job_id": None, "result": None, "supervisor": None,
        "result_path": CANONICAL_CONTROL + "/run/RESULT.json", "supervisor_path": None,
        "artifacts": None, "final_git_metadata_gzip": None, "final_git_metadata_raw": None,
        "final_index_raw": None, "final_index_audit": None}
    assert qualification["runtime_guard"] == old_qualification["runtime_guard"]
    source_cfg = copy.deepcopy(old_source_cfg)
    source_cfg.update({"state": "HOLD_FOR_ACTUAL_FINAL_SOURCE_BINDINGS", "object_repository": CURRENT,
                       "source_sha": None, "source_tree": None, "source_checkout": None, "records": None, "run_identity": None})

    old_spans = spans("ADMISSION_23D412.original.py")
    unchanged = ["check", "identity", "pin", "load", "Admission.read", "Admission.observed_proof", "Admission.current_lock", "Admission.before_native_stage", "Admission.close"]
    proposed = {
        "Admission.__init__": ["Keep the state/Root approval guard, original separate h/m V5 instances, path separation, original environment and output handling.",
            "Bind explicit historical86dd, donorcc57 and currenta489 roles; validate materialized d256/a489 only as the chain start.",
            "Final source/tree/parents and all current baselines must be non-null actual canonical bindings; do not use fixed cc57 or fixed d256 as final qualification identity.",
            "Record and retain full canonical metadata independently of the original V5 projection; no historical ENV rewriting."],
        "Admission.acquire_and_validate": ["Keep actual SH lock, immutable plan, exact original gate/control pins and complete initial inventory checks.",
            "Validate actual3bb, then actual41e, then future actual finalfmt, then future actual canonical alignment in producer order.",
            "Finalfmt must name currenta489 repo, pre-canonical d256/a489/parentcc57; its baseline_inventory and baseline_physical_tree must equal actual41e full4a77/c026, and its actual_maintenance_job/result must equal41e.",
            "Canonical must name currenta489 repo, bind this exact finalfmt job/result/supervisor/git-state, consume its final inventory/physical tree, and prove unchanged physical bytes/modes while updating only reviewed Git identity/index.",
            "Set initial_git from actual aligned.after.git_state, not3bb current_git_state_after. Bind complete canonical metadata and original normal index audit before any gate.",
            "Preserve the original plan bytes; substitute only the exact reviewed workflow pin at its original path. Keep all other11 pins and require final workflow/48 parents proof.",
            "Keep original h.environment_preflight and existing external target/cache/resource checks. Add separate archive-v3 proof without editing h.SEED, h.REPO or old ENV."],
        "Admission.validate_materialization": ["Translate only the actual new producer format/status and explicit donor/destination roles; keep actual normal0, three audits, four command/mutation/input/artifact records, fixed lock, input and cleanup checks.",
            "Bind3bb d256/a489/parentcc57/fullf1e2/native7647/15243, its own actual index and complete2234 metadata.",
            "Bind current four complete snapshots/16661objects and exact counts/129+83provided/16449donor from the actual packet/result; do not claim full ancestry or carry these counts into future canonical objects.",
            "Preserve actual donor15188 complete files, absent paths and complete Git file/ref scope. Remove obsolete seven-missing/15181 and historical86dd-donor assumptions.",
            "Return start-of-chain evidence; remove equality between materialization inventory and future canonical inventory/Git state."],
        "Admission.finish": ["Keep every original input check, SH lock, raw9field Git equality, original full source rows and explicit ignored-output extras.",
            "Also compare full post-gate canonical metadata including uid/gid to the full initial baseline, and compare the original V5 envelope through the explicit schema bridge.",
            "Do not label full physical inventory unchanged when original native tests legitimately add ignored JUnit/output files; original b92 snapshot equality remains independently required."]}
    assert set(unchanged) | set(proposed) == set(old_spans)
    changes = [{"function": name, "original": old_spans[name], "disposition": "preserve_exact_function_bytes" if name in unchanged else "necessary_schema_identity_successor", "required_changes": proposed.get(name, [])} for name in old_spans]
    new_methods = [
        {"name": "validate_completed_maintenance", "contract": "Strict41e RESULT/normal and original controls; exact3bb provenance, actual2 stages/fix7200+fmt900, normal0/full output,24 inputs,2verified audits,fullfinalinventory/postimages/rawGit/fullmetadata; no rerun of consumed fix."},
        {"name": "validate_archive_restoration", "contract": "Strict v3 RESULT/normal/readback/ARTIFACTS plus complete original stat and source scope. Preserve old86dd runtime proof/ENV unchanged and compare only the original five-field file-content projection for live environment identity."},
        {"name": "validate_canonical_metadata_baseline", "contract": "Read and pin complete canonical ARTIFACTS/GIT_METADATA.final/INDEX.final/audit and actual after.git_state. Fresh full metadata must match all original fields includinguid/gid; separately reconstruct the V5 DFS/serializer projection without claiming the projection retains ownership."},
    ]
    migration = {"format": "hepta-qualification-admission-static-migration-hold-v1", "status": "HOLD_NON_EXECUTABLE_MIGRATION_SPECIFICATION", "predecessor": input_pin("ADMISSION_23D412.original.py"),
                 "source_module_generated": False, "typed_request_generated": False, "gate_execution_authorized": False,
                 "function_changes": changes, "additional_proof_contracts": new_methods,
                 "top_level_identity_changes": {"HISTORICAL_REPO": {"unchanged": HISTORICAL}, "DONOR_REPO": {"new_explicit_role": DONOR},
                     "CURRENT_REPO": {"before": DONOR, "after": CURRENT}, "materialized_subject": SUBJECT,
                     "final_subject": None, "expected_file_count": {"before": 15188, "after_contract": 15243, "future_actual_confirmed": False},
                     "materialization_objects": {"before":16449, "actual3bb":16661, "future_canonical":None},
                     "MATERIALIZATION_CONTROL": {"before": EVIDENCE + "/cc57-isolated-materialization-v1", "after": MATERIALIZATION_CONTROL},
                     "MATERIALIZER_PIN": input_pin("MATERIALIZER_3BB.original.py"), "MATERIALIZATION_PACKET_PIN": input_pin("MATERIALIZATION_3BB_PACKET.json"),
                     "MATERIALIZER_CONFIG_PIN": input_pin("MATERIALIZATION_3BB_CONFIG.json"),
                     "MATERIALIZED_NATIVE_INVENTORY_PIN": clean_start["native_inventory"], "FINAL_NATIVE_INVENTORY_PIN": None},
                 "forbidden_shortcuts": ["Do not admit old cc57/old physical tree from hard-coded23d anchors.", "Do not treat future expected8ebb as actual finalfmt/canonical.",
                     "Do not compare canonical index/rawGit to3bb index/rawGit after an intentional canonical update.", "Do not drop canonicaluid/gid or assume DFS equals global path sort.",
                     "Do not mutate original plan/driver/wrapper/commands/budgets/filters/JUnit to pass changed identities.", "Do not skip workflow pin or copy old33/39 root-parent counts into final48.",
                     "Do not promote maintenance normal0 to tests/qualification or a real task-chain result."]}
    metadata = {"format":"hepta-qualification-complete-git-metadata-bridge-hold-v1", "status":"STATIC_SCHEMA_ONLY_FUTURE_CANONICAL_NULL",
        "actual_start": {"producer": "3bb", "pin": input_pin("MATERIALIZATION_3BB_GIT_METADATA.json"), "shape": "6 regular files; full raw identity and st_* includinguid/gid; no directory rows"},
        "actual_maintenance": {"producer":"41e", "pin":input_pin("MAINTENANCE_41E_GIT_METADATA.json"), "shape":"V5 format/root/files;6file+6directory rows; no uid/gid fields",
                               "all_six_file_common_fields_match_actual3bb":True, "ownership_inferred_from_projection":False},
        "future_canonical":{"actual":None,"shape":"{root,files}, globally os.fsencode(path)-sorted realfile/dir rows includinguid/gid; exact templatee8d606",
                             "template":input_pin("CANONICAL_TEMPLATE_E8D606.HOLD.py")},
        "field_map": {"path":"path","kind":"kind","mode":"mode","device":"device","inode":"inode","nlink":"nlink","mtime_ns":"mtime_ns","ctime_ns":"ctime_ns","bytes":"bytes (files)","sha256":"sha256 (files)","uid":"Retain and compare in complete canonical observation; absent in V5 projection","gid":"Retain and compare in complete canonical observation; absent in V5 projection"},
        "v5_projection":{"format":"hepta-source-git-metadata-inventory-v1","ordering":"Original recursive per-directory os.fsencode(name)-sorted DFS, not arbitrary global path sorting","serializer":"json.dumps(ensure_ascii=False,sort_keys=True,separators=(',',':')) + LF, UTF-8","pure_reference_function":"prepare_static_migration.py::canonical_to_v5_projection","called_with_future_actual_data":False},
        "fresh_observation_requirements":["Same real.git root; no symlink or unsupported kind; complete membership.","Stable exact integer stat fields before/open/after each file includinguid/gid, and complete byte hash/length; no JavaScript-number roundtrip of nanosecond times.","Complete canonical original and fresh observations equal before and after original gates.","Full canonical.uid/gid retained separately from the exact V5 byte projection.","Original nine-field Git-state equality remains required but is not full metadata proof."]}
    checks = {"format":"hepta-qualification-producer-chain-pure-checks-v1","scope":"Complete immutable producer bytes; no native observation or gate execution in this preparation.",
        "normal_proofs":normals,"materialized_subject":SUBJECT,"materialized_full_inventory":clean_start["inventory"],"materialized_native_inventory":clean_start["native_inventory"],
        "materialized_counts":{"physical_leaves":15243,"objects":16661,"donor_objects":16449},"materialization_records_full_pin_equal":True,
        "actual_maintenance_source_initial_equals_materialization":True,"actual_maintenance_git_state_equals_materialization_start":True,
        "actual_maintenance_final_inventory":maintenance["actual_final_source"]["inventory"],"actual_maintenance_final_physical_tree":maintenance["actual_final_source"]["postimages"]["all_actual_physical_tree"],
        "actual_maintenance_2_stages_2_audits_24_inputs":True,"actual_maintenance_test_commands":0,
        "current_finalfmt_template_baseline_equals_actual41e":True,"finalfmt_template_is_not_actual_result":True,
        "historical_runtime_guard_exact_equal":True,"historical_environment_original_pin":input_pin("HISTORICAL_ENVIRONMENT_READY.json"),
        "archive_v3_full_readback":archive_readback,"archive_original_five_field_projection_equal":True,
        "future_finalfmt_result":None,"future_canonical_result":None,"future_qualification":None,
        "real_authorized_task_chain_result":"Unknown; this preparation supplies no A/B/C result"}
    contracts = {"format":"hepta-qualification-original-controls-preservation-v1", "all_original_controls_left_unmodified":True,
        "original_source_and_native_modules":{name:input_pin(name) for name in ("SOURCE_GATES_5118.py","SOURCE_WRAPPER_8607.py","NATIVE_WRAPPER_DE3.py","NATIVE_DRIVER_B92.py","PLAN_3AEF.json")},
        "current_source_control_pin_bindings":controls,"only_explicit_source_pin_successor":WORKFLOW,
        "workflow_root_parent_count":bindings["workflow_root_parent_count"],"workflow_root_parents":bindings["workflow_root_parents"],
        "fourteen_phase_ids":bindings["fourteen_phase_ids"],"outer_budgets_seconds":bindings["outer_budgets_seconds"],
        "phase_budgets_seconds":bindings["phase_budgets_seconds"],"source_gate_tuples":bindings["source_gate_tuples"],
        "ordinary_packages_argv":bindings["ordinary_packages_argv"],"root_exact_expression":bindings["root_exact_expression"],
        "actual_static_native_command_payloads":bindings["actual_static_native_command_payloads"],
        "runtime_contract":bindings["runtime"],"do_not_change":["Full eval library and four original regressions","Original seven focused filters and five ordinary packages","Actual final workflow AST exact Root-parent expression, ignored-only/threads1/retries0 and exact complete JUnit name set","Original8MiB stack/timeouts/limits/output preservation","No additional phase or automatic retry"],
        "source_control_source_inventory_provenance":{"raw":identity(recovered_raw),"mode":"Exact offline recovery against original producer raw/gzip/parts; not a second native full read","recovery_placement":"2a5940b3023de46232465e01bb2acc75139193dd"}}
    assert contracts["workflow_root_parent_count"] == 48 and len(contracts["workflow_root_parents"]) == 48
    differences = []
    for key in sorted(set(old_qualification) | set(qualification)):
        if old_qualification.get(key) != qualification.get(key) or (key in old_qualification) != (key in qualification):
            differences.append({"field":key,"before_present":key in old_qualification,"before":old_qualification.get(key),"after":qualification.get(key)})
    missing = {"format":"hepta-final-qualification-missing-actual-bindings-v1","status":"HOLD",
        "actual_source_identity":{"commit":None,"tree":None,"parents":None,"leaf_count_observed":None},
        "actual_finalfmt":{"job_id":None,"result":None,"normal":None,"full_output":None,"raw_log":None,"all_postimages_reviewed":None,"complete_final_inventory":None,"git_state":None,"complete_metadata":None,"audits":None},
        "actual_canonical":{"job_id":None,"result":None,"normal":None,"full_output":None,"clean_inventory":None,"native_five_field_projection":None,"after_git_state":None,"full_metadata":None,"normal_index":None,"index_audit":None,"physical_before_after_equality":None,"audits":None},
        "execution_inputs":{"final_qualification_cfg":None,"final_source_cfg":None,"admission_source_successor":None,"bootstrap_source":None,"typed_source_request":None,"source_success_result_normal_originalrun":None,"typed_native_request":None,"separate_Root_exact_approval":None},
        "no_conversion_rule":"Prepared pins, expected8ebb, historicalnormal0, or41e maintenance success cannot fill any actual field above.",
        "completion_order":["actualfinalfmt bytes + complete audits + individual postimage/fence review","Root actualcanonical commit + exactalignment result/normal/fullsource/fullGit/index proof","freeze and peer actual admission code/config/bootstrap successor preserving original gates","Root exact approval and native-only sourcegates execution","actualsourcewrapperpassed+originalrunpassed+driver0+normal0/fulloutput+unchangedsource","Root exact approval and native-only original14phase qualification"],
        "counts_retained_as_contract_only":{"boundaries":633,"protected_rows":442,"provider_paths":45,"provider_scopes":288,"ordinary_scopes":34,"ordinary_literals":17,"QA_files":64,"QA_methods":607,"Root_parents":48}}
    outputs=[]
    for name,value in (("INPUT_INDEX.json",{"entries":checked,"count":44,"scope":"Original immutable Git fullGET corpus; future result bytes absent."}),
                       ("QUALIFICATION_BINDINGS.HOLD.json",qualification),("SOURCE_GATES_CONFIG.HOLD.json",source_cfg),
                       ("CONFIG_FIELD_DIFF.json",{"reference":"Decoded exact historical source request3ebc277; not misidentified as the23d412 isolated cfg","qualification_fields":differences,
                                                "source_fields":[{"field":key,"before":old_source_cfg.get(key),"after":source_cfg.get(key)} for key in sorted(source_cfg) if old_source_cfg.get(key)!=source_cfg.get(key)]}),
                       ("ADMISSION_MIGRATION.HOLD.json",migration),("COMPLETE_METADATA_BRIDGE.HOLD.json",metadata),
                       ("PRODUCER_CHAIN_STATIC_CHECKS.json",checks),("IMMUTABLE_CONTROL_BINDINGS.json",contracts),("MISSING_FINAL_BINDINGS.json",missing)):
        outputs.append(write(name,value))
    outputs.append(write("PURE_REPRODUCTION.json",{"format":"hepta-qualification-static-reproduction-v1","script":identity(Path(__file__).read_bytes()),
        "outputs":outputs,"actual_full_get_input_count":44,"project_modules_imported":0,"project_gates_run":0,"H_calls":0,
        "source_or_reference_mutations":0,"pure_static_checks_completed":True,"final_admission_passed":False,
        "future_finalfmt_or_canonical_observed":False,"preservation":"All input files read-only; generated files written only to this isolated directory."}))
    print(json.dumps({"status":"PURE_STATIC_HOLD_PREPARATION_COMPLETE","inputs":44,"outputs":outputs,"no_execution_qualification":True},indent=2))


if __name__ == "__main__":
    main()
