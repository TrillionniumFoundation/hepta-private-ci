"""Download only the six pinned, hash-checked official MiniLM files."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def download(directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("model directory must not be a symlink")
    source_path = Path(__file__).resolve().parent / "MODEL_SOURCE.json"
    source = json.loads(source_path.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in source["files"].items():
        url = f"https://huggingface.co/{source['repo']}/resolve/{source['revision']}/{name}"
        if expected["url"] != url:
            raise ValueError("source URL differs from pinned repository revision")
        path = directory / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("symlinks are not admitted to the model cache")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raw = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read(expected["bytes"] + 1)
        if (
            len(raw) != expected["bytes"]
            or hashlib.sha256(raw).hexdigest() != expected["sha256"]
        ):
            raise ValueError(
                f"pinned model file mismatch: {name}; use a new clean directory"
            )
        if not path.exists():
            with path.open("xb") as output:
                output.write(raw)
        print(json.dumps({"verified": name, "bytes": len(raw)}), flush=True)
    metadata = directory / "source.json"
    if metadata.is_symlink():
        raise ValueError("source metadata must not be a symlink")
    if metadata.exists() and json.loads(metadata.read_text()) != source:
        raise ValueError("existing model metadata conflicts with pinned source")
    if not metadata.exists():
        metadata.write_bytes(source_path.read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    download(parser.parse_args().directory)
