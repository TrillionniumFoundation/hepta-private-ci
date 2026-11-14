"""Fetch immutable official CPU encoder artifacts; no model files enter Git."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FILES = {
    "onnx/model.onnx": (90405214, "sha256", "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"),
    "tokenizer.json": (466247, "git", "cb202bfe2e3c98645018a6d12f182a434c9d3e02"),
    "config.json": (612, "git", "72b987fd805cfa2b58c4c8c952b274a11bfd5a00"),
    "sentence_bert_config.json": (53, "git", "59d594003bf59880a884c574bf88ef7555bb0202"),
    "modules.json": (349, "git", "952a9b81c0bfd99800fabf352f69c7ccd46c5e43"),
    "1_Pooling/config.json": (190, "git", "d1514c3162bbe87b343f565fadc62e6c06f04f03"),
    "tokenizer_config.json": (350, "git", "c79f2b6a0cea6f4b564fed1938984bace9d30ff0"),
    "special_tokens_map.json": (112, "git", "e7b0375001f109a6b8873d756ad4f7bbb15fbaa5"),
}


def file_identity(path, size, kind, expected):
    sha256 = hashlib.sha256()
    source = hashlib.sha256() if kind == "sha256" else hashlib.sha1(f"blob {size}\0".encode())
    actual_size = 0
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            actual_size += len(block)
            sha256.update(block)
            source.update(block)
    if actual_size != size or source.hexdigest() != expected:
        raise ValueError(f"Pinned artifact identity mismatch: {path}")
    return {"bytes": size, "sha256": sha256.hexdigest(), "source_digest": expected, "source_digest_kind": kind}


def download(directory):
    directory = Path(directory)
    identities = {}
    for name, (size, kind, expected) in FILES.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".part")
            url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
            with urllib.request.urlopen(url, timeout=60) as remote, open(temporary, "wb") as out:
                while chunk := remote.read(1 << 20):
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            file_identity(temporary, size, kind, expected)
            os.replace(temporary, path)
        identities[name] = file_identity(path, size, kind, expected)
    manifest = {"schema": "hepta-frozen-encoder-v1", "model_id": MODEL_ID, "revision": REVISION, "files": identities}
    (directory / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(download(parser.parse_args().directory), sort_keys=True, indent=2))
