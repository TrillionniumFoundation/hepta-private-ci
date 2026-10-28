"""Create-only evidence and exact committed import identities for V9 stages."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

from addressing.contracts import canonical
from .identity import unique_object


def write_json(path, value):
    with Path(path).open("xb") as handle:
        handle.write(canonical(value) + b"\n")


def sources():
    here = Path(__file__).resolve().parent.parent
    qualification, repo = here.parents[1], here.parents[2]
    paths = [*here.rglob("*.py"), *(qualification / "memory-cell-v7/addressing").glob("*.py")]
    paths += list((qualification / "memory-cell-v8/addressing").glob("*.py"))
    paths += list((qualification / "memory-cell-v8/addressing/v8_addressing").glob("*.py"))
    paths += [qualification / "memory-cell-v6/v6" / name for name in ("__init__.py", "encoder.py", "training_language.py")]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    hashes = {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    for name, expected in hashes.items():
        saved = subprocess.run(["git", "show", head + ":" + name], cwd=repo, capture_output=True, check=False)
        if saved.returncode or hashlib.sha256(saved.stdout).hexdigest() != expected:
            raise ValueError("addressing execution source must be committed before fitting: " + name)
    return {"source_commit": head, "execution_source_is_committed": True, "source_files": hashes,
            "python": platform.python_version(), "versions": {name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "scikit-learn", "onnxruntime", "tokenizers")}}, repo


def retain_sources(output, source, repo):
    for name in source["source_files"]:
        target = output / "execution-sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write((repo / name).read_bytes())


def load_json(path, maximum=16_000_000):
    path = Path(path).absolute()
    if any(value.is_symlink() for value in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("invalid bounded run artifact")
    return json.loads(path.read_bytes(), object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite run field")))


def check_source_lock(record, current):
    if record["source_files"] != current["source_files"] or record["versions"] != current["versions"] or record["python"] != current["python"]:
        raise ValueError("selected source or execution dependencies changed before evaluation")
