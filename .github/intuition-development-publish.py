"""Publish source objects only; this program has no ref-update operation."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

root = Path(sys.argv[1]).resolve()
source = os.environ["SOURCE_SHA"]
repo = os.environ["GITHUB_REPOSITORY"]
assert source == "301cc06cbc80fe339f8f3055db5315d53acfc177"
assert repo == "TrillionniumFoundation/hepta-private-ci"
assert os.environ["GITHUB_REF"] == "refs/heads/codex/intuition-devhost-20260928"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


assert git("rev-parse", "HEAD").decode().strip() == source
allowed = set(json.loads((root.parent / "author-allowed.json").read_text(encoding="utf-8")))
paths = [value.decode() for value in git("diff", "--name-only", "-z").split(b"\0") if value]
assert paths and set(paths) <= allowed and len(paths) <= 24
assert not git("ls-files", "--others", "--exclude-standard")
assert not git("diff", "--cached", "--name-only")
output = Path(os.environ["RUNNER_TEMP"]) / "intuition-source-proposal"
output.mkdir(exist_ok=False)
(output / "source.diff").write_bytes(git("diff", "--binary"))
entries = []


def post(kind: str, data: dict) -> dict:
    assert kind in {"blobs", "trees", "commits"}
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/{kind}",
        data=json.dumps(data).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


for path in paths:
    assert not (root / path).is_symlink()
    data = (root / path).read_bytes().replace(b"\r\n", b"\n")
    assert len(data) <= 2_000_000
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    blob = post("blobs", {"encoding": "base64", "content": base64.b64encode(data).decode()})
    assert blob["sha"] == digest
    entries.append({"path": path, "mode": "100644", "type": "blob", "sha": digest})
tree = post("trees", {"base_tree": git("rev-parse", "HEAD^{tree}").decode().strip(), "tree": entries})
commit = post("commits", {
    "message": "fix(intuition): route V4 natively and reconcile source-state documentation\n\nPreserve historical digest encodings without legacy decision dispatch. Enforce evaluator/observer controller separation and add matrix/signed-fixture regression sources. Generate canonical source-state projections, version matrix and requirement-to-test/artifact traceability. All production completion predicates remain false; durable orchestration, outward receipt transport, final exact-source/merge execution and operator acceptance remain unclosed. Source authored on an isolated development host and requires external diff review before candidate ref update.",
    "tree": tree["sha"], "parents": [source]})
result = {"schema": "hepta.intuition.source-proposal.v1", "sourceSha": source,
          "proposedCommit": commit["sha"], "tree": tree["sha"], "files": entries,
          "workflowRun": os.environ["GITHUB_RUN_ID"], "runAttempt": os.environ["GITHUB_RUN_ATTEMPT"],
          "candidateRefUpdated": False, "executionQualification": False,
          "claim": "Source authoring only. Review and immutable qualification remain external operations."}
(output / "proposal.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
print("INTUITION_SOURCE_PROPOSAL=" + commit["sha"])
