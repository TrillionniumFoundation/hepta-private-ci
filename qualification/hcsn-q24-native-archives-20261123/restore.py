"""Validate the original Q24 archive in temporary storage and publish without replacing an existing path."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
SIZE = 13_683_617
PART_SIZE = 480_000
EXPECTED = "9a5c21eb875d1f42713104015e481fc7c0206da6907d37d4c264c681e5f12652"

def require(condition, message):
    if not condition:
        raise SystemExit(message)

def restore(output):
    manifest = json.loads((ROOT / "manifest.json").read_bytes())
    require((manifest["version"], manifest["bytes"], manifest["part_bytes"], manifest["sha256"])
            == (1, SIZE, PART_SIZE, EXPECTED), "Archive manifest mismatch")
    count = (SIZE + PART_SIZE - 1) // PART_SIZE
    require(len(manifest["parts"]) == count, "Part count mismatch")
    out = output.absolute()
    digest = hashlib.sha256()
    offset = 0
    with TemporaryDirectory(prefix=".q24-restore-", dir=out.parent) as tmp:
        staged = Path(tmp) / "verified.zip"
        with staged.open("xb") as assembled:
            for number, part in enumerate(manifest["parts"], start=1):
                relative = f"parts/part-{number:04d}.bin"
                size = min(PART_SIZE, SIZE - offset)
                require((part["path"], part["offset"], part["bytes"]) == (relative, offset, size),
                        f"Invalid part metadata at {number}")
                source = ROOT / relative
                require(source.is_file() and not source.is_symlink(), f"Missing original part: {relative}")
                with source.open("rb") as stream:
                    raw = stream.read(size + 1)
                require(len(raw) == size and hashlib.sha256(raw).hexdigest() == part["sha256"],
                        f"Part checksum mismatch: {relative}")
                digest.update(raw)
                assembled.write(raw)
                offset += size
        require(offset == SIZE and digest.hexdigest() == EXPECTED, "Whole archive checksum mismatch")
        try:
            os.link(staged, out)
        except FileExistsError:
            raise SystemExit(f"Output already exists: {out}") from None
    print(f"{digest.hexdigest()}  {out}  ({offset} bytes)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=Path("q24_release.zip"))
    restore(parser.parse_args().output)
