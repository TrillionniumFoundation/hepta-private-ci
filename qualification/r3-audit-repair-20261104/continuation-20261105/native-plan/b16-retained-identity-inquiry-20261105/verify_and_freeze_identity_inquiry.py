"""Verify the already retained B16 identity inquiry. Never contacts a host."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "delivery"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/native-plan/b16-retained-identity-inquiry-20261105"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.write_bytes(raw)


def js(path, value):
    save(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def load(name):
    return json.loads((ROOT / name).read_bytes())


def unwrap(value):
    assert not value.get("isError", False)
    if isinstance(value.get("structuredContent"), dict):
        return value["structuredContent"]
    return json.loads(next(x["text"] for x in value["content"] if x["type"] == "text"))


def verify():
    response = unwrap(load("ai395-filtered-list.original-tool-response.json"))
    assert response["inventory_complete"] is True and response["status_authoritative"] is False
    jobs = response["jobs"]
    assert response["total"] == len(jobs) == 2463
    assert len({job["id"] for job in jobs}) == 2463
    fields = {"created_unix_ms", "execution_mode", "host", "id", "launch_state"}
    assert all(set(job) == fields and job["host"] == "ai395" for job in jobs)
    assert not any(field in fields for field in ["idempotency_key", "argv", "cwd", "fingerprint"])
    old = load("ai395-snapshot-summary.json")
    assert old["records"] == 384 and old["declared_total"] == 2462 and old["inventory_complete"] is False
    for name, phrase in [("first-global-page.original-tool-response.json", "durable inventory membership changed"), ("ai395-page-003.original-tool-response.json", "durable job inventory changed; restart from the first page")]:
        value = load(name)
        assert value["isError"] is True and phrase in json.dumps(value)
    return {"schema": "b16-retained-identity-inquiry-verification-v1", "task_request_key": "hepta-ai395-b16-driver-v7-20261105-v1", "result": "UNKNOWN_IDENTITY_BINDING_UNCHANGED", "retained_identity_snapshot": {"host": "ai395", "inventory_complete": True, "declared_total": response["total"], "actual_count": len(jobs), "unique_ids": 2463, "provided_fields": sorted(fields), "status_authoritative": False, "whole_original_response": identity((ROOT / "ai395-filtered-list.original-tool-response.json").read_bytes())}, "prior_partial_inquiry": {"records": 384, "declared_total": 2462, "inventory_complete": False, "inventory_change_errors_retained": 2}, "conclusion_zh": "完整 retained identity 清单只提供创建时间、执行模式、host、id、launch_state；没有 idempotency key、argv、cwd、fingerprint，无法唯一绑定此前三次启动超时而未得到 job id 的 B16 driver。这既不能证明未执行，也不能据此重放。", "request_envelope_limit": "The filtered-list original artifact retains its complete response; no absent request envelope is fabricated. Every returned row explicitly identifies ai395.", "no_native_start": True, "no_unknown_process_status_or_stdout_read": True, "no_capacity_query": True, "no_process_cancellation": True, "no_retry_or_replay": True, "blocker_ledger_modified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    report = verify()
    if args.verify_only:
        print(json.dumps(report, ensure_ascii=False))
        return
    js(ROOT / "identity-inquiry-verification.json", report)
    files = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and OUT not in p.parents and "__pycache__" not in p.parts]
    stream = io.BytesIO()
    members = []
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in files:
            raw = path.read_bytes()
            name = path.relative_to(ROOT).as_posix()
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            tar.addfile(info, io.BytesIO(raw))
            members.append({"name": name, **identity(raw)})
    archive = gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)
    save(OUT / "complete-inquiry.tar.gz", archive)
    encoded = base64.b64encode(archive) + b"\n"
    assert len(encoded) < 480000
    save(OUT / "complete-inquiry.part-000.base64.txt", encoded)
    js(OUT / "member-manifest.json", {"members": members, "member_count": len(members), "total_member_bytes": sum(row["bytes"] for row in members)})
    js(OUT / "transport-manifest.json", {"archive": identity(archive), "parts": [{"name": "complete-inquiry.part-000.base64.txt", "file": identity(encoded)}], "member_manifest": identity((OUT / "member-manifest.json").read_bytes())})
    assert base64.b64decode(encoded) == archive
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        assert tar.getnames() == [row["name"] for row in members]
        for row in members:
            assert identity(tar.extractfile(row["name"]).read()) == {k: row[k] for k in ["bytes", "sha256", "git_blob"]}
    selected = [ROOT / "identity-inquiry-verification.json", Path(__file__), OUT / "member-manifest.json", OUT / "transport-manifest.json", OUT / "complete-inquiry.part-000.base64.txt"]
    js(OUT / "upload-plan.json", {"files": [{"local_file": str(path), "repo_path": PREFIX + "/" + path.relative_to(ROOT).as_posix(), "name": path.relative_to(ROOT).as_posix(), **identity(path.read_bytes())} for path in selected]})
    print(json.dumps({"members": len(members), "archive": identity(archive), "part_bytes": len(encoded), "uploads": len(selected), "binding": "UNKNOWN"}))


if __name__ == "__main__":
    main()
