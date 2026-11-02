#!/usr/bin/env python3
"""Preserve exactly seven closed training groups using the original packer CLI."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


EVIDENCE = Path(__file__).resolve().parent
PUBLICATION = EVIDENCE.parent
STUDY = PUBLICATION.parent
PROJECT = STUDY.parents[1]
RUN = STUDY / "results/formal_03"
WORK = PROJECT.parent / "checkpoint_training_final7_work_001"
METADATA = WORK / "metadata"
RESTORE = WORK / "fresh_restore"
INPUTS = EVIDENCE / "inputs"
BUNDLE = PUBLICATION / "archives/checkpoint_training_final7"
PACKER = PUBLICATION / "pack_results.py"
SOURCE_COMMIT = "10e8b6e11a259bf6db14f93c1eae5f1ad7b2eff1"
PRIOR_BACKUP_COMMIT = "8a3ff71b390d08bb8c885863c5e722ac2a272dff"
GROUPS = ["binding_s15135_value", "binding_s15136_light", "binding_s15136_value",
          "binding_s15137_light", "binding_s15137_value", "binding_s15138_light", "binding_s15138_value"]
FIT_FILES = {"DATA.json", "POSTERIOR_QUALIFICATION.json", "SUMMARY.json", "TRACE.json", "final.pt", "selected.pt"}
GATE_BYTES = 512 * 1024 * 1024
EXPECTED_PACKER_SHA = "c2314d3157259037a0880b5bcd02508e81085d1378054327a722c18906ca3dcd"
sources, operations = [], []


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())


def gate(name):
    free = shutil.disk_usage(PROJECT).free
    record = dict(operation=name, available_bytes=free, minimum_bytes=GATE_BYTES, passed=free >= GATE_BYTES,
                  scope="Publication pack/restore only; scientific and training guards unchanged")
    write_json(EVIDENCE / (name + "_DISK_GATE.json"), record)
    require(record["passed"], f"Deferred: {name} has {free} available bytes")


def source_record(relative, kind):
    path = RUN / relative
    require(path.is_file() and not path.is_symlink(), f"Unsafe or absent closed source: {relative}")
    record = dict(source_path=relative, archive_path="formal_03/" + relative,
                  kind=kind, bytes=path.stat().st_size, sha256=sha(path))
    sources.append(record)
    return record


def stage(relative, kind):
    record = source_record(relative, kind)
    data = (RUN / relative).read_bytes()
    require(len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"],
            f"Closed metadata changed while staging: {relative}")
    write(METADATA / relative, data)


def command(arguments, label):
    argv = [sys.executable, "-B", str(PACKER), *arguments]
    completed = subprocess.run(argv, cwd=PROJECT, capture_output=True)
    write(EVIDENCE / (label + ".stdout.log"), completed.stdout)
    write(EVIDENCE / (label + ".stderr.log"), completed.stderr)
    record = dict(argv=argv, exit_code=completed.returncode, original_packer_sha256=sha(PACKER),
                  invocation="Original packer CLI, without import-time patches or cleanup interception")
    operations.append(record)
    write_json(EVIDENCE / (label + "_COMMAND.json"), record)
    require(completed.returncode == 0, f"Original packer {label} failed; outputs retained")
    result = json.loads(completed.stdout)
    write_json(EVIDENCE / (label + "_RECEIPT.json"), result)
    return result


def same_bytes(left, right):
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            x, y = a.read(1024 * 1024), b.read(1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def main():
    for path in (WORK, INPUTS, BUNDLE):
        require(not path.exists(), f"Existing evidence refused: {path}")
    require(sha(PACKER) == EXPECTED_PACKER_SHA, "Original packer source identity changed")
    gate("before_metadata_staging")
    total = json.loads((RUN / "receipts/train/TOTAL.json").read_text())
    result = json.loads((RUN / "attempts/train_resume_001/RESULT.json").read_text())
    require(total["stage"] == "train" and total["jobs"] == 32 and total["failed"] == 0
            and total["accounting_kind"] == "resumed_consolidated" and total["original_launcher_completed"] is False,
            "Closed consolidated training TOTAL required")
    require(result["completed"] is True and result["complete_groups"] == result["expected_groups"] == 32
            and result["failed_jobs"] == 0 and result["attempt_id"] == "train_resume_001",
            "Closed successful resume RESULT required")
    roots = []
    for name in GROUPS:
        fit = RUN / "fits" / name
        require({p.name for p in fit.iterdir()} == FIT_FILES, f"Unexpected canonical fit inventory: {name}")
        receipt_relative = f"receipts/train/{name}.json"
        job_relative = f"attempts/train_resume_001/jobs/{name}"
        receipt = json.loads((RUN / receipt_relative).read_text())
        promotion = json.loads((RUN / job_relative / "PROMOTION.json").read_text())
        process_id = "train_resume_001/" + name
        require(receipt["exit_code"] == 0 and receipt["name"] == name and receipt["process_attempt_id"] == process_id,
                f"Canonical receipt is not the selected closed success: {name}")
        require(promotion["canonical_promotion"] is True and promotion["name"] == name
                and promotion["process_attempt_id"] == process_id and promotion["canonical_fit"] == f"fits/{name}"
                and promotion["canonical_receipt"] == receipt_relative, f"Promotion mismatch: {name}")
        require(sha(RUN / receipt_relative) == sha(RUN / job_relative / "RECEIPT.json") == promotion["receipt_sha256"],
                f"Canonical and immutable attempt receipt bytes differ: {name}")
        require({row["path"] for row in promotion["fit_files"]} == {f"fits/{name}/{x}" for x in FIT_FILES},
                f"Promotion inventory differs: {name}")
        for row in promotion["fit_files"]:
            record = source_record(row["path"], "direct_canonical_fit")
            require((record["bytes"], record["sha256"]) == (row["bytes"], row["sha256"]),
                    f"Canonical fit bytes differ from promotion: {row['path']}")
        roots.append((f"formal_03/fits/{name}", fit))
        stage(receipt_relative, "canonical_success_receipt")
        for filename in ("LAUNCH_INTENT.json", "STARTED.json", "RECEIPT.json", "PROMOTION.json"):
            value = json.loads((RUN / job_relative / filename).read_text())
            require(value["process_attempt_id"] == process_id, f"Closed job provenance mismatch: {name}/{filename}")
            stage(f"{job_relative}/{filename}", "closed_resume_job_provenance")
        for key, filename in (("stdout_path", "stdout.log"), ("stderr_path", "stderr.log")):
            require(receipt[key] == f"{job_relative}/{filename}", f"Unexpected actual log path: {name}/{key}")
            stage(receipt[key], "actual_resume_log_referenced_by_canonical_receipt")
    for relative, kind in (("receipts/train/TOTAL.json", "closed_training_consolidated_total"),
                           ("attempts/train_resume_001/REGISTRATION.json", "immutable_resume_registration"),
                           ("attempts/train_resume_001/RESULT.json", "closed_resume_result"),
                           ("attempts/train_resume_001/EVENTS.jsonl", "closed_resume_events")):
        stage(relative, kind)
    preservation = RUN / "attempts/train_02_enospc/PRESERVATION.json"
    pointer = dict(path="formal_03/attempts/train_02_enospc/PRESERVATION.json",
                   bytes=preservation.stat().st_size, sha256=sha(preservation), included_in_this_archive=False,
                   source_commit=SOURCE_COMMIT, meaning="Original ENOSPC preservation pointer; no original partial model is copied")
    write_json(INPUTS / "PRESERVATION_POINTER.json", pointer)
    write_json(INPUTS / "SOURCE_FILES.json", dict(schema="hcsn.r15.closed-training-preservation.sources.v1", files=sources))
    design = dict(schema="hcsn.r15.closed-training-preservation.design.v1", source_commit=SOURCE_COMMIT,
                  prior_25_backup_commit_provided_by_parent=PRIOR_BACKUP_COMMIT, groups=GROUPS,
                  additional_training_groups=7, prior_training_groups=25, combined_training_groups=32,
                  training_span_finished_utc=total["span_finished_utc"],
                  backup_generated_after_formal_confirmation_started=True,
                  confirmation_started_status_source="Parent task context; no confirmation outputs read by this preservation operation",
                  preservation_itself_is_not_preregistration=True, scientific_acceptance_claimed=False,
                  confirmation_data_or_outcome_accessed=False, active_fit_read=False,
                  checkpoint_or_npz_deserialized=False, canonical_fit_staging_copies=0,
                  bulk_metadata_staging=str(METADATA), fresh_restore=str(RESTORE),
                  bulk_staging_and_fresh_restore_outside_study=True, disk_gate_bytes=GATE_BYTES,
                  chunk_bytes=48 * 1024, dictionary_bytes=16 * 1024**2,
                  original_packer_sha256=EXPECTED_PACKER_SHA, invocation="Original packer CLI; no monkeypatch or cleanup interception",
                  pre_existing_evidence_deleted=False, remote_writes_performed=False,
                  cpu_accounting="Canonical and attempt receipts are aliases; TOTAL and resume RESULT are summaries, not additional process charges")
    write_json(INPUTS / "PACKING_DESIGN.json", design)
    write(INPUTS / "CHECKPOINT_TRAINING_FINAL7_NOTE.md", (
        "# Final seven closed training groups: preservation record\n\n"
        f"Source commit: `{SOURCE_COMMIT}`. Earlier 25-group backup commit supplied by the parent: `{PRIOR_BACKUP_COMMIT}`.\n\n"
        "This bundle covers exactly the seven binding groups listed in PACKING_DESIGN.json. With the earlier 25 groups, "
        "the training preservation packages cover all 32 planned groups. This operation performs no remote write; "
        "publication of this new bundle is a separate step. No scientific acceptance or gain is asserted.\n\n"
        f"The closed consolidated training TOTAL records completion at `{total['span_finished_utc']}`. "
        "Formal confirmation has already started at the time this backup is prepared. This backup handles only the "
        "previously fixed training bytes and closed training provenance; it does not read test data, evaluation outcomes "
        "or live fit outputs. This archive and its publication must not be described as preceding confirmation or as preregistration.\n\n"
        "The original packer CLI reads seven canonical fit roots directly, with 48 KiB shards and a 16 MiB XZ dictionary. "
        "Only small training metadata and actual logs named in successful receipts are staged. Bulk staging and fresh restore "
        "are outside the study directory. At least 512 MiB free space is checked immediately before pack and restore. "
        "No scientific, training, protocol, or guard settings change. The original packer's ordinary fresh-temporary cleanup is unmodified; "
        "no pre-existing evidence is deleted.\n\n"
        "Canonical and immutable attempt receipts document the same successful process, and must not be charged twice. "
        "The 32-job TOTAL and resume RESULT summarize already recorded workers and are not additional CPU addends. "
        "Original missing wait4 CPU remains unknown. Original ENOSPC evidence is referenced by its PRESERVATION path and SHA.\n"
    ).encode())
    roots.extend([("formal_03/receipts/train", METADATA / "receipts/train"),
                  ("formal_03/attempts/train_resume_001", METADATA / "attempts/train_resume_001"),
                  (INPUTS.relative_to(STUDY).as_posix(), INPUTS)])
    arguments = ["pack", "--output", str(BUNDLE), "--chunk-bytes", "49152", "--dict-mib", "16"]
    for prefix, path in roots:
        arguments += ["--root", f"{prefix}={path}"]
    gate("before_pack")
    packed = command(arguments, "PACK")
    gate("before_restore")
    require(not RESTORE.exists(), "Fresh restore directory already exists")
    restored = command(["restore", "--bundle", str(BUNDLE), "--destination", str(RESTORE),
                        "--manifest-sha256", packed["manifest_sha256"]], "RESTORE")
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    expected = {}
    for prefix, directory in roots:
        for path in directory.rglob("*"):
            if path.is_file():
                name = prefix + "/" + path.relative_to(directory).as_posix()
                require(name not in expected, "Archive prefix collision")
                expected[name] = path
    require(set(expected) == {row["path"] for row in manifest["members"]}, "Archive membership differs from allowed source roots")
    checks = []
    for row in manifest["members"]:
        original, fresh = expected[row["path"]], RESTORE / row["path"]
        require(same_bytes(original, fresh), f"Fresh restored bytes differ: {row['path']}")
        require(sha(original) == row["sha256"] and original.stat().st_size == row["bytes"],
                f"Source changed after pack: {row['path']}")
        checks.append(dict(**row, byte_identical=True))
    for row in sources:
        path = RUN / row["source_path"]
        require(sha(path) == row["sha256"] and path.stat().st_size == row["bytes"],
                f"Original closed training evidence changed: {row['source_path']}")
    require(sha(preservation) == pointer["sha256"], "Original preservation pointer changed")
    require(sha(PACKER) == EXPECTED_PACKER_SHA, "Packer changed during operation")
    verified = dict(schema="hcsn.r15.closed-training-preservation.byte-verification.v1", passed=True,
                    utc=datetime.now(timezone.utc).isoformat(), source_commit=SOURCE_COMMIT,
                    prior_backup_commit=PRIOR_BACKUP_COMMIT, helper_sha256=sha(Path(__file__)),
                    tool_sha256=sha(PACKER), operations=operations, bundle=str(BUNDLE),
                    metadata_staging=str(METADATA), fresh_restore=str(RESTORE),
                    manifest_sha256=sha(BUNDLE / "manifest.json"), archive=manifest["archive"],
                    members=len(checks), parts=len(manifest["parts"]), source_bytes=manifest["total_member_bytes"],
                    metadata_staging_bytes=sum(p.stat().st_size for p in METADATA.rglob("*") if p.is_file()),
                    canonical_originals_verified_unchanged=len(sources), canonical_fit_staging_copies=0,
                    all_fresh_restored_bytes_identical=True, already_identical_members=restored["already_identical_members"],
                    archive_note_path=INPUTS.relative_to(STUDY).as_posix() + "/CHECKPOINT_TRAINING_FINAL7_NOTE.md",
                    archive_note_matches_retained_study_relative_path=True,
                    groups=GROUPS, additional_training_groups=7, combined_training_groups=32,
                    training_span_finished_utc=total["span_finished_utc"], backup_generated_after_confirmation_started=True,
                    confirmation_data_or_outcome_accessed=False, active_fit_read=False,
                    checkpoint_or_npz_deserialized=False, scientific_acceptance_claimed=False,
                    pre_existing_evidence_deleted=False, remote_writes_performed=False,
                    available_bytes_after=shutil.disk_usage(PROJECT).free, files=checks)
    write_json(EVIDENCE / "VERIFICATION.json", verified)
    publication_records = []
    for directory in (BUNDLE, EVIDENCE):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                publication_records.append(dict(path=path.relative_to(PROJECT).as_posix(),
                                                bytes=path.stat().st_size, sha256=sha(path)))
    inventory_path = EVIDENCE / "PUBLICATION_FILES.json"
    write_json(inventory_path, dict(schema="hcsn.r15.closed-training-preservation.publication-files.v1",
               inventory_path=inventory_path.relative_to(PROJECT).as_posix(), files=publication_records,
               records_exclude_this_inventory_file=True, inventory_self_hash_reported_separately=True,
               publication_file_count_including_this_inventory=len(publication_records)+1,
               external_work_not_for_publication=str(WORK), source_commit=SOURCE_COMMIT,
               backup_generated_after_confirmation_started=True, remote_writes_performed=False))
    print(json.dumps(dict(passed=True, members=verified["members"], parts=verified["parts"],
          source_bytes=verified["source_bytes"], archive=verified["archive"],
          manifest_sha256=verified["manifest_sha256"], verification_sha256=sha(EVIDENCE / "VERIFICATION.json"),
          publication_inventory_sha256=sha(inventory_path), publication_files=len(publication_records)+1,
          metadata_staging_bytes=verified["metadata_staging_bytes"],
          canonical_originals_verified_unchanged=len(sources), available_bytes_after=verified["available_bytes_after"])))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        write_json(EVIDENCE / "ERROR.json", dict(passed=False, error_type=type(error).__name__, error=str(error),
                   traceback=traceback.format_exc(), operations=operations,
                   existing_outputs_preserved=True, pre_existing_evidence_deleted=False,
                   remote_writes_performed=False))
        raise
