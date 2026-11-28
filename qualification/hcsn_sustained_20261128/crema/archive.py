"""Verify the original study outputs and publish their allowlisted evidence to the results branch."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

REPO = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
BRANCH = "research/hcsn-sustained-boundary-20261128-1140569-results"
PREFIX = "qualification/hcsn_sustained_20261128/crema/evidence/"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def inventory(root, kind):
    term = read(root/"terminal.json")
    if term["seal_sha256"] != sha(root/"seal.json"):
        raise ValueError("seal checksum mismatch")
    sealed = read(root/"seal.json")
    files = {root/"terminal.json",root/"seal.json"}
    if kind == "edit":
        if len(sealed)!=15 or len(term["cells"])!=15:
            raise ValueError("incomplete edit conditions")
        for group in sealed.values():
            for row in group:
                weights=root/row["path"]
                if sha(weights)!=row["sha256"]:
                    raise ValueError("edit weights mismatch")
                files.update((weights,weights.parent/"fit.json",weights.parent/"cold.npz"))
    else:
        if len(sealed)!=12 or len(term["cells"])!=12:
            raise ValueError("incomplete sustained conditions")
        files.update(root/name for name in ("sessions.jsonl","segments.jsonl","events.jsonl"))
        for key,j in sealed.items():
            p=root/key
            progress=read(p/"progress.json")
            if progress["optimization_wall"] < 3150:
                raise ValueError("optimization under budget")
            for row in progress["history"]:
                if sha(p/row["file"]) != row["sha256"]:
                    raise ValueError("sustained checkpoint mismatch")
            files.update((p/"progress.json",p/"cold.npz",p/j["best"]["file"]))
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
