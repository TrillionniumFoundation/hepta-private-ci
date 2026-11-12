"""Publish existing 4092 diagnostic originals through normal gh authorization.

This is an artifact-only operation: no Torch import, model, or optimizer call.
An unknown API response requires inspection of STATE and the immutable ref;
the script never resumes itself or overwrites an existing STATE or Git ref.
"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile

REPO = "TrillionniumFoundation/hepta-private-ci"
PARENT = "3d2451ebfcaf19912a77a5a888d01c55f7a9dca3"
MODEL_SOURCE = "5cb83d9c76beedf4c1c917e4bf561f5f26261ce7"
AUDIT_SOURCE = "d8bcfac912c3cc24faeadf3bb234d1df5107f088"
BRANCH = "artifact/hcsn-diagnostic-originals-20261112-c06d-v1"
BASE_BRANCH = "research/hcsn-real-recovery-results-20261112-4092"
PREFIX = "qualification/hcsn_differentiable/replay_v1/artifact/diagnostic-4092/"
ROOT = Path("/home/qian-qi/hcsn-real-recovery-20261112-4092")
STATE = Path("/home/qian-qi/hcsn-diagnostic-originals-gh-c06d-v1")
EXPECTED = {
    "originals.tar.xz": (7070892, "f3f6992f31d7ab85a10eaa727dfc894fdb72ef5dafbba6bc43fc36d23a899dc7"),
    "ARCHIVE.json": (550, "e1a0213e3f8a86c902912f7f9fb67605681f8d3dc033bc1feb839f1d5b993e45"),
    "ORIGINALS-MANIFEST.json": (21930, "2de3cda19999b5b41d36cdfcea190b0417e4091049f5815e7af2e48885825ebc"),
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def git_blob(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def identity(path):
    row = path.lstat()
    if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
        raise RuntimeError("input must be a regular file with one link: " + str(path))
    return (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)


def checked_inputs():
    identities = {}
    raw = {}
    for name, (size, sha256) in EXPECTED.items():
        path = ROOT/name
        identities[name] = identity(path)
        raw[name] = path.read_bytes()
        if len(raw[name]) != size or digest(raw[name]) != sha256:
            raise RuntimeError("frozen input bytes changed: " + name)
        if identity(path) != identities[name]:
            raise RuntimeError("input identity changed while reading: " + name)
    manifest = json.loads(raw["ORIGINALS-MANIFEST.json"])
    receipt = json.loads(raw["ARCHIVE.json"])
    if (manifest["schema"] != "hcsn-real-recovery-originals-v1"
            or manifest["source_commit"] != MODEL_SOURCE
            or manifest["audit_commit"] != AUDIT_SOURCE
            or manifest["native_training_job"] != "1a1ce749808-2564-1688"
            or manifest["file_count"] != 118
            or manifest["new_independent_complete_training_replays"] != 0
            or manifest["scientific_admission"] != "HOLD_NO_GO"):
        raise RuntimeError("original diagnostic identity changed")
    if (receipt["schema"] != "hcsn-real-recovery-archive-receipt-v1"
            or receipt["path"] != str(ROOT/"originals.tar.xz")
            or receipt["bytes"] != len(raw["originals.tar.xz"])
            or receipt["sha256"] != digest(raw["originals.tar.xz"])
            or receipt["manifest_sha256"] != digest(raw["ORIGINALS-MANIFEST.json"])
            or receipt["original_files"] != 118
            or receipt["new_optimizer_calls"] != 0
            or receipt["closed_source_and_outputs_rechecked"] is not True):
        raise RuntimeError("original archive receipt mismatch")
    records = manifest["files"]
    expected_members = {}
    for row in records:
        name = row["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name or name in expected_members:
            raise RuntimeError("unsafe or duplicate original member")
        expected_members[name] = (row["bytes"], row["sha256"])
    if (len(expected_members) != 118
            or sum(size for size, _ in expected_members.values()) != manifest["uncompressed_bytes"]
            or manifest["uncompressed_bytes"] != receipt["uncompressed_bytes"]):
        raise RuntimeError("original member accounting mismatch")
    expected_members["ORIGINALS-MANIFEST.json"] = EXPECTED["ORIGINALS-MANIFEST.json"]
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw["originals.tar.xz"]), mode="r:xz") as archive:
        for member in archive:
            if not member.isfile() or member.name in seen or member.name not in expected_members:
                raise RuntimeError("unexpected, linked, or duplicate tar member")
            content = archive.extractfile(member).read()
            if (len(content), digest(content)) != expected_members[member.name]:
                raise RuntimeError("tar member bytes differ from original manifest")
            if member.name == "ORIGINALS-MANIFEST.json" and content != raw[member.name]:
                raise RuntimeError("tar manifest raw bytes differ")
            seen.add(member.name)
    if seen != set(expected_members):
        raise RuntimeError("missing original tar members")
    return raw, identities


def api(path, payload=None):
    command = ["/usr/bin/gh", "api", path]
    with tempfile.TemporaryDirectory(prefix="c2-diagnostic-gh-request-") as directory:
        if payload is not None:
            body = Path(directory)/"request.json"
            body.write_text(json.dumps(payload))
            command += ["--method", "POST", "--input", str(body)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("gh API failed; inspect retained STATE before any retry: " + path)
    return json.loads(result.stdout)


def record(name, value):
    with (STATE/(name + ".json")).open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def main():
    STATE.mkdir(exist_ok=False)
    user = api("user")
    repo = api("repos/" + REPO)
    if (not user.get("login") or repo.get("full_name") != REPO
            or repo.get("permissions", {}).get("push") is not True):
        raise RuntimeError("normal noninteractive push authorization not established")
    record("authorization", {"login": user["login"], "repo": repo["full_name"], "push": True})
    current = api("repos/"+REPO+"/pulls/6173")
    if current["head"]["sha"] != PARENT:
        raise RuntimeError("base changed; inspect before publishing")
    raw, identities = checked_inputs()
    record("input", {"scope": "diagnostic originals, distinct from original input ZIP",
                     "source": MODEL_SOURCE, "audit": AUDIT_SOURCE, "base": PARENT,
                     "new_model_executions": 0, "new_optimizer_calls": 0,
                     "files": {name: {"bytes": len(content), "sha256": digest(content),
                                       "git_blob_sha1": git_blob(content)}
                               for name, content in raw.items()}})
    entries = []
    for name, content in raw.items():
        blob = api("repos/"+REPO+"/git/blobs", {"encoding": "base64", "content": base64.b64encode(content).decode()})
        record("blob-"+name, blob)
        if blob["sha"] != git_blob(content):
            raise RuntimeError("Git blob identity mismatch")
        entries.append({"path": PREFIX+name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    for name in raw:
        if identity(ROOT/name) != identities[name]:
            raise RuntimeError("original input version changed before publication")
    export = {"schema": "hcsn-diagnostic-originals-publication-v1", "receipt_parent": PARENT,
              "source_commit": MODEL_SOURCE, "audit_commit": AUDIT_SOURCE,
              "native_training_job": "1a1ce749808-2564-1688", "artifact_kind": "diagnostic originals",
              "new_model_executions": 0, "new_optimizer_calls": 0,
              "new_independent_complete_training_replays": 0, "scientific_admission": "HOLD_NO_GO",
              "files": [{"path": name, "bytes": len(content), "sha256": digest(content),
                         "git_blob_sha1": git_blob(content)} for name, content in raw.items()]}
    entries.append({"path": PREFIX+"PUBLICATION.json", "mode": "100644", "type": "blob",
                    "content": json.dumps(export, sort_keys=True, indent=2)+"\n"})
    parent = api("repos/"+REPO+"/git/commits/"+PARENT)
    tree = api("repos/"+REPO+"/git/trees", {"base_tree": parent["tree"]["sha"], "tree": entries})
    record("tree", tree)
    commit = api("repos/"+REPO+"/git/commits", {"message": "artifact(hcsn): preserve 4092 diagnostic originals (zero model execution)",
                    "tree": tree["sha"], "parents": [PARENT]})
    record("commit", commit)
    ref = api("repos/"+REPO+"/git/refs", {"ref": "refs/heads/"+BRANCH, "sha": commit["sha"]})
    record("ref", ref)
    pull = api("repos/"+REPO+"/pulls", {"base": BASE_BRANCH, "head": BRANCH, "draft": True,
        "title": "artifact(hcsn): preserve 4092 diagnostic original states and independent audit (HOLD)",
        "body": "Artifact-only publication of the existing 7070892-byte originals.tar.xz, SHA256 f3f6992f31d7ab85a10eaa727dfc894fdb72ef5dafbba6bc43fc36d23a899dc7, plus verbatim ARCHIVE.json and ORIGINALS-MANIFEST.json. All 118 original files and the embedded manifest are byte-verified before publication. Distinct diagnostic attempt 4092, native job 1a1ce749808-2564-1688; this publication performs zero model executions and optimizer calls. Checkpoint continuity evidence is not independent complete C2 training replay or scientific efficacy. HOLD_NO_GO."})
    record("pull", pull)
    check = api("repos/"+REPO+"/git/ref/heads/"+BRANCH)
    if check["object"]["sha"] != commit["sha"]:
        raise RuntimeError("new artifact branch readback mismatch")
    print(json.dumps({"commit": commit["sha"], "tree": tree["sha"], "pull": pull["html_url"],
                      "branch": BRANCH, "publication": PREFIX+"PUBLICATION.json"}, sort_keys=True))


if __name__ == "__main__":
    main()
