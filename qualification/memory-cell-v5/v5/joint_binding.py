"""Complete source and immutable path checks before formal execution."""

import json
from pathlib import Path, PurePosixPath
import re

from .contracts import file_identity


PROJECT = Path(__file__).resolve().parents[1]
SEEDS = (1019, 1021, 1031, 1033, 1039)
GATES = {"known_correct_accepted_min": 0.8, "ood_false_accept_max": 0.05,
         "parameter_oracle_exact": 1.0, "composed_ablation_gain_min": 0.10}


def immutable_path(value):
    """Reject links on the supplied path before any resolution erases them."""
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("immutable paths must not contain parent traversal")
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("immutable input uses a symbolic link: " + str(part))
    return path.resolve(strict=True)


def relative_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("artifact names must be nonempty relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError("unsafe or noncanonical artifact path")
    return path


def required_source_files():
    paths = set(PROJECT.glob("*.py"))
    for directory in ("v5", "legacy_v3", "maintenance"):
        paths.update((PROJECT / directory).glob("*.py"))
    return {path.relative_to(PROJECT).as_posix() for path in paths} | {
        "PROTOCOL.json", "VENDOR.json", "assets/ASSETS.json"}


def verify_freeze(path):
    path = immutable_path(path)
    if path != PROJECT / "FREEZE.json":
        raise ValueError("formal execution needs the project FREEZE.json")
    frozen = json.loads(path.read_bytes())
    if frozen["frozen"] is not True or frozen["seeds"] != list(SEEDS) or frozen["gates"] != GATES:
        raise ValueError("formal seed, gate or freeze state differs")
    if not isinstance(frozen.get("source_commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", frozen["source_commit"]):
        raise ValueError("frozen source commit must be a full lowercase Git SHA")
    sources = frozen["source_files"]
    if not isinstance(sources, dict):
        raise ValueError("frozen source inventory must be a file mapping")
    missing = required_source_files() - sources.keys()
    if missing:
        raise ValueError("formal freeze omits required sources: " + ", ".join(sorted(missing)))
    for relative, identity in sources.items():
        source = immutable_path(PROJECT.joinpath(*relative_path(relative).parts))
        if not source.is_file() or file_identity(source) != identity:
            raise ValueError("executed source differs from freeze: " + relative)
    assets = file_identity(immutable_path(PROJECT / "assets/ASSETS.json"))
    if frozen.get("assets_binding_sha256") != assets["sha256"]:
        raise ValueError("frozen asset binding differs from the fixed ASSETS.json")
    return frozen, file_identity(path)
