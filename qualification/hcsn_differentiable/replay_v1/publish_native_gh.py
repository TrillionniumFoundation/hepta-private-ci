"""Prepared native gh publisher: run only after noninteractive authorization is observed."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

REPO = "TrillionniumFoundation/hepta-private-ci"
PARENT = "a832b028abdf1a1c9ab66534332457c6d76a91ca"
MODEL_SOURCE = "5cb83d9c76beedf4c1c917e4bf561f5f26261ce7"
BRANCH = "artifact/hcsn-c2-export-20261112-c06d-v1"
BASE_BRANCH = "research/hcsn-real-checkpoint-replay-20261112-c06d"
PREFIX = "qualification/hcsn_differentiable/replay_v1/artifact/"
FILE = Path("/home/qian-qi/hcsn-real-replay-c06d-export-v1.zip")
EXPECTED_BYTES = 11397159
EXPECTED_SHA = "37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75"
STATE = Path("/home/qian-qi/hcsn-c2-native-gh-export-c06d-v1")


def api(path, payload=None):
    command = ["gh", "api", path]
    with tempfile.TemporaryDirectory(prefix="c2-gh-request-") as directory:
        if payload is not None:
            body = Path(directory)/"request.json"
            body.write_text(json.dumps(payload))
            command += ["--method", "POST", "--input", str(body)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("gh API failed without exposing credential details: " + path)
    return json.loads(result.stdout)


def record(name, value):
    path = STATE/(name + ".json")
    with path.open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def main():
    STATE.mkdir(exist_ok=False)
    user = api("user")
    repo = api("repos/" + REPO)
    if not user.get("login") or repo.get("permissions", {}).get("push") is not True:
        raise RuntimeError("normal noninteractive push authorization not established")
    record("authorization", {"login": user["login"], "repo": repo["full_name"],
                             "push": repo["permissions"]["push"]})
    current = api("repos/"+REPO+"/pulls/6130")
    if current["head"]["sha"] != PARENT:
        raise RuntimeError("base changed; inspect before publishing")
    before = FILE.stat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    content = FILE.read_bytes()
    if len(content) != EXPECTED_BYTES or hashlib.sha256(content).hexdigest() != EXPECTED_SHA:
        raise RuntimeError("original export bytes changed")
    expected_blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    record("input", {"path": str(FILE), "bytes": len(content), "sha256": EXPECTED_SHA,
                     "expected_git_blob": expected_blob, "base": PARENT, "source": MODEL_SOURCE})
    blob = api("repos/"+REPO+"/git/blobs", {"encoding": "base64", "content": base64.b64encode(content).decode()})
    after = FILE.stat()
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if blob["sha"] != expected_blob or after_identity != identity:
        raise RuntimeError("blob or input version mismatch")
    record("blob", blob)
    parent = api("repos/"+REPO+"/git/commits/"+PARENT)
    export = {"schema": "hcsn-real-replay-export-parts-v1", "source_parent": MODEL_SOURCE,
              "receipt_parent": PARENT, "archive": {"bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA},
              "parts": [{"path": "part-000.zip", "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA}]}
    tree = api("repos/"+REPO+"/git/trees", {"base_tree": parent["tree"]["sha"], "tree": [
        {"path": PREFIX+"part-000.zip", "mode": "100644", "type": "blob", "sha": expected_blob},
        {"path": PREFIX+"EXPORT.json", "mode": "100644", "type": "blob", "content": json.dumps(export, sort_keys=True, indent=2)+"\n"}]})
    record("tree", tree)
    commit = api("repos/"+REPO+"/git/commits", {"message": "artifact(hcsn): preserve original six-checkpoint replay export (zero model execution)",
                    "tree": tree["sha"], "parents": [PARENT]})
    record("commit", commit)
    ref = api("repos/"+REPO+"/git/refs", {"ref": "refs/heads/"+BRANCH, "sha": commit["sha"]})
    record("ref", ref)
    pull = api("repos/"+REPO+"/pulls", {"base": BASE_BRANCH, "head": BRANCH, "draft": True,
        "title": "artifact(hcsn): publish original bound six-checkpoint replay ZIP (HOLD)",
        "body": "Zero-model artifact publication only. Preserves the original 11397159-byte export, SHA256 " + EXPECTED_SHA +
                ". Parent includes the native failure receipts; model source remains " + MODEL_SOURCE +
                ". No original worktree/source refs changed, no training or replay run. Artifact manifest uses ordered relative part paths for CPU profile checkout. HOLD_NO_GO."})
    record("pull", pull)
    check = api("repos/"+REPO+"/git/ref/heads/"+BRANCH)
    if check["object"]["sha"] != commit["sha"]:
        raise RuntimeError("new artifact branch readback mismatch")
    print(json.dumps({"commit": commit["sha"], "tree": tree["sha"], "blob": expected_blob,
                      "pull": pull["html_url"], "branch": BRANCH, "manifest": PREFIX+"EXPORT.json"}, sort_keys=True))


if __name__ == "__main__":
    main()
