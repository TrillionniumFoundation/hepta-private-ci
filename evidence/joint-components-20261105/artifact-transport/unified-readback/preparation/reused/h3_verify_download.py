#!/usr/bin/env python3
"""Local verification of H3 version-pinned, read-only binary_read responses."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
COMPLETION = WORKSPACE / "w1/h3-elf-export/H3-export-completion.json"
COMPLETION_SHA = "93d7bf08914054e4bcf05f17eea3cd5ef36fac9bbf0d1e601dda59084e758cd3"
VERSION = None  # Established only from the first actual verified response.
BLOCK = 65536
MAX_BATCH = 2  # W1 uses these two slots for H2 or H3 sequentially; H1 owns the other two.


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if path.exists():
        require(path.read_bytes() == raw, "refuse overwrite: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def completion():
    raw = COMPLETION.read_bytes()
    require(sha(raw) == COMPLETION_SHA, "original completion bytes changed")
    value = json.loads(raw)
    require(value["status"] == "COMPLETE" and value["phase"] == "H3", "completion phase/status")
    require(value["archive_bytes"] == 283427280 and value["archive_sha256"] ==
            "5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773", "archive identity")
    offset = 0
    for index, part in enumerate(value["parts"]):
        require(part["index"] == index and part["offset"] == offset and
                part["name"] == "H3-actual-retained-elfs.tar.xz.part-" + str(index).zfill(4), "part layout")
        require(0 < part["bytes"] <= 4194304 and offset % BLOCK == 0, "part extent")
        offset += part["bytes"]
    require(len(value["parts"]) == 68 and offset == value["archive_bytes"], "complete part coverage")
    return value


def chunk_path(offset, suffix):
    return ROOT / "chunks" / (str(offset).zfill(9) + suffix)


def read_version_pin(spec):
    path = ROOT / "version-pin.json"
    if not path.exists():
        return None
    value = json.loads(path.read_bytes())
    require(value["schema"] == "h3-actual-first-chunk-version-pin-v1" and
            value["path"] == spec["archive_path"] and value["size"] == spec["archive_bytes"] and
            value["completion_sha256"] == COMPLETION_SHA, "version pin source")
    require(isinstance(value["version"], str) and 0 < len(value["version"]) <= 512,
            "opaque observed version required")
    require(sha(chunk_path(0, ".rpc.json").read_bytes()) == value["first_rpc_sha256"] and
            sha(chunk_path(0, ".request.json").read_bytes()) == value["first_request_sha256"],
            "version pin original first response changed")
    return value["version"]


def verified_chunk(spec, offset):
    global VERSION
    require(offset in range(0, spec["archive_bytes"], BLOCK), "invalid requested offset")
    path = chunk_path(offset, ".rpc.json")
    raw = path.read_bytes()
    envelope = json.loads(raw)
    require(not envelope.get("isError") and "transport_exception" not in envelope,
            "remote response is an error: " + str(offset))
    payload = envelope.get("structuredContent")
    if payload is None:
        texts = [entry["text"] for entry in envelope["content"] if entry["type"] == "text"]
        require(len(texts) == 1, "one unambiguous payload required")
        payload = json.loads(texts[0])
    data = base64.b64decode(payload["data_base64"], validate=True)
    size = min(BLOCK, spec["archive_bytes"] - offset)
    observed_version = payload["version"]
    require(isinstance(observed_version, str) and 0 < len(observed_version) <= 512,
            "opaque response version required")
    require(payload["path"] == spec["archive_path"] and
            (observed_version == VERSION if VERSION is not None else offset == 0),
            "chunk source/version")
    require(payload["size"] == spec["archive_bytes"] and payload["offset"] == offset and
            len(data) == size and payload["next_offset"] == offset + size, "chunk extent")
    require(payload["eof"] is (offset + size == spec["archive_bytes"]), "chunk EOF")
    require(sha(data) == payload["chunk_sha256"], "chunk SHA")
    request = json.loads(chunk_path(offset, ".request.json").read_bytes())
    require(request["host"] == "desktop" and request["path"] == spec["archive_path"] and
            request["offset"] == offset and request["limit"] == BLOCK, "request binding")
    require(set(request) <= {"host", "path", "offset", "limit", "expected_version"},
            "unexpected request field")
    require(request.get("expected_version") == VERSION if offset else
            request.get("expected_version") in (None, VERSION), "request expected version")
    if VERSION is None:
        require(offset == 0 and request.get("expected_version") is None,
                "only the initial unpinned read can establish version")
        save_json(ROOT / "version-pin.json", dict(
            schema="h3-actual-first-chunk-version-pin-v1", path=spec["archive_path"],
            size=spec["archive_bytes"], version=observed_version, completion_sha256=COMPLETION_SHA,
            first_rpc_sha256=sha(raw), first_request_sha256=sha(chunk_path(0, ".request.json").read_bytes()),
            first_chunk_sha256=sha(data), initial_bytes_actually_verified=len(data),
            native_evidence_credit=False))
        VERSION = observed_version
    return data, payload, raw


def active_offsets():
    path = ROOT / "active-batch.json"
    if not path.exists():
        return []
    value = json.loads(path.read_bytes())
    offsets = value.get("pending_offsets", value["offsets"])
    require(isinstance(offsets, list) and len(offsets) == len(set(offsets)) and
            set(offsets) <= set(value["offsets"]), "active batch offset state")
    return offsets


def progress(spec, status, in_flight=None, errors=None):
    offsets = sorted(int(p.name.split(".", 1)[0]) for p in (ROOT / "chunks").glob("*.verified.json"))
    expected = list(range(0, spec["archive_bytes"], BLOCK))
    require(set(offsets) <= set(expected), "unexpected verified offsets")
    present = set(offsets)
    next_offset = next((offset for offset in expected if offset not in present), spec["archive_bytes"])
    parts = sorted((ROOT / "parts").glob("*.verified.json")) if (ROOT / "parts").exists() else []
    pending = active_offsets()
    if in_flight is None:
        in_flight = len(pending)
    if status == "PAUSED" and pending:
        status = "PAUSE_PENDING"
    value = dict(schema="h3-actual-elf-download-progress-v1", status=status, in_flight=in_flight,
                 next_offset=next_offset, verified_chunks=len(offsets), required_chunks=len(expected),
                 verified_bytes=sum(min(BLOCK, spec["archive_bytes"] - n) for n in offsets),
                 verified_parts=len(parts), expected_archive_bytes=spec["archive_bytes"], version=VERSION,
                 native_execution=False, errors=errors or [], pending_offsets=pending)
    (ROOT / "progress.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def complete_parts(spec):
    directory = ROOT / "parts"
    directory.mkdir(exist_ok=True)
    published = []
    for part in spec["parts"]:
        destination = directory / part["name"]
        record = directory / (part["name"] + ".verified.json")
        if record.exists():
            continue
        offsets = list(range(part["offset"], part["offset"] + part["bytes"], BLOCK))
        if not all(chunk_path(offset, ".verified.json").exists() for offset in offsets):
            continue
        temporary = destination.with_name(destination.name + ".partial")
        require(not destination.exists() and not temporary.exists(), "fresh part output required")
        total, digest = 0, hashlib.sha256()
        with temporary.open("xb") as stream:
            for offset in offsets:
                data, _, _ = verified_chunk(spec, offset)
                stream.write(data)
                digest.update(data)
                total += len(data)
        require(total == part["bytes"] and digest.hexdigest() == part["sha256"] and
                file_sha(temporary) == part["sha256"], "part written bytes/hash")
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        result = dict(part, local_path=str(destination), pinned_version=VERSION,
                      original_completion_sha256=COMPLETION_SHA,
                      independently_verified_original_rpc_chunks=len(offsets),
                      actual_written_part_reopened_and_hashed=True,
                      native_execution=False)
        save_json(record, result)
        published.append(result)
    return published


def assemble_extract(spec):
    require(progress(spec, "ASSEMBLING")["verified_chunks"] == len(range(0, spec["archive_bytes"], BLOCK)),
            "all verified chunks required")
    complete_parts(spec)
    archive = ROOT / "H3-actual-retained-elfs.tar.xz"
    temporary = archive.with_name(archive.name + ".partial")
    require(not archive.exists() and not temporary.exists(), "fresh archive destination required")
    digest = hashlib.sha256()
    with temporary.open("xb") as output:
        for part in spec["parts"]:
            data = (ROOT / "parts" / part["name"]).read_bytes()
            require(len(data) == part["bytes"] and sha(data) == part["sha256"], "part changed before assembly")
            digest.update(data)
            output.write(data)
    require(temporary.stat().st_size == spec["archive_bytes"] and digest.hexdigest() == spec["archive_sha256"]
            and file_sha(temporary) == spec["archive_sha256"], "whole archive byte/hash mismatch")
    os.link(temporary, archive, follow_symlinks=False)
    temporary.unlink()
    staging, final = ROOT / "extracted.partial", ROOT / "extracted"
    require(not staging.exists() and not final.exists(), "fresh extraction destination required")
    staging.mkdir(mode=0o700)
    actual, total = {}, 0
    with tarfile.open(archive, "r|xz") as stream:
        for member in stream:
            relative = PurePosixPath(member.name)
            require(member.isfile() and not relative.is_absolute() and ".." not in relative.parts and
                    relative.as_posix() == member.name and member.name not in actual and len(actual) < 16,
                    "unsafe/duplicate/unexpected archive member")
            total += member.size
            require(0 <= member.size <= spec["total_actual_elf_bytes"] and
                    total <= spec["total_actual_elf_bytes"] + 64 * 1024 * 1024, "archive extraction bound")
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            size, digest = 0, hashlib.sha256()
            with stream.extractfile(member) as source, destination.open("xb") as output:
                while data := source.read(1024 * 1024):
                    output.write(data)
                    digest.update(data)
                    size += len(data)
            require(size == member.size and file_sha(destination) == digest.hexdigest(), "member written byte/hash mismatch")
            actual[member.name] = dict(bytes=size, sha256=digest.hexdigest())
    index_raw = (staging / "export-index.json").read_bytes()
    require(sha(index_raw) == spec["archive_index_sha256"], "index SHA mismatch")
    index = json.loads(index_raw)
    require(index["schema"] == "hepta-actual-retained-elf-archive-index-v1" and index["phase"] == "H3" and
            (index["source_commit"], index["source_tree"]) == (spec["source_commit"], spec["source_tree"]), "index source")
    require(len(index["files"]) == 11 and len(index["embedded_metadata_files"]) == 4, "H3 explicit member counts")
    expected = {row["name"]: {key: row[key] for key in ("bytes", "sha256")} for row in index["files"]}
    require(len(expected) == 11, "duplicate ELF entry")
    expected.update(index["embedded_metadata_files"])
    expected["export-index.json"] = dict(bytes=len(index_raw), sha256=sha(index_raw))
    require(actual == expected and len(actual) == 16, "all original ELF and embedded metadata binding")
    require(sum(row["bytes"] for row in index["files"]) == spec["total_actual_elf_bytes"] and
            index["original_run_outcome"] == spec["original_run_outcome"] and
            index["native_reexecution"] is False, "H3 original outcome/scope")
    for row in index["files"]:
        with (staging / row["name"]).open("rb") as elf:
            require(elf.read(4) == b"\x7fELF", "actual retained image is not ELF")
    binding = verify_complete_image_binding(spec, index, staging)
    staging.rename(final)
    report = dict(schema="h3-actual-retained-elf-independent-readback-v1", status="VERIFIED",
                  archive=str(archive), archive_bytes=spec["archive_bytes"], archive_sha256=spec["archive_sha256"],
                  source_commit=spec["source_commit"], source_tree=spec["source_tree"], version=VERSION,
                  original_completion_sha256=COMPLETION_SHA, original_index_sha256=sha(index_raw),
                  parts_verified=68, original_rpc_chunks_verified=len(range(0, spec["archive_bytes"], BLOCK)),
                  files=actual, total_actual_elf_bytes=spec["total_actual_elf_bytes"],
                  raw_directory=str(final), original_run_outcome=index["original_run_outcome"],
                  native_reexecution=False, capture_gaps_filled=False, capture_limits=index["capture_limits"],
                  complete_image_binding=binding, partial_artifacts_recorded=0,
                  partial_absence_scope=binding["partial_absence_scope"],
                  second_daemon_full_hash_or_copy_inferred=False)
    save_json(ROOT / "readback-verification.json", report)
    progress(spec, "COMPLETE")
    return report


def verify_complete_image_binding(spec, index, staging):
    """Preserve this exact H3 inventory and its actual attribution limitations."""
    plan_raw = (staging / "export-plan.json").read_bytes()
    require(sha(plan_raw) == spec["plan_sha256"] and
            sha((staging / "exporter.py").read_bytes()) == spec["exporter_sha256"] and
            sha((staging / "owned-release-proof.json").read_bytes()) == spec["release_proof_sha256"],
            "embedded exact plan/exporter/release binding")
    plan = json.loads(plan_raw)
    original_raw = (staging / "H3/original-source-map.json").read_bytes()
    require(len(original_raw) == plan["source_map"]["bytes"] and
            sha(original_raw) == plan["source_map"]["sha256"] and
            base64.b64decode(plan["source_map"]["data_base64"], validate=True) == original_raw,
            "exact original H3 inventory bytes differ")
    original = json.loads(original_raw)
    planned = {row["name"]: row for row in plan["files"]}
    originals = {row["sha256"]: row for row in original["images"]}
    require(len(planned) == len(originals) == len(index["files"]) == 11 and
            original["partial_artifacts"] == [], "eleven recorded complete H3 images required")
    aliases = set()
    for row in index["files"]:
        require(row["name"] in planned and all(row.get(k) == v for k, v in planned[row["name"]].items()),
                "complete image original map/aliases/observations changed")
        require(row["other_aliases_reopened_by_this_export"] is False and
                row["second_read_sha256"] == row["sha256"] and
                row["first_read_metadata"] == row["second_read_metadata"], "retained-source observation scope")
        own = originals[row["sha256"]]
        require(row["bytes"] == own["bytes"] and row["aliases"] == own["retained_aliases"] and
                row["original_actual_paths"] == own["actual_paths"] and
                row["original_observations"] == own["observations"] and
                row["source_path"] in row["aliases"], "original H3 independent image records changed")
        aliases.update(row["aliases"])
    require(len(aliases) == original["complete_retained_alias_count"] == 30 and
            original["status"] == "FAILED" and index["original_run_outcome"]["result"] == "FAILED" and
            index["original_run_outcome"]["unmatched_live_observations"] == original["unmatched_live_observations"],
            "original H3 failure/capture gap or aliases changed")
    daemons = [row for row in original["images"] if row["kind"] == "ordinary-daemon"]
    require(len(daemons) == 1 and len(daemons[0]["retained_aliases"]) == 1 and
            len(daemons[0]["observations"]) == 2 and
            [row["full_hash_and_copy_this_capture"] for row in daemons[0]["observations"]] == [True, False] and
            [row["same_held_file_object_verified"] for row in daemons[0]["observations"]] == [False, True],
            "first full daemon capture / second held-object reuse scope changed")
    return dict(original_map_sha256=sha(original_raw), complete_images=11,
                original_retained_aliases=30, selected_sources=11, unselected_aliases_metadata_only=19,
                original_native_outcome="FAILED", unmatched_live_observations=original["unmatched_live_observations"],
                ordinary_daemon_observations=daemons[0]["observations"],
                partial_absence_scope=original["partial_artifact_scope"],
                second_process_full_hash_or_copy_inferred=False, capture_gaps_filled=False)


def main():
    global VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dispatch", "verify", "status", "finalize"))
    parser.add_argument("offsets", nargs="*", type=int)
    args = parser.parse_args()
    spec = completion()
    VERSION = read_version_pin(spec)
    if args.mode == "dispatch":
        if (ROOT / "PAUSE_REMOTE_READS").exists():
            value = progress(spec, "PAUSED")
            value["dispatch_offsets"] = []
        else:
            require(not (ROOT / "active-batch.json").exists(), "previous batch not finalized")
            missing = [n for n in range(0, spec["archive_bytes"], BLOCK) if not chunk_path(n, ".verified.json").exists()][:MAX_BATCH]
            if VERSION is None:
                require(not any((ROOT / "chunks").glob("*.verified.json")), "unknown version with verified bytes")
                missing = [0]
            require(all(not chunk_path(n, ".rpc.json").exists() for n in missing), "unverified original response needs review")
            value = progress(spec, "DISPATCHED" if missing else "TRANSFER_COMPLETE", len(missing))
            value.update(dispatch_offsets=missing, path=spec["archive_path"], host="desktop", limit=BLOCK,
                         expected_version=VERSION, max_parallel=MAX_BATCH)
            value["requests"] = [dict(host="desktop", path=spec["archive_path"], offset=n, limit=BLOCK,
                                      **({"expected_version": VERSION} if VERSION is not None else {}))
                                 for n in missing]
            if missing:
                save_json(ROOT / "active-batch.json", dict(offsets=missing, version=VERSION))
    elif args.mode == "verify":
        errors = []
        confirmed_completed = []
        for offset in args.offsets:
            try:
                data, payload, original = verified_chunk(spec, offset)
                # A verified, correctly attributed response proves this read
                # returned. An exception or missing/ambiguous response does not.
                confirmed_completed.append(offset)
                destination = chunk_path(offset, ".bin")
                if destination.exists():
                    require(destination.read_bytes() == data, "saved chunk changed")
                else:
                    destination.write_bytes(data)
                verified = {key: val for key, val in payload.items() if key != "data_base64"}
                verified.update(actual_bytes=len(data), rpc_bytes=len(original), rpc_sha256=sha(original), independently_verified=True)
                # The initial preserved receipt was independently checked before this helper existed.
                old = chunk_path(offset, ".verified.json")
                if old.exists():
                    require(json.loads(old.read_bytes()) == verified, "prior verification differs")
                else:
                    save_json(old, verified)
            except Exception as error:
                errors.append(dict(offset=offset, error=str(error)))
        active = ROOT / "active-batch.json"
        if active.exists():
            current = json.loads(active.read_bytes())
            require(current["offsets"] == args.offsets, "active batch offset mismatch")
            completed = set(current.get("confirmed_completed_offsets", [])) | set(confirmed_completed)
            pending = [offset for offset in current["offsets"] if offset not in completed]
            if pending:
                current.update(confirmed_completed_offsets=sorted(completed), pending_offsets=pending,
                               state="UNRESOLVED_RESPONSE_REQUIRES_RECONCILIATION")
                active.write_text(json.dumps(current, indent=2) + "\n")
            else:
                active.unlink()
        published = complete_parts(spec)
        value = progress(spec, "ERROR" if errors else "PAUSED" if (ROOT / "PAUSE_REMOTE_READS").exists() else "READY", errors=errors)
        value["new_parts"] = published
        print(json.dumps(value), flush=True)
        raise SystemExit(bool(errors))
    elif args.mode == "finalize":
        value = assemble_extract(spec)
    else:
        value = progress(spec, "PAUSED" if (ROOT / "PAUSE_REMOTE_READS").exists()
                         else "ACTIVE" if active_offsets() else "READY")
    print(json.dumps(value), flush=True)


if __name__ == "__main__":
    main()
