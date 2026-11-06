#!/usr/bin/env python3
"""Restore the complete frozen packet; optionally replay both read-only verifiers."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def safe_relative(name):
    value = PurePosixPath(name)
    assert name and "\\" not in name and not value.is_absolute()
    assert all(part not in ("", ".", "..") for part in value.parts)
    assert value.as_posix() == name
    return Path(*value.parts)


def restore(delivery, destination, verify=False):
    manifest = json.loads((delivery / "delivery-manifest.json").read_text())
    encoded = []
    for part in manifest["archive"]["parts"]:
        body = (delivery / safe_relative(part["path"])).read_bytes()
        assert identity(body) == {k: part[k] for k in ("bytes", "sha256", "git_blob")}
        encoded.append(body)
    archive = base64.b64decode(b"".join(encoded), validate=True)
    assert identity(archive) == {k: manifest["archive"][k] for k in ("bytes", "sha256", "git_blob")}
    members = manifest["members"]
    assert len(members) == manifest["member_count"]
    assert len({row["path"] for row in members}) == len(members)
    objects = {row["sha256"]: row for row in members}
    assert len(objects) == manifest["unique_file_bodies"]
    bodies = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as stream:
        names = stream.namelist()
        assert len(names) == len(set(names)) == len(objects)
        assert set(names) == {"objects/" + sha for sha in objects}
        for sha, row in objects.items():
            info = stream.getinfo("objects/" + sha)
            assert info.file_size == row["bytes"]
            body = stream.read(info)
            assert identity(body) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
            bodies[sha] = body
    destination.mkdir(parents=True, exist_ok=False)
    for name in manifest["directories"]:
        (destination / safe_relative(name)).mkdir(parents=True, exist_ok=True)
    for row in members:
        path = destination / safe_relative(row["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bodies[row["sha256"]])
        assert identity(path.read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    # Both author versions and their historical output are retained exactly.
    core = destination / "core"
    independent = destination / "independent-review"
    addendum = destination / "author-proof-addendum"
    for name, other in (
        ("new-verifier.py", core / "verify_candidate.py"),
        ("new-static.stdout.json", core / "static-final.stdout.json"),
        ("old-verifier.py", independent / "restored/verify_candidate.py"),
        ("old-static.stdout.json", independent / "restored/static-final.stdout.json"),
    ):
        assert (addendum / name).read_bytes() == other.read_bytes()
    report = {"schema": "b21-rebuilt-lossless-packet-restoration-v1",
              "members_restored": len(members), "unique_bodies": len(objects),
              "explicit_directories": len(manifest["directories"]),
              "all_original_bytes_equal": True,
              "historical_and_final_author_versions_preserved": True,
              "source_workflow": manifest["source_workflow_actual"],
              "collector": manifest["collector_actual"],
              "independent_review": manifest["independent_review_actual"],
              "author_proof_addendum": manifest["author_proof_addendum_actual"],
              "native_execution": False, "ref_mutation": False, "replays": []}
    if verify:
        for label, command, expected in (
            ("core", [sys.executable, "-B", str(core / "verify_candidate.py"), str(core)],
             core / "static-final.stdout.json"),
            ("independent", [sys.executable, "-B", str(independent / "verify_independent_portable.py")],
             independent / "REVIEW.json"),
        ):
            result = subprocess.run(command, capture_output=True, timeout=120, cwd=destination)
            assert result.returncode == 0, (label, result.stderr)
            assert result.stderr == b""
            assert result.stdout == expected.read_bytes(), label
            report["replays"].append({"component": label, "exit": 0,
                                     "stdout_full_bytes_equal": True, **identity(result.stdout)})
    return report


if __name__ == "__main__":
    assert len(sys.argv) in (3, 4)
    do_verify = len(sys.argv) == 4
    if do_verify:
        assert sys.argv[3] == "--verify"
    result = restore(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), do_verify)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
