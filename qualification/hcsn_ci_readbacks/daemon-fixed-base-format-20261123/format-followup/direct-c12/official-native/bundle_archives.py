"""Store or restore original Actions ZIPs as verified, bounded, lossless binary parts."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import tempfile


PART = 470_000
BASENAMES = ("native.zip", "caller.zip")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pack(source, output):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in BASENAMES:
        original = (source / name).read_bytes()
        encoded = lzma.compress(original, format=lzma.FORMAT_XZ, filters=[{"id": lzma.FILTER_LZMA2, "preset": 4, "dict_size": 16 << 20}])
        assert lzma.decompress(encoded) == original
        chunks = []
        for offset in range(0, len(encoded), PART):
            filename = f"{name}.xz.part-{offset // PART:03}"
            block = encoded[offset : offset + PART]
            (output / filename).write_bytes(block)
            chunks.append({"name": filename, "bytes": len(block), "sha256": sha(block)})
        manifest[name] = {"bytes": len(original), "sha256": sha(original), "xz_bytes": len(encoded), "xz_sha256": sha(encoded), "parts": chunks}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def restore(source, output):
    manifest = json.loads((source / "manifest.json").read_text())
    if sorted(manifest) != sorted(BASENAMES):
        raise ValueError("archive list changed")
    output.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in BASENAMES:
        row = manifest[name]
        parts = []
        for i, part in enumerate(row["parts"]):
            expected_name = f"{name}.xz.part-{i:03}"
            assert part["name"] == expected_name
            block = (source / expected_name).read_bytes()
            assert 0 < len(block) <= PART and len(block) == part["bytes"] and sha(block) == part["sha256"]
            parts.append(block)
        encoded = b"".join(parts)
        assert len(encoded) == row["xz_bytes"] and sha(encoded) == row["xz_sha256"]
        data = lzma.decompress(encoded, format=lzma.FORMAT_XZ, memlimit=128 << 20)
        assert len(data) == row["bytes"] and sha(data) == row["sha256"]
        dest = output / name
        if dest.exists():
            if not dest.is_file() or dest.is_symlink() or sha(dest.read_bytes()) != row["sha256"]:
                raise FileExistsError(dest)
        else:
            with tempfile.NamedTemporaryFile(dir=output, prefix=".artifact-", delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            path = Path(tmp.name)
            try:
                os.link(path, dest)
            finally:
                path.unlink(missing_ok=True)
        result[name] = row["sha256"]
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pack", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    (pack if args.action == "pack" else restore)(args.source, args.output)


if __name__ == "__main__":
    main()
