"""Verify retained evidence as data; never extract or execute payload members."""

import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def check(data, expected):
    assert identity(data) == {k: expected[k] for k in ("bytes", "sha256")}


def relative(name):
    p = PurePosixPath(name)
    assert not p.is_absolute() and ".." not in p.parts and "\\" not in name
    assert str(p) == name and name not in ("", ".")
    return p


def member_records(data):
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        assert len(infos) == len({i.filename for i in infos})
        assert sum(i.file_size for i in infos) < 512 * 1024 * 1024
        for info in infos:
            name = info.filename
            relative(name.rstrip("/") if info.is_dir() else name)
            assert not stat.S_ISLNK(info.external_attr >> 16)
            value = archive.read(info)
            assert len(value) == info.file_size
            result[name] = identity(value)
        assert archive.testzip() is None
    return result


def main():
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    index = json.loads((root / "INDEX.json").read_text())
    assert index["schema"] == "hepta-retained-normal-evidence-index-v1"
    results = []
    for payload in index["payloads"]:
        pieces = []
        offset = 0
        for number, pin in enumerate(payload["chunks"]):
            path = root / relative(pin["path"])
            assert path.is_file() and not path.is_symlink() and root in path.resolve().parents
            raw = path.read_bytes()
            check(raw, pin)
            obj = json.loads(raw)
            assert obj["schema"] == "hepta-evidence-base64-chunk-v1"
            assert obj["payload"] == payload["name"] and obj["index"] == number
            assert obj["offset"] == offset
            block = base64.b64decode(obj["base64"], validate=True)
            check(block, obj)
            assert 0 < len(block) <= 32768
            pieces.append(block)
            offset += len(block)
        data = b"".join(pieces)
        check(data, payload)
        records = member_records(data)
        assert records == payload["members"]
        official_count = nested_members = 0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            check(archive.read(payload["manifest_member"]), payload["manifest"])
            for pin in payload["official_artifacts"]:
                original = archive.read(pin["zip_member"])
                check(original, pin)
                official = json.loads(archive.read(pin["metadata_member"]))
                assert official["id"] == pin["artifact_id"]
                assert official["size_in_bytes"] == pin["bytes"]
                assert official["digest"] == "sha256:" + pin["sha256"]
                assert official["workflow_run"]["id"] == payload["run_id"]
                assert official["workflow_run"]["head_sha"] == payload["harness"]
                nested = member_records(original)
                check(json.dumps(nested, sort_keys=True, separators=(",", ":")).encode(), pin["members_manifest"])
                assert len(nested) == pin["member_count"]
                official_count += 1
                nested_members += len(nested)
        results.append({
            "payload": payload["name"], "run_id": payload["run_id"],
            **identity(data), "outer_members_verified": len(records),
            "official_zip_bytes_and_metadata_verified": official_count,
            "official_zip_members_verified": nested_members,
            "retained_original_outcomes": payload["retained_original_outcomes"],
        })
    result = {
        "schema": "hepta-retained-normal-evidence-verification-v1",
        "result": "PASS_DATA_INTEGRITY", "payloads": results,
        "native_executions": 0, "artifact_code_executions": 0,
        "network_requests": 0, "extracted_files": 0,
        "scope": "Payload, member and official artifact identities verified. Retained source-specific outcomes are not new test executions.",
    }
    print(json.dumps(result, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
