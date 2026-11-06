#!/usr/bin/env python3
"""Freeze a lossless evidence archive only; never run product or native tools."""

import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parent
DEST = ROOT / "delivery"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/native-plan/b11-host-neither-observation-candidate-20261105/v3/"


def identity(body):
    return {
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
    }


def main():
    assert (ROOT / "independent-review").is_dir()
    completion = json.loads((ROOT / "review-completion.json").read_text())
    assert completion["candidate_git_blob"] == "8c16416c185f17871c25139bc16c6fd112b5fd41"
    assert completion["independent_review_complete"] is True
    assert not completion["native_execution_performed"] and not completion["ref_mutation_performed"]
    originals = {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in sorted(ROOT.rglob("*"))
        if path.is_file() and "delivery" not in path.relative_to(ROOT).parts
        and "__pycache__" not in path.parts
    }
    checkpoint = (DEST / "materialization-checkpoints.json").read_bytes()
    originals["registration-witnesses/pre-archive-materialization-checkpoints.json"] = checkpoint
    for path in sorted((DEST / "full-GET-originals").glob("*.json")):
        originals["registration-witnesses/pre-archive-full-GET-originals/" + path.name] = path.read_bytes()
    assert originals["candidate/codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs"] == json.loads((DEST / "full-GET-originals/8c16416c185f17871c25139bc16c6fd112b5fd41.json").read_text())["content"].encode()
    records = [{"path": name, **identity(body)} for name, body in sorted(originals.items())]
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, body in sorted(originals.items()):
            assert not name.startswith("/") and ".." not in Path(name).parts
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            archive.addfile(info, io.BytesIO(body))
    compressed = gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)
    (DEST / "originals.tar.gz").write_bytes(compressed)
    text = base64.b64encode(compressed).decode()
    parts = []
    for index, start in enumerate(range(0, len(text), 400000)):
        name = f"originals.part-{index:03d}.base64.txt"
        body = (text[start:start + 400000] + "\n").encode()
        (DEST / name).write_bytes(body)
        parts.append({"path": name, **identity(body)})
    restored = base64.b64decode("".join((DEST / row["path"]).read_text().strip() for row in parts), validate=True)
    assert restored == compressed
    with tarfile.open(fileobj=io.BytesIO(restored), mode="r:gz") as archive:
        actual = {}
        for member in archive.getmembers():
            assert member.isfile() and member.name not in actual
            body = archive.extractfile(member).read()
            assert body == originals[member.name]
            actual[member.name] = identity(body)
        assert sorted(actual) == sorted(originals)
        assert all(actual[row["path"]] == {k: row[k] for k in ["bytes", "sha256", "git_blob"]} for row in records)
    manifest = {
        "schema": "b11-v3-lossless-transport",
        "scope": "Complete frozen candidate, source dependencies, initial failure, primary declarations, static and independent review originals, and pre-archive full GET payloads.",
        "archive": {"path": "originals.tar.gz", **identity(compressed)},
        "members": records,
        "member_count": len(records),
        "base64_parts": parts,
        "maximum_part_bytes": max(row["bytes"] for row in parts),
        "all_member_bytes_roundtrip_equal": True,
        "native_execution_performed": False,
        "ref_mutation_performed": False,
        "B11": "OPEN",
    }
    (DEST / "transport-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    checkpoints = json.loads(checkpoint)
    direct = [row["local_file"] for row in checkpoints["files"]]
    direct.extend([str(DEST / "transport-manifest.json"), *[str(DEST / row["path"]) for row in parts]])
    assert len(direct) == len(set(direct))
    plan = []
    for local in direct:
        path = Path(local)
        relative = path.relative_to(ROOT).as_posix()
        row = {"local_file": str(path), "repo_path": PREFIX + relative, "path": PREFIX + relative, **identity(path.read_bytes())}
        assert row["bytes"] < 480000
        plan.append(row)
    (DEST / "registration-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"members": len(records), "archive": manifest["archive"], "parts": len(parts), "objects": len(plan), "roundtrip_equal": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
