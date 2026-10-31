"""Bounded public download of the frozen, offline-only Whisper evaluator."""

import argparse
import importlib.metadata
import json
from pathlib import Path

from .fetch_assets import download


REVISION = "0d3d19a32d3338f10357c0889762bd8d64bbdeba"
REPOSITORY = "Systran/faster-whisper-tiny.en"
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    metadata_path = args.output / "file-metadata.json"
    rows = [download(f"https://huggingface.co/api/models/{REPOSITORY}/tree/{REVISION}",
                     metadata_path, 2_000_000)]
    metadata = {row["path"]: row for row in json.loads(metadata_path.read_text())}
    for filename in FILES:
        row = download(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{filename}",
                       args.output / filename, 85_000_000)
        expected = metadata[filename].get("lfs", {}).get("oid")
        if expected and row["sha256"] != expected:
            raise ValueError("External model does not match pinned LFS identity")
        rows.append(row)
    manifest = {"schema": "hepta.abc3.external-asr-assets.v1", "repository": REPOSITORY,
                "revision": REVISION, "role": "qualification and terminal evaluation only; never policy selection",
                "license": "MIT", "sources": rows,
                "packages": {name: importlib.metadata.version(name) for name in
                             ("faster-whisper", "ctranslate2", "tokenizers", "av")}}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"downloaded_bytes": sum(row["bytes"] for row in rows),
                      "model_sha256": next(row["sha256"] for row in rows if row["path"] == "model.bin")}))


if __name__ == "__main__":
    main()
