"""Independently recover the fixed failed ARM run packet in memory."""

import ast
import datetime
import hashlib
import json
from pathlib import Path
import runpy
import stat
import sys


ROOT = Path("/workspace/scratch/3f6a885bb83c")
PROOF = ROOT / "round3_local_qualification/arm5188_checkpoint_root"
PACKAGE = ROOT / "round3_ci/arm5188_hash_timing_backend_checkpoint_20261107"
NATIVE = ROOT / "round3_ci/port_diagnosis/arm5188"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity_bytes(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def identity(path):
    require(path.is_file() and not path.is_symlink(), "ordinary source file")
    return identity_bytes(path.read_bytes())


def pinned(path, sha):
    found = identity(path)
    require(found["sha256"] == sha, "frozen input identity")
    return found


def seal(source):
    values = [
        ast.literal_eval(node.value)
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_INDEX_SHA256"
            for target in node.targets
        )
    ]
    require(len(values) == 1, "one fixed INDEX seal")
    return values[0]


def main():
    require(sys.flags.optimize == 1, "actual optimized interpreter review")
    v1_path = ROOT / "round3_ci/ARM5188_HASH_TIMING_BACKEND_EVIDENCE_PUBLICATION.json"
    v2_path = (
        ROOT / "round3_ci/ARM5188_HASH_TIMING_BACKEND_EVIDENCE_PUBLICATION_V2.json"
    )
    v1_id = pinned(
        v1_path, "2ce9c38ff826e30061ee926776aee32866eeff83d0976150bdc16dffedd7fcd4"
    )
    v2_id = pinned(
        v2_path, "fa71cf1cf48f98cebbefea74913db1a2d877a66f9b0260adb70eac2d467bc535"
    )
    v1, v2 = json.loads(v1_path.read_bytes()), json.loads(v2_path.read_bytes())
    rows1, rows2 = ({row["path"]: row for row in item["files"]} for item in (v1, v2))
    require(
        len(rows1) == len(rows2) == len(v1["files"]) == len(v2["files"]) == 30,
        "unique complete publication paths",
    )
    require(set(rows1) == set(rows2), "unchanged publication path set")
    require(
        [name for name in rows1 if rows1[name] != rows2[name]] == ["restore.py"],
        "only reader publication row changed",
    )
    for name, row in rows2.items():
        require(
            identity(Path(row["source_file"]))
            == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
            "publication source bytes",
        )
        require(row["mode"] == "100644", "inert published mode")
    reader = Path(rows2["restore.py"]["source_file"])
    original_reader = Path(rows1["restore.py"]["source_file"])
    template = ROOT / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_id = pinned(
        template, "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d"
    )
    reader_id = pinned(
        reader, "d4ca355cbc8fee3dcc1952bfebf6f60da5ff49f201682cad26b7e0184800e7cd"
    )
    reader_source, template_source = reader.read_text(), template.read_text()
    require(
        template_source.count(seal(template_source)) == 1,
        "single template seal literal",
    )
    require(
        reader_source
        == template_source.replace(seal(template_source), seal(reader_source)),
        "canonical reader only INDEX seal replacement",
    )
    require(
        ast.dump(ast.parse(reader_source))
        == ast.dump(ast.parse(original_reader.read_text())),
        "v1 and v2 full AST identical",
    )
    require(
        not any(
            isinstance(node, ast.Assert) for node in ast.walk(ast.parse(reader_source))
        ),
        "reader gates survive optimization",
    )
    source_api_path = PROOF / "READER_SOURCE_API.json"
    api_id = pinned(
        source_api_path,
        "8ce4b583eefb979c79fbe3db36864a3e16cdf2cf7d2e366d25a78f77ad242287",
    )
    source_api = json.loads(source_api_path.read_bytes())
    require(
        source_api["head"] == "fcc50184ae2a21e4a444906c843470f0ffd004e5"
        and source_api["tree"] == "7c62cf3246894fbea60aea6b42e74aa6abe34919",
        "published canonical source binding",
    )
    require(len(source_api["leaves"]) == 1, "one canonical reader leaf")
    leaf = next(iter(source_api["leaves"].values()))
    require(
        leaf["sha"] == template_id["git_blob"]
        and leaf["size"] == template_id["bytes"]
        and leaf["mode"] == "100644",
        "published reader equals local canonical bytes",
    )
    failure_id = pinned(
        PROOF / "INITIAL_READER_FORMAT_FAILURE.json",
        "607ca4572669a745d2af41af0a39fce0ebd8aa6cc2a3ad279c23939f2afdbe05",
    )
    owner_id = pinned(
        ROOT / "round3_ci/arm5188_reader_format_v2/READER_SUCCESSOR_REVIEW.json",
        "223ec366c7d96ceb81c1f3890b64becadcbc2e5e0749163a6d1df363073eb43d",
    )
    loaded = runpy.run_path(str(reader), run_name="verified_packet_reader")
    index, restored = loaded["read_package"](PACKAGE)
    index_id = identity(PACKAGE / "INDEX.json")
    require(
        index_id == v1["index"] == v2["index"]
        and index_id["sha256"] == seal(reader_source),
        "unchanged sealed INDEX",
    )
    entries = {row["path"]: row for row in index["files"]}
    require(
        len(entries) == len(index["files"]) == len(restored) == 236
        and set(entries) == set(restored),
        "complete unique recovered inventory",
    )
    for name, data in restored.items():
        row = entries[name]
        source = ROOT / name
        require(
            identity_bytes(data)
            == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
            "restored full member identity",
        )
        require(
            source.read_bytes() == data and not source.is_symlink(),
            "restored bytes equal original local source",
        )
        require(
            format(stat.S_IMODE(source.stat().st_mode), "04o") == row["original_mode"],
            "original mode inventory",
        )
    require(
        sum(map(len, restored.values())) == v2["raw_source_bytes"] == 106266595,
        "complete recovered byte count",
    )
    require(
        len(index["parts"]) == 27
        and index["compressed_bytes"] == 11788972
        and index["archive_bytes"] == 106516480,
        "fixed archive dimensions",
    )
    freeze_path = NATIVE / "FREEZE.json"
    freeze_id = pinned(
        freeze_path, "9fef493ab90f11d29ca56fae62f7914c1c770868b5650bb5cf0449933fd683cd"
    )
    freeze = json.loads(freeze_path.read_bytes())
    require(
        len(freeze["files"]) == freeze["file_count"] == 185, "complete original freeze"
    )
    for name, row in freeze["files"].items():
        path = NATIVE / name
        require(
            identity(path) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
            and stat.S_IMODE(path.stat().st_mode) == row["mode"],
            "unchanged original freeze bytes and mode",
        )
    qualification = index["qualification"]
    require(
        qualification == v1["qualification_scope"] == v2["qualification_scope"],
        "native outcome was not changed by reader repair",
    )
    retention = qualification["archive_retention"]
    excluded = retention["excluded_original_console_files"]
    require(
        set(excluded) == {"job-128217534470.log", "job-128217534470.raw.json"},
        "explicit private console exclusions",
    )
    prefix = NATIVE.relative_to(ROOT).as_posix() + "/"
    for name, row in excluded.items():
        require(
            row == freeze["files"][name]
            and prefix + name not in restored
            and row["mode"] == 0o600,
            "private console remains excluded and unchanged",
        )
    retained = set(freeze["files"]) - set(excluded)
    require(
        {name[len(prefix) :] for name in restored if name.startswith(prefix)}
        == retained | {"FREEZE.json"},
        "183 retained frozen originals plus original freeze",
    )
    require(
        len(retained) == retention["retained_frozen_file_count"] == 183
        and sum(freeze["files"][name]["bytes"] for name in retained)
        == retention["retained_frozen_bytes"],
        "exact retained original count and bytes",
    )
    require(
        retention["original_freeze"] == freeze_id
        and restored[prefix + "FREEZE.json"] == freeze_path.read_bytes(),
        "original freeze retained byte for byte",
    )
    native_review_path = (
        ROOT / "round3_local_qualification/arm5188_root/ROOT_REVIEW.json"
    )
    native_review_id = pinned(
        native_review_path,
        "93ef445e2b8f7abb074592e79a08c8567203d987c03a83134b5f31562c710820",
    )
    native = json.loads(native_review_path.read_bytes())
    for key in ("run_id", "attempt", "job_id"):
        require(qualification[key] == native[key], "actual native run scope")
    require(
        qualification["overall_job"] == native["job_conclusion"] == "failure",
        "failed native job preserved",
    )
    require(
        qualification["native_source_commit"] == native["source_head"]
        and qualification["native_source_tree"] == native["source_tree"]
        and qualification["workflow_merge_commit"] == native["workflow_merge"],
        "native source identities",
    )
    for key in ("prepared_native_worktree_commit", "prepared_native_worktree_tree"):
        require(qualification[key] == native[key], "actual prepared source identity")
    for name, row in native["archives"].items():
        require(
            identity_bytes(restored[prefix + name])["sha256"] == row["sha256"]
            and len(restored[prefix + name]) == row["bytes"],
            "both original narrow artifact ZIPs retained",
        )
    business = qualification["business"]
    old_business = native["business_result"]
    for packet_key, root_key in (
        ("tests", "native_tests_run"),
        ("passed", "passed"),
        ("timed_out", "timed_out"),
        ("filtered", "filtered_out"),
        ("just_exit", "just_exit_code"),
        ("just_wall_seconds", "wall_seconds"),
        ("aggregate_child_cpu_seconds", "aggregate_child_cpu_seconds"),
        ("stderr", "stderr"),
        ("junit", "junit"),
    ):
        require(
            business[packet_key] == old_business[root_key],
            "native business outcome preserved",
        )
    spans = qualification["completed_read_and_validation_spans"]
    for packet_key, root_key in (
        ("completed_calls", "completed_calls"),
        ("completed_elapsed_ms", "elapsed_ms"),
        ("completed_bytes", "bytes"),
        ("phases", "phases"),
        ("pending_at_kill", "incomplete_span"),
    ):
        require(
            spans[packet_key] == native["timing"][root_key],
            "original timed spans preserved",
        )
    require(
        native["timing"]["starts"] == 37
        and spans["completed_calls"] == 36
        and not spans["post_ready_record_b_completed"]
        and not spans["post_ready_sync_a_reached"],
        "incomplete span and unreached later stage remain open",
    )
    require(
        retention["full_artifact_api_only"] == native["full_artifact_API_only"]
        and not retention["full_artifact_downloaded_or_reconstructed"],
        "large whole artifact remains API-only",
    )
    require(
        retention["complete_selected_view_files"]
        == native["declared_selected_files"]
        == 1447
        and retention["complete_selected_view_bytes"] == native["selected_bytes"]
        and retention["source_catalogue_entries"]
        == native["source_catalogue_entries"]
        == 84421,
        "original selected-view audit scope preserved",
    )
    require(
        native["actual_compilation"]["arm_sha2_artifact"]["features"]
        == ["default", "std"]
        and native["actual_compilation"]["arm_sha2_artifact"]["profile"]["opt_level"]
        == "0",
        "actual software backend compilation scope",
    )
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": [sys.executable, "-B", "-O", str(Path(__file__))],
        "interpreter_optimized": True,
        "publication_v1": v1_id,
        "publication_v2": v2_id,
        "index": index_id,
        "reader": reader_id,
        "published_reader_template": template_id,
        "reader_source_API": api_id,
        "initial_reader_format_failure": failure_id,
        "owner_reader_successor_review": owner_id,
        "original_freeze": freeze_id,
        "independent_native_audit": native_review_id,
        "canonical_reader_only_seal_changed": True,
        "v1_v2_full_AST_equal": True,
        "publication_only_one_reader_row_changed": True,
        "complete_recovered_files": len(restored),
        "complete_recovered_bytes": sum(map(len, restored.values())),
        "all_member_bytes_git_blobs_and_original_modes_equal": True,
        "original_frozen_inputs_unchanged": 185,
        "retained_frozen_originals": 183,
        "private_console_originals_excluded": 2,
        "native_job_conclusion": "failure",
        "native_business_passes": 0,
        "artifact_selected_view_files": 1447,
        "artifact_catalogue_entries": 84421,
        "restored_to_disk": False,
        "archive_sources_executed": False,
        "native_commands_or_scanner_reexecuted": False,
        "limits": [
            "This review verifies lossless packet recovery in memory; it does not claim an expanded disk restore.",
            "Original input modes are evidence only. The canonical restore program writes regular 0644 files.",
            "The 1.79 GB whole artifact retains API identity only. Both original narrow ZIPs and the complete selected view are retained.",
            "The original native job and business case remain failed. Timing measures original file reads plus validation, not isolated hash CPU time.",
            "The reader successor and root companions are outside the already frozen 236-member INDEX; no earlier evidence was rewritten.",
        ],
    }
    output = PROOF / "ROOT_REVIEW.json"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "root_review": identity(output),
                "files": len(restored),
                "bytes": sum(map(len, restored.values())),
                "native_result": "failure",
            }
        )
    )


if __name__ == "__main__":
    main()
