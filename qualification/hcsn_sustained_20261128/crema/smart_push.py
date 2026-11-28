"""Publish verified panel parts through Git transport using the existing private results branch."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from archive import BRANCH, PREFIX, sha
from publish_results import HOST_DIR, SSH, run


def publish(files, kind, root, repo):
    base = root / kind
    git = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
           "--git-dir=" + str(repo)]
    entries = []
    for path in files:
        name = str(path.relative_to(base))
        if name.startswith("/") or any(c in name for c in "\t\r\n") or ".." in Path(name).parts:
            raise ValueError(name)
        content = path.read_bytes()
        want = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        oid = run(git + ["hash-object", "-w", str(path)]).decode().strip()
        if oid != want:
            raise ValueError(name)
        entries.append(f"100644 {oid}\t{PREFIX}{kind}/{name}\n")
    for attempt in range(6):
        run(git + ["fetch", "--quiet", "--no-tags", "--depth=1", "--filter=blob:none", "origin", "refs/heads/" + BRANCH])
        head = run(git + ["rev-parse", "FETCH_HEAD"]).decode().strip()
        with tempfile.TemporaryDirectory(dir=root) as folder:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / "index"))
            def operation(args, data=None):
                return subprocess.run(git + args, env=env, input=data, check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900).stdout.decode().strip()
            operation(["read-tree", head])
            operation(["update-index", "--index-info"], "".join(entries).encode())
            tree = operation(["write-tree"])
            if tree == operation(["rev-parse", head + "^{tree}"]):
                return head
            commit = operation(["-c", "user.name=Hepta Research", "-c", "user.email=hepta-research@users.noreply.github.com",
                                "commit-tree", tree, "-p", head, "-m", "Archive verified CREMA-D " + kind + " research"])
            try:
                operation(["push", "--quiet", "origin", commit + ":refs/heads/" + BRANCH])
            except subprocess.CalledProcessError as exc:
                if attempt == 5:
                    raise RuntimeError(exc.stderr.decode(errors="replace")[-900:]) from exc
                time.sleep(5)
                continue
            actual = run(git + ["ls-remote", "--heads", "origin", "refs/heads/" + BRANCH]).decode().split()[0]
            if actual == commit:
                return commit
    raise RuntimeError("concurrent results update")


def stage(root, base, kind, repo):
    local = root / kind
    local.mkdir(exist_ok=True, parents=True)
    remote = str(base) + "/" + kind
    manifest = json.loads(run(SSH + ["cat", remote + "/manifest.json"]))
    names = ["manifest.json"] + [r["name"] for r in manifest["parts"]]
    if any(Path(n).name != n or ".." in n or "\n" in n for n in names):
        raise ValueError("bad part")
    run(["rsync", "-a", "--files-from=-", "-e", "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
         "ai395:" + remote + "/", str(local) + "/"], ("\n".join(names) + "\n").encode())
    combined = hashlib.sha256()
    for part in manifest["parts"]:
        content = (local / part["name"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != part["sha256"]:
            raise ValueError("part digest")
        combined.update(content)
    if combined.hexdigest() != manifest["archive_sha256"]:
        raise ValueError("archive digest")
    with (repo.parent / "update.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        commit = publish([local / n for n in names], kind, root, repo)
    receipt = dict(files=manifest["file_count"], parts=len(manifest["parts"]), archive_sha256=combined.hexdigest(),
                   terminal_sha256=manifest["terminal_sha256"], commit=commit, utc=time.time())
    tmp = root / (kind + "-receipt.tmp")
    tmp.write_text(json.dumps(receipt, indent=2) + "\n")
    tmp.replace(root / (kind + "-receipt.json"))
    print(kind, json.dumps(receipt), flush=True)


if __name__ == "__main__":
    root, repo, remote = map(Path, sys.argv[1:4])
    root.mkdir(exist_ok=True, parents=True)
    for kind in sys.argv[4:]:
        while not (root / (kind + "-receipt.json")).is_file():
            try:
                stage(root, remote, kind, repo)
            except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(kind, str(exc)[-900:], flush=True)
                time.sleep(45)
