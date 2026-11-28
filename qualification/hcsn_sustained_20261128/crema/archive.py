"""Verify the original study outputs and publish their allowlisted evidence to the results branch."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

REPO = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
BRANCH = "research/hcsn-sustained-boundary-20261128-1140569-results"
PREFIX = "qualification/hcsn_sustained_20261128/crema/evidence/"
COLD_SCHEMA = "hcsn-cold-selection-v1"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def retain(path, payload):
    """Keep the first bytes; an exact resumed write is idempotent."""
    fd, temporary = tempfile.mkstemp(prefix=".cold-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError("retained evidence bytes changed: " + path.name)
    finally:
        Path(temporary).unlink()


def retain_cold_scores(root, checkpoint, arrays, best=False):
    """Bind every actually scored checkpoint to its original numeric output."""
    import numpy as np

    name = checkpoint["file"]
    if Path(name).name != name or not name.endswith(".pt"):
        raise ValueError("unexpected checkpoint name")
    output = root / ("cold-" + Path(name).stem + ".npz")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    payload = buffer.getvalue()
    retain(output, payload)
    if best:
        retain(root / "cold.npz", payload)
    return dict(
        file=output.name, sha256=sha(output), checkpoint_sha256=checkpoint["sha256"]
    )


def retain_cold_index(root, index):
    retain(
        root / "cold_index.json",
        (json.dumps(index, sort_keys=True, indent=2) + "\n").encode(),
    )


def inventory(root, kind):
    """Publisher boundary: this pinned collector requires the current run profile."""
    return _inventory(root, kind, require_cold_schema=True)


def legacy_inventory(root):
    """Recover surviving originals without certifying complete cold evidence."""
    return dict(
        status="UNKNOWN",
        complete=False,
        reason="legacy runs may lack original quality-gate score arrays",
        files=_inventory(root, "run", require_cold_schema=False),
    )


def _inventory(root, kind, *, require_cold_schema):
    term = read(root / "terminal.json")
    if term["seal_sha256"] != sha(root / "seal.json"):
        raise ValueError("seal checksum mismatch")
    sealed = read(root / "seal.json")
    files = {root / "terminal.json", root / "seal.json"}
    if kind == "edit":
        if len(sealed) != 15 or len(term["cells"]) != 15:
            raise ValueError("incomplete edit conditions")
        for group in sealed.values():
            for row in group:
                weights = root / row["path"]
                if sha(weights) != row["sha256"]:
                    raise ValueError("edit weights mismatch")
                files.update(
                    (weights, weights.parent / "fit.json", weights.parent / "cold.npz")
                )
    else:
        if len(sealed) != 12 or len(term["cells"]) != 12:
            raise ValueError("incomplete sustained conditions")
        schema = term.get("cold_evidence_schema")
        if require_cold_schema and schema != COLD_SCHEMA:
            raise ValueError("pinned collector requires current cold evidence schema")
        if schema is not None and schema != COLD_SCHEMA:
            raise ValueError("unsupported cold evidence schema")
        files.update(
            root / name for name in ("sessions.jsonl", "segments.jsonl", "events.jsonl")
        )
        for key, j in sealed.items():
            p = root / key
            progress = read(p / "progress.json")
            if progress["optimization_wall"] < 3150:
                raise ValueError("optimization under budget")
            for row in progress["history"]:
                weights = p / row["file"]
                if sha(weights) != row["sha256"]:
                    raise ValueError("sustained checkpoint mismatch")
                files.add(weights)
            selected = [
                row for row in [j["best"], *j["gates"].values()] if row is not None
            ]
            if any(row not in progress["history"] for row in selected):
                raise ValueError("sealed checkpoint is absent from verified history")
            needed = {row["file"]: row for row in selected}
            index_path = p / "cold_index.json"
            if schema == COLD_SCHEMA and not index_path.is_file():
                raise ValueError("declared cold index is missing")
            if index_path.exists():
                index = read(index_path)
                if set(index) != set(needed):
                    raise ValueError("cold index does not cover the sealed selections")
                for name, row in needed.items():
                    item = index[name]
                    expected_name = "cold-" + Path(name).stem + ".npz"
                    if (
                        item["file"] != expected_name
                        or item["checkpoint_sha256"] != row["sha256"]
                        or sha(p / item["file"]) != item["sha256"]
                    ):
                        raise ValueError("cold score binding mismatch")
                    files.add(p / item["file"])
                if sha(p / "cold.npz") != index[j["best"]["file"]]["sha256"]:
                    raise ValueError("selected cold score alias mismatch")
                files.add(index_path)
            # Legacy runs retain every original checkpoint and their existing best
            # scores. Missing historical gate scores are never manufactured here.
            files.update((p / "progress.json", p / "cold.npz"))
    return sorted(files)


def run(args, cwd, data=None):
    cmd = ["git",*args]
    q=subprocess.run(cmd,cwd=cwd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     env={**os.environ,"GIT_TERMINAL_PROMPT":"0"},timeout=600)
    if q.returncode:
        # The command uses a fixed credential-free repository name.
        raise RuntimeError(f"git {args[0]} returned {q.returncode}: {q.stderr.decode(errors='replace')[-350:]}")
    return q.stdout.decode().strip()


def publish(path,kind,repo,files):
    listing=[]
    for p in files:
        oid=run(["hash-object","-w","--",str(p)],repo)
        listing.append((str(p.relative_to(path)),oid))
    if not listing:
        raise ValueError("missing evidence")
    for _ in range(5):
        run(["fetch","--depth=1","--filter=blob:none","origin","refs/heads/"+BRANCH],repo)
        base=run(["rev-parse","FETCH_HEAD"],repo)
        run(["read-tree",base],repo)
        entries=b"".join((f"100644 blob {oid}\t{PREFIX}{kind}/{dest}\0").encode() for dest,oid in listing)
        run(["update-index","-z","--index-info"],repo,entries)
        tree=run(["write-tree","--missing-ok"],repo)
        if tree==run(["rev-parse",base+"^{tree}"],repo):
            return base
        commit=run(["-c","user.name=HCSN Research Runner","-c","user.email=hcsn-research@users.noreply.github.com",
                    "commit-tree",tree,"-p",base],repo,f"Archive verified CREMA-D {kind} results and trained states\n".encode())
        try:
            run(["push","origin",f"{commit}:refs/heads/{BRANCH}"],repo)
        except RuntimeError:
            fresh=run(["ls-remote","--heads","origin","refs/heads/"+BRANCH],repo).split()[0]
            if fresh==commit:
                return commit
            if fresh==base:
                raise
            continue
        return commit
    raise RuntimeError("concurrent branch updates exhausted retries")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("study",type=Path)
    a=p.parse_args()
    task=a.study.resolve()
    state=task/"archive"
    state.mkdir(exist_ok=True)
    with (state/"archive.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        repo=state/"objects.git"
        if not repo.exists():
            run(["init","--bare",str(repo)],state)
        if not run(["remote"],repo):
            run(["remote","add","origin",REPO],repo)
        for kind in ("edit","run"):
            path=task/kind
            while not (path/"terminal.json").is_file():
                time.sleep(45)
            files=inventory(path,kind)
            record=state/(kind+".json")
            identities={str(f.relative_to(path)):sha(f) for f in files}
            if record.exists() and read(record).get("objects")==identities:
                continue
            for attempt in range(5):
                try:
                    tip=publish(path,kind,repo,files)
                    break
                except (RuntimeError,subprocess.TimeoutExpired) as exc:
                    print(kind,str(exc),flush=True)
                    if attempt==4:
                        raise
                    time.sleep(min(60,5*2**attempt))
            temp=record.with_suffix(".tmp")
            temp.write_text(json.dumps(dict(commit=tip,branch=BRANCH,objects=identities),indent=1)+"\n")
            temp.replace(record)
            print(kind,tip,len(files),flush=True)


if __name__=="__main__":
    main()
