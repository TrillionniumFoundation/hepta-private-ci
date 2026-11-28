"""Exact OTEL time migration; source custody is separate from runtime qualification."""
import json
from pathlib import Path
import stat

from .dependencies import ROOT_FILES, _identity, _pair_identity, _read

HISTORY = Path(__file__).with_name("otel_source_history_20261128.json")
HISTORY_SHA256 = "298ba4ea19333fc3ec22526767815efcaacff113b9e2a5f829b70ef56c7d2d0f"
CRATE = "codex-rs/otel"


def _history(path=HISTORY):
    data, binding = _read(path)
    if binding["sha256"] != HISTORY_SHA256:
        raise RuntimeError("complete OTEL dependency history changed")
    value = json.loads(data)
    if value["schema"] != "codex.hia.otel-dependency-source-history.v1":
        raise RuntimeError("unrecognized OTEL dependency source history")
    return value, binding


def _directory(path):
    path = Path(path).absolute()
    before = path.lstat()
    if not stat.S_ISDIR(before.st_mode) or path.resolve(strict=True) != path:
        raise RuntimeError("OTEL source directory must be physical: " + str(path))
    return {"path": str(path), "device": before.st_dev, "inode": before.st_ino,
            "mode": stat.S_IMODE(before.st_mode), "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns, "links": before.st_nlink}


def _crate(repo, history):
    root = Path(repo).absolute() / CRATE
    files, directories, pending = {}, {}, [root]
    while pending:
        directory = pending.pop()
        binding = _directory(directory)
        directories[directory.relative_to(root).as_posix()] = binding
        for path in sorted(directory.iterdir()):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                files[path.relative_to(root).as_posix()] = _read(path)
            else:
                raise RuntimeError("OTEL source must be a physical regular file: " + str(path))
        if _directory(directory) != binding:
            raise RuntimeError("OTEL source directory changed during capture")
    expected = history["crate"]["current_files"]
    if set(files) != set(expected) or sorted(directories) != history["crate"]["directories"]:
        raise RuntimeError("complete OTEL source inventory changed")
    for path, (data, binding) in files.items():
        mode = "100755" if binding["mode"] & 0o111 else "100644"
        if _identity(data) != expected[path] or mode != history["crate"]["modes"][path]:
            raise RuntimeError("physical OTEL source changed: " + path)
    original = {}
    for path, (data, _) in files.items():
        if path in history["crate"]["inverse"]:
            before = history["crate"]["inverse"][path]["before"]
            if before is None:
                continue
            data = before.encode()
        original[path] = _identity(data)
    if original != history["crate"]["original_files"]:
        raise RuntimeError("complete OTEL source inverse changed")
    return {"files": {p: row[1] for p, row in files.items()}, "directories": directories}


def restore_predecessor(repo, actual, predecessor_identity):
    history, history_binding = _history()
    if _pair_identity(actual) != history["current_files"]:
        raise RuntimeError("unreviewed or mixed workspace dependency source pair")
    if predecessor_identity != history["predecessor_files"]:
        raise RuntimeError("OTEL source predecessor differs from the complete OAuth2 pair")
    physical = {p: _read(Path(repo) / p) for p in ROOT_FILES}
    if {p: row[0] for p, row in physical.items()} != actual:
        raise RuntimeError("OTEL source input differs from physical current pair")
    restored = dict(actual)
    blocks = restored[ROOT_FILES[1]].split(b"\n[[package]]\n")
    after = history["lock_inverse"]["after"].encode()
    if blocks.count(after) != 1:
        raise RuntimeError("OTEL lock inverse must match one complete package")
    blocks[blocks.index(after)] = history["lock_inverse"]["before"].encode()
    restored[ROOT_FILES[1]] = b"\n[[package]]\n".join(blocks)
    if _pair_identity(restored) != predecessor_identity:
        raise RuntimeError("OTEL inverse did not recover the complete OAuth2 pair")
    bazel_data, bazel_binding = _read(Path(repo) / "MODULE.bazel.lock")
    if _identity(bazel_data) != history["bazel_lock"]:
        raise RuntimeError("OTEL current Bazel dependency lock changed")
    crate = _crate(repo, history)
    _, helper_binding = _read(__file__)
    report = {"schema": "codex.hia.otel-dependency-source-admission.v1",
              "source_variant": history["source_variant"],
              "repo": str(Path(repo).absolute()),
              "actual_files": {p: row[1] for p, row in physical.items()},
              "predecessor_files": predecessor_identity, "crate": crate,
              "bazel_lock": bazel_binding, "history": history_binding, "helper": helper_binding,
              "unchanged_lock_packages": history["unchanged_lock_packages"],
              "dependency_graph_equivalence_claimed": False}
    return {"restored": restored, "report": report}


def verify_predecessor(admission):
    if admission is None:
        return
    report = admission["report"]
    for binding in [*report["actual_files"].values(), report["bazel_lock"],
                    report["history"], report["helper"]]:
        _, actual = _read(binding["path"])
        if actual != binding:
            raise RuntimeError("captured OTEL source identity changed: " + binding["path"])
    history, _ = _history()
    if _crate(report["repo"], history) != report["crate"]:
        raise RuntimeError("captured OTEL crate identity changed")
