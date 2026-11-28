"""Exact workspace-source history; actual dependency graphs are qualified separately."""
import hashlib
import json
from pathlib import Path
import stat

ROOT_FILES = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock")
HISTORY = Path(__file__).with_name("dependency_source_history_20261127.json")
HISTORY_SHA256 = "151080d3dd24f67cae951c5166755fdd874d2b7197bcde08a1121ec2f1a503a6"


def _identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _read(path):
    path = Path(path).absolute()
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.resolve(strict=True) != path:
        raise RuntimeError("dependency source must be a physical regular file: " + str(path))
    data = path.read_bytes()
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
    if tuple(getattr(before, x) for x in fields) != tuple(getattr(after, x) for x in fields):
        raise RuntimeError("dependency source changed while captured: " + str(path))
    return data, {"path": str(path), **_identity(data), "device": after.st_dev,
                  "inode": after.st_ino, "mode": stat.S_IMODE(after.st_mode),
                  "mtime_ns": after.st_mtime_ns, "ctime_ns": after.st_ctime_ns,
                  "links": after.st_nlink}


def _history(path=HISTORY):
    data, binding = _read(path)
    if binding["sha256"] != HISTORY_SHA256:
        raise RuntimeError("the complete dependency source history changed")
    value = json.loads(data)
    if value["schema"] != "codex.hia.workspace-dependency-source-history.v1":
        raise RuntimeError("unrecognized dependency source history")
    return value, binding


def _pair_identity(files):
    if set(files) != set(ROOT_FILES):
        raise RuntimeError("both complete workspace dependency files are required")
    return {path: _identity(files[path]) for path in ROOT_FILES}


def _reverse(files, transition, identities):
    if _pair_identity(files) != identities[transition["after"]]:
        raise RuntimeError("dependency source transition input is not the complete pinned pair")
    result = dict(files)
    replacement = transition["manifest"]
    old, new = replacement["before"].encode(), replacement["after"].encode()
    if result[ROOT_FILES[0]].count(new) != 1:
        raise RuntimeError("dependency manifest inverse must have exactly one match")
    result[ROOT_FILES[0]] = result[ROOT_FILES[0]].replace(new, old, 1)
    blocks = result[ROOT_FILES[1]].split(b"\n[[package]]\n")
    for change in transition["changes"]:
        current = change["after"].encode()
        if blocks.count(current) != 1:
            raise RuntimeError("dependency lock inverse must have exactly one complete package: " +
                               change["package"])
        index = blocks.index(current)
        if change["before"] is None:
            blocks.pop(index)
        else:
            blocks[index] = change["before"].encode()
    result[ROOT_FILES[1]] = b"\n[[package]]\n".join(blocks)
    if _pair_identity(result) != identities[transition["before"]]:
        raise RuntimeError("dependency inverse did not recover the complete predecessor pair")
    return result


def admit_workspace_sources(repo, originals):
    """Keep identical originals, or prove the one explicit current-to-original inverse."""
    _pair_identity(originals)
    captured = {path: _read(Path(repo) / path) for path in ROOT_FILES}
    actual = {path: row[0] for path, row in captured.items()}
    if actual == originals:
        return None
    history, history_binding = _history()
    identities = history["identities"]
    if _pair_identity(originals) != identities["original"]:
        raise RuntimeError("dependency source inverse requires the unchanged a201/aeb original pair")
    restored = actual
    observed = []
    oauth2_admission = None
    if _pair_identity(actual) != identities["sqlx"]:
        from .oauth2_source_history import restore_predecessor
        oauth2_admission = restore_predecessor(repo, actual, identities["sqlx"])
        restored = oauth2_admission["restored"]
        if "otel_source_history" in oauth2_admission["report"]:
            outer = oauth2_admission["report"]["otel_source_history"]
            if "external_migration_source_history" in outer:
                external = outer["external_migration_source_history"]
                observed.append({"name": "external-agent-time-source", "from": "external-time",
                                 "to": "otel-time", "complete_package_inverses": 1,
                                 "restored_files": external["predecessor_files"]})
            observed.append({"name": "otel-time-source", "from": "otel-time",
                             "to": "oauth2-epoch", "complete_package_inverses": 1,
                             "restored_files": outer["predecessor_files"]})
        observed.append({"name": "oauth2-epoch-source", "from": "oauth2-epoch",
                         "to": "sqlx", "complete_package_inverses": 1,
                         "restored_files": _pair_identity(restored)})
    for transition in history["inverse"]:
        restored = _reverse(restored, transition, identities)
        observed.append({"name": transition["name"], "from": transition["after"],
                         "to": transition["before"],
                         "complete_package_inverses": len(transition["changes"]),
                         "restored_files": _pair_identity(restored)})
    if restored != originals:
        raise RuntimeError("dependency source inverse differs from the actual immutable originals")
    _, helper_binding = _read(Path(__file__))
    result = {"restored": restored, "report": {
        "schema": "codex.hia.workspace-dependency-source-admission.v1",
        "actual_revision": (history["revisions"]["sqlx"] if oauth2_admission is None else
                            oauth2_admission["report"].get("workspace_variant",
                                oauth2_admission["report"]["source_variant"])),
        "original_revisions": history["revisions"]["original"],
        "actual_files": {path: row[1] for path, row in captured.items()},
        "original_files": _pair_identity(originals), "inverse": observed,
        "history": history_binding, "helper": helper_binding,
        "dependency_graph_equivalence_claimed": False,
        "qualification_scope": "The unchanged complete original owners and current owners must "
            "execute with the independently captured actual current dependency graph; this "
            "source inverse alone confers no behavioral or dependency qualification.",
    }}
    if oauth2_admission is not None:
        result["report"]["oauth2_source_history"] = oauth2_admission["report"]
    return result


def verify_workspace_sources(admission):
    """Re-read physical current source and inverse inputs at the terminal boundary."""
    if admission is None:
        return
    report = admission["report"]
    for binding in [*report["actual_files"].values(), report["history"], report["helper"]]:
        _, actual = _read(binding["path"])
        if actual != binding:
            raise RuntimeError("captured dependency source identity changed: " + binding["path"])

    if "oauth2_source_history" in report:
        from .oauth2_source_history import verify_predecessor
        verify_predecessor({"report": report["oauth2_source_history"]})
