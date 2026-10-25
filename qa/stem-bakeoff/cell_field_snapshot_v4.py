"""Fetch the exact six-file, frozen Granite snapshot used by the Cell studies."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import urllib.request


REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
BASE = "https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2/resolve/"
FILES = {
    "README.md": (20684, "a73d22110e7e6d947f55cdd4f1a8b0b622e340fd09a66d302f5fe800899024bd"),
    "config.json": (1216, "de948b0bdc6f356afad7a84b276d8dd7e7fe10fb9add1bb5e610621c28e41ebc"),
    "model.safetensors": (194889568, "f3ea88b230492811046145513710e76b4cc8c2ad49e8708da0e7247e548903be"),
    "special_tokens_map.json": (871, "013787ee251ff611722479197c00853b62113ad303cb0a36524231783c676c69"),
    "tokenizer.json": (25301672, "4f2842d568e2724370aec203652a42ac783c7937f8347a1a2cc7506d71f1582f"),
    "tokenizer_config.json": (12860, "6ed69389e30a8ecabfce2f9ebcdf0c908b34056f24d994340f2f216521c057d5"),
}


def fetch(snapshot):
    root = Path(snapshot)
    root.mkdir(parents=True, exist_ok=True)

    def one(item):
        name, (size, digest) = item
        path = root / name
        if path.is_symlink():
            raise ValueError("snapshot may not contain symlinks")
        if not path.exists():
            temporary = root / (name + ".partial")
            with urllib.request.urlopen(BASE + REVISION + "/" + name, timeout=120) as source:
                with temporary.open("xb") as target:
                    total = 0
                    while chunk := source.read(1 << 20):
                        total += len(chunk)
                        if total > size:
                            raise ValueError("download exceeds pinned byte size")
                        target.write(chunk)
            temporary.replace(path)
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if path.stat().st_size != size or actual != digest:
            raise ValueError("snapshot bytes differ: " + name)
        return name

    with ThreadPoolExecutor(max_workers=3) as pool:
        for name in pool.map(one, FILES.items()):
            print("verified " + name, flush=True)
    if {p.name for p in root.iterdir()} != set(FILES):
        raise ValueError("snapshot must contain exactly the pinned six files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    fetch(parser.parse_args().snapshot)
