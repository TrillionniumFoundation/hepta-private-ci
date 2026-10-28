"""Freeze and verify executable inputs before registered research runs."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
NATIVE_ROOTS = (
    "codex-rs/hepta-types",
    "codex-rs/hepta-infer-core",
    "codex-rs/hepta-neuron",
)
NATIVE_FILES = (
    "codex-rs/hepta-agentd/src/neuron_runtime.rs",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_paths():
    """Include executable study sources and the original native source closure."""
    selected = set()
    for path in STUDY.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(STUDY)
        if any(
            part in {"results", "runs", "evidence", "__pycache__", ".venv"}
            for part in relative.parts
        ):
            continue
        if (
            path.suffix in {".py", ".rs", ".toml", ".lock", ".json"}
            or path.name == "requirements.txt"
        ):
            selected.add(path)
    for directory in NATIVE_ROOTS:
        selected.update(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and path.suffix in {".rs", ".toml"}
        )
    selected.update(ROOT / path for path in NATIVE_FILES)
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Input is not an ordinary repository file: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
    return sorted(selected)


def inventory():
    return {
        str(path.relative_to(ROOT)): {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in input_paths()
    }


def environment():
    import numpy
    import scipy

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
    }


def freeze(destination):
    """Require committed inputs, then create an immutable-by-convention seal."""
    paths = input_paths()
    relative = [str(path.relative_to(ROOT)) for path in paths]
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    missing = sorted(set(relative) - tracked)
    if missing:
        raise ValueError(f"Uncommitted source inputs: {missing}")
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *relative], cwd=ROOT, check=True
    )
    for directory in ("learning", "owner"):
        protocol = STUDY / directory / "PROTOCOL.json"
        if not protocol.is_file():
            raise ValueError(f"Missing registered subprotocol: {protocol}")
        json.loads(protocol.read_text())
    payload = {
        "schema": "hepta.free-boundary.source-seal.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip(),
        "inputs": inventory(),
        "environment": environment(),
        "evidence": "Inputs sealed before scientific execution; no outcome claim",
    }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")
    return {
        "seal": str(destination),
        "sha256": sha256(destination),
        "inputs": len(paths),
    }


def verify(source_seal):
    seal = json.loads(Path(source_seal).read_text())
    actual = inventory()
    expected = seal["inputs"]
    if actual != expected:
        changed = sorted(
            path
            for path in set(actual) | set(expected)
            if actual.get(path) != expected.get(path)
        )
        raise ValueError(f"Frozen inputs changed: {changed}")
    return {
        "source_commit": seal["source_commit"],
        "seal_sha256": sha256(source_seal),
        "verified_inputs": len(actual),
        "environment": environment(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze").add_argument("destination", type=Path)
    sub.add_parser("verify").add_argument("source_seal", type=Path)
    args = parser.parse_args()
    result = (
        freeze(args.destination)
        if args.command == "freeze"
        else verify(args.source_seal)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
