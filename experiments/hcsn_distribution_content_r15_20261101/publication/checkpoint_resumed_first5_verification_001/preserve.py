#!/usr/bin/env python3
"""Bounded, direct-root preservation of five closed training groups only."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import traceback


PUBLICATION = Path(__file__).resolve().parent.parent
EVIDENCE = Path(__file__).resolve().parent
RUN = PUBLICATION.parent / "results/formal_03"
STAGING = PUBLICATION / "checkpoint_resumed_first5_metadata_001"
BUNDLE = PUBLICATION / "archives/checkpoint_resumed_first5"
RESTORE = PUBLICATION / "checkpoint_resumed_first5_fresh_restore_001"
SOURCE_COMMIT = "5fac50a59a33b30e3110ea0334508d949de73984"
GROUPS = ["recall_s15137_value", "recall_s15138_light", "recall_s15138_value",
          "binding_s15131_light", "binding_s15131_value"]
FIT_FILES = {"DATA.json", "POSTERIOR_QUALIFICATION.json", "SUMMARY.json",
             "TRACE.json", "final.pt", "selected.pt"}
GATE_BYTES = 512 * 1024 * 1024
cleanup_requests = []
operations = []
sources = []


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def write_json(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def source_record(relative, kind):
    path = RUN / relative
    require(path.is_file() and not path.is_symlink(), f"Unsafe or missing source: {relative}")
    info = path.stat()
    result = dict(source_path=relative, archive_path="formal_03/" + relative,
                  kind=kind, bytes=info.st_size, sha256=sha(path))
    sources.append(result)
    return result


def stage(relative, kind):
    record = source_record(relative, kind)
    data = (RUN / relative).read_bytes()
    require(len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"],
            f"Source changed during metadata staging: {relative}")
    write(STAGING / relative, data)


def gate(name):
    free = shutil.disk_usage(PUBLICATION).free
    value = dict(operation=name, available_bytes=free, minimum_bytes=GATE_BYTES,
                 passed=free >= GATE_BYTES, scope="publication preservation only; training guards unchanged")
    write_json(EVIDENCE / (name + "_DISK_GATE.json"), value)
    require(value["passed"], f"Deferred: {name} has only {free} available bytes")
    return value


def preserve_temporary(path, *args, **kwargs):
    # The existing packer normally removes private temporary directories. Keep
    # those directories in this no-deletion preservation run, including errors.
    cleanup_requests.append(dict(path=str(path), action="retained_without_deletion"))


def invoke(module, arguments):
    previous = sys.argv
    output = io.StringIO()
    sys.argv = [str(PUBLICATION / "pack_results.py"), *arguments]
    try:
        with contextlib.redirect_stdout(output):
            module.main()
    finally:
        sys.argv = previous
    result = json.loads(output.getvalue())
    operations.append(dict(argv=arguments, result=result))
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
    for path in (STAGING, BUNDLE, RESTORE):
        require(not path.exists(), f"Existing output refused; preserve prior attempt: {path}")
    gate("before_metadata_staging")
    roots = []
    for name in GROUPS:
        fit = RUN / "fits" / name
        require({p.name for p in fit.iterdir()} == FIT_FILES, f"Unexpected fit inventory: {name}")
        relative_job = f"attempts/train_resume_001/jobs/{name}"
        receipt_relative = f"receipts/train/{name}.json"
        receipt = json.loads((RUN / receipt_relative).read_text())
        promotion = json.loads((RUN / relative_job / "PROMOTION.json").read_text())
        process_id = "train_resume_001/" + name
        require(receipt["exit_code"] == 0 and receipt["name"] == name and
                receipt["process_attempt_id"] == process_id, f"Receipt is not a closed success: {name}")
        require(promotion["canonical_promotion"] is True and promotion["name"] == name and
                promotion["process_attempt_id"] == process_id and
                promotion["canonical_fit"] == f"fits/{name}" and
                promotion["canonical_receipt"] == receipt_relative, f"Promotion identity mismatch: {name}")
        require(sha(RUN / receipt_relative) == sha(RUN / relative_job / "RECEIPT.json") ==
                promotion["receipt_sha256"], f"Canonical / immutable receipt mismatch: {name}")
        expected = {f"fits/{name}/{filename}" for filename in FIT_FILES}
        require({row["path"] for row in promotion["fit_files"]} == expected,
                f"Promotion inventory mismatch: {name}")
        for row in promotion["fit_files"]:
            record = source_record(row["path"], "direct_canonical_fit")
            require((record["bytes"], record["sha256"]) == (row["bytes"], row["sha256"]),
                    f"Canonical file differs from promotion: {row['path']}")
        roots.append((f"formal_03/fits/{name}", fit))
        stage(receipt_relative, "canonical_success_receipt")
        for filename in ("LAUNCH_INTENT.json", "STARTED.json", "RECEIPT.json", "PROMOTION.json"):
            value = json.loads((RUN / relative_job / filename).read_text())
            require(value["process_attempt_id"] == process_id, f"Job provenance mismatch: {name}/{filename}")
            stage(f"{relative_job}/{filename}", "closed_resume_job_provenance")
        for key, filename in (("stdout_path", "stdout.log"), ("stderr_path", "stderr.log")):
            require(receipt[key] == f"{relative_job}/{filename}", f"Unexpected actual log path: {name}/{key}")
            stage(receipt[key], "actual_resume_job_log_from_receipt")
    stage("attempts/train_resume_001/REGISTRATION.json", "immutable_resume_registration")
    preservation = RUN / "attempts/train_02_enospc/PRESERVATION.json"
    pointer = dict(path="formal_03/attempts/train_02_enospc/PRESERVATION.json",
                   source_commit=SOURCE_COMMIT, bytes=preservation.stat().st_size,
                   sha256=sha(preservation), included_in_this_archive=False,
                   meaning="Pointer to original ENOSPC preservation; no original partial fit is copied here")
    note = STAGING / "checkpoint_note"
    write_json(note / "PRESERVATION_POINTER.json", pointer)
    write_json(note / "SOURCE_FILES.json", dict(schema="hcsn.r15.partial-preservation.sources.v1",
                                               source_commit=SOURCE_COMMIT, files=sources))
    design = dict(schema="hcsn.r15.partial-preservation.direct-roots.v1", source_commit=SOURCE_COMMIT,
                  groups=GROUPS, additional_groups=5, previously_preserved_groups=13,
                  combined_preserved_groups=18, planned_training_groups=32,
                  scientific_gain_claimed=False, confirmation_data_accessed=False,
                  checkpoint_or_npz_deserialized=False, active_fit_read=False,
                  canonical_fit_staging_copies=0, metadata_only_staging=True,
                  old_publication_gate_bytes=2 * 1024**3, publication_gate_bytes=GATE_BYTES,
                  reason_for_changed_resource_requirement="Five canonical fit roots read directly; one fresh restored inode per member, no second fit staging copy",
                  estimated_fresh_restore_bytes=32 * 1024**2, estimated_compressed_bytes=1024**2,
                  estimates_are_not_measurements=True, chunk_bytes=48 * 1024, dictionary_bytes=16 * 1024**2,
                  training_low_free_gib=1, training_high_free_gib=2, training_guards_unchanged=True,
                  deletions_performed=False, remote_writes_performed=False,
                  temporary_cleanup_policy="Retain packer temporary paths; successful restore links identical inodes without a second data copy")
    write_json(note / "PACKING_DESIGN.json", design)
    write(note / "NOTE.md", (
        "# Resumed training partial preservation: five completed groups\n\n"
        "This archive preserves exactly the five groups listed in PACKING_DESIGN.json. "
        "Together with the earlier 13 preserved groups, coverage is 18 of 32 planned training groups. "
        "This is an operational checkpoint, not a scientific gain or confirmation result.\n\n"
        "Canonical fit directories are direct packer roots. Only small JSON and the actual resumed job logs "
        "named by canonical receipts are staged. The pre-pack and pre-restore publication free-space gate "
        "is 512 MiB because there is no fit staging copy. The resumer's 1 / 2 GiB training guard is unchanged. "
        "No source is deleted, and the packer's private temporary directories are retained. Fresh restore "
        "uses hardlinks to its verified temporary extraction, so retaining that extraction does not duplicate fit data.\n\n"
        "Receipt copies in canonical and attempt locations document one process lifetime; they must not "
        "be charged twice. Original missing wait4 CPU remains unknown. The original PRESERVATION is referenced "
        "by path and SHA only. No active fit or test data was read; checkpoints were handled only as bytes.\n"
    ).encode())
    roots.extend([("formal_03/receipts/train", STAGING / "receipts/train"),
                  ("formal_03/attempts/train_resume_001", STAGING / "attempts/train_resume_001"),
                  ("checkpoint_resumed_first5", note)])
    spec = importlib.util.spec_from_file_location("closed_group_existing_packer", PUBLICATION / "pack_results.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_rmtree = shutil.rmtree
    shutil.rmtree = preserve_temporary
    try:
        pack_arguments = ["pack", "--output", str(BUNDLE), "--chunk-bytes", "49152", "--dict-mib", "16"]
        for prefix, path in roots:
            pack_arguments += ["--root", f"{prefix}={path}"]
        gate("before_pack")
        packed = invoke(module, pack_arguments)
        write_json(EVIDENCE / "PACK_RECEIPT.json", packed)
        gate("before_restore")
        require(not RESTORE.exists(), "Fresh restore destination appeared unexpectedly")
        restored = invoke(module, ["restore", "--bundle", str(BUNDLE), "--destination", str(RESTORE),
                                  "--manifest-sha256", packed["manifest_sha256"]])
        write_json(EVIDENCE / "RESTORE_RECEIPT.json", restored)
    finally:
        shutil.rmtree = original_rmtree
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    expected = {}
    for prefix, directory in roots:
        for path in directory.rglob("*"):
            if path.is_file():
                archive_path = prefix + "/" + path.relative_to(directory).as_posix()
                require(archive_path not in expected, "Noncolliding root requirement failed")
                expected[archive_path] = path
    require(set(expected) == {row["path"] for row in manifest["members"]}, "Archive scope differs from direct roots")
    checks = []
    for row in manifest["members"]:
        source, destination = expected[row["path"]], RESTORE / row["path"]
        require(same_bytes(source, destination), f"Fresh restored bytes differ: {row['path']}")
        require(sha(source) == row["sha256"] and source.stat().st_size == row["bytes"],
                f"Source changed after pack: {row['path']}")
        checks.append(dict(path=row["path"], bytes=row["bytes"], sha256=row["sha256"], byte_identical=True))
    for row in sources:
        original = RUN / row["source_path"]
        require(original.stat().st_size == row["bytes"] and sha(original) == row["sha256"],
                f"Original canonical/provenance content changed: {row['source_path']}")
    temporary = [Path(row["path"]) for row in cleanup_requests]
    require(len(temporary) == 1 and (temporary[0] / "members").is_dir(), "Unexpected retained restore staging")
    same_inodes = all((RESTORE / row["path"]).stat().st_ino ==
                     (temporary[0] / "members" / row["path"]).stat().st_ino for row in manifest["members"])
    require(same_inodes, "Retained restore staging must not be a second data copy")
    result = dict(schema="hcsn.r15.partial-preservation.byte-verification.v1", passed=True,
                  source_commit=SOURCE_COMMIT, source_sha256=sha(Path(__file__)),
                  tool_sha256=sha(PUBLICATION / "pack_results.py"),
                  bundle=str(BUNDLE), restore=str(RESTORE), staging=str(STAGING),
                  manifest_sha256=sha(BUNDLE / "manifest.json"), archive=manifest["archive"],
                  members=len(checks), parts=len(manifest["parts"]), source_bytes=manifest["total_member_bytes"],
                  staged_metadata_bytes=sum(p.stat().st_size for p in STAGING.rglob("*") if p.is_file()),
                  canonical_originals_verified_unchanged=len(sources), canonical_fit_staging_copies=0,
                  all_fresh_restored_bytes_identical=True, already_identical_members=restored["already_identical_members"],
                  retained_restore_members_share_inodes=same_inodes, cleanup_requests=cleanup_requests,
                  available_bytes_after=shutil.disk_usage(PUBLICATION).free,
                  deletions_performed=False, remote_writes_performed=False, confirmation_data_accessed=False,
                  active_fit_read=False, checkpoint_or_npz_deserialized=False,
                  groups=GROUPS, additional_groups=5, combined_with_prior_preserved_groups=18,
                  planned_training_groups=32, scientific_gain_claimed=False, files=checks, operations=operations)
    write_json(EVIDENCE / "VERIFICATION.json", result)
    print(json.dumps({key:result[key] for key in ("passed", "manifest_sha256", "archive", "members", "parts",
          "source_bytes", "staged_metadata_bytes", "available_bytes_after", "canonical_originals_verified_unchanged")}))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        write_json(EVIDENCE / "ERROR.json", dict(passed=False, error_type=type(error).__name__,
                   error=str(error), traceback=traceback.format_exc(), operations=operations,
                   cleanup_requests=cleanup_requests, partial_outputs_preserved=True,
                   deletions_performed=False, remote_writes_performed=False))
        raise
