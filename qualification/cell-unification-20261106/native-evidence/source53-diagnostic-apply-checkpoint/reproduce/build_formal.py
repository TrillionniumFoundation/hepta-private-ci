"""Seal one new local evidence group after independently reading closed inputs.

This script does not invoke Git, native control, Rust, metadata or a gate runner.
All copied files are immutable original bytes; generated readbacks are labelled.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import tarfile

import prepare_attachment_plan as common

ROOT, OUT = common.ROOT, common.OUT
REPORT = ROOT / "hepta-cell/qualification/cell-unification-20261106"
DEST = REPORT / "native-evidence/source53-diagnostic-apply-checkpoint"
V2 = ROOT / "native-validation-results/source53-apply-v2-closed"
E = V2 / "evidence"
R = E / "native-source53-apply"
PIN_KEYS = ("bytes", "sha256", "git_blob")


def write(path, raw):
    assert not path.exists() and not path.is_symlink(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(raw)
    assert path.read_bytes() == raw


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def snapshot_pin(path):
    return {"path": path.relative_to(ROOT).as_posix(), **common.pin(common.read(path))}


def canonical_tree(value):
    assert value["truncated"] is False
    entries = value["tree"]
    assert len({entry["path"] for entry in entries}) == len(entries)
    body = bytearray()
    for entry in sorted(entries, key=lambda e: (e["path"] + ("/" if e["type"] == "tree" else "")).encode()):
        assert "/" not in entry["path"] and entry["path"] not in (".", "..")
        mode = entry["mode"].lstrip("0")
        body.extend(mode.encode() + b" " + entry["path"].encode() + b"\0" + bytes.fromhex(entry["sha"]))
    result = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
    assert result == value["sha"]
    return result


def verify_git_and_rows(manifest, delta):
    direct = ROOT / "source53-root-preparation/actual-tree-reads"
    paths = ["", "codex-rs", "codex-rs/app-server", "codex-rs/app-server/src",
             "codex-rs/app-server/src/request_processors",
             "codex-rs/app-server/src/request_processors/account_processor",
             "codex-rs/app-server/tests", "codex-rs/app-server/tests/suite",
             "codex-rs/app-server/tests/suite/v2"]
    trees = {}
    for path in paths:
        prefix = path.replace("/", "__") if path else "ROOT"
        for side in ("before", "after"):
            raw = common.read(direct / (prefix + "-" + side + ".json"))
            value = json.loads(raw)
            trees[(path, side)] = value
            canonical_tree(value)
    assert trees[("", "before")]["sha"] == common.TREE52
    assert trees[("", "after")]["sha"] == common.TREE53
    differences = []

    def visit(path):
        before = {entry["path"]: entry for entry in trees[(path, "before")]["tree"]}
        after = {entry["path"]: entry for entry in trees[(path, "after")]["tree"]}
        assert set(before) == set(after)
        for name in before:
            left, right = before[name], after[name]
            assert left["mode"] == right["mode"] and left["type"] == right["type"]
            if left["sha"] == right["sha"]:
                continue
            child = path + "/" + name if path else name
            if left["type"] == "tree":
                assert trees[(child, "before")]["sha"] == left["sha"]
                assert trees[(child, "after")]["sha"] == right["sha"]
                visit(child)
            else:
                differences.append({"path": child, "mode": left["mode"], "before": left["sha"], "after": right["sha"]})

    visit("")
    expected = {row["path"]: (row["before"]["mode"], row["before"]["git_blob"], row["after"]["git_blob"])
                for row in delta["files"]}
    assert {row["path"]: (row["mode"], row["before"], row["after"]) for row in differences} == expected
    response = common.obj(ROOT / "source53-root-preparation/ACTUAL-COMMIT-API-RESPONSE.json")
    commit = json.loads(response["structuredContent"]["content"])
    assert commit["sha"] == common.SOURCE53 and commit["tree"]["sha"] == common.TREE53
    assert [parent["sha"] for parent in commit["parents"]] == [common.SOURCE52]
    old_raw = common.read(ROOT / "source53-apply-preparation/references/source52-actual-manifest.json")
    new_raw = common.read(E / "native-candidate-r30-source.json")

    def row_slices(raw):
        text = raw.decode()
        match = re.search(r'"changed_files"\s*:\s*\[', text)
        assert match
        cursor, rows = match.end(), {}
        decoder = json.JSONDecoder()
        while True:
            while text[cursor].isspace() or text[cursor] == ",":
                cursor += 1
            if text[cursor] == "]":
                break
            value, end = decoder.raw_decode(text, cursor)
            assert value["path"] not in rows
            rows[value["path"]] = (value, text[cursor:end].encode())
            cursor = end
        return rows

    old, new = row_slices(old_raw), row_slices(new_raw)
    assert len(old) == 195 and len(new) == 197
    assert set(new) - set(old) == set(expected) and not (set(old) - set(new))
    assert all(new[path] == old[path] for path in old)
    assert len(manifest["changed_files"]) == 197
    assert sum(row["path"].endswith(".rs") for row in manifest["changed_files"]) == 183
    return {"direct_trees_canonical_hash_recomputed": 18,
            "old_tree": common.TREE52, "new_tree": common.TREE53,
            "exact_changed_existing_leaves": differences,
            "single_parent_commit": common.SOURCE52,
            "old195_row_values_and_individual_JSON_slices_exact": True,
            "manifest_scope": {"all": 197, "rust": 183, "other": 14}}


def replay_diff(raw, before):
    lines = raw.decode().splitlines(keepends=True)
    result, index = {}, 0
    while index < len(lines):
        if not lines[index].startswith("--- a/"):
            index += 1
            continue
        path = lines[index][6:].rstrip("\n")
        assert lines[index + 1] == "+++ b/" + path + "\n"
        source, output, cursor = before[path].decode().splitlines(keepends=True), [], 0
        index += 2
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if not lines[index].startswith("@@ "):
                index += 1
                continue
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
            assert match
            start, old_count, new_start, new_count = [int(value) if value is not None else 1 for value in match.groups()]
            start = start - 1 if old_count else start
            assert start >= cursor
            output.extend(source[cursor:start])
            assert len(output) == (new_start - 1 if new_count else new_start)
            cursor, removed, added = start, 0, 0
            index += 1
            while index < len(lines) and lines[index][:1] in (" ", "+", "-"):
                line = lines[index]
                if line[0] in " -":
                    assert source[cursor] == line[1:]
                    cursor += 1
                    removed += 1
                if line[0] in " +":
                    output.append(line[1:])
                    added += 1
                index += 1
            assert removed == old_count and added == new_count
        output.extend(source[cursor:])
        assert path not in result
        result[path] = "".join(output).encode()
    assert set(result) == set(before)
    return result


def verify_v2():
    local = common.obj(V2 / "LOCAL-READBACK.json", {"bytes": 13786, "sha256": "baab5bcb17a07814cdc1ac14dfd2d4cdeb58a730bb2719de6bee8228d303bb72"})
    assert len(local["files"]) == 43
    for row in local["files"]:
        common.read(V2 / common.safe(row["path"]), row)
    assert {p.relative_to(V2).as_posix() for p in V2.rglob("*") if p.is_file()} == {row["path"] for row in local["files"]} | {"LOCAL-READBACK.json"}
    terminal = common.obj(V2 / "controller/terminal.json")
    common.terminal(terminal, "1a1b2552130-fc05-7d91", "succeeded", 0)
    assert common.read(V2 / "controller/terminal.json") == common.read(E / "native-source53-apply-v2-terminal-process-status.json")
    complete, post = common.obj(R / "complete.json"), common.obj(R / "post-apply-source-guard.json")
    assert complete["schema"] == "hepta.source53-apply-complete.v1"
    assert post["schema"] == "hepta.source53-apply-postguard.v1"
    for value in (complete, post):
        assert value["source_commit"] == common.SOURCE53
        tree_key = "source_tree" if value is complete else "actual_tree"
        assert value[tree_key] == common.TREE53 and value["actual_changed_file_count"] == 197
        assert value["prior_changed_file_count"] == 195
        assert value["cargo_lock_sha256"] == common.CARGO and value["bazel_lock_sha256"] == common.BAZEL
        assert value["diagnostic_only"] and value["behavior_repair_claimed"] is False
        assert value["dependency_inputs_changed_paths"] == []
    assert complete["native_git_head"] == post["native_head"] == common.HEAD
    assert complete["source_guards_pass"] and post["pass"] and post["changed_path_set_matches"]
    assert post["unstaged_paths"] == post["untracked_paths"] == post["file_mismatches"] == []
    assert complete["source_before_commit"] == common.SOURCE52 and complete["source_before_tree"] == common.TREE52
    assert not any(complete[key] for key in ("rust_executed", "bazel_lock_update_executed", "fix_fmt_executed"))
    for key in ("source_manifest", "delta_manifest", "source_postguard"):
        common.read(E / complete[key]["path"], complete[key])
    manifest = common.obj(E / complete["source_manifest"]["path"])
    delta = common.obj(E / complete["delta_manifest"]["path"])
    assert manifest["source_commit"] == common.SOURCE53 and manifest["source_tree"] == common.TREE53
    inputs = ROOT / "source53-apply-preparation/derived/source53-apply-input.tar.gz"
    with tarfile.open(inputs, "r:gz") as archive:
        members = archive.getmembers()
        assert len(members) == 7 and len({member.name for member in members}) == 7
        for member in members:
            assert member.isfile() and member.mode == 0o600
            common.safe(member.name)
            assert archive.extractfile(member).read() == common.read(R / "input" / member.name)
    old_manifest = common.obj(ROOT / "source53-apply-preparation/references/source52-actual-manifest.json")
    expected_old_paths = {row["path"] for row in old_manifest["changed_files"]}
    expected_new_paths = {row["path"] for row in manifest["changed_files"]}
    for name in ("pre-apply-source-guard.json", "immediately-before-apply-source-guard.json"):
        value = common.obj(R / name)
        assert value["pass"] and value["actual_tree"] == common.TREE52
        assert value["native_head"] == common.HEAD and value["actual_changed_file_count"] == 195
        assert set(value["changed_paths"]) == expected_old_paths
        assert value["file_mismatches"] == value["unstaged_paths"] == value["untracked_paths"] == []
        assert value["cargo_lock_sha256"] == common.CARGO and value["bazel_lock_sha256"] == common.BAZEL
    assert set(post["changed_paths"]) == expected_new_paths
    paths = [row["path"] for row in delta["files"]]
    assert complete["changed_from_source52_paths"] == post["changed_from_source52_paths"] == paths
    prestage = common.obj(R / "prestage-source-guard.json")
    assert prestage["pass"] and prestage["index_tree"] == common.TREE52
    assert prestage["unstaged_paths"] == paths and prestage["untracked_paths"] == prestage["mismatches"] == []
    patch = "/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source53-apply/input/candidate.patch"
    expected_commands = [("apply-check", ["git", "apply", "--check", patch]),
                         ("apply", ["git", "apply", patch]),
                         ("stage-exact-paths", ["git", "add", "--", *paths])]
    raw_commands, previous_end = [], None
    for phase, command in expected_commands:
        raw = common.obj(R / (phase + "-raw-process-result.json"))
        receipt = common.obj(R / (phase + "-receipt.json"))
        assert raw["schema"] == "hepta.source53-original-git-command-result.v1"
        assert all(receipt[key] == value for key, value in raw.items())
        assert raw["command"] == command and raw["exit_code"] == 0 and raw["wait_exception"] is None
        assert raw["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source"
        assert raw["ended_unix"] >= raw["started_unix"]
        assert previous_end is None or raw["started_unix"] >= previous_end
        previous_end = raw["ended_unix"]
        for stream in ("stdout", "stderr"):
            common.read(R / (phase + "-" + stream + ".log"), receipt[stream])
        raw_commands.append(raw)
    assert terminal["at_unix_ms"] / 1000 >= previous_end
    before, after = {}, {}
    for row in delta["files"]:
        before[row["path"]] = common.read(R / "input/before" / row["path"], row["before"])
        after[row["path"]] = common.read(R / "input/after" / row["path"], row["after"])
    actual_patch = common.read(R / "actual-source52-to-source53.patch")
    assert replay_diff(actual_patch, before) == after
    tree = verify_git_and_rows(manifest, delta)
    return {
        "schema": "hepta.source53-actual-apply-independent-closure.v1",
        "status": "APPLY_ONLY_NATURAL_0_DIAGNOSTIC_SOURCE53_EXACT197",
        "actual_source_commit": common.SOURCE53, "actual_source_tree": common.TREE53,
        "source_before_commit": common.SOURCE52, "source_before_tree": common.TREE52,
        "native_HEAD": common.HEAD, "checkout_of_registered_commit_claimed": False,
        "original_apply_job": terminal["job_id"], "original_outer_exit": 0,
        "natural_complete_durable_terminal": True, "three_original_Git_commands": raw_commands,
        "all43_underlying_files_and_local_readback_rehashed": True,
        "seven_input_members_equal_exact_approved_archive": True,
        "pre195_intermediate_exact_two_unstaged_and_post197_guards_verified": True,
        "native_guard_attests_full_raw_source_rehash": True,
        "reviewer_independently_read_all197_native_source_payloads": False,
        "source_identity_independent_git_and_manifest_verification": tree,
        "actual_native_diff_pure_python_forward_replay_matches_both_after_files": True,
        "original_Git_harness_has_raw_timing_and_receipts_not_time_resources": True,
        "preliminary_plan_resource_wording_superseded_by_actual_schema": True,
        "dual_locks_unchanged": True, "dependency_inputs_changed": [],
        "complete": snapshot_pin(R / "complete.json"), "postguard": snapshot_pin(R / "post-apply-source-guard.json"),
        "source_manifest": snapshot_pin(E / "native-candidate-r30-source.json"),
        "original_v1_path_failure_preserved": True, "diagnostic_only": True,
        "behavior_repair_claimed": False, "root_cause_proven": False,
        "Rust_lock_update_fix_fmt_executed_by_apply": False,
        "R30_R31_execution_or_results_in_this_group": False,
        "scientific_disposition": "HOLD", "authority": "DENY_ALL",
        "this_readback_runs_only_local_Python_data_checks": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal", action="store_true", help="Create only the authorized new local formal evidence directory")
    args = parser.parse_args()
    assert args.seal, "Use explicit --seal; no automatic creation"
    assert not DEST.exists(), "The formal directory already exists; never overwrite a frozen group"
    first = common.verify_attempt1()
    actual = verify_v2()
    plan = common.obj(OUT / "PREPARATION-PLAN.json")
    # R30 preparations/results belong to their separate gate group. This group
    # freezes only the diagnostic candidate, registration and actual apply.
    entries = [entry for entry in plan["entries"] if not entry["destination"].startswith("r30-static-review/")]
    for path in sorted(V2.rglob("*")):
        if path.is_file():
            entries.append({"source": path.relative_to(ROOT).as_posix(),
                            "destination": "attempt2/" + path.relative_to(V2).as_posix(),
                            **common.pin(common.read(path))})
    for source, destination in (
        ("source53-root-preparation/ACTUAL-APPLY-V2-READBACK.json", "root-registration-and-authorization/ACTUAL-APPLY-V2-READBACK.json"),
        ("source53-diagnostic-formal-preparation/prepare_attachment_plan.py", "reproduce/prepare_attachment_plan.py"),
        ("source53-diagnostic-formal-preparation/build_formal.py", "reproduce/build_formal.py"),
        ("source53-diagnostic-formal-preparation/PREPARATION-PLAN.json", "reproduce/PREPARATION-PLAN.json"),
    ):
        entries.append({"source": source, "destination": destination, **common.pin(common.read(ROOT / source))})
    assert len({entry["destination"] for entry in entries}) == len(entries)
    # Read and verify every planned original before the first destination write.
    payloads = [(entry, common.read(ROOT / common.safe(entry["source"]), entry)) for entry in entries]
    generated = {
        "INDEPENDENT-READBACK.json": json_bytes(actual),
        "CLOSURE.json": json_bytes({
            "schema": "hepta.source53-diagnostic-apply-checkpoint-closure.v1",
            "classification": "DIAGNOSTIC_SOURCE_REGISTERED_AND_APPLIED_NOT_BEHAVIOR_REPAIR",
            "source_commit": common.SOURCE53, "source_tree": common.TREE53,
            "parent_commit": common.SOURCE52, "parent_tree": common.TREE52,
            "native_HEAD": common.HEAD, "source_count": 197, "rust_paths": 183, "other_paths": 14,
            "owners": 26, "CI_package_selectors": 27,
            "attempt1": {"job": first["original_apply_job"], "exit_code": 1, "classification": "PREPARATION_INPUT_PATH_FAILURE_BEFORE_GIT", "read_only_guard_exit": 0, "unchanged_source52_count": 195},
            "attempt2": {"job": actual["original_apply_job"], "exit_code": 0, "original_git_exit_codes": [0, 0, 0], "full197_and_HEAD_dual_lock_guards_pass": True},
            "corrected_input_placement_only_same_script_and_same_tar": True,
            "diagnostic_only": True, "behavior_repair_claimed": False, "original_Bedrock_root_cause_proven": False,
            "original_R29_failed100_retained": True,
            "R30_R31_results": None, "R30_R31_originals_not_in_this_group": True,
            "Rust_tests_lock_update_fix_fmt_executed_by_apply": False,
            "independent_readback": {"path": "INDEPENDENT-READBACK.json", **common.pin(json_bytes(actual))},
            "science": "HOLD", "authority": "DENY_ALL", "closure_gaps_for_this_apply_scope": [],
            "limits": ["Native source guards are original evidence; this local review independently rehashes all supplied artifacts and rebuilds the18 direct Git trees, not a second native197-file read.", "Actual source manifest remains its immutable registration-time text; native applied state is supplied by separate complete/postguard/outer originals.", "Source53 only adds nine fixed stage events and one child logging filter. No timeout, assertion, retry, request, permission or model behavior was changed.", "Project/workspace qualification and a root-cause conclusion require separate actual execution evidence."]}),
        "README.md": ("# Source53 diagnostic registration and native application\n\n"
            "This frozen group preserves the two-file diagnostic candidate, exact source53 GitData registration, independent static reviews, and both native apply attempts. Source53 is diagnostic only; it is not a demonstrated behavioral repair.\n\n"
            "Attempt1 naturally exited1 because the input archive was uploaded under evidence/ while the unchanged reviewed script read the task root. The complete traceback and a separate natural0 read-only guard prove source52 remained unchanged:195 paths, native HEAD bef, both locks and the two before leaves. The wrong-location copy, missing-path response, corrected create-only upload and explicit new-key authorization remain separate originals.\n\n"
            "The corrected attempt2 naturally exited0. Original git apply --check, git apply and exact two-path stage each exited0; pre195/intermediate two-path/post197 guards, HEAD and both locks passed. The exact original7-member input and all43 closed artifacts were rehashed. The local independent readback also recomputes18 direct Git tree objects, verifies the single parent and two-leaf delta, preserves each old195 manifest row value and JSON slice, and replays the native diff against original before/after bytes.\n\n"
            "No Rust gate, lock update, fix or formatter ran in either apply task. R30/R31 results are deliberately absent from this apply-only group. Original source52 R29 failed100 remains unchanged. A later actual engineering PASS would not prove the Bedrock root cause repaired or grant scientific adoption; HOLD and DENY_ALL remain.\n\n"
            "Files under attempt1/ and attempt2/ retain their exact original bytes. Earlier preparation manifests and first readbacks keep their historical not-applied/pending wording; CLOSURE.json binds the later actual application. SOURCE-DESTINATION-MAPPING.json names every copied source and its raw/SHA256/Git blob pins. ATTACHMENT-MANIFEST.json inventories every group file except itself. The preliminary preparation-plan word resources is superseded by the real Git harness schema, which records raw timing/receipts/stdout/stderr and does not collect /usr/bin/time resources.\n").encode(),
        "SOURCE-DESTINATION-MAPPING.json": json_bytes({"schema": "hepta.source53-diagnostic-attachment-mapping.v1", "entries": entries, "count": len(entries), "all_original_bytes_preserved": True, "no_original_result_rewritten": True}),
    }
    for entry, raw in payloads:
        write(DEST / common.safe(entry["destination"]), raw)
    for name, raw in generated.items():
        write(DEST / name, raw)
    files = [{"path": path.relative_to(DEST).as_posix(), **common.pin(common.read(path))}
             for path in sorted(DEST.rglob("*")) if path.is_file()]
    manifest = {"schema": "hepta.source53-diagnostic-attachment-manifest.v1", "files": files,
                "listed_file_count": len(files), "listed_bytes": sum(row["bytes"] for row in files),
                "manifest_itself_excluded": True, "diagnostic_only": True, "behavior_repair_claimed": False}
    write(DEST / "ATTACHMENT-MANIFEST.json", json_bytes(manifest))
    binaries = []
    for row in files:
        try:
            common.read(DEST / row["path"]).decode("utf-8")
        except UnicodeDecodeError:
            binaries.append({"path": "qualification/cell-unification-20261106/native-evidence/source53-diagnostic-apply-checkpoint/" + row["path"], **{key: row[key] for key in PIN_KEYS}})
    write(OUT / "BINARY-PLAN.json", json_bytes({"schema": "hepta.source53-diagnostic-binary-upload-plan.v1", "binary_entries": binaries, "uploaded_or_ledger_registered_by_this_script": False}))
    output = {"schema": "hepta.source53-diagnostic-formal-handoff.v1", "formal_directory": DEST.relative_to(ROOT).as_posix(),
              "file_count_including_manifest": len(files) + 1,
              "total_bytes_including_manifest": sum(row["bytes"] for row in files) + (DEST / "ATTACHMENT-MANIFEST.json").stat().st_size,
              "attachment_manifest": snapshot_pin(DEST / "ATTACHMENT-MANIFEST.json"),
              "closure": snapshot_pin(DEST / "CLOSURE.json"), "independent_readback": snapshot_pin(DEST / "INDEPENDENT-READBACK.json"),
              "binary_plan": snapshot_pin(OUT / "BINARY-PLAN.json"), "canonical_reports_INDEX_ledger_source_written": False,
              "Rust_or_native_executed_by_assembler": False}
    write(OUT / "HANDOFF-MANIFEST.json", json_bytes(output))
    print(json.dumps(output))


if __name__ == "__main__":
    main()
