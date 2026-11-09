"""Prepare bounded records-only checks and the exact 010 publication file plan."""

import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import textwrap

R = Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
W = Path("/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e")
REL = "qualification/cell_common_candidate/20261108/execution_history"
O = R / "increment010-publisher-preparation-v1"
SCRIPT = R / "publish-evidence-increment-010-v1.py"
SCRIPT_SHA = "ee64fc6da971f04b5a3819d343d0f68be10db74827a37e4b07efb4c66c46bbe5"
BASE = R / "publish-evidence-increment-009-v1.py"
BASE_SHA = "a3b2813942f8a35b3d1566ec0b918e4ea7bd675698aef4eb58cb63ad0765b58e"
INPUT = R / "increment010-two-ready-packet-preparation-v2/DRAFT_INPUTS.json"
INPUT_SHA = "0fc8f813c9d06f759aec536265aeb571246eaeda737f736075998d2e186f4dec"
APPEND = R / "evidence-addendum-increment-010a/RESULT.json"
APPEND_SHA = "893fb6dc4230f8358340f02c903e2867a8cbbb2e77ab3cf818ddeadc6450432d"
PARENT = "6e162bab21438b857179a22c6207552feda9331b"
PRIOR = R / "increment010-two-ready-packet-preparation-v2/PARENT_MANIFEST.json"
MAX = 512000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stable(path):
    a = path.lstat()
    assert stat.S_ISREG(a.st_mode) and a.st_nlink == 1 and not path.is_symlink(), str(path)
    data = path.read_bytes()
    b = path.lstat()
    assert (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (
        b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns, b.st_ctime_ns
    ), str(path)
    return data


def pin(path):
    data = stable(path)
    return {"path": str(path), "bytes": len(data), "sha256": sha(data)}


def main():
    if not __debug__:
        raise RuntimeError("Evidence assertions must remain enabled")
    O.mkdir(mode=0o700, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    script, base, raw_input, raw_append, prior_bytes = (
        stable(path) for path in (SCRIPT, BASE, INPUT, APPEND, PRIOR)
    )
    assert sha(script) == SCRIPT_SHA and len(script) == 58780
    assert sha(base) == BASE_SHA
    assert sha(raw_input) == INPUT_SHA and len(raw_input) == 386917
    assert sha(raw_append) == APPEND_SHA
    assert sha(prior_bytes) == "0cf1005179c11c185da89843f4bd23d41ce61428de620783bf9f87a5642fc2de"
    tree, old_tree = ast.parse(script), ast.parse(base)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    old_functions = {node.name: node for node in old_tree.body if isinstance(node, ast.FunctionDef)}
    ns = {"Path": Path, "os": os, "hashlib": hashlib, "datetime": datetime, "timezone": timezone}
    pure_names = ("sha", "now", "same_typed", "is_evidence_python_script")
    pure = ast.Module(body=[functions[name] for name in pure_names], type_ignores=[])
    exec(compile(ast.fix_missing_locations(pure), str(SCRIPT) + ":pure-functions-only", "exec"), ns)
    literals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    observations = literals["OBSERVATION_PATHS"]
    supplemental = literals["SUPPLEMENTARY_PATHS"]
    assert len(observations) == len(set(observations)) == 71
    assert len(supplemental) == len(set(supplemental)) == 26
    assert set(supplemental) <= set(observations)
    inputs, appended, prior = map(json.loads, (raw_input, raw_append, prior_bytes))
    source = script.decode()
    scope_start = source.index("    retained_validation = ")
    scope_end = source.index("    assert index['latest_reviewed_common_source_sha']", scope_start)
    scope_program = compile(textwrap.dedent(source[scope_start:scope_end]), "010-scope-guards-only", "exec")
    cases = []

    def record(label, detail=None):
        cases.append({"case": label, "passed": True, "detail": detail})

    def scope_check(value):
        exec(scope_program, {"json": json, "same_typed": ns["same_typed"],
                             "index": {"current_common_validation": value}, "prior": prior})

    def reject_scope(label, mutate):
        value = copy.deepcopy(inputs["current_common_validation"])
        mutate(value)
        try:
            scope_check(value)
        except (AssertionError, KeyError):
            record(label)
        else:
            raise AssertionError("Rejected scope was accepted: " + label)

    scope_check(copy.deepcopy(inputs["current_common_validation"]))
    record("exact_two_actual_source_observations_accepted")
    def put(key, field, value):
        return lambda current: current["separate_source_observations"][key].__setitem__(field, value)
    timeout_key="desktop_6ec_workspace_timeout_and_artifact_availability_history"
    negative_key="d274_counterfactual_negative_native_retention_history"
    reject_scope("retained_common_source_change_rejected", lambda value: value.__setitem__("source_sha", "0" * 40))
    reject_scope("workspace_timeout_cannot_be_mislabeled_pass", put(timeout_key,"status","PASS"))
    reject_scope("workspace_missing_XML_cannot_claim_case_closure", put(timeout_key,"case_closure_verified",True))
    reject_scope("workspace_unknown_counts_must_remain_null", put(timeout_key,"verified_counts",0))
    reject_scope("partial_keys_not_promoted_to_other_count", lambda value: value["separate_source_observations"][timeout_key]["count_bindings"]["partial_readback"].__setitem__("raw_pass_shaped_unique_keys",6822))
    reject_scope("failed_retainer_cannot_claim_copy", lambda value: value["separate_source_observations"][timeout_key]["count_bindings"]["forensic_retainer"].__setitem__("copied_paths",1))
    reject_scope("d274_failed_oracle_cannot_be_mislabeled_pass", put(negative_key,"status","PASS"))
    reject_scope("negative_source_identity_not_inherited_from_positive", put(negative_key,"source_sha","6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"))
    reject_scope("negative_expected_failure_not_a_green_test", put(negative_key,"counterfactual_assertion_observed_does_not_turn_FAIL_into_PASS",False))
    reject_scope("native_integer_count_not_boolean", lambda value: value["separate_source_observations"][negative_key]["count_bindings"]["original_native"].__setitem__("passed",False))
    assert not ns["same_typed"]({"value": 1}, {"value": True})
    assert not ns["same_typed"]({"value": 1794219243183664456}, {"value": 1794219243183664400})
    assert not ns["same_typed"]({"value": 1794219243183664456}, {"value": float(1794219243183664456)})
    record("typed_integer_and_nanosecond_rounding_rejected")
    is_script = ns["is_evidence_python_script"]
    assert is_script([b"python3", b"/records/publish-evidence-increment-010-v1.py"])
    assert is_script([b"python3", b"-u", b"--", b"/records/recover-evidence-increment010-publication-v1.py"])
    assert not is_script([b"python3", b"-c", b"print('/records/publish-evidence-increment-010-v1.py')"])
    assert not is_script([b"python3", b"-m", b"publish-evidence-increment-010-v1"])
    assert not is_script([b"python3", b"/records/unrelated.py", b"/records/publish-evidence-increment-010-v1.py"])
    record("python_targeting_uses_script_argument_not_wrapper_text")

    new_main = {node.name: node for node in functions["main"].body if isinstance(node, ast.FunctionDef)}
    old_main = {node.name: node for node in old_functions["main"].body if isinstance(node, ast.FunctionDef)}
    shared = (
        "write", "run", "git", "api", "common_clean", "safe_regular", "blob",
        "inventory", "tree_map", "index_map", "git_projection", "exact_changes",
        "verify_blobs", "unchanged_old", "inspect_new_objects", "fresh_transport_admission",
    )
    for name in shared:
        assert ast.dump(new_main[name], include_attributes=False) == ast.dump(old_main[name], include_attributes=False), name
    record("sixteen_original_identity_transport_and_blob_guard_functions_ast_identical", list(shared))
    closure_ns = {"WORK": Path("/synthetic-not-opened"), "sha": sha}
    for name in ("exact_changes", "verify_blobs", "unchanged_old"):
        module = ast.Module(body=[new_main[name]], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "original-closure-pure-stubs", "exec"), closure_ns)
    case_path = REL + "/observations/new.json"
    closure_ns["run"] = lambda *args, **kwargs: b"A\0" + case_path.encode() + b"\0"
    closure_ns["exact_changes"]("synthetic", ["--cached", "HEAD"], {case_path: "A"})
    try:
        closure_ns["exact_changes"]("synthetic", ["--cached", "HEAD"], {})
    except AssertionError:
        record("unlisted_new_git_index_path_rejected")
    else:
        raise AssertionError("Unlisted path accepted")
    payload = b"original bytes\n"
    oid = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    expected = {case_path: {"oid": oid, "bytes": len(payload), "sha256": sha(payload)}}
    closure_ns["safe_regular"] = lambda path: payload
    closure_ns["run"] = lambda *args, **kwargs: (oid + " blob " + str(len(payload)) + "\n").encode() + payload + b"\n"
    closure_ns["verify_blobs"]("synthetic", "", [case_path], expected)
    broken = copy.deepcopy(expected)
    broken[case_path]["sha256"] = "0" * 64
    try:
        closure_ns["verify_blobs"]("synthetic", "", [case_path], broken)
    except AssertionError:
        record("same_size_wrong_blob_bytes_rejected")
    else:
        raise AssertionError("Wrong blob accepted")
    try:
        closure_ns["unchanged_old"]({case_path: {"mode": "100755", "oid": oid}}, {case_path: {"mode": "100644", "oid": oid}}, set())
    except AssertionError:
        record("historical_blob_mode_change_rejected")
    else:
        raise AssertionError("Mode change accepted")
    force_adds = [node for node in ast.walk(tree) if isinstance(node, ast.List)
                  and any(isinstance(item, ast.Constant) and item.value == "-f" for item in node.elts)]
    assert len(force_adds) == 1
    expected_force_list=ast.parse("['git','add','-f','--',*sorted(force_add_original_pins)]",mode="eval").body
    assert ast.dump(force_adds[0],include_attributes=False)==ast.dump(expected_force_list,include_attributes=False)
    forced=literals["EXACT_FORCE_ADD_ORIGINAL_LOG_PATHS"]
    assert len(forced)==len(set(forced))==13
    original_ignore=json.loads(stable(R/"increment010-staging-paths-readonly-v1/RESULT.json"))
    assert original_ignore["ignored_paths"]==list(forced)
    force_start=source.index("    ignore_original = ")
    force_end=source.index("    # The three readable reviewed patches",force_start)
    force_program=compile(textwrap.dedent(source[force_start:force_end]),"exact-ignored-original-log-guards-only","exec")
    def force_check(ignore_value):
        context={"json":json,"RECORDS":R,"INPUTS_SHA":INPUT_SHA,"EXACT_FORCE_ADD_ORIGINAL_LOG_PATHS":forced,
                 "VERIFY_REL":REL+"/observations/evidence-addendum-increment-010a/VERIFY.log","sha":sha,
                 "source_originals":{str(R/"increment010-staging-paths-readonly-v1/RESULT.json"):json.dumps(ignore_value).encode()},
                 "observation_bytes":{path:b"exact original log bytes\n" for path in forced}}
        exec(force_program,context)
        return context["force_add_original_pins"]
    assert len(force_check(copy.deepcopy(original_ignore)))==13
    record("thirteen_exact_original_logs_are_the_only_force_add_paths")
    for label,mutator in (
        ("omitted_ignored_original_log_rejected",lambda value:value["ignored_paths"].pop()),
        ("arbitrary_extra_ignored_path_rejected",lambda value:value["ignored_paths"].append(REL+"/observations/arbitrary.log")),
        ("ignore_observation_wrong_source_input_rejected",lambda value:value.__setitem__("input_sha256","0"*64)),
    ):
        value=copy.deepcopy(original_ignore);mutator(value)
        try:force_check(value)
        except (AssertionError,KeyError):record(label)
        else:raise AssertionError(label+" accepted")
    assert "'push', '--progress', 'publish', 'HEAD:refs/heads/' + BRANCH" in source
    assert "'--force'" not in source and "'--amend'" not in source
    record("single_normal_push_and_only_exact_original_log_force_add")
    assert "assert len(append_paths) == 39" in source
    assert "assert len(rows) == len(OBSERVATION_PATHS) == 71" in source
    assert "expected_supplementary_paths = {'observations/' + path for path in SUPPLEMENTARY_PATHS}" in source
    assert "whitespace_exemption_paths_are_unchanged_historical_blobs" in source
    record("exact39_appender_paths_71_observations_26_supplemental_and_no_new_whitespace_exemption")

    commands = []
    def git(label, *args):
        cp = subprocess.run(["git", *args], cwd=W, capture_output=True)
        (O / (label + ".stdout")).write_bytes(cp.stdout)
        (O / (label + ".stderr")).write_bytes(cp.stderr)
        commands.append({"label": label, "argv": ["git", *args], "returncode": cp.returncode,
                         "stdout": pin(O / (label + ".stdout")), "stderr": pin(O / (label + ".stderr"))})
        assert cp.returncode == 0, label
        return cp.stdout
    status_before = git("readonly-status-before", "status", "--porcelain=v1", "--untracked-files=all")
    assert git("readonly-head-before", "rev-parse", "HEAD").decode().strip() == PARENT
    tree_bytes = git("readonly-old-tree", "ls-tree", "-r", "-z", PARENT, "--", REL)
    old_files = {}
    for row in tree_bytes.split(b"\0"):
        if not row:
            continue
        info, path = row.split(b"\t", 1)
        mode, kind, object_id = info.decode().split()
        assert kind == "blob"
        old_files[path.decode()] = {"mode": mode, "oid": object_id}
    assert len(old_files) == 1427
    old_files_before = {}
    for path, entry in old_files.items():
        raw = stable(W / path)
        mode = "100755" if (W / path).stat().st_mode & 0o111 else "100644"
        if path != REL + "/manifest.json":
            oid_actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            assert entry == {"mode": mode, "oid": oid_actual}, path
        old_files_before[path] = {"bytes": len(raw), "sha256": sha(raw), "mode": mode}

    append_paths = {REL + "/increment-010a-inputs.json", REL + "/increment-010a-pattern-review.json"}
    for row in appended["added_packets"]:
        path = REL + "/" + row["manifest_path"]
        data = stable(W / path)
        assert sha(data) == row["manifest_sha256"]
        manifest = json.loads(data)
        append_paths.add(path)
        archive_parts, offset = [], 0
        for sequence, chunk in enumerate(manifest["publication_chunks"], 1):
            part_path = REL + "/" + chunk["path"]
            assert chunk["sequence"] == sequence and chunk["offset"] == offset
            part = stable(W / part_path)
            assert len(part) == chunk["bytes"] and sha(part) == chunk["sha256"]
            append_paths.add(part_path)
            archive_parts.append(part)
            offset += len(part)
        original_archive = b"".join(archive_parts)
        assert len(original_archive) == row["archive_bytes"] and sha(original_archive) == row["archive_sha256"]
    assert {row["path"] for row in appended["supplementary_observations"]} == {"observations/" + path for path in supplemental}
    for row in appended["supplementary_observations"]:
        path = REL + "/" + row["path"]
        data = stable(W / path)
        assert len(data) == row["bytes"] and sha(data) == row["sha256"]
        append_paths.add(path)
    assert len(append_paths) == 39 and not (append_paths & set(old_files))
    actual_paths = {p.relative_to(W).as_posix() for p in (W / REL).rglob("*") if p.is_file()}
    assert actual_paths == set(old_files) | append_paths
    untracked = git("readonly-untracked", "ls-files", "--others", "--exclude-standard", "-z")
    expected_ignored_append=set(forced)&append_paths
    assert len(expected_ignored_append)==8
    assert {path.decode() for path in untracked.split(b"\0") if path} == append_paths-expected_ignored_append
    ignored=git("readonly-ignored-untracked","ls-files","--others","--ignored","--exclude-standard","-z","--",REL)
    assert {path.decode() for path in ignored.split(b"\0") if path}==expected_ignored_append
    assert git("readonly-staged", "diff", "--cached", "--name-only") == b""
    for relative in observations:
        if relative == "increment010-publisher-preparation-v1/CHECKS.json":
            continue
        assert len(stable(R / relative)) <= MAX, relative
    record("actual_pending_tree_matches39_added_paths_and_1427_baseline")
    checks = {
        "status": "STATIC_AND_PURE_NEGATIVE_CONTROLS_PASSED",
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "publisher": pin(SCRIPT), "base": pin(BASE), "checker": pin(Path(__file__)),
        "cases": cases, "case_count": len(cases), "publisher_main_invoked": False,
        "git_commands_read_only": True, "new_native_tests": 0,
        "appender_not_reexecuted": True, "commit_or_push_invoked": False,
    }
    (O / "CHECKS.json").write_text(json.dumps(checks, indent=2) + "\n")
    observation_pins = []
    for relative in observations:
        row = pin(R / relative)
        assert row["bytes"] <= MAX
        observation_pins.append({"relative_path": relative, "bytes": row["bytes"], "sha256": row["sha256"]})
    future_obs = {REL + "/observations/" + path for path in observations}
    future_new = append_paths | future_obs | {
        REL + "/increment010-metadata.json", REL + "/increment010-publication-index-closure.json",
        REL + "/increment010-publication-pattern-review.json",
    }
    assert len(future_new) == 87 and not (future_new & set(old_files))
    plan = {
        "status": "EXACT_PUBLICATION_FILE_PLAN_NOT_EXECUTED",
        "parent_commit": PARENT, "parent_git_file_count": 1427,
        "appender_added_files": sorted(append_paths), "appender_added_file_count": 39,
        "publisher_observation_count": len(observation_pins), "observations": observation_pins,
        "future_added_paths": sorted(future_new), "future_added_path_count": len(future_new),
        "future_modified_existing_paths": [REL + "/README.md", REL + "/manifest.json"],
        "expected_committed_git_file_count_after_all_closures": 1514,
        "actual_committed_file_count_still_requires_git_index_and_commit_verification": True,
        "all_observation_files_within512000": True,
        "max_prepared_observation_bytes": max(row["bytes"] for row in observation_pins),
        "packet_count": 95, "member_entries_with_overlap": 11384,
        "all_93_old_packet_entries_preserved": True, "new_native_tests": 0,
        "new_whitespace_exemptions_added": False, "exact_force_add_original_log_paths": list(forced),
        "full_history_cost": None, "stages": {f"S{i}": "HOLD" for i in range(6)},
    }
    (O / "CLOSED_FILE_PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    (O / "OBSERVATION_INPUT_PINS.json").write_text(json.dumps(observation_pins, indent=2) + "\n")
    status_after = git("readonly-status-after", "status", "--porcelain=v1", "--untracked-files=all")
    assert status_before == status_after
    assert git("readonly-head-after", "rev-parse", "HEAD").decode().strip() == PARENT
    for path, entry in old_files_before.items():
        data = stable(W / path)
        assert {"bytes": len(data), "sha256": sha(data),
                "mode": "100755" if (W / path).stat().st_mode & 0o111 else "100644"} == entry
    assert stable(SCRIPT) == script and stable(BASE) == base and stable(INPUT) == raw_input and stable(APPEND) == raw_append
    (O / "READ_ONLY_COMMANDS.json").write_text(json.dumps(commands, indent=2) + "\n")
    result = {"status": "CHECKS_AND_EXACT_NEW_FILE_PLAN_PREPARED_NOT_PUBLISHED",
              "finished_at": datetime.now(timezone.utc).isoformat(), "script": pin(SCRIPT),
              "checks": pin(O / "CHECKS.json"), "file_plan": pin(O / "CLOSED_FILE_PLAN.json"),
              "observation_pins": pin(O / "OBSERVATION_INPUT_PINS.json"),
              "readonly_commands": pin(O / "READ_ONLY_COMMANDS.json"),
              "pending_evidence_tree_before_after_unchanged": True, "new_native_tests": 0,
              "commit_or_push_invoked": False, "publication_result": None}
    (O / "CHECK_PREPARATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"preparation": pin(O / "CHECK_PREPARATION.json"), **result}), flush=True)


if __name__ == "__main__":
    main()
