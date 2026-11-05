"""Exact owned-source guards. No ordinary index/ref/HEAD writes or resets."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def record(path):
    p = Path(path)
    need(p.is_file(), "missing file: " + str(p))
    h = hashlib.sha256()
    size = 0
    with p.open("rb") as f:
        while b := f.read(1024 * 1024):
            h.update(b)
            size += len(b)
    return {"path": str(p), "bytes": size, "sha256": h.hexdigest()}


def same_record(path, expected):
    actual = record(path)
    return all(actual[k] == expected[k] for k in ("bytes", "sha256"))


def relative(path):
    p = PurePosixPath(path)
    need(bool(p.parts) and not p.is_absolute() and ".." not in p.parts and ".git" not in p.parts,
         "unsafe relative source path: " + path)
    need(str(p) == path, "non-canonical source path")
    return p


def validate_binding(b, manifest_sha):
    # Run before mkdir, Git, environment probes, source writes or subprocesses.
    for key in ("final_A_tree", "initial_tree", "ordinary_head"):
        value = b.get(key)
        need(isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value),
             "explicit reviewed " + key + " is required; the unbound template cannot run")
    need(b.get("approved_payload_sha256") == manifest_sha, "payload approval identity mismatch")
    need(b.get("authorized_epoch") in ("foundation", "driver", "pool", "checkpoint", "owning"), "epoch missing")
    need(b.get("approval_reference") and b.get("execute") is True, "explicit execution guard missing")
    need(set(b["locks"]) == {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}, "both real locks required")
    need(b.get("cargo_profile") == "dev-small" and b.get("nextest_profile") == "local", "unreviewed profiles")
    need(b.get("junit_relative_path") == "codex-rs/target/nextest/local/junit.xml", "review actual original nextest report path")
    need(isinstance(b.get("ordinary_index"), dict) and b["ordinary_index"].get("sha256"), "ordinary index pin missing")
    need(isinstance(b.get("baseline_metadata"), dict) and b["baseline_metadata"].get("sha256"), "actual full metadata pin missing")
    need(b.get("allowed_untracked_source_paths") == [], "review nonempty untracked allowlist separately")
    need(b.get("min_free_bytes") == 8000000000, "keep the existing 8 GB prerequisite")
    need({t.get("name") for t in b.get("tools", [])} >= {"git", "cargo", "rustc", "just", "cargo-nextest", "bazel"}, "pin all six actual tool files")
    need({r.get("path") for r in b.get("recipe_sources", [])} >=
         {"justfile", "scripts/run-nextest.py", "scripts/check-module-bazel-lock.sh", ".bazelrc", "defs.bzl"},
         "pin the actual recipe, launcher, lock check and Bazel registration sources")
    if b["authorized_epoch"] == "foundation":
        need(b["initial_tree"] == b["final_A_tree"], "foundation must start at final A")
    else:
        need(b.get("previous_epoch_receipt") and b["previous_epoch_receipt"].get("sha256"), "previous qualified epoch is required")


class SourceGuard:
    def __init__(self, binding, manifest, sources, out, env):
        self.b, self.manifest, self.sources = binding, manifest, sources
        self.tree, self.out, self.env = Path(binding["source_directory"]).resolve(), Path(out), env
        self.source, self.locks, self.sequence = binding["initial_tree"], dict(binding["locks"]), 0
        self.extra_untracked = {}

    def save(self, name, value):
        p = self.out / (name + ".json")
        with p.open("xb") as f:
            f.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
        return record(p)

    def git(self, args, env=None, data=None):
        r = subprocess.run(["git", *args], cwd=self.tree, env=env or self.env,
                           input=data, capture_output=True, check=False)
        need(r.returncode == 0, "Git failed: " + repr(args) + "\n" + r.stderr.decode(errors="replace"))
        return r.stdout

    def private_index(self, label):
        self.sequence += 1
        env = dict(self.env, GIT_INDEX_FILE=str(self.out / f"{self.sequence:04}-{label}.index"))
        need(not Path(env["GIT_INDEX_FILE"]).exists(), "private index collision")
        return env

    def check_path(self, path):
        p = self.tree / relative(path)
        for parent in (p, *p.parents):
            if parent == self.tree:
                break
            need(not parent.is_symlink(), "symlink in approved source path: " + path)
        need(p.resolve().is_relative_to(self.tree), "source path escaped checkout")
        return p

    def snapshot(self, label, except_locks=()):
        env = self.private_index(label)
        self.git(["read-tree", self.source], env)
        self.git(["add", "-u", "--", "."], env)
        actual = self.git(["write-tree"], env).decode().strip()
        untracked = [os.fsdecode(p) for p in self.git(["ls-files", "--others", "--exclude-standard", "-z"], env).split(b"\0") if p]
        index = Path(self.git(["rev-parse", "--git-path", "index"]).decode().strip())
        index = index if index.is_absolute() else self.tree / index
        head = self.git(["rev-parse", "HEAD"]).decode().strip()
        observed = {"label": label, "expected_tree": self.source, "actual_tree": actual,
                    "head": head, "ordinary_index": record(index), "untracked": untracked,
                    "locks": {p: record(self.tree / p) for p in self.locks}}
        self.save(f"{self.sequence:04}-{label}-guard", observed)
        need(head == self.b["ordinary_head"], "ordinary HEAD changed")
        need(same_record(index, self.b["ordinary_index"]), "ordinary index changed")
        need(set(untracked) <= set(self.extra_untracked), "unreviewed untracked source paths")
        for p in self.locks:
            file = self.check_path(p)
            need(file.is_file() and not file.stat().st_mode & 0o111, "lock must stay a regular non-executable file")
        for p, expected in self.extra_untracked.items():
            need(same_record(self.check_path(p), expected), "owned temporary config drift")
        for p, expected in self.locks.items():
            if p not in except_locks:
                need(same_record(self.check_path(p), expected), "lock drift: " + p)
        return actual

    def guard(self, label):
        need(self.snapshot(label) == self.source, "whole source drift: " + label)

    def predict(self, rows, label):
        # Expected tree is computed from the approved preimages + approved bytes,
        # before any working-tree write. It is not the post-write snapshot itself.
        env = self.private_index(label + "-expected")
        self.git(["read-tree", self.source], env)
        for f in rows:
            path = relative(f["path"])
            listing = self.git(["ls-files", "--stage", "--", str(path)], env).decode().strip()
            before = listing.split()[1] if listing else None
            need(before == f["before_blob"], "approved preimage differs from current source: " + str(path))
            if listing:
                need(listing.split()[0] == f["mode"], "source mode changed")
            b = self.sources[f["after_blob"]]["text"].encode()
            need(identity(b) == {"blob": f["after_blob"], "bytes": f["bytes"], "sha256": f["sha256"]}, "payload byte mismatch")
            blob = self.git(["hash-object", "-w", "--stdin"], data=b).decode().strip()
            need(blob == f["after_blob"], "Git object mismatch")
            self.git(["update-index", "--add", "--cacheinfo", f["mode"], blob, str(path)], env)
        return self.git(["write-tree"], env).decode().strip()

    def apply(self, name):
        d = self.manifest["deltas"][name]
        self.guard(name + "-before")
        expected = self.predict(d["files"], name)
        for f in d["files"]:
            p = self.check_path(f["path"])
            need((not p.exists()) if f["before_blob"] is None else
                 p.is_file() and identity(p.read_bytes())["blob"] == f["before_blob"], "working preimage mismatch")
        before = self.source
        for f in d["files"]:
            p = self.check_path(f["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix=".b16-owned-", dir=p.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(self.sources[f["after_blob"]]["text"].encode())
                os.chmod(temp, int(f["mode"][-3:], 8))
                os.replace(temp, p)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        self.source = expected
        self.guard(name + "-after")
        self.save(name + "-applied", {"before_tree": before, "after_tree": expected, "delta": d})

    def accept_generated_locks(self, label, permitted):
        actual = self.snapshot(label, permitted)
        changed = self.git(["diff-tree", "--no-commit-id", "--name-only", "-r", self.source, actual]).decode().splitlines()
        need(set(changed) <= set(permitted), "generator changed non-permitted source: " + repr(changed))
        before = self.source
        old = dict(self.locks)
        self.source = actual
        self.locks = {p: record(self.tree / p) for p in self.locks}
        self.save(label + "-actual-lock-delta", {"before_tree": before, "after_tree": actual,
                  "changed_paths": changed, "locks_before": old, "locks_after": self.locks,
                  "actual_diff": self.git(["diff", before, actual, "--", *permitted]).decode()})
        self.guard(label + "-accepted-only-generated-paths")
