"""Explicit host-approved, immutable input inventories for V8 evidence archives."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


BLOCK = 1 << 20
MAX_FILES = 200_000
MAX_JSON = 64 << 20
TOOLS = ("archive_plan_v8.py", "archive_pack_v8.py", "archive_verify_v8.py", "archive_cli_v8.py")
CACHE_PARTS = {".git", ".hg", ".svn", ".venv", "pft-venv", "node_modules", "target", "__pycache__", ".pytest_cache"}
MODEL_PARTS = {"encoder-weights", "model-weights", "huggingface", "hf-cache", "encoder-cache"}
SECRET_NAMES = {"credentials", "credentials.json", "token.json", ".env", "id_rsa", "id_ed25519"}
SOURCE_SUFFIXES = {".py", ".rs", ".sh", ".bzl"}


class ArchiveError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ArchiveError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pin(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "an external SHA256 pin is required")
    return value


def read_json(path, expected):
    stream, before = checked_open(Path(path).absolute())
    with stream:
        require(before["bytes"] <= MAX_JSON, "bounded ordinary JSON required")
        data = stream.read(MAX_JSON + 1)
        require(len(data) <= MAX_JSON and fingerprint(os.fstat(stream.fileno())) == before,
                "JSON exceeded its bound or changed while reading")
    require(digest(data) == pin(expected), "external JSON identity differs")
    return json.loads(data), data


def write_new(path, data):
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def relative_name(value):
    require(isinstance(value, str) and value not in {"", "."} and "\\" not in value and "\x00" not in value, "invalid member name")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value
            and all(p not in {".", ".."} for p in path.parts)
            and len(value.encode("utf-8")) <= 2048, "unsafe or oversized member path")
    return value


def exclusion(relative):
    path = PurePosixPath(relative)
    names = {p.lower() for p in path.parts}
    if names & CACHE_PARTS:
        return "rebuildable cache or version-control internals"
    if names & MODEL_PARTS or path.suffix.lower() in {".safetensors", ".gguf", ".onnx", ".pt", ".pth", ".ckpt"}:
        return "encoder/model weights"
    name = path.name.lower()
    if (name in SECRET_NAMES or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}
            or re.search(r"(^|[-_.])(private[-_]?key|signing[-_]?key|api[-_]?key|secret|credentials)([-_.]|$)", name)):
        return "private key or credential name; contents not read"
    if re.fullmatch(r"pytorch_model(?:-\d+-of-\d+)?\.bin", name):
        return "encoder/model weights"
    return None


def fingerprint(info):
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns, "mode": stat.S_IMODE(info.st_mode)}


def checked_open(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), "symlink input is forbidden")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    stream = os.fdopen(descriptor, "rb")
    info = os.fstat(stream.fileno())
    try:
        require(stat.S_ISREG(info.st_mode), "only ordinary files may be archived")
        if expected is not None:
            require(fingerprint(info) == expected, "input changed since the approved inventory")
    except BaseException:
        stream.close()
        raise
    return stream, fingerprint(info)


def hash_file(path, expected=None):
    stream, before = checked_open(path, expected)
    h = hashlib.sha256()
    with stream:
        for block in iter(lambda: stream.read(BLOCK), b""):
            h.update(block)
        require(fingerprint(os.fstat(stream.fileno())) == before, "input changed while hashing")
    return h.hexdigest(), before


def tool_hashes():
    return {name: hash_file(Path(__file__).with_name(name))[0] for name in TOOLS}


def absolute_name(value):
    require(isinstance(value, str) and value.startswith("/") and "\\" not in value and "\x00" not in value,
            "absolute workspace path required")
    path = Path(value)
    require(str(path) == value and ".." not in path.parts, "canonical absolute path required")
    return path


def source_reference(value):
    require(isinstance(value, dict) and set(value) == {"repository", "commit", "path", "sha256"},
            "exact published Git file reference required")
    require(isinstance(value["repository"], str) and re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"])
            and re.fullmatch(r"[0-9a-f]{40}", value["commit"]), "immutable public/provider Git reference required")
    relative_name(value["path"])
    pin(value["sha256"])


def validate_roots(config, live=True):
    require(config.get("schema") == "hepta.evidence-archive-roots.v8", "explicit V8 archive root configuration required")
    base = absolute_name(config["workspace"])
    if live:
        require(base.resolve(strict=True) == base, "canonical workspace required")
    roots, names, paths = config["roots"], set(), []
    require(0 < len(roots) <= 64, "one to 64 exact approved roots required")
    for root in roots:
        label, path = root["label"], absolute_name(root["path"])
        require(isinstance(label, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", label)
                and label not in names, "unique simple root labels required")
        require(path != base and base in path.parents, "exact workspace evidence roots required")
        if live:
            require(path.resolve(strict=True) == path and path.is_dir() and not (path / ".git").exists(),
                    "whole Git worktrees, aliases and missing roots are forbidden")
        require(root["status"] in {"sealed", "interrupted", "tools"}, "live/unsealed roots cannot be inventoried")
        require(isinstance(root["purpose"], str) and 0 < len(root["purpose"]) <= 500, "root purpose required")
        require(isinstance(root["pins"], dict) and (root["pins"] or root["status"] == "interrupted"), "sealed/tool roots need external file pins")
        for name, value in root["pins"].items():
            relative_name(name)
            pin(value)
        references = root.get("source_references", {})
        require(isinstance(references, dict), "explicit per-file published source references required")
        for name, reference in references.items():
            relative_name(name)
            source_reference(reference)
            require(PurePosixPath(name).suffix in SOURCE_SUFFIXES
                    and PurePosixPath(reference["path"]).suffix == PurePosixPath(name).suffix,
                    "raw evidence cannot be replaced by a published-source reference")
        require(all(path not in p.parents and p not in path.parents and path != p for p in paths), "overlapping roots are forbidden")
        names.add(label)
        paths.append(path)
    dependencies = config.get("prerequisite_archives", [])
    require(isinstance(dependencies, list) and len(dependencies) <= 64, "bounded external archive dependencies required")
    for dependency in dependencies:
        require(set(dependency) == {"name", "sha256", "bytes", "location"}
                and isinstance(dependency["name"], str) and isinstance(dependency["location"], str)
                and type(dependency["bytes"]) is int and dependency["bytes"] > 0,
                "external archive name, exact size, hash and location required")
        pin(dependency["sha256"])
    return sorted(roots, key=lambda row: row["label"])


def scan(config, with_hashes):
    members, excluded = [], []
    for root in validate_roots(config):
        directory = Path(root["path"])
        references, seen_references = root.get("source_references", {}), set()
        for current, directories, filenames in os.walk(directory, followlinks=False):
            current = Path(current)
            for name in sorted(directories.copy()):
                path = current / name
                relative = path.relative_to(directory).as_posix()
                why = exclusion(relative)
                if why:
                    directories.remove(name)
                    excluded.append({"member": root["label"] + "/" + relative, "reason": why, "subtree": True})
                else:
                    require(not path.is_symlink(), "unapproved directory symlink: " + str(path))
            directories.sort()
            for name in sorted(filenames):
                path = current / name
                relative = relative_name(path.relative_to(directory).as_posix())
                member = root["label"] + "/" + relative
                why = exclusion(relative)
                if why:
                    excluded.append({"member": member, "reason": why, "subtree": False})
                    continue
                if relative in references:
                    actual, info = hash_file(path)
                    require(actual == references[relative]["sha256"], "published source reference differs from actual source")
                    excluded.append({"member": member, "reason": "exact published Git source dependency", "subtree": False,
                                     "reference": references[relative], "source_stat": info})
                    seen_references.add(relative)
                    continue
                stream, info = checked_open(path)
                stream.close()
                row = {"member": member, "root": root["label"], "relative_path": relative,
                       "bytes": info["bytes"], "source_stat": info,
                       "archive_mode": 0o755 if info["mode"] & 0o111 else 0o644}
                if with_hashes:
                    row["sha256"], _ = hash_file(path, info)
                members.append(row)
                require(len(members) <= MAX_FILES, "archive member count exceeded")
        require(seen_references == set(references), "every approved Git source omission must match an actual ordinary file")
    members.sort(key=lambda row: row["member"])
    excluded.sort(key=lambda row: row["member"])
    return members, excluded


def unchanged(plan):
    current, excluded = scan(plan["configuration"], False)
    fields = ("member", "root", "relative_path", "bytes", "source_stat", "archive_mode")
    require(current == [{k: row[k] for k in fields} for row in plan["members"]]
            and excluded == plan["excluded"], "approved input inventory changed")


def bind_expected_files(config, members):
    for root in config["roots"]:
        retained = {row["relative_path"]: row["sha256"] for row in members if row["root"] == root["label"]}
        references = {name: row["sha256"] for name, row in root.get("source_references", {}).items()}
        if root["status"] != "interrupted":
            require(set(retained) <= set(root["pins"]),
                    "sealed/tool roots require expected external pins for every retained file")
        for name, expected in root["pins"].items():
            require(retained.get(name, references.get(name)) == expected,
                    "required external root pin differs or was excluded")


def guard_output(config, output, inputs=()):
    path = Path(output).absolute()
    base = Path(config["workspace"])
    require(path.parent.resolve(strict=True) == path.parent and base in path.parents,
            "canonical output directory must remain inside the approved workspace")
    require(all(Path(root["path"]) != path and Path(root["path"]) not in path.parents for root in config["roots"]),
            "new output must remain outside every evidence root")
    require(path not in {Path(value).absolute() for value in inputs}, "output conflicts with an input document")
    return path


def make_plan(roots_file, roots_sha256, output):
    started_sources = tool_hashes()
    config, _ = read_json(roots_file, roots_sha256)
    validate_roots(config)
    destination = guard_output(config, output, (roots_file,))
    require(not destination.exists() and not destination.is_symlink(), "approved manifest output must be new")
    members, excluded = scan(config, True)
    require(members, "empty evidence archive")
    bind_expected_files(config, members)
    unique = {}
    for row in members:
        key = row["sha256"], row["bytes"], row["archive_mode"]
        row["link_to"] = unique.get(key)
        unique.setdefault(key, row["member"])
    plan = {"schema": "hepta.evidence-archive-plan.v8", "configuration_sha256": roots_sha256,
            "configuration": config, "members": members, "excluded": excluded,
            "logical_bytes": sum(row["bytes"] for row in members),
            "stored_file_bytes": sum(row["bytes"] for row in members if row["link_to"] is None),
            "hardlinks": sum(row["link_to"] is not None for row in members),
            "tool_sources": started_sources,
            "scientific_verdict_from_archive": False}
    unchanged(plan)
    require(tool_hashes() == started_sources, "archive planner source changed while scanning inputs")
    raw = canonical(plan)
    require(len(raw) <= MAX_JSON, "bounded complete archive manifest required")
    write_new(destination, raw)
    return {"plan_sha256": digest(raw), "members": len(members), "excluded": len(excluded),
            "logical_bytes": plan["logical_bytes"], "stored_file_bytes": plan["stored_file_bytes"]}


def validate_plan(path, expected, check_tools=False):
    plan, raw = read_json(path, expected)
    require(plan.get("schema") == "hepta.evidence-archive-plan.v8" and canonical(plan) == raw, "canonical complete archive plan required")
    roots = validate_roots(plan["configuration"], live=False)
    labels = {r["label"] for r in roots}
    pin(plan["configuration_sha256"])
    require(plan["scientific_verdict_from_archive"] is False, "archives cannot grant scientific acceptance")
    require(0 < len(plan["members"]) <= MAX_FILES, "bounded member inventory required")
    names = set()
    previous = {}
    for row in plan["members"]:
        name = relative_name(row["member"])
        require(name not in names and name != "MANIFEST.json" and type(row["bytes"]) is int
                and row["bytes"] >= 0 and row["archive_mode"] in {0o644, 0o755}, "invalid member framing")
        pin(row["sha256"])
        require(row["root"] in labels and name == row["root"] + "/" + relative_name(row["relative_path"])
                and exclusion(row["relative_path"]) is None
                and row["source_stat"]["bytes"] == row["bytes"], "root/member mapping differs")
        if row["link_to"] is not None:
            target = previous.get(row["link_to"])
            require(target and target["link_to"] is None and all(target[k] == row[k]
                    for k in ("sha256", "bytes", "archive_mode")), "hardlinks must name an earlier identical regular member")
        names.add(name)
        previous[name] = row
    require([r["member"] for r in plan["members"]] == sorted(names), "stable complete member order required")
    require(plan["logical_bytes"] == sum(r["bytes"] for r in plan["members"])
            and plan["stored_file_bytes"] == sum(r["bytes"] for r in plan["members"] if r["link_to"] is None)
            and plan["hardlinks"] == sum(r["link_to"] is not None for r in plan["members"]), "complete archive totals differ")
    bind_expected_files(plan["configuration"], plan["members"])
    if check_tools:
        require(plan["tool_sources"] == tool_hashes(), "archive writer source changed after plan approval")
    return plan, raw
