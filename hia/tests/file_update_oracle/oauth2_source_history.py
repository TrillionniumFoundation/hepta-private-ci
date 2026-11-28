"""Pinned OAuth2 source transition; dependency behavior is qualified separately."""
import json
from pathlib import Path
import stat

from .dependencies import ROOT_FILES, _identity, _pair_identity, _read

HISTORY = Path(__file__).with_name("oauth2_source_history_20261128.json")
HISTORY_SHA256 = "3ce6e2158869d74f5c2a26d124bfcdd0ae17375fbe61c128822749d33184aac0"
VENDOR = "codex-rs/third_party/oauth2-5.0.0"


def _history(path=HISTORY):
    data, binding = _read(path)
    if binding["sha256"] != HISTORY_SHA256:
        raise RuntimeError("complete OAuth2 dependency history changed")
    value = json.loads(data)
    if value["schema"] != "codex.hia.oauth2-dependency-source-history.v1":
        raise RuntimeError("unrecognized OAuth2 dependency source history")
    return value, binding


def _directory(path):
    path = Path(path).absolute()
    before = path.lstat()
    if not stat.S_ISDIR(before.st_mode) or path.resolve(strict=True) != path:
        raise RuntimeError("OAuth2 source directory must be physical: " + str(path))
    return {"path": str(path), "device": before.st_dev, "inode": before.st_ino,
            "mode": stat.S_IMODE(before.st_mode), "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns, "links": before.st_nlink}


def _vendor(repo, history):
    root = Path(repo).absolute() / VENDOR
    files, directories, pending = {}, {}, [root]
    while pending:
        directory = pending.pop()
        binding = _directory(directory)
        key = directory.relative_to(root).as_posix()
        directories[key] = binding
        for path in sorted(directory.iterdir()):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(path)
            elif stat.S_ISREG(mode):
                key = path.relative_to(root).as_posix()
                files[key] = _read(path)
            else:
                raise RuntimeError("OAuth2 source must be a physical regular file: " + str(path))
        if _directory(directory) != binding:
            raise RuntimeError("OAuth2 source directory changed during capture")
    expected = history["vendor"]["current_files"]
    if set(files) != set(expected) or sorted(directories) != history["vendor"]["directories"]:
        raise RuntimeError("complete OAuth2 vendor inventory changed")
    for path, (data, _) in files.items():
        if _identity(data) != expected[path]:
            raise RuntimeError("physical OAuth2 source changed: " + path)
    upstream = {}
    inverse = history["vendor"]["inverse"]
    for path, (data, _) in files.items():
        if path in inverse:
            before = inverse[path]["before"]
            if before is None:
                continue
            data = before.encode()
        upstream[path] = _identity(data)
    if upstream != history["vendor"]["original_files"]:
        raise RuntimeError("complete OAuth2 upstream source inverse changed")
    return {"files": {p: row[1] for p, row in files.items()},
            "directories": directories}


def restore_predecessor(repo, actual, predecessor_identity):
    history, history_binding = _history()
    if predecessor_identity != history["predecessor_files"]:
        raise RuntimeError("OAuth2 source predecessor differs from frozen SQLx pair")
    physical = {p: _read(Path(repo) / p) for p in ROOT_FILES}
    if {p: row[0] for p, row in physical.items()} != actual:
        raise RuntimeError("OAuth2 source input differs from physical current pair")
    restored = dict(actual)
    otel_admission = None
    if _pair_identity(actual) != history["current_files"]:
        from .otel_source_history import restore_predecessor as restore_otel
        otel_admission = restore_otel(repo, actual, history["current_files"])
        restored = otel_admission["restored"]
    for splice in history["manifest_inverse"]:
        after, before = splice["after"].encode(), splice["before"].encode()
        if restored[ROOT_FILES[0]].count(after) != 1:
            raise RuntimeError("OAuth2 manifest inverse must have one exact match")
        restored[ROOT_FILES[0]] = restored[ROOT_FILES[0]].replace(after, before, 1)
    blocks = restored[ROOT_FILES[1]].split(b"\n[[package]]\n")
    after = history["lock_inverse"]["after"].encode()
    if blocks.count(after) != 1:
        raise RuntimeError("OAuth2 lock inverse must match one complete package")
    blocks[blocks.index(after)] = history["lock_inverse"]["before"].encode()
    restored[ROOT_FILES[1]] = b"\n[[package]]\n".join(blocks)
    if _pair_identity(restored) != predecessor_identity:
        raise RuntimeError("OAuth2 inverse did not recover the complete SQLx pair")
    bazel_data, bazel_binding = _read(Path(repo) / "MODULE.bazel.lock")
    if _identity(bazel_data) != history["bazel_lock"]:
        raise RuntimeError("OAuth2 current Bazel dependency lock changed")
    vendor = _vendor(repo, history)
    _, helper_binding = _read(__file__)
    report = {"schema": "codex.hia.oauth2-dependency-source-admission.v1",
              "source_variant": history["source_variant"],
              "repo": str(Path(repo).absolute()),
              "actual_files": {p: row[1] for p, row in physical.items()},
              "predecessor_files": predecessor_identity,
              "upstream_archive": history["vendor"]["upstream_archive"],
              "vendor": vendor, "bazel_lock": bazel_binding,
              "history": history_binding, "helper": helper_binding,
              "dependency_graph_equivalence_claimed": False}
    if otel_admission is not None:
        report["otel_source_history"] = otel_admission["report"]
        report["workspace_variant"] = otel_admission["report"]["source_variant"]
        report["projected_oauth2_files"] = history["current_files"]
    return {"restored": restored, "report": report}


def verify_predecessor(admission):
    if admission is None:
        return
    report = admission["report"]
    for binding in [*report["actual_files"].values(), report["bazel_lock"],
                    report["history"], report["helper"]]:
        _, actual = _read(binding["path"])
        if actual != binding:
            raise RuntimeError("captured OAuth2 source identity changed: " + binding["path"])
    history, _ = _history()
    if _vendor(report["repo"], history) != report["vendor"]:
        raise RuntimeError("captured OAuth2 vendor identity changed")

    if "otel_source_history" in report:
        from .otel_source_history import verify_predecessor as verify_otel
        verify_otel({"report": report["otel_source_history"]})
