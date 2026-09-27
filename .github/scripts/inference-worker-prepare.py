"""User-requested source preparation, never a qualification receipt or ref writer."""
from __future__ import annotations
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

BASE = "21b9e1129375e4a3a0fa7a7d4c526d839c6705ef"
BASE_TREE = "65f786ae9db3b8f2fb492bdda8e8f38b04a34520"
PATCH_SHA256 = "86276f28f1e3df93fcf8b9fd1c7aeed04e2725e9e9c95acb2153276f7eaf7848"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
ROOTS = (
    "codex-rs/hepta-contracts/", "codex-rs/hepta-infer-core/",
    "codex-rs/hepta-infer-worker-host/", "codex-rs/hepta-agentd/src/test_support.rs",
)

def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

def prepare(checkout: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError("preparation destination must be new")
    if git(checkout, "rev-parse", f"{BASE}^{{tree}}") != BASE_TREE:
        raise RuntimeError("source baseline mismatch")
    packed = b"".join(path.read_bytes() for path in sorted((checkout / ".github/remediation").glob("inference-worker.patch.part*.b64")))
    patch = gzip.decompress(base64.b64decode(packed, validate=False))
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise RuntimeError("patch content mismatch")
    subprocess.run(["git", "-C", str(checkout), "worktree", "add", "--detach", str(destination), BASE], check=True)
    subprocess.run(["git", "-C", str(destination), "apply", "--index", "--whitespace=error", "-"], input=patch, check=True)
    paths = git(destination, "diff", "--cached", "--name-only", BASE).splitlines()
    if not paths or any(not path.startswith(ROOTS) for path in paths):
        raise RuntimeError("patch escapes user-authorized source scope")
    subprocess.run(["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "-p", "codex-hepta-contracts", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-infer-worker-host", "-p", "codex-hepta-agentd"], cwd=destination, check=True)
    subprocess.run(["git", "-C", str(destination), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(destination), "diff", "--cached", "--check"], check=True)

def publish(root: Path, output: Path) -> None:
    # This step writes content-addressed blobs/trees only. It deliberately has
    # no API for commits, refs, merges, branch protection or check results.
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RuntimeError("unexpected repository")
    output.mkdir(parents=True, exist_ok=True)
    paths = git(root, "diff", "--cached", "--name-only", BASE).splitlines()
    if not paths or any(not path.startswith(ROOTS) for path in paths):
        raise RuntimeError("formatted source escapes explicit scope")
    token = os.environ["GITHUB_TOKEN"]
    def post(resource: str, value: dict) -> dict:
        if resource not in ("blobs", "trees"):
            raise RuntimeError("only immutable Git objects may be written")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPOSITORY}/git/{resource}",
            data=json.dumps(value).encode(), method="POST", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28",
            })
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    elements, inventory = [], []
    for path in paths:
        entry = git(root, "ls-files", "--stage", "--", path).split()
        if not entry:
            elements.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            continue
        mode, expected, stage = entry[:3]
        if stage != "0" or mode != "100644":
            raise RuntimeError("only regular text source is supported")
        raw = subprocess.check_output(["git", "-C", str(root), "show", f":{path}"])
        created = post("blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if created["sha"] != expected:
            raise RuntimeError("Git blob identity mismatch")
        elements.append({"path": path, "mode": mode, "type": "blob", "sha": expected})
        inventory.append({"path": path, "git_blob": expected, "sha256": hashlib.sha256(raw).hexdigest()})
    created = post("trees", {"base_tree": BASE_TREE, "tree": elements})
    expected = git(root, "write-tree")
    if created["sha"] != expected:
        raise RuntimeError("Git tree identity mismatch")
    (output / "proposed-tree.json").write_text(json.dumps({
        "base_commit": BASE, "base_tree": BASE_TREE, "proposed_tree": expected,
        "preparation_commit": os.environ["GITHUB_SHA"], "files": inventory,
        "qualification": False, "independent_acceptance": False,
        "ref_or_commit_written": False,
    }, indent=2) + "\n")
    patch = subprocess.check_output(["git", "-C", str(root), "diff", "--cached", "--binary", BASE])
    (output / "proposed-source.diff").write_bytes(patch)
    subprocess.run(["git", "-C", str(root), "archive", "--format=tar.gz", "--output", str(output / "proposed-source.tar.gz"), expected], check=True)
    print(f"Proposed content-addressed tree: {expected}; no commit/ref or acceptance written")

if __name__ == "__main__":
    operation, first, second = sys.argv[1:]
    if operation == "prepare": prepare(Path(first), Path(second))
    elif operation == "publish": publish(Path(first), Path(second))
    else: raise SystemExit("expected prepare or publish")
