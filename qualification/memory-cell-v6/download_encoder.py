"""Download only an exact predeclared encoder; verify every existing or new file."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

from v6.artifacts import durable_bytes
from v6.contracts import canonical
from v6.encoder import multilingual_source


def download(model, output):
    project = Path(__file__).resolve().parent
    source = (
        multilingual_source()
        if model == "multilingual"
        else json.loads((project.parent / "memory-cell-v2/MODEL_SOURCE.json").read_bytes())
    )
    output = Path(output).absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("encoder destination must not use symlinks")
    output.mkdir(parents=True, exist_ok=True)
    source_path = output / "source.json"
    if source_path.exists() and json.loads(source_path.read_bytes()) != source:
        raise ValueError("destination already contains a different encoder")
    for name, binding in source["files"].items():
        path = output / name
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("symlinked encoder component")
        if path.exists():
            raw = path.read_bytes()
        else:
            with urllib.request.urlopen(binding["url"], timeout=120) as response:
                raw = response.read(binding["bytes"] + 1)
        if len(raw) != binding["bytes"] or hashlib.sha256(raw).hexdigest() != binding["sha256"]:
            raise ValueError("encoder component failed pinned bytes/hash: " + name)
        if not path.exists():
            durable_bytes(path, raw)
        print(json.dumps({"file": name, "bytes": len(raw), "sha256": binding["sha256"]}), flush=True)
    durable_bytes(source_path, canonical(source))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("english", "multilingual"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    download(args.model, args.output)
