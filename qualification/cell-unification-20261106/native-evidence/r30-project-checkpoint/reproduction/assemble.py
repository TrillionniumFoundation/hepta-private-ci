"""Pure local R30 archive verification and create-only formal assembly.

No Git/native/Rust processes. An exact archive pin must be supplied in a new
input JSON. Without --seal this verifies inputs and prints a small readback;
it does not create the formal group. Existing groups are never overwritten.
"""
from pathlib import Path, PurePosixPath
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile

ROOT = Path(__file__).resolve().parent.parent
PREP = Path(__file__).resolve().parent
FORMAL = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence/r30-project-checkpoint"
PREFIX = "native-source53-project-r30"
COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
JOB = "1a1b25b399f-fc05-7daa"
SOURCE = "native-candidate-r30-source.json"
SOURCE_PIN = {"bytes": 56747, "sha256": "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda", "git_blob": "eea9da2308a920486e1bbfd613745d390cde61de"}
LOCKS = {"codex-rs/Cargo.lock": "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c",
         "MODULE.bazel.lock": "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"}
BEDROCK = ("codex-app-server::all", "suite::v2::bedrock_setup::setup_bedrock_profile_and_environment")
NEW_LEAVES = {"codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
              "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs"}
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")


def require(value, message):
    if not value:
        raise RuntimeError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe(name):
    p = PurePosixPath(name)
    require(isinstance(name, str) and name and not p.is_absolute() and ".." not in p.parts
            and str(p) == name and "\\" not in name, "unsafe relative path: " + str(name))
    return p


def read_local(name, expected=None):
    path = ROOT / str(safe(name))
    require(path.is_file() and not path.is_symlink(), "missing/nonregular input: " + name)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
    require(all(getattr(before, key) == getattr(after, key) for key in fields), "input changed during read: " + name)
    actual = pin(raw)
    if expected is not None:
        require(all(actual[key] == expected[key] for key in ("bytes", "sha256", "git_blob")), "input pin mismatch: " + name)
    return raw


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def json_member(members, path):
    return json.loads(members[path])


def pointer(value, name, members):
    require(value == {"path": name, **pin(members["evidence/" + name])}, "original pointer mismatch: " + name)


def guard(value):
    require(value["pass"] is True and value["source_commit"] == COMMIT
            and value["actual_tree"] == value["expected_tree"] == TREE, "original source identity/guard mismatch")
    require(value["changed_file_count"] == 197 and value["native_head"] == HEAD
            and value["changed_path_set_matches"] is True, "original source path/HEAD mismatch")
    require(value["file_mismatches"] == value["unstaged_paths"] == value["untracked_paths"] == [], "source mismatches")
    require(value["cargo_lock_sha256"] == LOCKS["codex-rs/Cargo.lock"]
            and value["bazel_lock_sha256"] == LOCKS["MODULE.bazel.lock"], "original dual-lock guard mismatch")


def parse_log(raw):
    lines = []
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        lines.append((number, offset, ANSI.sub(b"", line).decode("utf-8", "replace").rstrip("\r\n")))
        offset += len(line)
    starts = [(n, o, s, re.match(r"^\s*Starting ([0-9]+) tests?\b", s)) for n, o, s in lines]
    starts = [r for r in starts if r[3]]
    summaries = [(n, o, s, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", s)) for n, o, s in lines]
    summaries = [r for r in summaries if r[3]]
    require(len(starts) == len(summaries) == 1, "exact Starting/Summary pair absent")
    start, summary = starts[0], summaries[0]
    require(start[0] < summary[0], "invalid nextest boundaries")
    rows, footer = [], []
    for number, offset, line in lines:
        match = re.match(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$", line)
        if match:
            row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
                   "line": number, "byte_offset": offset}
            if start[0] < number < summary[0]:
                rows.append(row)
            elif number > summary[0]:
                footer.append(row)
    identities = {(r["binary"], r["name"]) for r in rows}
    require(len(rows) == len(identities) == int(start[3][1]) == int(summary[3][2]) == 1345, "original full test population differs")
    counts = {label: sum(row["status"] == label for row in rows) for label in ("PASS", "FAIL", "TIMEOUT")}
    require(counts == {"PASS": 1345, "FAIL": 0, "TIMEOUT": 0}, "this known R30 gate is not all PASS")
    tail = summary[3][3]
    def count(label):
        match = re.search(r"\b([0-9]+) " + label + r"\b", tail)
        return int(match[1]) if match else 0
    require(count("passed") == 1345 and count("failed") == count("timed out") == 0
            and count("skipped") == 2 and not footer, "summary/skip/footer mismatch")
    require({row["binary"].split("::", 1)[0] for row in rows} == {"codex-app-server"}, "unexpected package")
    chosen = [r for r in rows if (r["binary"], r["name"]) == BEDROCK]
    require(len(chosen) == 1 and chosen[0]["status"] == "PASS" and chosen[0]["seconds"] == 0.352, "known Bedrock original row differs")
    return rows, {"starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
                  "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2]},
                  "unique_test_count": 1345, "counts": counts, "reported_skipped": 2,
                  "nextest_seconds": float(summary[3][1]), "bedrock_current_row": chosen[0],
                  "skip_identities_inferred": False, "footer_duplicates": 0}


def verify_archive(raw, expected, plan):
    require(pin(raw) == expected, "complete archive pin differs")
    members, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for item in tf.getmembers():
            safe(item.name)
            require(item.isfile() and not item.issym() and not item.islnk()
                    and item.name not in members, "unsafe/duplicate/nonregular archive member")
            data = tf.extractfile(item).read()
            require(len(data) == item.size, "member size differs")
            members[item.name], modes[item.name] = data, item.mode
    index_raw = members["INDEX.json"]
    index = json.loads(index_raw)
    require(index["schema"] == "hepta.source53-project-closed-index.v1", "unknown archive index schema")
    rows = index["files"]
    require(len({row["path"] for row in rows}) == len(rows) == len(members) - 1, "index duplicate/count mismatch")
    require({row["path"] for row in rows} == set(members) - {"INDEX.json"}, "index membership mismatch")
    for row in rows:
        safe(row["path"])
        require(pin(members[row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "index byte/hash mismatch")
        require(isinstance(row["mode"], int) and modes[row["path"]] == row["mode"], "index mode mismatch")
    require(index["source_commit"] == COMMIT and index["source_tree"] == TREE and index["source_count"] == 197, "index source mismatch")
    require(index["diagnostic_only"] is True and index["behavior_repair_claimed"] is False, "diagnostic classification mismatch")
    source_raw = members["input/" + SOURCE]
    require(pin(source_raw) == SOURCE_PIN, "registered manifest differs")
    source = json.loads(source_raw)
    require(source["source_commit"] == COMMIT and source["source_tree"] == TREE, "manifest identity differs")
    source_rows = source["changed_files"]
    files = {row["path"]: row for row in source_rows}
    require(len(files) == len(source_rows) == 197, "source count/duplicates")
    require({name for name in members if name.startswith("source/")} == {"source/" + name for name in files}, "archive source set differs")
    for name, row in files.items():
        member = "source/" + name
        require(pin(members[member]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "raw source differs: " + name)
        mode = "100755" if modes[member] & 0o111 else "100644"
        require(mode == row["mode"], "source Git mode mismatch: " + name)
    parent = json_member(members, "input/ancestor-manifests/native-candidate-r28-source.json")
    old = {r["path"]: r for r in parent["changed_files"]}
    require(parent["source_commit"] == "1e0910becc37383e6d17ecf861ea844fd07d8862"
            and parent["source_tree"] == "211f15baff19095e8c98bcea2b0ed99ca2270ade", "parent52 identity differs")
    require(len(old) == 195 and set(files) - set(old) == NEW_LEAVES
            and all(files[name] == row for name, row in old.items()), "old195/new2 scope mismatch")
    for name, sha in LOCKS.items():
        require(pin(members["locks/" + name])["sha256"] == sha, "raw dual lock differs")
    for row in plan["closed_original_pins"]:
        require(pin(members["evidence/" + row["name"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "closed local/native original differs")
    records = {name: json.loads(data) for name, data in members.items() if name.startswith("evidence/" + PREFIX) and name.endswith(".json")}
    def original(suffix):
        return records["evidence/" + PREFIX + suffix]
    terminal_raw = members["evidence/" + PREFIX + "-terminal-process-status.json"]
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == JOB and terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "original outer not natural0")
    for flag in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[flag] is True, "original terminal not durable/complete")
    for flag in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[flag] is False, "original terminal not natural")
    require(members["controller/terminal-process-status.json"] == terminal_raw, "controller terminal differs")
    launch = json_member(members, "controller/launch.json")
    job = launch["job"]
    require(job["id"] == JOB and job["idempotency_key"] == "cell-source53-project-r30-20261106-v1"
            and job["args"] == ["/home/alex/work/hepta-cell-unified-20261106-a/native-run-r30.py"]
            and job["executable"] == "/usr/bin/python3" and job["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a"
            and job["env_keys"] == [] and launch["launch"]["ok"] is True and launch["reused"] is False,
            "original direct-file launch mismatch")
    controller_reads = [json.loads(data) for name, data in members.items() if re.fullmatch(r"controller/read-[0-9]+\.json", name)]
    require(controller_reads, "controller ranges missing")
    for stream in ("stdout", "stderr"):
        chunks = []
        for value in controller_reads:
            require(value["job_id"] == JOB, "controller range job mismatch")
            part = value[stream]
            data = bytes.fromhex(part["bytes_hex"])
            require(data == part["text"].encode() and len(data) == part["next_offset"] - part["offset"], "controller hex/text/range mismatch")
            chunks.append((part["offset"], data))
        joined = b""
        for offset, data in sorted(chunks, key=lambda item: item[0]):
            if not data:
                require(offset <= len(joined), "empty range outside known output")
            else:
                require(offset == len(joined), "controller gap/duplicate")
                joined += data
        require(joined == members["controller/original-" + stream + ".txt"], "controller reconstruction differs")
        require(terminal["log_bytes"][stream]["seen"] == terminal["log_bytes"][stream]["stored"] == len(joined), "controller terminal totals mismatch")
    phase_readback = []
    previous_end = None
    expected_commands = {
        "strict": ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"]}
    for phase in ("strict", "tests"):
        stem = PREFIX + "-" + phase
        r = json_member(members, "evidence/" + stem + "-raw-process-result.json")
        receipt = json_member(members, "evidence/" + stem + "-receipt.json")
        for value in (r, receipt):
            require(value["source_commit"] == COMMIT and value["source_tree"] == TREE
                    and value["phase"] == phase and value["exit_code"] == 0
                    and value["command"] == expected_commands[phase], "original phase identity/command/return mismatch")
        for key in ("phase", "source_commit", "source_tree", "command", "cwd", "start_unix", "end_unix", "exit_code"):
            require(r[key] == receipt[key], "original phase/raw fields differ")
        require(receipt["effective_exit_code"] == 0 and receipt["phase_pass"] is True
                and receipt["issues"] == [] and receipt["source_guards_pass"] is True, "phase postprocessing failed")
        require(previous_end is None or r["start_unix"] >= previous_end, "phase ordering differs")
        previous_end = r["end_unix"]
        require(terminal["at_unix_ms"] / 1000 >= r["end_unix"], "terminal predates phase")
        require(abs(receipt["elapsed_seconds"] - (r["end_unix"] - r["start_unix"])) < 1e-6, "elapsed accounting differs")
        pointer(receipt["raw_process_result"], stem + "-raw-process-result.json", members)
        pointer(receipt["source_postguard"], stem + "-source-post-verification.json", members)
        for side in ("pre", "post"):
            value = json_member(members, "evidence/" + stem + "-source-" + side + "-verification.json")
            guard(value)
            if side == "post":
                require(value["phase"] == phase and value["gate_exit_code"] == 0, "postguard phase mismatch")
        log_raw = members["evidence/" + stem + ".log"]
        resource_raw = members["evidence/" + stem + "-resources.txt"]
        require(receipt["log_sha256"] == pin(log_raw)["sha256"] and receipt["resources_sha256"] == pin(resource_raw)["sha256"], "log/resource pointer mismatch")
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M) == [b"0"], "resource original exit mismatch")
        phase_readback.append({"phase": phase, "raw_exit": 0, "effective_exit": 0,
                               "elapsed_seconds": receipt["elapsed_seconds"], "command": receipt["command"],
                               "log": pin(log_raw), "resources": pin(resource_raw), "source_guard_pass": True})
    for suffix in ("-source-pre-verification.json", "-source-final-verification.json"):
        guard(original(suffix))
    parsed, log_readback = parse_log(members["evidence/" + PREFIX + "-tests.log"])
    require(parsed == original("-tests-test-results.json"), "entire parsed execution rows differ")
    baseline = json_member(members, "input/baseline/source53-app-server-r29-baseline.json")
    require({(r["binary"], r["name"]) for r in parsed} == {(r["binary"], r["name"]) for r in baseline["test_ids"]}, "exact1345 baseline differs")
    review = original("-tests-result-review.json")
    require(review["pass"] is True and review["unique_test_count"] == 1345
            and review["counts"] == log_readback["counts"] and review["reported_skipped"] == 2,
            "original parsed readback differs")
    finish = original("-complete.json")
    require(finish["source_commit"] == COMMIT and finish["source_tree"] == TREE
            and finish["strict_exit"] == finish["tests_exit"] == 0 and finish["required_old_ids"] == 1345
            and finish["all_old_ids_observed_pass"] is True and finish["diagnostic_only"] is True
            and finish["behavior_repair_claimed"] is False and finish["original_r29_failure_relabelled_as_pass"] is False
            and finish["whole_workspace_qualification"] == "PENDING_SEPARATE_ORIGINAL_GATE", "original complete meaning differs")
    return members, modes, {
        "schema": "hepta.source53-r30-formal-independent-readback.v1",
        "scope": "Independent local raw archive/INDEX/source/closure/controller/log verification; no runner execution.",
        "archive": expected, "archive_regular_members": len(members), "index_rows": len(rows),
        "original_index": pin(index_raw), "every_member_bytes_sha_gitblob_mode_verified": True,
        "source_commit": COMMIT, "source_tree": TREE, "source_manifest": pin(source_raw),
        "source_count": 197, "source_rust_count": sum(name.endswith(".rs") for name in files),
        "raw_source_manifest_matches": True, "old195_rows_unchanged": True,
        "full_git_tree_rebuilt_by_this_assembler": False,
        "git_identity_basis": "Actual registered manifest plus original/native export guards; all 197 archived raw blobs/modes independently matched.",
        "original_gate_job": JOB, "original_outer_exit": 0, "phase_results": phase_readback,
        "full_original_log_readback": log_readback,
        "original_1345_ids_all_match_baseline": True, "complete_controller_output_reconstructed": True,
        "historical_comparison": {"source52_r29_status": "FAIL", "source52_r29_seconds": 10.643,
                                  "source53_r30_status": "PASS", "source53_r30_seconds": 0.352,
                                  "same_test_id": list(BEDROCK), "causal_behavior_repair_proved": False},
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "r31_results_included": False, "workspace_qualification": "PENDING_SEPARATE_ORIGINAL_GATE",
        "science": "HOLD", "authority": "DENY_ALL", "native_or_rust_executed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    input_raw = read_local(args.inputs)
    inputs = json.loads(input_raw)
    require(inputs["schema"] == "hepta.source53-r30-final-assembly-inputs.v1", "unknown final input schema")
    require(isinstance(inputs["archive"], dict), "actual archive is not bound")
    plan_raw = (PREP / "PREPARATION-PLAN.json").read_bytes()
    plan = json.loads(plan_raw)
    require(pin(plan_raw) == inputs["preparation_plan"], "frozen static plan differs")
    archive_spec = inputs["archive"]
    archive_raw = read_local(archive_spec["path"], {key: archive_spec[key] for key in ("bytes", "sha256", "git_blob")})
    members, modes, readback = verify_archive(archive_raw, pin(archive_raw), plan)
    contents, mappings = {}, []
    def put(name, raw):
        safe(name)
        require(name not in contents, "destination collision: " + name)
        contents[name] = raw
    def copy(name, raw, origin):
        destination, data, encoding = name, raw, "identity"
        if len(raw) >= 65536 and not name.endswith("INDEX.json"):
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                data = gzip.compress(raw, mtime=0)
                require(gzip.decompress(data) == raw, "gzip byte roundtrip failed")
                destination += ".gz"
                encoding = "gzip-mtime0"
        put(destination, data)
        mappings.append({"source": origin, "source_pin": pin(raw), "destination": destination,
                         "destination_pin": pin(data), "encoding": encoding,
                         "original_bytes_restorable_exactly": True})
        return destination
    put("archive/checkpoint-r30-closed.tar.gz", archive_raw)
    archive_member_map = []
    for name, raw in sorted(members.items()):
        row = {"member": name, **pin(raw), "transport_mode": modes[name]}
        if name.startswith("source/"):
            row.update(storage="full_archive_member_only", archive="archive/checkpoint-r30-closed.tar.gz")
        else:
            destination = "archive/INDEX.json" if name == "INDEX.json" else "original/" + name
            row.update(storage="individual_copy_and_full_archive", destination=copy(destination, raw, {"archive_member": name}))
        archive_member_map.append(row)
    static_entries = plan["static_inputs"] + inputs.get("extra_inputs", [])
    for entry in static_entries:
        require("r31" not in entry["destination"].lower(), "R31 result/preparation outside this group")
        raw = read_local(entry["source"], entry)
        copy(entry["destination"], raw, {"workspace_path": entry["source"]})
    export_terminal = read_local("native-validation-results/r30-export-closed/controller/terminal-original.json")
    exporter = json.loads(export_terminal)
    require(exporter["state"] == "succeeded" and exporter["exit_code"] == 0
            and exporter["job_id"] == "1a1b278cf52-fc05-7e29", "actual exporter not naturally complete")
    require(exporter["timed_out"] is exporter["cancelled"] is exporter["automatic_retry"] is False
            and exporter["output_durable"] is exporter["output_complete"] is True, "export terminal incomplete")
    result_raw = read_local("native-validation-results/r30-export-closed/evidence/checkpoint-r30-export.json")
    exported = json.loads(result_raw)
    require(all(exported[key] == archive_spec[key] for key in ("bytes", "sha256", "git_blob")), "actual export archive proof mismatch")
    require(exported["members"] == len(members) and exported["actual_original_count"] == 19
            and exported["archive_export_complete"] is True and exported["original_outer_exit"] == 0,
            "actual export counts/results mismatch")
    readback["export_terminal"] = pin(export_terminal)
    readback["export_result"] = pin(result_raw)
    readback["exporter_success_is_not_gate_result"] = True
    readback["static_attachment_sources_reverified"] = len(static_entries)
    require(not FORMAL.exists(), "formal directory exists; never overwrite a frozen group")
    if not args.seal:
        print(json.dumps({"classification": "VERIFIED_NOT_ASSEMBLED", "archive": pin(archive_raw),
                          "members": len(members), "source_count": 197, "static_inputs": len(static_entries)}))
        return
    put("INDEPENDENT-READBACK.json", encode(readback))
    put("ORIGINAL-MEMBER-MAPPING.json", encode({"schema": "hepta.r30-original-member-mapping.v1",
        "archive": pin(archive_raw), "members": archive_member_map,
        "full197_source_in_archive": True, "source_files_reduplicated_individually": False}))
    put("SOURCE-DESTINATION-MAPPING.json", encode({"schema": "hepta.r30-source-destination-mapping.v1", "files": mappings}))
    put("reproduction/assemble.py", Path(__file__).read_bytes())
    put("reproduction/prepare_plan.py", (PREP / "prepare_plan.py").read_bytes())
    put("reproduction/PREPARATION-PLAN.json", plan_raw)
    put("reproduction/FINAL-INPUTS.json", input_raw)
    readme = """# R30 app-server project checkpoint — source53 diagnostic build

The original app-server strict gate and full project test gate completed naturally with return code 0 on source53. The complete original log contains 1,345 unique PASS rows, zero FAIL/TIMEOUT, and two reported skips. This checkpoint does not contain R31 results and does not establish whole-workspace or scientific qualification.

The source is commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b`, tree `440d4a8e09af4009e4d9ea067388826308da8803`, with 197 changed paths. All archived source bytes, Git blobs and modes match the registered manifest and original source guards. The complete raw source remains in the preserved archive; it is not duplicated as 197 separate report files. This assembler does not claim a new offline full-Git-tree reconstruction.

Strict command wall time is 189.01348495483398 seconds. The full test command wall time is 972.5199980735779 seconds; nextest's Summary time is 404.442 seconds. These are different measures and are not added together.

`setup_bedrock_profile_and_environment` is PASS at 0.352 seconds in this execution. The same test's original source52 R29 result remains FAIL at 10.643 seconds. Source53 adds diagnostic stage logging and a narrow fixture child log filter only. This subsequent PASS does not establish the cause of the original deadline or claim a behavior repair. The earlier failure excerpt is retained separately under `historical-comparison/`.

The archive, original INDEX, original two-phase receipts/raw results/resources/full logs/test rows, terminal and complete controller output are preserved. Root and differentiation independent reviews, exact project binding/authorization, exporter preparation/binding/authorization and its separate natural terminal are included. Export success is a custody result, not an additional test pass. Source50's lock update remains historical unchanged-dependency provenance; no new lock run is claimed here.

`ORIGINAL-MEMBER-MAPPING.json` identifies every archive member. `SOURCE-DESTINATION-MAPPING.json` records original bytes separately from report-copy bytes. Large UTF-8 artifacts use lossless gzip with an exact roundtrip; the original archive always retains their original bytes. `INDEPENDENT-READBACK.json` documents local verification and its limits. `ATTACHMENT-MANIFEST.json` is an integrity inventory, not a qualification decision.

Scientific studies remain **HOLD** and authority remains **DENY_ALL**. No Rust, runner, formatter, network probe, source edit or publication was performed by the local assembler.
"""
    # Bind the prose duration to the actual original instead of silently guessing precision.
    test_seconds = readback["phase_results"][1]["elapsed_seconds"]
    readme = readme.replace("972.5199980735779", str(test_seconds))
    require(readback["full_original_log_readback"]["nextest_seconds"] == 404.442, "known nextest duration differs")
    put("README.md", readme.encode())
    closure = {"schema": "hepta.r30-project-checkpoint-closure.v1", "classification": "FROZEN_ORIGINAL_PROJECT_GATE_EVIDENCE",
        "source_commit": COMMIT, "source_tree": TREE, "source_count": 197, "diagnostic_only": True,
        "behavior_repair_claimed": False, "original_gate_job": JOB, "strict_exit": 0, "tests_exit": 0,
        "original_outer_exit": 0, "unique_test_count": 1345, "counts": {"PASS": 1345, "FAIL": 0, "TIMEOUT": 0},
        "reported_skipped": 2, "phase_wall_seconds": {p["phase"]: p["elapsed_seconds"] for p in readback["phase_results"]},
        "nextest_seconds": 404.442, "historical_r29_failed_result_preserved": True,
        "root_cause_resolved_claimed": False, "r31_results_included": False,
        "workspace_qualification": "PENDING_SEPARATE_ORIGINAL_GATE", "science": "HOLD", "authority": "DENY_ALL",
        "archive": {"path": "archive/checkpoint-r30-closed.tar.gz", **pin(archive_raw)},
        "independent_readback": {"path": "INDEPENDENT-READBACK.json", **pin(contents["INDEPENDENT-READBACK.json"])},
        "formal_file_count_including_attachment_manifest": len(contents) + 2,
        "originals_modified": False, "source_or_native_execution_by_assembler": False}
    put("CLOSURE.json", encode(closure))
    attachment = {"schema": "hepta.r30-project-checkpoint-attachment-manifest.v1", "files": [
        {"path": name, **pin(raw), "git_mode": "100644"} for name, raw in sorted(contents.items())],
        "listed_file_count": len(contents), "listed_bytes": sum(map(len, contents.values())),
        "manifest_itself_excluded": True, "integrity_inventory_not_qualification": True}
    put("ATTACHMENT-MANIFEST.json", encode(attachment))
    require(len(contents) == closure["formal_file_count_including_attachment_manifest"], "final count mismatch")
    FORMAL.mkdir(parents=True, exist_ok=False)
    for name, raw in sorted(contents.items()):
        path = FORMAL / str(safe(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
        os.chmod(path, 0o644)
        require(path.read_bytes() == raw, "written formal bytes differ")
    binaries = []
    for name, raw in sorted(contents.items()):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            binaries.append({"path": str((FORMAL / name).relative_to(ROOT / "hepta-cell")), **pin(raw)})
    binary_raw = encode({"schema": "hepta.r30-formal-binary-plan.v1", "files": binaries,
                         "uploaded_by_this_assembler": False, "ledger_modified": False})
    with (PREP / "BINARY-PLAN.json").open("xb") as stream:
        stream.write(binary_raw)
    seal = {"schema": "hepta.r30-formal-assembly-handoff.v1", "formal_directory": str(FORMAL.relative_to(ROOT)),
            "file_count": len(contents), "bytes": sum(map(len, contents.values())),
            "attachment_manifest": pin(contents["ATTACHMENT-MANIFEST.json"]),
            "closure": pin(contents["CLOSURE.json"]), "independent_readback": pin(contents["INDEPENDENT-READBACK.json"]),
            "binary_plan": pin(binary_raw), "binary_path_count": len(binaries),
            "canonical_reports_index_ledger_modified": False, "r31_results_included": False}
    seal_raw = encode(seal)
    with (PREP / "HANDOFF-MANIFEST.json").open("xb") as stream:
        stream.write(seal_raw)
    print(json.dumps(seal))


if __name__ == "__main__":
    main()
