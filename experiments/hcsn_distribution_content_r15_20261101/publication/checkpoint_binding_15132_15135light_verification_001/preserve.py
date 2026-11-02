#!/usr/bin/env python3
"""Preserve exactly seven closed binding groups with the original packer CLI."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import traceback


EVIDENCE = Path(__file__).resolve().parent
PUBLICATION = EVIDENCE.parent
STUDY = PUBLICATION.parent
REPO = STUDY.parents[1]
RUN = STUDY / "results/formal_03"
LABEL = "checkpoint_binding_15132_15135light"
STAGING = PUBLICATION / (LABEL + "_metadata_001")
BUNDLE = PUBLICATION / "archives" / LABEL
RESTORE = PUBLICATION / (LABEL + "_fresh_restore_001")
PACKER = PUBLICATION / "pack_results.py"
PACKER_SHA256 = "c2314d3157259037a0880b5bcd02508e81085d1378054327a722c18906ca3dcd"
SOURCE_COMMIT = "5fac50a59a33b30e3110ea0334508d949de73984"
PRIOR_REMOTE_COMMIT = "42ef5081ef1ff233abe26468a8d26ccbfb9e61f9"
GROUPS = ["binding_s15132_light", "binding_s15132_value",
          "binding_s15133_light", "binding_s15133_value",
          "binding_s15134_light", "binding_s15134_value", "binding_s15135_light"]
FIT_FILES = {"DATA.json", "POSTERIOR_QUALIFICATION.json", "SUMMARY.json",
             "TRACE.json", "final.pt", "selected.pt"}
GATE_BYTES = 512 * 1024 * 1024
sources = []
operations = []


def require(value, message):
    if not value:
        raise RuntimeError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def sha(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def git_blob(path):
    result = hashlib.sha1(b"blob " + str(path.stat().st_size).encode() + b"\0")
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def gate(name):
    available = shutil.disk_usage(PUBLICATION).free
    result = dict(utc=utc(), operation=name, available_bytes=available,
                  minimum_bytes=GATE_BYTES, passed=available >= GATE_BYTES,
                  scope="Publication preservation only; training guards unchanged")
    write_json(EVIDENCE / (name + "_DISK_GATE.json"), result)
    require(result["passed"], f"Deferred: {name} has {available} available bytes")
    return result


def source_record(relative, kind):
    path = RUN / relative
    require(path.is_file() and not path.is_symlink(), f"Unsafe or missing source: {relative}")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), f"Not a regular source: {relative}")
    digest = sha(path)
    require(signature(before) == signature(path.stat()), f"Source changed while hashing: {relative}")
    result = dict(source_path=relative, archive_path="formal_03/" + relative, kind=kind,
                  bytes=before.st_size, sha256=digest, signature=signature(before))
    sources.append(result)
    return result


def stage(record):
    path = RUN / record["source_path"]
    raw = path.read_bytes()
    require(len(raw) == record["bytes"] and hashlib.sha256(raw).hexdigest() == record["sha256"],
            f"Source changed during staging: {path}")
    write(STAGING / record["source_path"], raw)


def same_bytes(left, right):
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            x, y = a.read(1024 * 1024), b.read(1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def invoke_cli(name, arguments):
    command = [sys.executable, "-B", str(PACKER), *arguments]
    completed = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
    write(EVIDENCE / (name + "_CLI.stdout.txt"), completed.stdout.encode())
    write(EVIDENCE / (name + "_CLI.stderr.txt"), completed.stderr.encode())
    item = dict(command=command, returncode=completed.returncode, utc=utc(),
                unmodified_original_cli=True, cleanup_interception=False)
    operations.append(item)
    require(completed.returncode == 0, f"{name} CLI failed: {completed.stderr}")
    result = json.loads(completed.stdout)
    item["receipt"] = result
    write_json(EVIDENCE / (name + "_RECEIPT.json"), result)
    return result


def main():
    require(sha(PACKER) == PACKER_SHA256, "Original packer SHA256 changed")
    for path in (STAGING, BUNDLE, RESTORE):
        require(not path.exists(), f"Refuse existing output: {path}")
    gate("before_preflight")
    roots, metadata, preflight = [], [], []
    for name in GROUPS:
        fit = RUN / "fits" / name
        require(fit.is_dir() and not fit.is_symlink(), f"Missing canonical fit: {name}")
        require({p.name for p in fit.iterdir()} == FIT_FILES, f"Unexpected fit inventory: {name}")
        task, seed_text, mode = name.split("_")
        seed = int(seed_text.removeprefix("s"))
        relative_job = f"attempts/train_resume_001/jobs/{name}"
        process_id = "train_resume_001/" + name
        receipt_relative = f"receipts/train/{name}.json"
        receipt = json.loads((RUN / receipt_relative).read_text())
        promotion = json.loads((RUN / relative_job / "PROMOTION.json").read_text())
        summary = json.loads((fit / "SUMMARY.json").read_text())
        require(receipt["exit_code"] == 0 and receipt["name"] == name and
                receipt["process_attempt_id"] == process_id and
                receipt["measurement_status"] == "complete_process_lifetime_wait4",
                f"Not a closed wait4 success: {name}")
        require((receipt["task"], receipt["seed"], receipt["train_mode"]) == (task, seed, mode),
                f"Receipt identity mismatch: {name}")
        require((summary["task"], summary["seed"], summary["train_mode"]) == (task, seed, mode) and
                summary["updates"] == 768 and summary["heldout_opened"] is False,
                f"Summary completion or identity mismatch: {name}")
        require(summary["checkpoint_path"] == f"fits/{name}/selected.pt", f"Checkpoint path mismatch: {name}")
        require(promotion["canonical_promotion"] is True and promotion["name"] == name and
                promotion["process_attempt_id"] == process_id and
                promotion["canonical_fit"] == f"fits/{name}" and
                promotion["canonical_receipt"] == receipt_relative, f"Promotion mismatch: {name}")
        require(sha(RUN / receipt_relative) == sha(RUN / relative_job / "RECEIPT.json") ==
                promotion["receipt_sha256"], f"Receipt copies differ: {name}")
        require({x["path"] for x in promotion["fit_files"]} == {f"fits/{name}/{f}" for f in FIT_FILES},
                f"Promotion inventory mismatch: {name}")
        fit_hashes = {}
        for row in promotion["fit_files"]:
            record = source_record(row["path"], "direct_closed_canonical_fit")
            require((record["bytes"], record["sha256"]) == (row["bytes"], row["sha256"]),
                    f"Promotion hash mismatch: {row['path']}")
            fit_hashes[Path(row["path"]).name] = record["sha256"]
        require(fit_hashes["selected.pt"] == summary["checkpoint_sha256"] and
                fit_hashes["final.pt"] == summary["final_checkpoint_sha256"],
                f"Selected/final hashes differ from SUMMARY: {name}")
        roots.append((f"formal_03/fits/{name}", fit))
        metadata.append(source_record(receipt_relative, "canonical_success_receipt"))
        for filename in ("LAUNCH_INTENT.json", "STARTED.json", "RECEIPT.json", "PROMOTION.json"):
            value = json.loads((RUN / relative_job / filename).read_text())
            require(value["process_attempt_id"] == process_id, f"Job identity mismatch: {name}/{filename}")
            if filename in ("LAUNCH_INTENT.json", "STARTED.json"):
                require(value["command"] == receipt["command"] and
                        value["work_root"] == relative_job + "/work", f"Started command mismatch: {name}")
            metadata.append(source_record(relative_job + "/" + filename, "closed_job_provenance"))
        for key, filename in (("stdout_path", "stdout.log"), ("stderr_path", "stderr.log")):
            require(receipt[key] == relative_job + "/" + filename, f"Actual log path mismatch: {name}")
            metadata.append(source_record(receipt[key], "actual_log_from_canonical_receipt"))
        preflight.append(dict(name=name,exit_code=0,measurement_status=receipt["measurement_status"],
                              updates=768,heldout_opened=False,process_attempt_id=process_id,
                              selected_sha256=fit_hashes["selected.pt"],final_sha256=fit_hashes["final.pt"],
                              all_six_promotion_file_hashes_match=True,canonical_and_attempt_receipts_identical=True))
    registration_relative = "attempts/train_resume_001/REGISTRATION.json"
    registration = json.loads((RUN / registration_relative).read_text())
    require(registration["attempt_id"] == "train_resume_001" and registration["source_files_unchanged"] is True,
            "Resume registration mismatch")
    metadata.append(source_record(registration_relative, "immutable_resume_registration"))
    preservation_relative = "attempts/train_02_enospc/PRESERVATION.json"
    require(registration["preserved_original"] == preservation_relative, "Original preservation pointer differs")
    preservation = RUN / preservation_relative
    pointer = dict(path="formal_03/" + preservation_relative, source_commit=SOURCE_COMMIT,
                   bytes=preservation.stat().st_size, sha256=sha(preservation), included_in_this_archive=False,
                   meaning="Original ENOSPC preservation pointer only; original partial fits are not copied here")
    gate("before_metadata_staging")
    for record in metadata:
        stage(record)
    note = STAGING / "checkpoint_note"
    write_json(note / "PRESERVATION_POINTER.json", pointer)
    write_json(note / "SOURCE_FILES.json", dict(schema="hcsn.r15.partial-preservation.sources.v1",
                                               source_commit=SOURCE_COMMIT, files=sources))
    design = dict(schema="hcsn.r15.partial-preservation.direct-roots.v1", source_commit=SOURCE_COMMIT,
                  prior_remote_commit_reported_by_coordinator=PRIOR_REMOTE_COMMIT,
                  groups=GROUPS, additional_groups=7, previously_preserved_groups=18,
                  combined_preserved_groups=25, planned_training_groups=32,
                  coverage_basis="Exactly these seven plus the previously published eighteen; not a live run count",
                  preflight=preflight, scientific_gain_claimed=False, confirmation_data_accessed=False,
                  checkpoint_or_npz_deserialized=False, active_fit_read=False,
                  canonical_fit_staging_copies=0, metadata_only_staging=True,
                  publication_gate_bytes=GATE_BYTES, chunk_bytes=49152, dictionary_bytes=16 * 1024**2,
                  training_guards_unchanged=True, pre_existing_evidence_deleted=False,
                  remote_writes_performed=False, original_cli_unchanged=True,
                  temporary_cleanup_policy="Normal cleanup of only the packer's newly created private temporary files",
                  helper_source_path=str(Path(__file__).relative_to(REPO)), helper_sha256=sha(Path(__file__)))
    write_json(note / "PACKING_DESIGN.json", design)
    write(note / "NOTE.md", (
        "# Partial preservation: seven completed binding groups\n\n"
        "This archive preserves exactly the seven groups in PACKING_DESIGN.json. Together with the "
        "previous eighteen published groups, backup coverage is 25 of 32 planned groups; this is not "
        "a current live completion count. No scientific benefit or confirmation result is claimed.\n\n"
        "Each canonical fit is a direct packer root. Only small receipts, actual logs named by those "
        "receipts, and immutable job/registration provenance are staged. The unchanged original "
        "pack_results.py CLI uses its normal cleanup of newly created private temporary files. "
        "No pre-existing evidence is deleted. Publication free space must be at least 512 MiB before "
        "packing and again before fresh restoration; training guards are unchanged.\n\n"
        "Canonical and job receipt copies describe one process lifetime and must not be charged twice. "
        "The original ENOSPC preservation is referenced by SHA256 and path only; missing original wait4 "
        "measurements remain unknown. No active fit or test data was read; checkpoints were handled as bytes.\n"
    ).encode())
    roots.extend([("formal_03/receipts/train", STAGING / "receipts/train"),
                  ("formal_03/attempts/train_resume_001", STAGING / "attempts/train_resume_001"),
                  (LABEL, note)])
    arguments = ["pack", "--output", str(BUNDLE), "--chunk-bytes", "49152", "--dict-mib", "16"]
    for prefix, directory in roots:
        arguments += ["--root", prefix + "=" + str(directory)]
    gate("before_pack")
    packed = invoke_cli("PACK", arguments)
    gate("before_restore")
    require(not RESTORE.exists(), "Fresh restore destination appeared")
    restored = invoke_cli("RESTORE", ["restore", "--bundle", str(BUNDLE), "--destination", str(RESTORE),
                                      "--manifest-sha256", packed["manifest_sha256"]])
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    expected = {}
    for prefix, directory in roots:
        for path in directory.rglob("*"):
            require(not path.is_symlink(), f"Unexpected source symlink: {path}")
            if path.is_file():
                relative = prefix + "/" + path.relative_to(directory).as_posix()
                require(relative not in expected, "Root collision")
                expected[relative] = path
    require(set(expected) == {r["path"] for r in manifest["members"]}, "Archive scope differs from explicit roots")
    restored_files = {p.relative_to(RESTORE).as_posix() for p in RESTORE.rglob("*") if p.is_file()}
    require(restored_files == set(expected), "Fresh restore has missing/extra members")
    checks = []
    for row in manifest["members"]:
        original, restored_file = expected[row["path"]], RESTORE / row["path"]
        require(same_bytes(original, restored_file) and sha(original) == row["sha256"] and
                original.stat().st_size == row["bytes"], f"Restored byte mismatch: {row['path']}")
        checks.append(dict(path=row["path"],bytes=row["bytes"],sha256=row["sha256"],byte_identical=True))
    for record in sources:
        original = RUN / record["source_path"]
        require(sha(original) == record["sha256"] and signature(original.stat()) == record["signature"],
                f"Canonical/provenance source changed: {record['source_path']}")
    require(sha(preservation) == pointer["sha256"] and sha(PACKER) == PACKER_SHA256,
            "Preservation pointer or original packer changed")
    execution = dict(schema="hcsn.r15.partial-preservation.execution-scope.v1", entrypoint="Original CLI via subprocess",
                     original_packer_path=str(PACKER.relative_to(REPO)),original_packer_sha256=PACKER_SHA256,
                     cleanup_interception=False,normal_fresh_temporary_cleanup=True,
                     pre_existing_evidence_deleted=False,canonical_fit_staging_copies=0,
                     active_fit_read=False,confirmation_data_accessed=False,remote_writes_performed=False,
                     helper_source_path=str(Path(__file__).relative_to(REPO)),helper_source_sha256=sha(Path(__file__)))
    write_json(EVIDENCE / "EXECUTION_SCOPE.json", execution)
    verification = dict(schema="hcsn.r15.partial-preservation.byte-verification.v1",passed=True,completed_at_utc=utc(),
                        source_commit=SOURCE_COMMIT,prior_remote_commit_reported_by_coordinator=PRIOR_REMOTE_COMMIT,
                        source_sha256=sha(Path(__file__)),helper_source_path=str(Path(__file__).relative_to(REPO)),
                        tool_sha256=PACKER_SHA256,bundle=str(BUNDLE),restore=str(RESTORE),staging=str(STAGING),
                        manifest_sha256=sha(BUNDLE / "manifest.json"),archive=manifest["archive"],
                        members=len(checks),parts=len(manifest["parts"]),source_bytes=manifest["total_member_bytes"],
                        staged_metadata_bytes=sum(p.stat().st_size for p in STAGING.rglob("*") if p.is_file()),
                        canonical_originals_verified_unchanged=len(sources),canonical_fit_staging_copies=0,
                        all_fresh_restored_bytes_identical=True,already_identical_members=restored["already_identical_members"],
                        available_bytes_after=shutil.disk_usage(PUBLICATION).free,
                        pre_existing_evidence_deleted=False,normal_own_temporary_cleanup=True,
                        remote_writes_performed=False,confirmation_data_accessed=False,active_fit_read=False,
                        checkpoint_or_npz_deserialized=False,groups=GROUPS,additional_groups=7,
                        prior_preserved_groups=18,combined_with_prior_preserved_groups=25,planned_training_groups=32,
                        coverage_is_fixed_backup_scope_not_live_completion=True,scientific_gain_claimed=False,
                        frozen_science_guard_and_report_sources_modified=False,preflight=preflight,files=checks,operations=operations)
    write_json(EVIDENCE / "VERIFICATION.json", verification)
    publication_files = sorted([p for p in BUNDLE.iterdir() if p.is_file()] +
                               [p for p in EVIDENCE.iterdir() if p.is_file()])
    filelist = dict(schema="hcsn.r15.partial-preservation.publication-files.v1",manifest_sha256=verification["manifest_sha256"],
                    bundle_file_count=sum(p.parent == BUNDLE for p in publication_files),
                    listed_file_count=len(publication_files),publish_this_index_in_addition=True,
                    index_path=str((EVIDENCE / "PUBLICATION_FILES.json").relative_to(REPO)),
                    helper_source_included=True,raw_staging_and_restore_copies_do_not_need_upload=True,
                    files=[dict(path=str(p.relative_to(REPO)),bytes=p.stat().st_size,sha256=sha(p),git_blob_sha1=git_blob(p))
                           for p in publication_files])
    write_json(EVIDENCE / "PUBLICATION_FILES.json", filelist)
    print(json.dumps({k:verification[k] for k in ("passed","manifest_sha256","archive","members","parts","source_bytes",
                     "staged_metadata_bytes","available_bytes_after","canonical_originals_verified_unchanged")} | dict(
                     publication_index=str(EVIDENCE / "PUBLICATION_FILES.json"),publication_index_sha256=sha(EVIDENCE / "PUBLICATION_FILES.json"),
                     total_publication_files=len(publication_files)+1,helper_sha256=sha(Path(__file__)),verification_sha256=sha(EVIDENCE / "VERIFICATION.json"))))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        try:
            write_json(EVIDENCE / "ERROR.json",dict(passed=False,error_type=type(error).__name__,error=str(error),
                       utc=utc(),traceback=traceback.format_exc(),operations=operations,partial_outputs_preserved=True,
                       normal_own_temporary_cleanup=True,pre_existing_evidence_deleted=False,remote_writes_performed=False))
        except OSError:
            pass
        raise
