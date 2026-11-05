"""Freeze repository-backed B20 evidence; no native execution or Git ref writes."""
import base64
import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "delivery"
REPO_PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/reviews/b20-original-exit-independent-20261105"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.write_bytes(raw)


def write_json(path, value):
    save(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    upstream = ROOT.parent / "b07-complete-originals-recovery-20261105"
    for source, name in [(upstream / "v7-main-windows/transport-manifest.json", "existing-v7-transport-manifest.json"), (upstream / "v7-main-windows/original-files-manifest.json", "existing-v7-original-files-manifest.json"), (upstream / "recovery-receipt-v1.json", "existing-b07-recovery-receipt.json")]:
        save(ROOT / "windows" / name, source.read_bytes())
    verification = json.loads((ROOT / "derived/independent-verification.json").read_bytes())
    assert verification["recommendation"] == "ORIGINAL_B20_EXIT_EVIDENCE_SATISFIED_PENDING_ROOT_REVIEW"
    assert not verification["blocker_ledger_modified"] and not verification["native_execution_started"]
    files = [path for path in sorted(ROOT.rglob("*")) if path.is_file() and OUT not in path.parents and "__pycache__" not in path.parts]
    members = []
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            raw = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(raw))
            members.append({"name": name, **identity(raw)})
    archive = gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)
    save(OUT / "complete-evidence.tar.gz", archive)
    write_json(OUT / "member-manifest.json", {"schema": "b20-complete-original-evidence-members-v1", "members": members, "member_count": len(members), "total_member_bytes": sum(row["bytes"] for row in members)})
    parts = []
    for index, offset in enumerate(range(0, len(archive), 350000)):
        raw = archive[offset:offset + 350000]
        encoded = base64.b64encode(raw) + b"\n"
        name = f"complete-evidence.part-{index:03d}.base64.txt"
        save(OUT / name, encoded)
        parts.append({"index": index, "name": name, "compressed_offset": offset, "file": identity(encoded), "decoded_chunk": identity(raw)})
    write_json(OUT / "transport-manifest.json", {"schema": "b20-complete-original-evidence-transport-v1", "archive": identity(archive), "member_manifest": identity((OUT / "member-manifest.json").read_bytes()), "member_count": len(members), "part_count": len(parts), "parts": parts, "no_product_execution": True, "no_ref_update": True})
    # Confirm the entire frozen delivery before requesting any Git object creation.
    restored = b"".join(base64.b64decode((OUT / row["name"]).read_bytes()) for row in parts)
    assert restored == archive
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        assert tar.getnames() == [row["name"] for row in members]
        for row in members:
            assert identity(tar.extractfile(row["name"]).read()) == {k: row[k] for k in ["bytes", "sha256", "git_blob"]}
    selected = [ROOT / "REVIEW.zh-CN.md", ROOT / "verify_b20_original_exit_v1.py", ROOT / "prepare_windows_supplement.py", ROOT / "freeze_delivery.py", ROOT / "derived/independent-verification.json", ROOT / "windows/original-selection-and-execution-verification.json", OUT / "member-manifest.json", OUT / "transport-manifest.json"] + [OUT / row["name"] for row in parts]
    rows = [{"local_file": str(path), "name": path.relative_to(ROOT).as_posix(), "repo_path": REPO_PREFIX + "/" + path.relative_to(ROOT).as_posix(), **identity(path.read_bytes())} for path in selected]
    write_json(OUT / "upload-plan.json", {"schema": "b20-actual-Git-upload-plan-v1", "actual_upload_not_yet_done": True, "files": rows})
    print(json.dumps({"files": len(files), "archive": identity(archive), "parts": len(parts), "uploads": len(rows), "plan": str(OUT / "upload-plan.json")}))


if __name__ == "__main__":
    main()
