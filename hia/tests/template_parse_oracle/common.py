"""Bounded commands, complete checkout identities and immutable evidence."""
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
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
    require(path.is_file(), "bound input is not a regular file: " + str(path))
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
            "the complete public gate requires a clean checkout")
    return {"head": git(root, "rev-parse", "HEAD").decode().strip(),
            "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip()}


def outside(path, roots):
    path = Path(path).resolve()
    require(not any(path == root or path.is_relative_to(root) for root in roots),
            "qualification outputs must be outside the source and native build directories")
    return path


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


class Resources:
    """The target is separate; this bound covers evidence, stages and observers."""
    def __init__(self, work):
        self.work = work
        self.limit = 192 * 1024 * 1024
        self.reserve = 48 * 1024 * 1024
        require(self.free() >= 512 * 1024 * 1024, "public gate needs 512 MiB initial free space")
        current_soft, current_hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = 2 * 1024 * 1024 * 1024
        finite = [value for value in (current_soft, current_hard, limit) if value != resource.RLIM_INFINITY]
        resource.setrlimit(resource.RLIMIT_AS, (min(finite), current_hard))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        self.memory_limit = min(finite)

    def free(self):
        value = os.statvfs(self.work)
        return value.f_bavail * value.f_frsize

    def check(self, label, allowance=0):
        allocated = sum(path.stat().st_blocks * 512 for path in self.work.rglob("*") if path.is_file())
        available = self.free()
        require(allocated + allowance <= self.limit, "evidence budget exceeded: " + label)
        require(available >= self.reserve + allowance, "free-space reserve unavailable: " + label)
        return {"stage": label, "work_allocated_bytes": allocated, "work_limit_bytes": self.limit,
                "available_bytes": available, "reserve_bytes": self.reserve,
                "address_space_soft_limit_bytes": self.memory_limit, "cargo_workers": 1}


class Commands:
    def __init__(self, output, resources):
        self.output, self.records, self.resources = output, [], resources
        output.mkdir()

    def run(self, label, argv, *, cwd, env, jsonl=False):
        before = self.resources.check(label)
        stdout = self.output / (label + (".jsonl" if jsonl else ".stdout"))
        stderr = self.output / (label + ".stderr")
        record = {"label": label, "argv": [str(arg) for arg in argv], "cwd": str(cwd),
                  "started_unix": time.time(), "resources_before": before,
                  "environment": {key: env.get(key) for key in (
                      "RUSTC", "RUSTUP_TOOLCHAIN", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                      "CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL",
                      "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG",
                      "CODEX_HIA_NATIVE_LIB_DIR", "CLIPPY_ARGS")}}
        try:
            with stdout.open("xb") as out, stderr.open("xb") as err:
                done = subprocess.run(record["argv"], cwd=cwd, env=env, stdout=out, stderr=err)
            record.update(returncode=done.returncode, signal=-done.returncode if done.returncode < 0 else None)
        except BaseException as error:
            record["launch_or_wait_exception"] = repr(error)
            raise
        finally:
            record["finished_unix"] = time.time()
            record.update({name: binding(path) for name, path in (("stdout", stdout), ("stderr", stderr)) if path.exists()})
            self.records.append(record)
            (self.output / "commands.json").write_text(json.dumps(self.records, indent=2) + "\n")
        require(done.returncode == 0, f"actual command failed: {label}; see {stderr}")
        self.resources.check(label + " completed")
        return stdout

    def verify(self):
        for row in self.records:
            require(row.get("returncode") == 0, "a prerequisite command did not succeed")
            verify(row["stdout"])
            verify(row["stderr"])
        return binding(self.output / "commands.json")
