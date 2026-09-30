#!/usr/bin/env python3
"""Tracked-only source provenance for one exact channel.matrix checkout."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA1 = re.compile(r"[0-9a-f]{40}")
STAGES = ("checkout", "post-qualification")
DEFAULT_WORKFLOW = ".github/workflows/channel-matrix-readiness.yml"

def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, check=check, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=120)

def sha256(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def file_sha(path: Path) -> str: return sha256(path.read_bytes())

def read_json(path: Path) -> dict:
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out: raise ValueError(f"duplicate JSON key: {k}")
            out[k] = v
        return out
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32*1024*1024:
        raise ValueError("invalid source snapshot")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict): raise ValueError("source snapshot must be an object")
    return value

def clean(root: Path) -> dict:
    def rows(payload: bytes) -> list[str]:
        return [x.decode() for x in payload.split(b"\0") if x]
    tracked = rows(git(root, "diff", "--name-only", "-z", "HEAD", "--").stdout)
    staged = rows(git(root, "diff", "--cached", "--name-only", "-z", "HEAD", "--").stdout)
    others = rows(git(root, "ls-files", "--others", "--exclude-standard", "-z", "--").stdout)
    return {"clean": not tracked and not staged and not others, "trackedChanges": tracked,
            "stagedChanges": staged, "untrackedNonIgnored": others}

def exact(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA1.fullmatch(value): raise ValueError(f"invalid {label}")
    return value

def rust_env(root: Path) -> dict:
    version = target = "unavailable"
    try:
        text = subprocess.run(["rustc", "-vV"], cwd=root, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout
        version = text.strip()
        target = next((x.removeprefix("host: ") for x in text.splitlines() if x.startswith("host: ")), target)
    except (OSError, subprocess.SubprocessError): pass
    image = f"{os.getenv('ImageOS') or os.getenv('RUNNER_OS') or 'unknown'}@{os.getenv('ImageVersion') or 'unknown'}"
    return {"workflowRunId": os.getenv("GITHUB_RUN_ID"), "attemptId": os.getenv("GITHUB_RUN_ATTEMPT"),
            "runnerImage": image, "runnerOs": os.getenv("RUNNER_OS", "unknown"),
            "runnerArch": os.getenv("RUNNER_ARCH", "unknown"), "targetTriple": target,
            "rustcVersionVerbose": version}

def build(root_value: Path, snapshot_path: Path, expected_sha: str, stage: str, workflow_path: str) -> dict:
    if stage not in STAGES: raise ValueError("unsupported provenance stage")
    root = root_value.resolve(strict=True); expected_sha = exact(expected_sha, "expected SHA")
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
    if head != expected_sha: raise ValueError("checkout SHA drifted")
    source = read_json(snapshot_path)
    if source.get("schema") != "hepta.channel-matrix-source-snapshot.v1" or source.get("testedSha") != head or source.get("testedTree") != tree:
        raise ValueError("source snapshot does not bind checkout")
    before = clean(root)
    if not before["clean"]: raise ValueError("checkout is not clean")
    tracked = {x.decode() for x in git(root, "ls-files", "-z", "--").stdout.split(b"\0") if x}
    files = []
    requested = source.get("files")
    if not isinstance(requested, list) or not requested: raise ValueError("source snapshot lacks files")
    for item in requested:
        rel = item.get("path") if isinstance(item, dict) else None
        if not isinstance(rel, str) or rel not in tracked: raise ValueError(f"non-tracked source path: {rel}")
        if git(root, "ls-files", "--error-unmatch", "--", rel, check=False).returncode:
            raise ValueError(f"git ls-files --error-unmatch failed: {rel}")
        path = (root / rel).resolve(strict=True)
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError(f"non-canonical source path: {rel}")
        data = path.read_bytes(); blob = git(root, "rev-parse", f"HEAD:{rel}").stdout.decode().strip()
        actual = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        if actual != blob or item.get("gitBlob") != blob or item.get("sha256") != sha256(data) or item.get("bytes") != len(data):
            raise ValueError(f"source bytes/blob mismatch: {rel}")
        first = git(root, "log", "--diff-filter=A", "--format=%H", "--reverse", "--", rel, check=False)
        first_sha = next((x for x in first.stdout.decode("ascii", "strict").splitlines() if x), head)
        fixture = "/fixtures/" in f"/{rel}/" or rel.startswith("tests/fixtures/")
        files.append({"absolutePath": str(path), "repoRelativePath": rel, "gitBlob": blob,
                      "sha256": sha256(data), "bytes": len(data), "tracked": True,
                      "gitLsFilesErrorUnmatch": True, "firstTrackedCommit": first_sha,
                      "firstAppearanceStage": "repository_history",
                      "sourceClass": "tracked_fixture" if fixture else "tracked_repository_source",
                      "fromGeneratedDirectory": False, "fromCache": False,
                      "fromArtifactDownload": False, "fixture": fixture})
    workflow_rel = Path(workflow_path)
    if workflow_rel.is_absolute() or ".." in workflow_rel.parts or workflow_path not in tracked:
        raise ValueError("workflow is not a tracked repository path")
    workflow = (root / workflow_rel).resolve(strict=True)
    workflow_blob = git(root, "rev-parse", f"HEAD:{workflow_path}").stdout.decode().strip()
    after = clean(root)
    if not after["clean"]: raise ValueError("checkout changed during source scan")
    return {"schema": "hepta.channel-matrix-source-provenance.v1", "stage": stage,
            "workspaceRoot": str(root), "checkoutSha": head, "treeSha": tree,
            "sourceSnapshotSha256": file_sha(snapshot_path),
            "scan": {"discoveryCommand": ["git","ls-files","-z","--"],
                     "verificationCommand": ["git","ls-files","--error-unmatch","--","<path>"],
                     "trackedRepositoryFileCount": len(tracked), "reportedSourceFileCount": len(files),
                     "filesystemWalkUsed": False},
            "workflow": {"path": workflow_path, "gitBlob": workflow_blob, "sha256": file_sha(workflow)},
            "execution": rust_env(root), "cleanTreeBefore": before, "cleanTreeAfter": after,
            "files": files, "claims": {"trackedOnly": True, "sourceClosurePassed": True,
            "generatedInputsIncluded": False, "cacheInputsIncluded": False,
            "artifactDownloadsIncluded": False, "productionQualified": False,
            "authorityGranted": False}}

def build_provenance(root: Path, snapshot: Path, expected_sha: str, stage: str) -> dict:
    workflow = DEFAULT_WORKFLOW
    if not (root / workflow).exists():
        workflow = ".github/workflows/channel-matrix-preserve-unknown.yml"
    return build(root, snapshot, expected_sha, stage, workflow)

def write(path_value: Path, value: dict, root: Path) -> None:
    path = path_value.absolute(); parent = path.parent.resolve(strict=True)
    if path_value.is_symlink() or path.exists() or parent.is_relative_to(root.resolve()):
        raise ValueError("output must be new and outside checkout")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True); stream.write("\n")

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-snapshot", type=Path, required=True); p.add_argument("--expected-sha", required=True)
    p.add_argument("--stage", choices=STAGES, required=True); p.add_argument("--workflow-path", default=DEFAULT_WORKFLOW)
    p.add_argument("--output", type=Path, required=True); p.add_argument("--repository-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = p.parse_args()
    try: write(a.output, build(a.repository_root, a.source_snapshot, a.expected_sha, a.stage, a.workflow_path), a.repository_root)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        p.exit(1, f"FAIL_CHANNEL_MATRIX_SOURCE_PROVENANCE: {exc}\n")
    return 0
if __name__ == "__main__": raise SystemExit(main())
