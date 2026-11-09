"""Captured fixed executable sub-closure, distinct from the signed whole bundle."""

import os
from pathlib import Path
import stat
import sys
import types

from qualification.hcsn_training.joint_protocol import require, sha

HC_MODULES = (
    "joint_protocol", "joint_store", "joint_process", "joint_sources",
    "joint_outputs", "joint_lifecycle", "joint_runner", "joint_worker_adapter",
)
HC_FILES = ("qualification/hcsn_training/__init__.py",) + tuple(
    "qualification/hcsn_training/" + name + ".py"
    for name in (*HC_MODULES, "joint_supervisor")
)
H_FILES = (
    "scripts/joint_text_training_contract.py", "scripts/joint_text_training_io.py",
    "scripts/joint_text_training_compute.py", "scripts/joint_generation_v4_text_worker.py",
    "scripts/joint_generation_v4_model.py", "scripts/joint_generation_v4_io.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
)
ABSENT = (
    "qualification/__init__.py", "scripts/__init__.py", "experiments/__init__.py",
    "experiments/multimodal_output_portfolio/__init__.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/__init__.py",
)


def physical_bytes(path, cap):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "physical source path")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= cap, "source byte bound")

    def identity(value):
        return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        expected = identity(before)
        require(identity(os.fstat(fd)) == expected, "source open race")
        raw = bytearray()
        while len(raw) <= cap:
            part = os.read(fd, min(65536, cap + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        require(len(raw) == before.st_size and expected == identity(os.fstat(fd))
                == identity(path.lstat()), "source read race")
        return bytes(raw), expected
    finally:
        os.close(fd)


class Sources:
    def __init__(self, repo, bootstrap):
        self.repo = Path(repo)
        require(self.repo.resolve(strict=True) == self.repo, "physical source root")
        self.snapshots = {name: physical_bytes(self.repo / name, 262144) for name in (*HC_FILES, *H_FILES)}
        require(set(bootstrap) == set(HC_FILES)
                and all(self.snapshots[name][0] == raw for name, raw in bootstrap.items()), "HC captured bootstrap changed")
        self.rows = [dict(path=name, bytes=len(self.snapshots[name][0]), sha256=sha(self.snapshots[name][0]))
                     for name in sorted(self.snapshots)]
        self.absent = sorted(ABSENT)
        self.python_path = Path(sys.executable).absolute()
        self.python_resolved = self.python_path.resolve(strict=True)
        self.python_snapshot = physical_bytes(self.python_resolved, 128 * 1024 * 1024)
        self.python = dict(path=str(self.python_path), resolved_path=str(self.python_resolved),
                           bytes=len(self.python_snapshot[0]), sha256=sha(self.python_snapshot[0]))
        self.contract = types.ModuleType("_joint_bound_H_contract")
        contract_path = self.repo / H_FILES[0]
        self.contract.__file__ = str(contract_path)
        exec(compile(self.snapshots[H_FILES[0]][0], str(contract_path), "exec"), self.contract.__dict__)
        self.check()

    def check(self):
        for name, snapshot in self.snapshots.items():
            require(physical_bytes(self.repo / name, len(snapshot[0])) == snapshot, "captured execution source changed")
        for name in ABSENT:
            try:
                (self.repo / name).lstat()
            except FileNotFoundError:
                continue
            raise ValueError("unexpected source initializer")
        require(self.python_path.resolve(strict=True) == self.python_resolved
                and physical_bytes(self.python_resolved, len(self.python_snapshot[0])) == self.python_snapshot,
                "captured interpreter changed")

    def h_rows(self):
        return [row for row in self.rows if row["path"] in H_FILES]

    def h_absent(self):
        return sorted(name for name in ABSENT if name != "qualification/__init__.py")

    def h_digest(self):
        return self.contract.source_digest(self.h_rows(), self.h_absent())

    def validate_reservation(self, reservation):
        require(reservation["sources"] == self.rows and reservation["absent_sources"] == self.absent
                and reservation["python"] == self.python, "retained executable closure changed")
        self.check()
