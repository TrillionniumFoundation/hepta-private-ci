"""Synthetic archive corruption contracts; no actual scientific inputs are read."""

import argparse
import copy
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
from unittest.mock import patch

import archive_integrity as audit


def payloads():
    return {"repository/PROTOCOL.json": b'{"contract":1}', "repository/source.py": b"pass\n",
            "run/receipt.json": b'{"passed":true}', "run/rows.jsonl.gz": gzip.compress(b"one\ntwo\n", mtime=0)
                + gzip.compress(b"three\n", mtime=0), "assets/small.bin": bytes(range(256))}


def manifest(data):
    return {"schema": audit.SCHEMA, "members": [{"path": name, "bytes": len(raw), "sha256": audit.sha(raw)}
        for name, raw in sorted(data.items())], "provenance": {"registered_commits": ["a" * 40],
        "protocol": {"path": "repository/PROTOCOL.json", "sha256": audit.sha(data["repository/PROTOCOL.json"])},
        "source_files": {"repository/source.py": audit.sha(data["repository/source.py"])},
        "receipts": {"run/receipt.json": audit.sha(data["run/receipt.json"])}}}


def build(data=None, metadata=None, entries=None, manifest_raw=None, trailing=None):
    data = payloads() if data is None else data
    metadata = manifest(data) if metadata is None else metadata
    raw_manifest = audit.canonical(metadata) if manifest_raw is None else manifest_raw
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo("MANIFEST.json")
        info.size = len(raw_manifest)
        tar.addfile(info, io.BytesIO(raw_manifest))
        for name, raw, kind in (entries if entries is not None else [(k, v, tarfile.REGTYPE) for k, v in sorted(data.items())]):
            info = tarfile.TarInfo(name)
            info.type, info.size = kind, len(raw) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "outside"
            tar.addfile(info, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
    content = output.getvalue()
    if trailing is not None:
        # Cut only the terminal zero padding, retaining payload padding, then
        # append the exact caller-specified end marker for trailer tests.
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as tar:
            end = max(row.offset_data + ((row.size + 511) // 512) * 512 for row in tar)
        content = content[:end] + trailing
    return gzip.compress(content, mtime=0), raw_manifest


def execute(directory):
    started = time.perf_counter_ns()
    checks = []
    counter = 0

    def verify(raw, **kwargs):
        nonlocal counter
        counter += 1
        path = directory / f"fixture-{counter}.tar.gz"
        path.write_bytes(raw)
        return audit.verify_archive(path, expected_sha256=kwargs.pop("expected_sha256", audit.sha(raw)), **kwargs)

    def rejects(name, operation):
        try:
            operation()
        except (ValueError, EOFError, gzip.BadGzipFile, tarfile.TarError):
            checks.append(name)
        else:
            raise AssertionError("Corruption accepted: " + name)

    raw, metadata = build()
    result = verify(raw, expected_manifest_sha256=audit.sha(metadata))
    assert result["payload_members"] == 5 and result["outer_gzip_crc_verified_to_physical_eof"]
    assert result["inner_gzip_members"] == [{"path": "run/rows.jsonl.gz", "gzip_members": 2,
                                           "uncompressed_bytes": 14, "crc_verified": True}]
    checks.append("valid_hash_inventory_outer_and_concatenated_inner_crc")
    target = directory / "restored"
    restored = verify(raw, restore_paths=["run/rows.jsonl.gz", "assets/small.bin"], destination=target)
    assert (target / "MANIFEST.json").read_bytes() == metadata
    assert (target / "assets/small.bin").read_bytes() == payloads()["assets/small.bin"]
    assert restored["restored_payload_bytes"] == sum(len(payloads()[name]) for name in ("run/rows.jsonl.gz", "assets/small.bin"))
    assert not (target / "repository").exists()
    checks.append("literal_exclusive_selective_restore")
    rejects("existing_restore_not_overwritten", lambda: verify(raw, restore_paths=["assets/small.bin"], destination=target))
    rejects("unknown_restore_member", lambda: verify(raw, restore_paths=["assets/missing"], destination=directory / "unknown"))
    rejects("restore_budget", lambda: verify(raw, restore_paths=["assets/small.bin"], destination=directory / "budget", max_restore_bytes=255))
    rejects("duplicate_restore_request", lambda: verify(raw, restore_paths=["assets/small.bin"] * 2, destination=directory / "duplicate"))
    rejects("wrong_archive_identity", lambda: verify(raw, expected_sha256="0" * 64))
    rejects("wrong_manifest_identity", lambda: verify(raw, expected_manifest_sha256="0" * 64))
    entries = [(k, v, tarfile.REGTYPE) for k, v in sorted(payloads().items())]
    rejects("duplicate_tar_member", lambda: verify(build(entries=entries + [entries[0]])[0]))
    rejects("missing_manifest_member", lambda: verify(build(entries=entries[:-1])[0]))
    rejects("unmanifested_extra_member", lambda: verify(build(entries=entries + [("run/extra", b"x", tarfile.REGTYPE)])[0]))
    for kind, label in ((tarfile.SYMTYPE, "symlink"), (tarfile.LNKTYPE, "hardlink"),
                        (tarfile.DIRTYPE, "directory"), (tarfile.CHRTYPE, "device"), (tarfile.FIFOTYPE, "fifo")):
        rejects("nonregular_" + label, lambda kind=kind: verify(build(entries=[("assets/small.bin", b"", kind), *entries[1:]])[0]))
    for index, name in enumerate(("../x", "/run/x", "run/../x", "run//x", "run/./x", "run/x/", "run\\x", "run/C:x",
                                  "outside/x", "run/x\n", "repository/.git/config", "assets/.env")):
        rejects("unsafe_path_" + str(index), lambda name=name: audit.safe_name(name))
    data = payloads()
    for name, extra in (("file_parent_collision", {"run/a": b"x", "run/a/b": b"y"}),
                        ("case_collision", {"run/A": b"x", "run/a": b"y"})):
        rejects(name, lambda extra=extra: verify(build(data={**data, **extra})[0]))
    broken = copy.deepcopy(manifest(data))
    broken["members"][0]["bytes"] += 1
    rejects("declared_payload_size", lambda: verify(build(metadata=broken)[0]))
    broken = copy.deepcopy(manifest(data))
    broken["members"][0]["sha256"] = "0" * 64
    rejects("payload_hash", lambda: verify(build(metadata=broken)[0]))
    broken = copy.deepcopy(manifest(data))
    broken["provenance"]["source_files"]["repository/source.py"] = "0" * 64
    rejects("source_provenance_binding", lambda: verify(build(metadata=broken)[0]))
    rejects("duplicate_json_keys", lambda: verify(build(manifest_raw=b'{"schema":1,"schema":2}')[0]))
    rejects("nonfinite_manifest", lambda: verify(build(manifest_raw=b'{"bad":NaN}')[0]))
    rejects("unsorted_manifest", lambda: verify(build(metadata={**manifest(data), "members": list(reversed(manifest(data)["members"]))})[0]))
    for name, transform in (("inner_crc", lambda value: value[:-8] + bytes([value[-8] ^ 1]) + value[-7:]),
                            ("inner_truncated", lambda value: value[:-1]),
                            ("inner_trailing_junk", lambda value: value + b"junk")):
        changed = {**data, "run/rows.jsonl.gz": transform(data["run/rows.jsonl.gz"])}
        rejects(name, lambda changed=changed: verify(build(data=changed)[0]))
    bad_outer = raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:]
    rejects("outer_crc_after_tar_eof", lambda: verify(bad_outer))
    rejects("outer_truncated_footer", lambda: verify(raw[:-1]))
    rejects("nonzero_after_tar_end", lambda: verify(build(trailing=b"\0" * 1024 + b"evil")[0]))
    rejects("one_tar_end_block", lambda: verify(build(trailing=b"\0" * 512)[0]))
    failure_target = directory / "failed-restore"
    rejects("failed_restore_never_published", lambda: verify(bad_outer, restore_paths=["assets/small.bin"], destination=failure_target))
    assert not failure_target.exists() and failure_target.with_name("failed-restore.partial").exists()
    raced_target, original_publish, appeared = directory / "raced-restore", audit.publish_no_replace, {}

    def destination_appears(staging, final):
        final.mkdir()
        appeared["inode"] = final.stat().st_ino
        original_publish(staging, final)

    with patch.object(audit, "publish_no_replace", destination_appears):
        try:
            verify(raw, restore_paths=["assets/small.bin"], destination=raced_target)
        except FileExistsError:
            pass
        else:
            raise AssertionError("Atomic publication replaced a newly appeared empty destination")
    assert raced_target.stat().st_ino == appeared["inode"] and list(raced_target.iterdir()) == []
    assert (raced_target.with_name("raced-restore.partial") / "assets/small.bin").read_bytes() == payloads()["assets/small.bin"]
    checks.append("destination_appears_before_atomic_publication_no_replacement")
    large = b"x" * (audit.CHUNK * 3 + 19)
    checker = audit.GzipCRC("large.gz")
    encoded = gzip.compress(large, mtime=0)
    for offset in range(0, len(encoded), 17):
        checker.feed(encoded[offset:offset + 17])
    assert checker.finish()["uncompressed_bytes"] == len(large)
    checks.append("bounded_decoder_drains_multi_chunk_output")
    rejects("inner_expansion_limit", lambda: audit.GzipCRC("limit.gz", maximum=10).feed(gzip.compress(b"x" * 11)))
    sparse = tarfile.TarInfo("run/x")
    sparse.sparse = [(0, 1)]
    rejects("sparse_payload", lambda: audit.regular(sparse))
    return {"schema": "hepta.field-bridge.v3.archive-integrity-contract.1", "passed": True,
            "synthetic_only": True, "checks": checks, "check_count": len(checks),
            "source_files": {Path(audit.__file__).name: audit.file_sha(audit.__file__), Path(__file__).name: audit.file_sha(__file__)},
            "scientific_model_native_network_calls": 0, "verification_wall_ns": time.perf_counter_ns() - started}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Refusing to overwrite a contract receipt"
    with tempfile.TemporaryDirectory(prefix="v3-archive-contract-") as temporary:
        result = execute(Path(temporary))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": result["passed"], "check_count": result["check_count"]}))
