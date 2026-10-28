"""Bind new experiments to committed inputs without replacing historical seals."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from experiments.free_boundary_neuron import provenance as previous
from .ledger import sha, write_json_exclusive


ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
EXTRA_NATIVE = ("codex-rs/hepta-learning-ledger/src/causal_v2.rs",)


def inventory():
    paths = set(previous.input_paths())
    for path in STUDY.rglob("*"):
        relative = path.relative_to(STUDY)
        if any(
            part in {"results", "runs", "__pycache__", ".venv"}
            for part in relative.parts
        ):
            continue
        if path.is_file() and (
            path.suffix in {".py", ".rs", ".toml", ".lock", ".json"}
            or path.name == "requirements.txt"
        ):
            paths.add(path)
    paths.update(ROOT / relative for relative in EXTRA_NATIVE)
    result = {}
    for path in sorted(paths):
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(ROOT.resolve())
            or not path.is_file()
        ):
            raise ValueError(f"Invalid source input: {path}")
        result[str(path.relative_to(ROOT))] = {
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        }
    return result


def freeze(destination):
    inputs = inventory()
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    if missing := sorted(set(inputs) - tracked):
        raise ValueError(f"Uncommitted inputs: {missing}")
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", *inputs], cwd=ROOT, check=True
    )
    payload = {
        "schema": "hepta.adaptive-neuron.source-seal.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip(),
        "inputs": inputs,
        "environment": previous.environment(),
        "registration": "New adaptive study, sealed before scientific seeds; historical v1 results retain their original seals.",
    }
    receipt = write_json_exclusive(destination, payload)
    return {**receipt, "inputs": len(inputs), "source_commit": payload["source_commit"]}


def verify(path):
    expected = json.loads(Path(path).read_text())
    if expected.get("schema") != "hepta.adaptive-neuron.source-seal.v2":
        raise ValueError("Wrong source-seal schema")
    actual = inventory()
    if actual != expected["inputs"]:
        changed = sorted(
            key
            for key in set(actual) | set(expected["inputs"])
            if actual.get(key) != expected["inputs"].get(key)
        )
        raise ValueError(f"Frozen inputs changed: {changed}")
    return {
        "source_commit": expected["source_commit"],
        "source_tree": expected["source_tree"],
        "seal_sha256": sha(path),
        "verified_inputs": len(actual),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            freeze(args.path) if args.command == "freeze" else verify(args.path),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
