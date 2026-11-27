"""Finish the two explicitly failed official-wheel ranges, then verify all bytes."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

from recover_runtime import EXPECTED, ETAG, NAME, ROOT, TOTAL, URL


FAILED_JOB = "1a1f253ff32-ffbe-adc"
MISSING = ((102680576, 111069183), (111069184, 119457791))


def main():
    started = time.monotonic()
    partial = ROOT / "wheels" / (NAME + ".partial")
    if not partial.is_file() or partial.is_symlink() or partial.stat().st_size != TOTAL:
        raise ValueError("missing exact prior partial wheel")
    final = ROOT / "wheels" / NAME
    if final.exists():
        raise FileExistsError(final)
    descriptor = os.open(partial, os.O_RDWR)

    def fetch(span):
        begin, end = span
        request = urllib.request.Request(URL, headers={
            "Range": f"bytes={begin}-{end}", "If-Match": ETAG,
        })
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 206 or response.headers["Content-Range"] != f"bytes {begin}-{end}/{TOTAL}":
                raise ValueError("official server did not honor the exact byte range")
            offset = begin
            while offset <= end:
                block = response.read(min(64 * 1024, end + 1 - offset))
                if not block or os.pwrite(descriptor, block, offset) != len(block):
                    raise ValueError("short range read/write")
                offset += len(block)
        print(json.dumps({"completed_range": [begin, end], "bytes": end - begin + 1}), flush=True)

    spans = [(start, min(end, start + 2 * 1024**2 - 1))
             for begin, end in MISSING for start in range(begin, end + 1, 2 * 1024**2)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(fetch, spans))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    digest = hashlib.sha256()
    with partial.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != EXPECTED:
        raise ValueError("official wheel full SHA256 mismatch")
    os.replace(partial, final)
    receipt = {
        "official_url": URL, "official_index_sha256": EXPECTED,
        "verified_sha256": actual, "bytes": TOTAL,
        "prior_failed_job": FAILED_JOB,
        "prior_completed_ranges_source": "authoritative failed-job stdout; full SHA256 independently verifies every retained byte",
        "replaced_ranges": MISSING, "bytes_downloaded_this_attempt": 2 * 8 * 1024**2,
        "parallel_requests_max": 8, "wall_seconds": time.monotonic() - started,
        "wheel": str(final), "optimizer_calls": 0,
    }
    with (ROOT / "WHEEL_RECOVERY.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
