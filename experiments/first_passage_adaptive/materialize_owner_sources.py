"""Read the explicitly pinned historical owner sources for research replay.

Current production dependency qualification remains a separate repository gate.
This helper never selects another revision or changes the frozen source identity.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


MANIFEST = Path(__file__).resolve().parent/"native/SOURCE_IDENTITY.json"
SUPPORT_SCRIPTS = {"scripts/run-nextest.py", "scripts/just-shell.py"}


def materialize(repository, output, manifest=MANIFEST):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    identity = json.loads(Path(manifest).read_text())
    commit = identity["source_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid pinned owner commit")
    expected = {row["path"]: row["git_blob_sha"] for row in identity["files"]}
    if len(expected) != len(identity["files"]):
        raise ValueError("Duplicate pinned owner source")
    paths = sorted(set(expected)|SUPPORT_SCRIPTS)
    payloads, receipt = {}, {}
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe pinned owner path")
        kind = subprocess.check_output(
            ["git", "-C", str(repository), "cat-file", "-t", f"{commit}:{name}"], text=True).strip()
        if kind != "blob":
            raise ValueError("Pinned owner source is not a Git blob")
        payload = subprocess.check_output(
            ["git", "-C", str(repository), "cat-file", "blob", f"{commit}:{name}"])
        git_sha = hashlib.sha1(b"blob "+str(len(payload)).encode()+b"\0"+payload).hexdigest()
        if name in expected and git_sha != expected[name]:
            raise ValueError("Historical owner source does not match its frozen identity")
        payloads[name] = payload
        receipt[name] = {"git_blob_sha": git_sha, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    # Validate the complete source set before creating any output directory.
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    result = {"schema": "hepta.first-passage.pinned-owner-materialization.v1", "source_commit": commit,
        "manifest_sha256": hashlib.sha256(Path(manifest).read_bytes()).hexdigest(), "files": receipt,
        "purpose": "Historical research replay; current production dependencies are independently qualified."}
    (output/"MATERIALIZATION.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.repository, args.output), indent=2))
