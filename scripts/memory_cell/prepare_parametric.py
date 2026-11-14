"""Acquire the previously registered public 135M decoder at exact publisher bytes."""

import argparse
import hashlib
import json
from pathlib import Path

REPOSITORY = "HuggingFaceTB/SmolLM2-135M-Instruct"
REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
# Git blob SHA-1 for small files; publisher LFS SHA-256 for the weights.
FILES = {
    "config.json": (861, "36293b6099200eb8aeb55ae2c01bca2ba46d80d0"),
    "generation_config.json": (132, "da6c4d71a43aa7e6f785bdbb28ea5025438a73fa"),
    "model.safetensors": (
        269060552,
        "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c",
    ),
    "special_tokens_map.json": (655, "44719d2e365acac0637fd25a3acf46494ca45940"),
    "tokenizer.json": (2104556, "f922b1797f0c88e71addc8393787831f2477a4bd"),
    "tokenizer_config.json": (3764, "8c7b22013909450429303ed10be4398bd63f5457"),
}


def prepare(output, *, download=False):
    output = Path(output)
    if output.is_symlink():
        raise ValueError("real model directory required")
    if download:
        from huggingface_hub import snapshot_download

        snapshot_download(
            REPOSITORY,
            revision=REVISION,
            local_dir=output,
            allow_patterns=list(FILES),
            token=False,
            max_workers=2,
        )
    actual_names = set()
    for path in output.rglob("*"):
        relative = path.relative_to(output)
        if relative.parts[0] == ".cache":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("unexpected non-cache model directory entry")
        actual_names.add(relative.as_posix())
    if actual_names != set(FILES):
        raise ValueError("model directory differs from complete publisher inventory")
    inventory = []
    for name, (size, expected) in sorted(FILES.items()):
        path = output / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"publisher file size/type mismatch: {name}")
        actual = hashlib.sha256()
        publisher = hashlib.sha256() if len(expected) == 64 else hashlib.sha1()
        if len(expected) == 40:
            publisher.update(f"blob {size}\0".encode())
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                actual.update(block)
                publisher.update(block)
        if publisher.hexdigest() != expected:
            raise ValueError(f"publisher content digest mismatch: {name}")
        inventory.append(dict(path=name, bytes=size, sha256=actual.hexdigest()))
    receipt = dict(
        schema="hepta.parametric-memory.acquisition.v1",
        repository=REPOSITORY,
        revision=REVISION,
        files=inventory,
        total_bytes=sum(row["bytes"] for row in inventory),
        source_registration_commit="c64e0ade0d2599841554b3ff91200d188d7e7671",
        production_accepted=False,
    )
    # Keep the receipt outside the model inventory used by LoRAReader.
    output.with_name(output.name + ".acquisition.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, download=args.download), sort_keys=True))
