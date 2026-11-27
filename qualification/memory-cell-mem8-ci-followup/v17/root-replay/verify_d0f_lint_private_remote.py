"""Verify complete remote d0f lint/private originals without replaying work."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "d0f-lint-private-remote"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    proofs = []
    for folder, filename, manifest_name, key, prefix, count in [
        ("windows-fix-d0f-original", "WINDOWS_SANDBOX_FIX_D0F_ORIGINAL.tar.xz", "PACKAGE_MANIFEST.json", "members", "", 30),
        ("private-d0f", "MEM_D0F_PRIVATE_ORIGINAL.tar.xz", "MANIFEST.json", "files", "package/", 25),
    ]:
        p = BASE / folder
        raw = (p / filename).read_bytes()
        out = p / "root-extracted"
        assert not out.exists()
        objects = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as packed:
            members = packed.getmembers()
            assert len(members) == len({m.name for m in members}) == count
            for item in members:
                name = PurePosixPath(item.name)
                assert item.isfile() and not name.is_absolute() and ".." not in name.parts
                assert "\\" not in item.name and str(name) == item.name
                objects[item.name] = packed.extractfile(item).read()
        manifest = json.loads((p / manifest_name).read_bytes())
        rows = manifest[key]
        assert len(rows) == len({r["path"] for r in rows}) == count - 1
        assert {prefix + r["path"] for r in rows} | {prefix + manifest_name} == set(objects)
        assert objects[prefix + manifest_name] == (p / manifest_name).read_bytes()
        for row in rows:
            assert pin(objects[prefix + row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        for name, data in objects.items():
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if folder == "windows-fix-d0f-original":
            command = [sys.executable, str(out / "verify_package.py"), str(out)]
            expected = (p / "OUTER_OFFLINE_REPLAY.json").read_bytes()
        else:
            old = (ROOT / "root-reviewed-extracted/private-c895/verify_private_original.py").read_text()
            current = (out / "package/verify_private_original.py").read_text()
            inverse = current
            for new, previous in [
                ("original d0f Windows-private", "original c895 Windows-private"),
                ("d0f6507e08f7f5c5855f5164d07c049a34d1a6d9", "c89540598693697577cda8cba31cb07f6ce65317"),
                ("658fa040046285116b1fd81b94ff8c96444072ad", "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"),
                ("43062473076", "43048568252"), ("130668436521", "130619111545"),
                ("13875243416", "13870555680"), ("13876965022", "13869303170"),
            ]:
                assert new in inverse
                inverse = inverse.replace(new, previous)
            assert inverse == old
            command = [sys.executable, str(out / "package/verify_private_original.py"), str(out / "package")]
            expected = (p / "AUDIT.json").read_bytes()
        result = subprocess.run(command, capture_output=True)
        assert result.returncode == 0 and result.stderr == b"", (result.returncode, result.stderr)
        assert json.loads(result.stdout) == json.loads(expected)
        (p / "ROOT_REMOTE_OFFLINE_REPLAY.json").write_bytes(result.stdout)
        audit = json.loads(result.stdout)
        proofs.append({"folder": folder, "archive": pin(raw), "members": count, "manifest_members": count - 1, "unchanged_reader_exit": 0, "complete_original_result_equal": True, "result": audit})
    proof = {"schema": "mem8.v17.d0f-lint-private-root-replay.v1", "immutable_commit": "5fbc64ca2fdc314af8d2a540d81eaf5925477e3e", "prior_full_remote_object_byte_checks": 24, "packets": proofs, "new_native_or_model_executions": 0}
    (ROOT / "ROOT_D0F_LINT_PRIVATE_REPLAY.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"status": "PASS_TWO_COMPLETE_REMOTE_PACKETS_AND_ORIGINAL_READERS", "packets": {r["folder"]: r["members"] for r in proofs}}, indent=2))


if __name__ == "__main__":
    main()
