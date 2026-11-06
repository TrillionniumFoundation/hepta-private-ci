"""Create the inert r31 source53 workspace template from fixed local originals.

This preparation script only reads immutable bytes, builds text, and parses AST.
It does not import or run a gate, invoke Git, Cargo, metadata, or a formatter.
"""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
R29_PATH = WORK / "native-validation-results/r29-archive-closed/original/input/native-run-r29.py"
R30_PATH = WORK / "source53-native-gates-preparation/native-run-r30-template-v2.py"
R29_SHA = "26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2"
R30_SHA = "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def put(relative, raw):
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        output.write(raw)
    return {"path": relative, **pin(raw)}


def obj(relative, value):
    return put(relative, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def change(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError("unexpected source occurrence: " + repr(old))
    return text.replace(old, new)


def module(raw):
    text = raw.decode()
    parsed = ast.parse(text)
    lines = text.splitlines(keepends=True)
    functions = {node.name: "".join(lines[node.lineno - 1:node.end_lineno])
                 for node in parsed.body if isinstance(node, ast.FunctionDef)}
    constants = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return text, parsed, functions, constants


R30_READER = r'''
def r30_required_names():
    names = [R30_PREFIX + suffix for suffix in (
        "-environment.json", "-preconditions.json", "-source-pre-verification.json",
        "-source-final-verification.json", "-complete.json",
    )]
    for phase in R30_PHASES:
        stem = R30_PREFIX + "-" + phase
        names.extend(stem + suffix for suffix in (
            ".log", "-resources.txt", "-raw-process-result.json", "-receipt.json",
            "-source-pre-verification.json", "-source-post-verification.json",
        ))
    names.extend((R30_PREFIX + "-tests-result-review.json", R30_PREFIX + "-tests-test-results.json"))
    return names


def check_bindings():
    check_source_bindings()  # False/None/optimization barriers precede any writes or subprocesses.
    require(type(SOURCE_MANIFEST_BYTES) is int and SOURCE_MANIFEST_BYTES > 0,
            "actual source53 full-manifest byte count missing")
    require(isinstance(R30_JOB_ID, str) and bool(R30_JOB_ID), "actual naturally closed r30 job missing")
    require(R30_JOB_ID not in (APPLY_JOB_ID, LOCK_JOB_ID, R24_JOB_ID, R26_JOB_ID, R29_JOB_ID, R28_JOB_ID),
            "r30 job identity reused")
    require(R30_TERMINAL_NAME == R30_PREFIX + "-terminal-process-status.json", "wrong r30 terminal name")
    require(hex_digest(R30_TERMINAL_SHA256, 64), "r30 natural terminal hash missing")
    require(type(R30_TERMINAL_BYTES) is int and R30_TERMINAL_BYTES > 0, "r30 terminal byte count missing")
    require(isinstance(R30_INPUT_PINS, dict) and set(R30_INPUT_PINS) == set(r30_required_names())
            and len(R30_INPUT_PINS) == 19, "all nineteen successful r30 originals required")
    for name, expected in R30_INPUT_PINS.items():
        safe_relative(name)
        require(not name.startswith(PREFIX + "-"), "input collides with create-only workspace output")
        require(set(expected) == {"bytes", "sha256"}, "unexpected r30 original pin fields")
        require(type(expected["bytes"]) is int and expected["bytes"] >= 0
                and hex_digest(expected["sha256"], 64), "r30 original byte/hash binding missing")


def r30_prerequisite(baseline, source_pin, baseline_pin, lock_pins, source50_pin,
                     source51_pin, source52_pin, apply_proof, r24_failed_pins,
                     r26_failed_pins, r29_failed_pins):
    originals = {name: pinned_read(name, R30_INPUT_PINS[name]) for name in r30_required_names()}
    records = {name: json.loads(raw) for name, raw in originals.items() if name.endswith(".json")}
    commands = {
        "strict": ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"],
    }
    receipts, previous_end = [], None
    for phase in R30_PHASES:
        stem = R30_PREFIX + "-" + phase
        raw_name, receipt_name = stem + "-raw-process-result.json", stem + "-receipt.json"
        pre_name, post_name = stem + "-source-pre-verification.json", stem + "-source-post-verification.json"
        raw, receipt = records[raw_name], records[receipt_name]
        require(raw["schema"] == "hepta.native-raw-process-result.v1"
                and receipt["schema"] == "hepta.native-gate-receipt.v2", "r30 phase schema mismatch")
        for value in (raw, receipt):
            require(value["phase"] == phase and value["command"] == commands[phase]
                    and value["cwd"] == str(S / "codex-rs"), "wrong complete app-server command")
            require(value["source_tree"] == EXPECTED_TREE and value["source_commit"] == EXPECTED_COMMIT
                    and value["exit_code"] == 0, "same-source r30 original phase did not pass")
        for key in ("source_tree", "source_commit", "phase", "command", "cwd", "start_unix", "end_unix", "exit_code"):
            require(raw[key] == receipt[key], "r30 raw/receipt mismatch: " + phase + "/" + key)
        require(receipt["end_unix"] >= receipt["start_unix"]
                and abs(receipt["elapsed_seconds"] - (receipt["end_unix"] - receipt["start_unix"])) < 1e-6,
                "r30 phase timing mismatch")
        require(previous_end is None or receipt["start_unix"] >= previous_end, "r30 phase ordering mismatch")
        previous_end = receipt["end_unix"]
        require(receipt["effective_exit_code"] == 0 and receipt["phase_pass"] is True
                and receipt["issues"] == [] and receipt["source_guards_pass"] is True,
                "r30 acceptance/source guard failed")
        require(receipt["source_manifest"] == SOURCE_MANIFEST_NAME
                and receipt["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256
                and receipt["environment_manifest"] == R30_PREFIX + "-environment.json",
                "r30 manifest/environment binding mismatch")
        require(receipt["packages"] == PACKAGES == ["codex-app-server"]
                and receipt["retries"] == (0 if phase == "tests" else None)
                and receipt["filters"] == "no_additions" and receipt["features"] == "unchanged_defaults",
                "r30 selection changed")
        require(receipt["fix_fmt_executed"] is False and receipt["baseline_used_as_filter"] is False
                and receipt["diagnostic_only"] is True and receipt["behavior_repair_claimed"] is False,
                "r30 diagnostic/scope semantics changed")
        verify_pointer(receipt["raw_process_result"], raw_name, originals)
        verify_pointer(receipt["source_postguard"], post_name, originals)
        verify_recorded_guard(records[pre_name], pre_name)
        verify_recorded_guard(records[post_name], post_name)
        require(records[post_name]["gate_exit_code"] == 0 and records[post_name]["phase"] == phase,
                "r30 postguard is not the successful phase")
        log_raw, resource_raw = originals[stem + ".log"], originals[stem + "-resources.txt"]
        require(receipt["log_sha256"] == sha(log_raw) and receipt["resources_sha256"] == sha(resource_raw),
                "r30 original log/resource hash mismatch")
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M) == [b"0"],
                "r30 original resource exit mismatch")
        if phase == "strict":
            require(receipt["acceptance_readback"] is None, "unexpected strict acceptance schema")
        else:
            review_name = stem + "-result-review.json"
            verify_pointer(receipt["acceptance_readback"], review_name, originals)
            rows, computed = review_tests(log_raw, baseline)
            require(records[stem + "-test-results.json"] == rows, "r30 test rows differ from full original log")
            require(computed["pass"] is True and records[review_name] == computed,
                    "r30 exact1345 full-log acceptance cannot be reproduced")
        receipts.append({"path": receipt_name, **data_pin(originals[receipt_name])})
    initial_name, final_name = R30_PREFIX + "-source-pre-verification.json", R30_PREFIX + "-source-final-verification.json"
    verify_recorded_guard(records[initial_name], initial_name)
    verify_recorded_guard(records[final_name], final_name)
    pre = records[R30_PREFIX + "-preconditions.json"]
    require(pre["schema"] == "hepta.source53-project-preconditions.v1", "r30 precondition schema mismatch")
    require(pre["source_tree"] == EXPECTED_TREE and pre["source_commit"] == EXPECTED_COMMIT
            and pre["actual_changed_file_count"] == EXPECTED_CHANGED_COUNT == 197,
            "r30 precondition source mismatch")
    require(pre["source_manifest"] == source_pin and pre["baseline"] == baseline_pin,
            "r30 source/baseline original inputs differ")
    require(pre["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and pre["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r30 precondition dual locks differ")
    verify_pointer(pre["initial_source_guard"], initial_name, originals)
    for key, expected in (
        ("source50_lock_originals_and_outer_terminal", lock_pins),
        ("source50_root_manifest", source50_pin), ("source51_historical_manifest", source51_pin),
        ("source52_parent_manifest", source52_pin), ("source53_apply", apply_proof),
        ("original_r24_failed_100_provenance", r24_failed_pins),
        ("original_r26_failed_100_provenance", r26_failed_pins),
        ("original_r29_failed_100_provenance", r29_failed_pins),
    ):
        require(pre[key] == expected, "r30 producer/consumer prerequisite differs: " + key)
    require(pre["source50_lock_inherited_only_for_unchanged_dependency_inputs"] is True
            and pre["source53_bazel_lock_update_executed"] is False
            and pre["patch_application_performed_by_this_runner"] is False
            and pre["lock_update_performed_by_this_runner"] is False,
            "r30 source/lock provenance relabelled")
    require(pre["baseline_use"] == "acceptance only after the full unfiltered app-server gate"
            and pre["previous_source52_workspace_result"] == "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
            "r30 baseline or original r29 failure meaning changed")
    require(pre["python_runner_source_unchanged"] is True and pre["python_suite_reexecuted"] is False
            and pre["diagnostic_only"] is True and pre["behavior_repair_claimed"] is False,
            "r30 diagnostic/Python classification changed")
    environment = records[R30_PREFIX + "-environment.json"]
    require(environment["schema"] == "hepta.source53-project-environment.v1", "r30 environment schema mismatch")
    require(environment["source_tree"] == EXPECTED_TREE and environment["source_commit"] == EXPECTED_COMMIT
            and environment["source_manifest"] == SOURCE_MANIFEST_NAME
            and environment["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256,
            "r30 environment source binding mismatch")
    require(environment["source_environment_immutable_during_gates"] is True
            and environment["test_deadlines_features_filters_retries_unchanged"] is True
            and environment["sandbox_or_network_protection_environment_overridden"] is False
            and environment["diagnostic_only"] is True and environment["behavior_repair_claimed"] is False,
            "r30 environment contract changed")
    complete = records[R30_PREFIX + "-complete.json"]
    require(complete["schema"] == "hepta.source53-project-gates-complete.v1", "r30 complete schema mismatch")
    require(complete["source_tree"] == EXPECTED_TREE and complete["source_commit"] == EXPECTED_COMMIT
            and complete["source_manifest"] == SOURCE_MANIFEST_NAME
            and complete["source_manifest_sha256"] == SOURCE_MANIFEST_SHA256,
            "r30 complete source mismatch")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r30 complete dual-lock mismatch")
    require(complete["strict_exit"] == complete["tests_exit"] == 0
            and complete["packages"] == PACKAGES and complete["required_old_ids"] == BASELINE_COUNT == 1345
            and complete["all_old_ids_observed_pass"] is True, "r30 complete coverage differs")
    require(complete["phase_receipts"] == receipts and complete["source_guards_pass"] is True,
            "r30 complete original receipts differ")
    require(complete["source50_lock_inherited_for_unchanged_dependency_inputs"] is True
            and complete["source53_bazel_lock_update_executed"] is False
            and complete["source53_apply_complete"] == apply_proof["complete"],
            "r30 completion lock/apply provenance differs")
    require(complete["workspace_not_started_by_this_runner"] is True and complete["fix_fmt_executed"] is False
            and complete["python_suite_reexecuted"] is False, "r30 completion phase confusion")
    require(complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False
            and complete["original_r29_failure_relabelled_as_pass"] is False
            and complete["whole_workspace_qualification"] == "PENDING_SEPARATE_ORIGINAL_GATE",
            "r30 diagnostic gate was relabelled as a repair/workspace result")
    terminal_raw = pinned_read(R30_TERMINAL_NAME, {"bytes": R30_TERMINAL_BYTES, "sha256": R30_TERMINAL_SHA256})
    terminal = closed_terminal(terminal_raw, R30_JOB_ID, "succeeded", 0)
    require(terminal["at_unix_ms"] / 1000 >= previous_end, "r30 terminal precedes completed tests")
    return {
        "schema": "hepta.r31-closed-r30-prerequisite-readback.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "originals": [{"path": name, **data_pin(originals[name])} for name in r30_required_names()],
        "outer_terminal": {"path": R30_TERMINAL_NAME, **data_pin(terminal_raw)},
        "phase_receipts": receipts, "old_app_server_ids_recomputed_from_full_log": BASELINE_COUNT,
        "same_source_strict_full_tests_and_outer_pass": True, "exact_old_test_id_set": True,
        "source53_apply": apply_proof, "source50_lock_originals": lock_pins,
        "source50_root_manifest": source50_pin, "source51_historical_manifest": source51_pin,
        "source52_parent_manifest": source52_pin,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "original_r26_failed_100_provenance": r26_failed_pins,
        "original_r29_failed_100_provenance": r29_failed_pins,
        "python_suite_reexecuted": False, "baseline_used_as_filter": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }, environment
'''


HISTORICAL_APPLY_READER = r'''
def historical_source52_apply_prerequisite(source_pin):
    # Historical apply originals remain fixed to source52. The current source53
    # apply is checked independently by the unmodified r30 producer functions.
    complete_raw, complete_pin = read_fixed(HISTORICAL_APPLY_COMPLETE_NAME, HISTORICAL_APPLY_COMPLETE_BYTES,
                                            HISTORICAL_APPLY_COMPLETE_SHA256)
    terminal_raw, terminal_pin = read_fixed(HISTORICAL_APPLY_TERMINAL_NAME, HISTORICAL_APPLY_TERMINAL_BYTES,
                                            HISTORICAL_APPLY_TERMINAL_SHA256)
    delta_raw, delta_pin = read_fixed(HISTORICAL_DELTA_MANIFEST_NAME, HISTORICAL_DELTA_MANIFEST_BYTES,
                                     HISTORICAL_DELTA_MANIFEST_SHA256)
    complete, delta = json.loads(complete_raw), json.loads(delta_raw)
    require(complete["schema"] == "hepta.source52-apply-complete.v1"
            and delta["schema"] == "hepta.source52-apply-delta.v1", "historical source52 apply schema changed")
    for value in (complete, delta):
        require(value["source_before_tree"] == SOURCE51_TREE and value["source_before_commit"] == SOURCE51_COMMIT
                and value["source_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
                "historical source52 apply identity changed")
    require(complete["source_manifest"] == source_pin and complete["delta_manifest"] == delta_pin,
            "historical source52 apply inputs changed")
    require(complete["source_guards_pass"] is True and complete["actual_changed_file_count"] == 195
            and complete["prior_changed_file_count"] == 194
            and complete["before_existing_repo_leaf_not_in_prior_changed_manifest"] is True,
            "historical source52 apply guard changed")
    require(complete["changed_from_source51_paths"] == list(ALLOWED_SOURCE52_DELTA)
            and complete["dependency_inputs_changed_paths"] == [], "historical source52 apply scope changed")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "historical source52 apply dual locks changed")
    for key in ("bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"):
        require(complete[key] is False, "historical apply-only phase changed")
    post = json.loads(read_pinned(complete["source_postguard"]))
    require(post["schema"] == "hepta.source52-apply-postguard.v1" and post["pass"] is True
            and post["actual_tree"] == SOURCE52_TREE and post["source_commit"] == SOURCE52_COMMIT
            and post["actual_changed_file_count"] == 195 and post["changed_path_set_matches"] is True,
            "historical source52 postguard identity/scope changed")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
            and not post["unstaged_paths"] and not post["untracked_paths"] and not post["file_mismatches"],
            "historical source52 postguard bytes changed")
    terminal = closed_terminal(terminal_raw, HISTORICAL_APPLY_JOB_ID, "succeeded", 0)
    if "ended_unix" in complete:
        require(terminal["at_unix_ms"] / 1000 >= complete["ended_unix"], "historical apply terminal order changed")
    raw = pinned_read(R28_PREFIX + "-preconditions.json", R28_INPUT_PINS[R28_PREFIX + "-preconditions.json"])
    proof = json.loads(raw)["source52_apply"]
    require(proof["complete"] == complete_pin and proof["terminal"] == terminal_pin
            and proof["delta_manifest"] == delta_pin and proof["source_postguard"] == complete["source_postguard"],
            "fixed r28 historical apply pointers differ")
    inheritance = proof["source50_lock_inheritance"]
    require(inheritance["schema"] == "hepta.source52-source50-lock-inheritance.v1"
            and inheritance["lock_executed_for_source_commit"] == LOCK_SOURCE50_COMMIT
            and inheritance["lock_executed_for_source_tree"] == LOCK_SOURCE50_TREE
            and inheritance["parent_source_commit"] == SOURCE51_COMMIT
            and inheritance["parent_source_tree"] == SOURCE51_TREE
            and inheritance["current_source_commit"] == SOURCE52_COMMIT
            and inheritance["current_source_tree"] == SOURCE52_TREE,
            "historical r28 lock-inheritance source identity differs")
    require(set(inheritance["actual_git_tree_changed_paths_from_source50"])
            == set(ALLOWED_SOURCE51_DELTA + ALLOWED_SOURCE52_DELTA)
            and inheritance["actual_git_tree_changed_paths_from_source51"] == list(ALLOWED_SOURCE52_DELTA)
            and inheritance["dependency_inputs_changed_paths"] == []
            and inheritance["source52_bazel_lock_update_executed"] is False,
            "historical r28 lock-inheritance scope differs")
    require(inheritance["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and inheritance["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "historical r28 lock-inheritance raw locks differ")
    require(inheritance["reviewed_delta_patch"] == delta["patch"], "historical source52 patch pin differs")
    require(bool(read_pinned(inheritance["resolved_patch_evidence"])), "historical source52 patch missing")
    return proof
'''


WORKSPACE_BASELINE_READER = r'''
def load_workspace_baseline():
    # Only old, fixed R29 bytes are parsed here. Fresh source53 metadata is a
    # separate later command. These old IDs never enter a test command/filter.
    originals = {name: pinned_read(name, expected) for name, expected in R29_WORKSPACE_BASELINE_INPUT_PINS.items()}
    old_prefix = "native-workspace-r29"
    metadata = json.loads(originals[old_prefix + "-metadata.json"])
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    require(metadata["workspace_root"] == str(S / "codex-rs")
            and metadata["target_directory"] == str(T / "target"), "original r29 metadata root/target differs")
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
            and set(members) == set(defaults), "original r29 default workspace scope differs")
    packages = {package["id"]: package for package in metadata["packages"]}
    require(len(packages) == len(metadata["packages"]) and set(members) <= set(packages),
            "original r29 metadata package identity ambiguity")
    names = {packages[identity]["name"] for identity in members}
    rows, computed = review_original_workspace(originals[old_prefix + "-tests.log"], names)
    require(rows == json.loads(originals[old_prefix + "-test-results.json"]),
            "original r29 rows differ from independently reparsed full log")
    require(computed == json.loads(originals[old_prefix + "-result-review.json"]),
            "original r29 full-log readback cannot be reproduced")
    require(computed["complete_execution_accounting"] is True and computed["pass"] is False
            and computed["terminal_unique_test_count"] == 20228
            and computed["terminal_counts"] == {"PASS": 20227, "FAIL": 1, "TIMEOUT": 0}
            and computed["reported_skipped"] == 130, "original r29 failure population was relabelled")
    identities = {(row["binary"], row["name"]) for row in rows}
    require(len(identities) == len(rows) == 20228, "original r29 binary/name identity count differs")
    receipt_raw, _ = read_fixed(old_prefix + "-tests-receipt.json",
                                R29_FAILURE_PINS[old_prefix + "-tests-receipt.json"]["bytes"],
                                R29_FAILURE_PINS[old_prefix + "-tests-receipt.json"]["sha256"])
    receipt = json.loads(receipt_raw)
    require(receipt["log_sha256"] == sha(originals[old_prefix + "-tests.log"]),
            "original r29 full log not bound to its failed receipt")
    verify_pointer(receipt["acceptance_readback"], old_prefix + "-result-review.json", originals)
    return identities, {
        "schema": "hepta.r31-original-r29-workspace-baseline.v1",
        "source_commit": SOURCE52_COMMIT, "source_tree": SOURCE52_TREE,
        "originals": [{"path": name, **data_pin(raw)} for name, raw in originals.items()],
        "identity_key": ["binary", "name"], "count": len(identities),
        "observed_original_counts": computed["terminal_counts"],
        "original_reported_skipped": computed["reported_skipped"],
        "original_failed_100_preserved": True, "test_ids_used_as_filter": False,
        "acceptance": "exact identity set only after the complete original unfiltered workspace gate",
        "old_metadata_reused_as_current": False,
    }
'''


RUN_FROZEN = r'''
def run_frozen():
    require(not list(E.glob(PREFIX + "-*")), "this run prefix already has evidence; no automatic retry")
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space")
    generated, lock_pins = lock_prerequisite()
    (files, source_pin, source50_files, source50_pin, source51_files,
     source51_pin, source52_files, source52_pin) = load_source(generated)
    require(source_pin["bytes"] == SOURCE_MANIFEST_BYTES, "source53 full-manifest byte count differs")
    r24_failed_pins = r24_failed_prerequisite()
    r26_failed_pins = r26_failed_prerequisite()
    r29_failed_pins = r29_failed_prerequisite()
    apply_proof = apply_prerequisite(files, source_pin, source50_files, source51_files, source52_files)
    baseline, baseline_pin = load_baseline()
    prerequisites, prior_environment = r30_prerequisite(
        baseline, source_pin, baseline_pin, lock_pins, source50_pin, source51_pin,
        source52_pin, apply_proof, r24_failed_pins, r26_failed_pins, r29_failed_pins,
    )
    historical_baseline, historical_baseline_pin = load_inherited_baseline()
    historical_apply = historical_source52_apply_prerequisite(source52_pin)
    inherited, historical_environment = r28_inherited_prerequisite(
        historical_baseline, source52_pin, historical_baseline_pin, lock_pins,
        source50_pin, source51_pin, historical_apply, r24_failed_pins, r26_failed_pins,
    )
    workspace_baseline, workspace_baseline_proof = load_workspace_baseline()
    initial = guard(files)
    initial_pin = write_json(PREFIX + "-source-pre-verification.json", initial)
    require(initial["pass"], "same source53 is not clean/byte-identical")
    env, selection, prerequisite_env_pin = execution_environment()
    require(selection == prior_environment["selection"], "selection environment differs from successful r30")
    require(prerequisite_env_pin == prior_environment["approved_prerequisite_env_pin"],
            "approved external prerequisites differ from successful r30")
    require(selection == historical_environment["selection"]
            and prerequisite_env_pin == historical_environment["approved_prerequisite_env_pin"],
            "inherited r28 environment/prerequisite identity differs")
    write_json(PREFIX + "-environment.json", {
        "schema": "hepta.source53-workspace-environment.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "selection": selection, "approved_prerequisite_env_pin": prerequisite_env_pin,
        "free_bytes_before": shutil.disk_usage(T).free,
        "original_default_workspace_selection": True,
        "outer_timeout_seconds_contract": OUTER_TIMEOUT_SECONDS_CONTRACT,
        "test_deadlines_features_filters_retries_unchanged": True,
        "sandbox_or_network_protection_environment_overridden": False,
        "fresh_current_source_metadata_required": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    })
    write_json(PREFIX + "-preconditions.json", {
        "schema": "hepta.source53-workspace-preconditions.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "actual_changed_file_count": len(files), "source_manifest": source_pin,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "initial_source_guard": initial_pin, "r30_closed_gate_readback": prerequisites,
        "source52_r28_historical_project_gate": inherited,
        "historical_project_pass_substitutes_for_r30": False,
        "source50_lock_originals_and_outer_terminal": lock_pins,
        "source50_root_manifest": source50_pin, "source51_historical_manifest": source51_pin,
        "source52_parent_manifest": source52_pin, "source53_apply": apply_proof,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "original_r26_failed_100_provenance": r26_failed_pins,
        "original_r29_failed_100_provenance": r29_failed_pins,
        "source50_lock_inherited_only_for_unchanged_dependency_inputs": True,
        "source53_bazel_lock_update_executed": False,
        "original_r29_workspace_baseline": workspace_baseline_proof,
        "workspace_baseline_used_as_filter": False,
        "workspace_baseline_exact_set_required_after_complete_execution": True,
        "prior_source52_workspace": "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
        "r25_remains_blocked_and_unexecuted": True, "r27_remains_blocked_and_unexecuted": True,
        "older_source_results_are_not_qualification_for_this_source": True,
        "patch_application_performed": False, "lock_update_performed": False,
        "python_suite_reexecuted": False, "workspace_test_command": COMMAND, "fix_fmt_executed": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    })
    scope, scope_pin = capture_metadata(env, files)
    return run_workspace(env, files, scope, scope_pin, workspace_baseline, workspace_baseline_proof)
'''


def main():
    old_raw, producer_raw = R29_PATH.read_bytes(), R30_PATH.read_bytes()
    if pin(old_raw)["sha256"] != R29_SHA or pin(producer_raw)["sha256"] != R30_SHA:
        raise RuntimeError("original runner/producer pin mismatch")
    old, old_ast, old_functions, old_constants = module(old_raw)
    producer, producer_ast, producer_functions, producer_constants = module(producer_raw)
    first_def = min(node.lineno for node in producer_ast.body if isinstance(node, ast.FunctionDef))
    header = "".join(producer.splitlines(keepends=True)[:first_def - 1])
    first_doc = ast.get_source_segment(producer, producer_ast.body[0])
    header = change(header, first_doc, '"""INERT source53 r31 default workspace diagnostic-source gate.\n\n'
                    'Only actual same-source r30 strict/full-app-server PASS and natural outer0\n'
                    'can admit fresh193 metadata and the original no-p workspace command.\n'
                    'R28 four-package/Python PASS remains source52 historical evidence; R29\n'
                    'failed100 stays unchanged. Exact original20228 IDs are post-gate acceptance\n'
                    'only. No apply, locks update, retry, filter, feature change, fix or fmt.\n'
                    'Source53 is diagnostic-only; passing it does not prove a behavior repair.\n'
                    '"""')
    header = change(header, 'PREFIX = "native-source53-project-r30"', 'PREFIX = "native-workspace-r31"')
    additional = {
        "SOURCE_MANIFEST_BYTES": None,
        "R30_PREFIX": "native-source53-project-r30", "R30_INPUT_PINS": None, "R30_JOB_ID": None,
        "R30_TERMINAL_NAME": None, "R30_TERMINAL_SHA256": None, "R30_TERMINAL_BYTES": None,
        "R30_PHASES": ("strict", "tests"), "R28_PHASES": ("python-runner", "strict", "tests"),
        "PYTHON_TEST_COUNT": 32,
        "COMMAND": ["just", "test", "--locked", "--retries", "0"],
        "METADATA_COMMAND": ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
        "EXPECTED_WORKSPACE_MEMBER_COUNT": 193, "OUTER_TIMEOUT_SECONDS_CONTRACT": 9600,
    }
    for name in ("R28_PREFIX", "R28_INPUT_PINS", "R28_JOB_ID", "R28_TERMINAL_NAME", "R28_TERMINAL_SHA256", "R28_TERMINAL_BYTES",
                 "PREVIOUS_SOURCE49_COMMIT", "PREVIOUS_SOURCE49_TREE"):
        additional[name] = old_constants[name]
    for name in ("BASELINE_NAME", "BASELINE_SHA256", "BASELINE_BYTES", "BASELINE_COUNT"):
        additional["HISTORICAL_" + name] = old_constants[name]
    for name in ("APPLY_COMPLETE_NAME", "APPLY_COMPLETE_SHA256", "APPLY_COMPLETE_BYTES", "APPLY_TERMINAL_NAME",
                 "APPLY_TERMINAL_SHA256", "APPLY_TERMINAL_BYTES", "APPLY_JOB_ID", "DELTA_MANIFEST_NAME",
                 "DELTA_MANIFEST_SHA256", "DELTA_MANIFEST_BYTES"):
        additional["HISTORICAL_" + name] = old_constants[name]
    archive_evidence = WORK / "native-validation-results/r29-archive-closed/original/evidence"
    baseline_pins = {}
    for suffix in ("-tests.log", "-test-results.json", "-result-review.json", "-metadata.json"):
        name = "native-workspace-r29" + suffix
        actual = pin((archive_evidence / name).read_bytes())
        baseline_pins[name] = {key: actual[key] for key in ("bytes", "sha256")}
    additional["R29_WORKSPACE_BASELINE_INPUT_PINS"] = baseline_pins
    header += "\n# Known historical originals are separate from every future r30 closure.\n"
    header += "\n".join(name + " = " + repr(value) for name, value in additional.items()) + "\n\n"
    parts = [header]
    common = []
    for name, function in producer_functions.items():
        if name in ("run_phase", "run_frozen", "main"):
            continue
        if name == "check_bindings":
            function = change(function, "def check_bindings():", "def check_source_bindings():")
        else:
            common.append(name)
        parts.append(function)
    for name in ("pinned_read", "verify_recorded_guard", "verify_pointer", "review_python"):
        parts.append(old_functions[name])
    inherited_guard = old_functions["verify_recorded_guard"]
    inherited_guard = inherited_guard.replace("verify_recorded_guard", "verify_inherited_guard")
    inherited_guard = inherited_guard.replace("EXPECTED_TREE", "SOURCE52_TREE").replace("EXPECTED_COMMIT", "SOURCE52_COMMIT")
    inherited_guard = inherited_guard.replace("EXPECTED_CHANGED_COUNT", "SOURCE52_CHANGED_COUNT")
    parts.append(inherited_guard)
    inherited_tests = old_functions["review_tests"].replace("def review_tests(", "def review_inherited_tests(")
    inherited_tests = inherited_tests.replace("PACKAGES", "HISTORICAL_FOUR_PACKAGES")
    parts.append(inherited_tests)
    inherited_baseline = old_functions["load_baseline"].replace("def load_baseline(", "def load_inherited_baseline(")
    for name in ("BASELINE_NAME", "BASELINE_SHA256", "BASELINE_BYTES", "BASELINE_COUNT"):
        inherited_baseline = inherited_baseline.replace(name, "HISTORICAL_" + name)
    inherited_baseline = inherited_baseline.replace("PACKAGES", "HISTORICAL_FOUR_PACKAGES")
    parts.append(inherited_baseline)
    required_names = old_functions["r28_required_names"].replace("PHASES", "R28_PHASES")
    parts.append(required_names)
    inherited = old_functions["r28_prerequisite"].replace("def r28_prerequisite(", "def r28_inherited_prerequisite(")
    for before, after in (("EXPECTED_TREE", "SOURCE52_TREE"), ("EXPECTED_COMMIT", "SOURCE52_COMMIT"),
                          ("EXPECTED_CHANGED_COUNT", "SOURCE52_CHANGED_COUNT"),
                          ("SOURCE_MANIFEST_NAME", "SOURCE52_MANIFEST_NAME"),
                          ("SOURCE_MANIFEST_SHA256", "SOURCE52_MANIFEST_SHA256"),
                          ("PACKAGES", "HISTORICAL_FOUR_PACKAGES"), ("BASELINE_COUNT", "HISTORICAL_BASELINE_COUNT"),
                          ("PHASES", "R28_PHASES"), ("verify_recorded_guard", "verify_inherited_guard"),
                          ("review_tests(", "review_inherited_tests(")):
        inherited = inherited.replace(before, after)
    inherited = change(inherited, '"schema": "hepta.r29-closed-r28-prerequisite-readback.v1",',
                       '"schema": "hepta.r31-historical-source52-r28-readback.v1",')
    inherited = change(inherited, '"same_source_all_three_phases_and_outer_pass": True,',
                       '"historical_source52_all_three_phases_and_outer_pass": True,\n'
                       '        "source53_execution_claimed": False, "substitutes_for_r30": False,')
    parts.extend([HISTORICAL_APPLY_READER, inherited, R30_READER])
    original_workspace = old_functions["review_workspace"].replace("def review_workspace(", "def review_original_workspace(")
    original_workspace = original_workspace.replace("EXPECTED_TREE", "SOURCE52_TREE").replace("EXPECTED_COMMIT", "SOURCE52_COMMIT")
    parts.extend([original_workspace, WORKSPACE_BASELINE_READER])
    metadata = old_functions["capture_metadata"].replace("source52", "source53")
    metadata = change(metadata, '"all_platforms_features_external_services_qualified": False,',
                      '"all_platforms_features_external_services_qualified": False,\n'
                      '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(metadata)
    workspace = old_functions["review_workspace"].replace("source52", "source53")
    workspace = change(workspace, "def review_workspace(raw, workspace_names):", "def review_workspace(raw, workspace_names, baseline):")
    workspace = change(workspace, '    passed = complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0',
                       '    missing = sorted(baseline - set(current))\n'
                       '    additional = sorted(set(current) - baseline)\n'
                       '    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")\n'
                       '    passed = (complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0\n'
                       '              and not missing and not additional and not unsuccessful)')
    workspace = change(workspace, '        "test_ids_used_as_filter": False, "pass": bool(passed),',
                       '        "test_ids_used_as_filter": False, "pass": bool(passed),\n'
                       '        "original_r29_baseline_count": len(baseline),\n'
                       '        "original_r29_baseline_is_failed_population": True,\n'
                       '        "exact_old_test_id_set_required": True,\n'
                       '        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],\n'
                       '        "additional_test_ids": [{"binary": b, "name": n} for b, n in additional],\n'
                       '        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],\n'
                       '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(workspace)
    run = old_functions["run_workspace"].replace("source52", "source53")
    run = change(run, "def run_workspace(env, files, scope, scope_pin):",
                 "def run_workspace(env, files, scope, scope_pin, workspace_baseline, workspace_baseline_proof):")
    run = change(run, "rows, review = review_workspace(log_raw, names)",
                 "rows, review = review_workspace(log_raw, names, workspace_baseline)")
    run = change(run, '        "free_space_is_shared_filesystem_sample_not_exclusive_gate_cost": True,',
                 '        "free_space_is_shared_filesystem_sample_not_exclusive_gate_cost": True,\n'
                 '        "original_r29_workspace_baseline": workspace_baseline_proof,\n'
                 '        "test_ids_used_as_filter": False, "exact_old_test_id_set_required": True,\n'
                 '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    run = change(run, '            "all_platforms_features_external_services_qualified": False,',
                 '            "all_platforms_features_external_services_qualified": False,\n'
                 '            "original_r29_workspace_baseline": workspace_baseline_proof,\n'
                 '            "exact_old_test_id_set_observed_pass": True, "test_ids_used_as_filter": False,\n'
                 '            "diagnostic_only": True, "behavior_repair_claimed": False,\n'
                 '            "original_r29_failure_relabelled_as_pass": False,')
    run = change(run, '            "fix_fmt_executed": False, "no_automatic_retry": True, "source_retained": True,',
                 '            "fix_fmt_executed": False, "no_automatic_retry": True, "source_retained": True,\n'
                 '            "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.extend([run, RUN_FROZEN])
    final_main = old_functions["main"].replace("source52", "source53")
    final_main = change(final_main, '                "no_automatic_retry": True, "source_retained": True, "fix_fmt_executed": False,',
                        '                "no_automatic_retry": True, "source_retained": True, "fix_fmt_executed": False,\n'
                        '                "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(final_main)
    output = "\n\n".join(part.strip("\n") for part in parts) + '\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'
    raw = output.encode()
    _, parsed, result_functions, result_constants = module(raw)
    if len(result_functions) != sum(isinstance(node, ast.FunctionDef) for node in parsed.body):
        raise RuntimeError("duplicate generated function names")
    for name in common:
        if result_functions[name] != producer_functions[name]:
            raise RuntimeError("r30 common function bytes changed: " + name)
    expected_checker = producer_functions["check_bindings"].replace("def check_bindings():", "def check_source_bindings():")
    if result_functions["check_source_bindings"] != expected_checker:
        raise RuntimeError("source binding checker differs beyond name")
    unknowns = sorted(name for name, value in result_constants.items() if value is None)
    if result_constants["FROZEN"] is not False or len(unknowns) != 21:
        raise RuntimeError("inert preparation binding count differs: " + repr(unknowns))
    created = []
    created.append(put("references/native-run-r29-actual.py", old_raw))
    created.append(put("references/native-run-r30-template-v2.py", producer_raw))
    created.append(put("native-run-r31-template.py", raw))
    diff = "".join(difflib.unified_diff(old.splitlines(keepends=True), output.splitlines(keepends=True),
                                     fromfile="actual-r29/native-run-r29.py", tofile="inert-r31/native-run-r31-template.py"))
    created.append(put("r29-r31-template.patch", diff.encode()))
    created.append(obj("MECHANICAL-READBACK.json", {
        "schema": "hepta.source53-r31-template-mechanical.v1", "template": pin(raw),
        "actual_r29": pin(old_raw), "r30_producer_v2": pin(producer_raw),
        "ast_parse_executed": True, "runner_imported_or_executed": False,
        "rust_metadata_formatter_native_executed": False,
        "same_r30_function_names": common, "same_r30_function_count": len(common),
        "source_binding_checker_only_renamed": True,
        "inert_frozen": result_constants["FROZEN"], "unknown_binding_count": len(unknowns),
        "unknown_binding_names": unknowns,
        "actual_r29_preserved_unchanged": True,
        "workspace_command": result_constants["COMMAND"],
        "outer_timeout_seconds_contract": result_constants["OUTER_TIMEOUT_SECONDS_CONTRACT"],
        "r30_success_original_count": 19, "r28_historical_original_count": 26,
        "r30_two_phases_only": True, "r28_historical_not_current_qualification": True,
        "raw_write_flush_fsync_copied_from_r30_v2": True,
        "workspace_exact20228_only_post_gate_not_filter": True,
        "diagnostic_classification_preserved": True,
    }))
    created.append(obj("INPUT-PINS.json", {
        "schema": "hepta.source53-r31-preparation-inputs.v1",
        "actual_r29": {"path": str(R29_PATH.relative_to(WORK)), **pin(old_raw)},
        "r30_producer_v2": {"path": str(R30_PATH.relative_to(WORK)), **pin(producer_raw)},
        "original_r29_baseline_pins": baseline_pins,
        "known_registered_source53_commit": "f74be175de66a4b351cd239d39d98cd34fe9cc1b",
        "known_registered_source53_tree": "440d4a8e09af4009e4d9ea067388826308da8803",
        "known_registered_changed_count": 197,
        "registration_does_not_supply_future_r30_closures": True,
        "bindings_deliberately_unset_in_inert_template": unknowns,
    }))
    print(json.dumps({"created": created, "common_functions": len(common), "unknown_bindings": len(unknowns)}, indent=2))


if __name__ == "__main__":
    main()
