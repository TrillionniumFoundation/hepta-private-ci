"""Cold-verify completed worker archives without reading mutable fit contents.

This is an operational packaging helper, not a scientific validity or CPU gate.
A failed scientific arm remains in a normally completed worker's archive.  No
network operation is performed; the upload index contains local Git blob IDs.
Confirmation requires the published seal and retains both full derived audit
tables alongside every original record.  No deferred-table mode is provided.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from ..archive import pack, restore


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_if_complete(path):
    try:
        return json.loads(path.read_bytes())
    except (FileNotFoundError, json.JSONDecodeError):
        # The controller may currently be writing this small, exclusive receipt.
        return None


def inventory(directory):
    rows = []
    for path in sorted(directory.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"archive source contains symlink: {path}")
        if path.is_file():
            raw = path.read_bytes()
            rows.append(dict(path=path.relative_to(directory).as_posix(),
                             bytes=len(raw), sha256=digest(raw)))
    return rows


def write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".temporary")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def cold_pack(root, source, name, destination, binding):
    before = inventory(source)
    folder = root / "archives" / name
    reused = folder.exists()
    manifest = read_if_complete(folder / "MANIFEST.json") if reused else pack(source, folder)
    if manifest is None or manifest["files"] != before:
        raise ValueError(f"archive source inventory differs: {name}")
    with tempfile.TemporaryDirectory(prefix="digital-feedback-live-cold-", dir="/tmp") as scratch:
        restored = Path(scratch) / "restored"
        verification = restore(folder, restored)
        if inventory(restored) != before:
            raise ValueError(f"cold restore differs from original: {name}")
    if inventory(source) != before:
        raise ValueError(f"source changed during packaging: {name}")
    return dict(name=name, destination=destination, binding=binding,
                files=len(before), uncompressed_bytes=sum(row["bytes"] for row in before),
                parts=len(manifest["parts"]), compressed_bytes=manifest["archive_bytes"],
                archive_sha256=manifest["archive_sha256"],
                manifest_sha256=digest((folder / "MANIFEST.json").read_bytes()),
                recovered_existing_archive=reused, verification=verification,
                packaged_utc=datetime.now(timezone.utc).isoformat())


def scan(root, group, include_control, seal_path=None):
    start = time.process_time()
    repository = root.parents[2]
    source = root / group
    launch = json.loads((source / "LAUNCH.json").read_bytes())
    frozen = json.loads((root / "SOURCE_FREEZE.json").read_bytes())
    if launch["source_sha256"] != frozen["source_sha256"]:
        raise ValueError("launch and current source freeze differ; restore the matching workspace")
    for path, sha in frozen["source_sha256"].items():
        if digest((repository / path).read_bytes()) != sha:
            raise ValueError(f"frozen source changed: {path}")
    fits = launch["fits"]
    stage = launch["stage"]
    if stage not in ("train", "confirm") or fits != frozen["fits"]:
        raise ValueError("expected exactly the registered formal fits and stage")
    seal, seal_sha256 = None, None
    if stage == "confirm":
        if seal_path is None:
            raise ValueError("confirmation packaging requires --seal")
        seal_bytes = Path(seal_path).read_bytes()
        seal, seal_sha256 = json.loads(seal_bytes), digest(seal_bytes)
        if (seal.get("schema") != "digital-feedback-sealed-models-v1"
                or seal.get("source_sha256") != frozen["source_sha256"]
                or seal.get("fits") != fits
                or seal.get("protocol") != json.loads((root / "protocol.json").read_bytes())):
            raise ValueError("confirmation seal differs from frozen source/protocol/fits")
        if any(seal.get("cpu_matching", {}).get(name) is not True
               for name in ("all_actual_cpu_matching", "all_training_valid")):
            raise ValueError("confirmation seal lacks registered training qualification")
        commit = seal.get("published_models_commit", "")
        if not isinstance(commit, str) or len(commit) != 40 or set(commit) - set("0123456789abcdef"):
            raise ValueError("confirmation requires a complete published model commit")
    elif seal_path is not None:
        raise ValueError("--seal is only used for confirmation packaging")
    evidence_path = root / "evidence" / f"PACK_{group}_live.json"
    old = read_if_complete(evidence_path)
    if old is not None and (old["group"] != group or old["registered_fits"] != fits):
        raise ValueError("live packaging evidence belongs to another registration")
    if old is not None and (old.get("stage", "train") != stage or old.get("seal_sha256") != seal_sha256):
        raise ValueError("previously packaged stage or seal differs")
    entries = [] if old is None else old["entries"]
    by_name = {entry["name"]: entry for entry in entries}
    states, new_entries = [], []
    for fit in fits:
        directory = source / f"fit_{fit}"
        receipt_path = source / "process_receipts" / f"fit_{fit}.json"
        receipt = read_if_complete(receipt_path)
        finished = read_if_complete(directory / "FINISHED.json")
        state = dict(fit=fit, process_receipt_present=receipt is not None,
                     finished_present=finished is not None)
        if receipt is None or finished is None:
            state["status"] = "not_eligible_yet"
        elif (type(receipt.get("returncode")) is not int or receipt["returncode"] != 0
              or receipt.get("spawned") is not True or receipt.get("cancelled") is not False
              or (directory / "FAILED.json").exists()):
            state["status"] = "completed_process_not_successful"
        else:
            started_path = directory / "STARTED.json"
            started = json.loads(started_path.read_bytes())
            for record in (receipt, finished, started):
                if record["fit"] != fit:
                    raise ValueError(f"worker identity differs: {fit}")
            if stage == "train":
                for record in (started, finished):
                    if record["source_sha256"] != frozen["source_sha256"]:
                        raise ValueError(f"worker source identity differs: {fit}")
                if started["stage"] != "formal_fit" or started["confirmation_generated"] is not False:
                    raise ValueError(f"not an untouched formal training worker: {fit}")
            else:
                if (started.get("seal_sha256") != seal_sha256
                        or started.get("published_models_commit") != seal["published_models_commit"]
                        or started.get("confirmation_preexisting") is not False):
                    raise ValueError(f"confirmation worker seal/publication binding differs: {fit}")
                required = ["summary.json"] + [split + suffix for split in ("iid", "ood")
                    for suffix in ("_cohort.json", "_episodes.json.gz", "_audits.json.gz",
                                   "_quality.json", "_runtime.json", "_probe.json.gz", "_decoder.json")]
                missing = [name for name in required if not (directory / name).is_file()]
                if missing or (directory / "DERIVED_DIAGNOSTICS.json").exists():
                    raise ValueError(f"complete original and derived confirmation files required: {fit}: {missing}")
            binding = dict(fit=fit, process_receipt_sha256=digest(receipt_path.read_bytes()),
                           started_sha256=digest(started_path.read_bytes()),
                           finished_sha256=digest((directory / "FINISHED.json").read_bytes()))
            if stage == "confirm":
                binding.update(seal_sha256=seal_sha256, published_models_commit=seal["published_models_commit"],
                               full_derived_audits=True)
            name = f"{group}_fit_{fit}"
            if name in by_name:
                if by_name[name]["binding"] != binding:
                    raise ValueError(f"previously packed worker receipt changed: {fit}")
            else:
                entry = cold_pack(root, directory, name, f"{group}/fit_{fit}", binding)
                by_name[name] = entry
                entries.append(entry)
                new_entries.append(name)
                print(json.dumps(dict(packed=name, files=entry["files"],
                                      parts=entry["parts"], cold_verified=True)), flush=True)
            state["status"] = "packed_cold_verified"
        states.append(state)
    controller = read_if_complete(source / "CONTROLLER_RECEIPT.json")
    all_processes_ended = bool(controller is not None and not controller.get("active_pids")
                               and not controller.get("pending_fits")
                               and controller.get("registered_fits") == fits
                               and all(row["process_receipt_present"] for row in states))
    control_ready = all_processes_ended
    if stage == "confirm":
        control_ready = bool(all_processes_ended and controller.get("stage") == "confirm"
            and controller.get("active_pids") == [] and controller.get("pending_fits") == []
            and controller.get("status") == "complete" and controller.get("error") is None
            and sorted(controller.get("completed_fits", [])) == sorted(fits)
            and all(row["status"] == "packed_cold_verified" for row in states))
    if include_control and control_ready:
        name = group + "_control"
        if name not in by_name:
            with tempfile.TemporaryDirectory(prefix="digital-feedback-live-control-", dir="/tmp") as scratch:
                staged = Path(scratch)
                for path in source.iterdir():
                    if path.is_file():
                        shutil.copy2(path, staged / path.name)
                shutil.copytree(source / "process_receipts", staged / "process_receipts")
                control_binding = dict(controller_sha256=digest((source / "CONTROLLER_RECEIPT.json").read_bytes()),
                                       launch_sha256=digest((source / "LAUNCH.json").read_bytes()))
                if stage == "confirm":
                    control_binding.update(seal_sha256=seal_sha256,
                                           published_models_commit=seal["published_models_commit"])
                entry = cold_pack(root, staged, name, group, control_binding)
            entries.append(entry)
            by_name[name] = entry
            new_entries.append(name)
    upload_rows = []
    for entry in sorted(entries, key=lambda row: row["name"]):
        directory = root / "archives" / entry["name"]
        manifest_path = directory / "MANIFEST.json"
        if digest(manifest_path.read_bytes()) != entry["manifest_sha256"]:
            raise ValueError(f"immutable archive manifest changed: {entry['name']}")
        manifest = json.loads(manifest_path.read_bytes())
        expected = {row["path"]: row["stored_sha256"] for row in manifest["parts"]}
        expected["MANIFEST.json"] = entry["manifest_sha256"]
        if sorted(p.name for p in directory.iterdir()) != sorted(expected):
            raise ValueError("unexpected file in immutable archive")
        for basename, expected_sha in sorted(expected.items()):
            path = directory / basename
            raw = path.read_bytes()
            if digest(raw) != expected_sha:
                raise ValueError(f"immutable archive changed: {path}")
            upload_rows.append(dict(path=path.relative_to(repository).as_posix(),
                                    absolute=str(path), bytes=len(raw), sha256=expected_sha,
                                    git_sha=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()))
    index_path = root / "orchestration" / (group.upper().replace("_", "") + "_UPLOAD_INDEX.json")
    index = dict(schema="digital-feedback-immutable-upload-index-v1",
                 repository="TrillionniumFoundation/hepta-private-ci", group=group, stage=stage,
                 seal_sha256=seal_sha256, full_derived_audits=stage == "confirm",
                 all_uploaded=False, network_operations=0, files=upload_rows)
    write_atomic(index_path, index)
    runs = [] if old is None else old["runs"]
    runs.append(dict(utc=datetime.now(timezone.utc).isoformat(), new_entries=new_entries,
                     scan_pack_and_restore_cpu_seconds=time.process_time() - start))
    evidence = dict(schema="digital-feedback-live-pack-v1", group=group, stage=stage,
                    seal_sha256=seal_sha256, full_derived_audits=stage == "confirm",
                    derived_tables_deferred=False, control_ready=control_ready,
                    registered_fits=fits, all_processes_ended=all_processes_ended,
                    all_fit_archives_verified=all(row["status"] == "packed_cold_verified" for row in states),
                    control_packaged=group + "_control" in by_name, states=states,
                    entries=entries, runs=runs, upload_index_sha256=digest(index_path.read_bytes()),
                    source_freeze_sha256=digest((root / "SOURCE_FREEZE.json").read_bytes()),
                    packaging_cpu_seconds=sum(run["scan_pack_and_restore_cpu_seconds"] for run in runs),
                    cost_scope="Packaging self CPU is separate from training workers; nested per-fit timing is not added again.",
                    network_operations=0)
    write_atomic(evidence_path, evidence)
    return dict(new_archives=new_entries, fit_archives=sum(row["status"] == "packed_cold_verified" for row in states),
                all_processes_ended=all_processes_ended, control_ready=control_ready,
                control_packaged=evidence["control_packaged"],
                upload_files=len(upload_rows), upload_bytes=sum(row["bytes"] for row in upload_rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("group")
    parser.add_argument("--include-control", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--seal", type=Path, help="Required immutable model seal for confirmation groups")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    while True:
        result = scan(root, args.group, args.include_control, args.seal)
        print(json.dumps(result, sort_keys=True), flush=True)
        if not args.watch or result["all_processes_ended"]:
            break
        time.sleep(20)


if __name__ == "__main__":
    main()
