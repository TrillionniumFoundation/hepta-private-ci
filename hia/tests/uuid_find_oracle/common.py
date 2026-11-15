"""Small source, command and immutable evidence helpers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def verify(record):
    require(binding(record["path"]) == record, "bound input changed: " + record["path"])


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def clean_identity(root):
    require(not git(root, "status", "--porcelain=v1", "--untracked-files=all").strip(),
            "the complete public gate requires a clean producing checkout")
    return {"head": git(root, "rev-parse", "HEAD").decode().strip(),
            "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip()}


def outside(path, roots):
    path = Path(path).resolve()
    require(not any(path == root or path.is_relative_to(root) for root in roots),
            "qualification outputs must be outside every source checkout")
    return path


class Commands:
    def __init__(self, output):
        self.output, self.records = output, []
        output.mkdir()

    def run(self, label, argv, *, cwd, env, jsonl=False):
        stdout = self.output / (label + (".jsonl" if jsonl else ".stdout"))
        stderr = self.output / (label + ".stderr")
        started = time.time()
        with stdout.open("xb") as out, stderr.open("xb") as err:
            done = subprocess.run([str(arg) for arg in argv], cwd=cwd, env=env, stdout=out, stderr=err)
        self.records.append({"label": label, "argv": [str(arg) for arg in argv], "cwd": str(cwd),
            "started_unix": started, "finished_unix": time.time(), "returncode": done.returncode,
            "signal": -done.returncode if done.returncode < 0 else None,
            "stdout": binding(stdout), "stderr": binding(stderr)})
        (self.output / "commands.json").write_text(json.dumps(self.records, indent=2) + "\n")
        require(done.returncode == 0, f"actual command failed: {label}; see {stderr}")
        return stdout

    def verify(self):
        for row in self.records:
            verify(row["stdout"])
            verify(row["stderr"])
        return binding(self.output / "commands.json")


def producer_files(producer):
    names = git(producer, "ls-files", "--cached", "-z").decode().split("\0")
    records = {}
    for name in filter(None, names):
        path = producer / name
        if path.is_symlink():
            data = os.readlink(path).encode()
            records[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "mode": stat.S_IMODE(path.lstat().st_mode), "symlink": True}
        else:
            require(path.is_file(), "missing producing file: " + name)
            records[name] = {"bytes": path.stat().st_size, "sha256": sha(path),
                             "mode": stat.S_IMODE(path.stat().st_mode), "symlink": False}
    return records
