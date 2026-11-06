from pathlib import Path
import base64
import gzip
import hashlib
import io
import json
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "packet"
BUNDLE = ROOT / "portable-bundle"


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest()}


assert not PACKET.exists() and not BUNDLE.exists(), "do not overwrite a frozen packet"
PACKET.mkdir()
for name in ("sources", "source-api", "authority", "verification-harness-first-iteration", "verification-harness-second-iteration"):
    shutil.copytree(ROOT / name, PACKET / name)
for name in ("artifact-13471885720.original.zip", "artifacts-page-1.original.json",
             "run-42123581408-jobs.original.json", "zip-members.json", "download.transport-receipt.json",
             "verify_evidence.py", "VERIFICATION.json", "verifier.stdout.json", "verifier.stderr.txt", "REVIEW.zh-CN.md"):
    shutil.copyfile(ROOT / name, PACKET / name)
records = [{"path": "packet/" + str(path.relative_to(PACKET)), **identity(path.read_bytes())}
           for path in sorted(PACKET.rglob("*")) if path.is_file()]
tar_body = io.BytesIO()
with tarfile.open(fileobj=tar_body, mode="w", format=tarfile.USTAR_FORMAT) as archive:
    for entry in records:
        data = (ROOT / entry["path"]).read_bytes()
        info = tarfile.TarInfo(entry["path"])
        info.size, info.mode, info.uid, info.gid, info.mtime = len(data), 0o644, 0, 0, 0
        archive.addfile(info, io.BytesIO(data))
compressed = gzip.compress(tar_body.getvalue(), compresslevel=9, mtime=0)
encoded = base64.b64encode(compressed).decode()
BUNDLE.mkdir()
parts = []
for index, offset in enumerate(range(0, len(encoded), 120000), 1):
    text = encoded[offset:offset + 120000]
    name = f"part-{index:03}.base64.txt"
    (BUNDLE / name).write_text(text)
    parts.append({"path": name, **identity(text.encode())})
manifest = {
    "schema": "objective-owner-67-originals-portable-bundle-v1",
    "encoding": "concatenate parts in manifest order, then strict base64 decode, then gzip tar",
    "compressed_archive_computed_identity": identity(compressed),
    "archive_identity_is_not_claimed_as_a_separately_registered_Git_object": True,
    "parts": parts, "members": records,
    "artifact": {"id": 13471885720, "zip_path": "packet/artifact-13471885720.original.zip", "zip_members": 52},
    "shared_console": {
        "member": "original/job-127581904963.original.log",
        "bytes": 1606119, "git_blob_computed": "5ca1c1c9543c21ff9647dcb90dfd32ada53e9f22",
        "sha256": "74fbbd060d64f9a1ae18bd91f3a483ca0a8f62fc5e7bab58828d89a5bf33c370",
        "custody": "shared root/format 0244 increment packet; exact immutable registry bound in external-dependencies.json",
        "required_verifier_argument": "--console /path/to/complete/shared/original/job-127581904963.original.log",
    },
    "native_execution_by_this_packet_builder": False,
}
(BUNDLE / "BUNDLE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"members": len(records), "parts": len(parts),
                  "compressed_archive": identity(compressed),
                  "manifest": identity((BUNDLE / "BUNDLE_MANIFEST.json").read_bytes())}, indent=2))
