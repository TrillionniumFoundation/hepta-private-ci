#!/usr/bin/env python3
"""Verify only the frozen local 50f archive and captured Git SDK bytes."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX_SHA = "ef30e3874442496c90cbd26fae098c225b6b6563"


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def sdk_object(raw):
    value = json.loads(raw)["structuredContent"]
    return value.get("structuredContent", value)


def write_new(name, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    with (ROOT / name).open("xb") as stream:
        stream.write(raw)
    return identity(raw)


def main():
    proof = json.loads((ROOT / "INPUT_BYTE_REVIEW.json").read_bytes())
    index_raw = (ROOT / "frozen/CLOSED_RUNTIME_ARCHIVE_INPUTS.json").read_bytes()
    assert identity(index_raw)["git_blob"] == INDEX_SHA
    index = json.loads(index_raw)
    rows = proof["entries"]
    assert len(rows) == 119 and len(index["files"]) == 118
    assert rows[:-1] == [dict(r, frozen_path=str(ROOT / "frozen" / r["name"])) for r in index["files"]]
    assert rows[-1]["name"] == "CLOSED_RUNTIME_ARCHIVE_INPUTS.json"
    assert len({r["evidence_path"] for r in rows}) == 119
    verified = {}
    ledger_rows = []
    for row in rows:
        raw = Path(row["frozen_path"]).read_bytes()
        assert identity(raw) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        assert Path(row["path"]).read_bytes() == raw
        assert len(raw) <= 512000 and raw.decode("utf8").encode("utf8") == raw
        sha = row["git_blob"]
        if sha not in verified:
            marker = json.loads((ROOT / "github" / (sha + ".VERIFIED.json")).read_bytes())
            assert marker["actual_create"] is True and marker["full_get_equal"] is True
            create_raw = Path(marker["create_sdk_path"]).read_bytes()
            get_raw = Path(marker["get_sdk_path"]).read_bytes()
            assert sdk_object(create_raw)["sha"] == sha
            assert sdk_object(get_raw)["content"].encode("utf8") == raw
            verified[sha] = {
                "kind": marker["kind"],
                "create_sdk": identity(create_raw),
                "get_sdk": identity(get_raw),
                "create_sdk_path": marker["create_sdk_path"],
                "get_sdk_path": marker["get_sdk_path"],
            }
        ledger_rows.append({
            "path": row["evidence_path"], "local_path": row["frozen_path"],
            "source_original_path": row["path"], "sha": sha,
            "bytes": row["bytes"], "sha256": row["sha256"],
            "actual_create": True, "full_readback_equal": True,
            "mode": "100644", "type": "blob", **verified[sha],
        })
    assert len(verified) == 110
    kinds = Counter(v["kind"] for v in verified.values())
    assert kinds["REUSED_COMPLETE_ORIGINAL_GIT_SDK"] == 25
    assert sum(kinds.values()) - kinds["REUSED_COMPLETE_ORIGINAL_GIT_SDK"] == 85
    target = "5f12cf36518f10f6453d022921d01b356124729b"
    first = (ROOT / "github" / (target + ".CREATE.original.json")).read_bytes()
    missing = (ROOT / "github" / (target + ".RECONCILIATION_GET_01.original.json")).read_bytes()
    success = (ROOT / "github" / (target + ".CREATE_02.original.json")).read_bytes()
    assert json.loads(first)["isError"] is True
    assert "RemoteProtocolError" in sdk_object(first)["error"]
    assert json.loads(missing)["isError"] is True
    assert "404" in sdk_object(missing)["error"]
    assert sdk_object(success)["sha"] == target
    transport = {
        "format": "hepta-archive-transport-observations-v1",
        "scope": "One Git evidence-blob creation transport failure, independent of H/source/test execution.",
        "fixed_blob": target,
        "first_create_error_original": {**identity(first), "utf8": first.decode()},
        "same_identity_get_404_original": {**identity(missing), "utf8": missing.decode()},
        "same_content_second_create_original": {**identity(success), "utf8": success.decode()},
        "final_full_get_equal": True,
        "source_original_unchanged": True,
        "new_H_calls": 0,
    }
    transport_pin = write_new("ARCHIVE_TRANSPORT_OBSERVATIONS.json", transport)
    ledger = {
        "format": "hepta-closed-runtime-archive-full-git-readback-v1",
        "original_index": identity(index_raw),
        "frozen_original_cutoff": index["frozen_at_utc"],
        "original_file_count": 118, "index_included": True,
        "entry_count": len(ledger_rows), "unique_git_blobs": len(verified),
        "verified_kinds": dict(kinds), "entries": ledger_rows,
        "sdk_storage": "All complete Git SDK responses retained locally. SDK identities are recorded; no claim that every new archiving SDK is a separately published blob.",
        "local_failure_and_reconciliation": transport_pin,
    }
    ledger_pin = write_new("ACTUAL_GIT_FULL_READBACK.json", ledger)
    report = {
        "format": "hepta-50f-closed-runtime-independent-archive-review-v1",
        "status": "COMPLETE_FIXED_118_PLUS_ORIGINAL_INDEX_GIT_FULL_READBACK",
        "original_index": identity(index_raw),
        "original_cutoff_utc": index["frozen_at_utc"],
        "job_id": index["job_id"],
        "original_paths": 118, "original_unique_blobs": 109,
        "paths_including_original_index": 119, "unique_blobs_including_original_index": 110,
        "original_local_utf8_and_all_three_identities_equal": True,
        "all_complete_git_contents_equal": True,
        "maximum_original_leaf_bytes": max(r["bytes"] for r in rows),
        "existing_complete_sdk_reused_unique": 25,
        "additional_complete_create_and_get_unique": 85,
        "original_native_read_error_count": index["native_read_error_count"],
        "original_local_decode_failure_and_v2_correction_preserved": True,
        "actual_request": "Exact757672-byte original represented by two unchanged lossless gzip/base64 parts; no oversized raw evidence leaf added.",
        "large_source_recovery": "ordinary's separate24-file exact recovery package is referenced by the original frozen EXACT_RECOVERY_REFERENCE.json; not duplicated or called a second native read.",
        "archive_transport_failure": "Original RemoteProtocolError and following same-SHA404 retained. Subsequent same-content create and complete GET equal. This is not an H/source/QA failure.",
        "ledger": ledger_pin, "transport_observations": transport_pin,
        "no_new_H_source_ref_or_project_execution": True,
        "future_canonical_or_qualification_observations_added": False,
        "qualification": False,
    }
    print(json.dumps({"REVIEW.json": write_new("REVIEW.json", report), "ACTUAL_GIT_FULL_READBACK.json": ledger_pin, "ARCHIVE_TRANSPORT_OBSERVATIONS.json": transport_pin}, indent=2))


if __name__ == "__main__":
    main()
