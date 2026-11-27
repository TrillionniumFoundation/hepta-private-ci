"""Resume the verified official CPU wheel after a bounded pip timeout."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request


ROOT = Path("/home/qian-qi/hepta-c2-cold-resume-20261119-d741")
URL = "https://download-r2.pytorch.org/whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl"
EXPECTED = "cb9a8ba8137ab24e36bf1742cb79a1294bd374db570f09fc15a5e1318160db4e"
TOTAL = 183914597
ETAG = '"866fffce39a2090dc66a8ea4878ebed7"'
PREFIX = Path("/tmp/pip-unpack-qm3igcnj/torch-2.8.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl")
NAME = "torch-2.8.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    started = time.monotonic()
    folder = ROOT / "wheels"
    folder.mkdir()
    partial = folder / (NAME + ".partial")
    if PREFIX.is_file() and not PREFIX.is_symlink() and PREFIX.stat().st_size < TOTAL:
        shutil.copyfile(PREFIX, partial)
        prefix_size = partial.stat().st_size
    else:
        partial.touch(exist_ok=False)
        prefix_size = 0
    prefix_sha = digest(partial)
    descriptor = os.open(partial, os.O_RDWR)
    os.ftruncate(descriptor, TOTAL)

    def fetch(span):
        begin, end = span
        request = urllib.request.Request(URL, headers={
            "Range": f"bytes={begin}-{end}", "If-Match": ETAG,
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 206 or response.headers["Content-Range"] != f"bytes {begin}-{end}/{TOTAL}":
                raise ValueError("official server did not honor the exact byte range")
            offset = begin
            while offset <= end:
                block = response.read(min(256 * 1024, end + 1 - offset))
                if not block or os.pwrite(descriptor, block, offset) != len(block):
                    raise ValueError("short range read/write")
                offset += len(block)
        print(json.dumps({"completed_range": [begin, end], "bytes": end - begin + 1}), flush=True)

    spans = [(begin, min(TOTAL - 1, begin + 8 * 1024**2 - 1))
             for begin in range(prefix_size, TOTAL, 8 * 1024**2)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(fetch, spans))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    actual = digest(partial)
    if actual != EXPECTED:
        raise ValueError("official wheel full SHA256 mismatch")
    final = folder / NAME
    os.replace(partial, final)
    receipt = {"official_url": URL, "official_index_sha256": EXPECTED,
               "verified_sha256": actual, "bytes": TOTAL, "prefix_bytes_reused": prefix_size,
               "prefix_sha256": prefix_sha, "parallel_requests_max": 8,
               "wall_seconds": time.monotonic() - started, "wheel": str(final)}
    with (ROOT / "WHEEL_RECOVERY.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
