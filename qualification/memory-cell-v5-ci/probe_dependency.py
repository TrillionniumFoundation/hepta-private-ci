"""Read-only diagnostics for one existing checksum-pinned Ubuntu dependency."""

import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


EXPECTED = "7074b6a2f6367a10d280c00a1cb02e74277709180bab4f2491a2f355ab2d6c20"
NAME = "zlib1g_1.3.dfsg-3.1ubuntu2.1_amd64.deb"
URLS = (
    "https://snapshot.ubuntu.com/ubuntu/20260801T000000Z/pool/main/z/zlib/" + NAME,
    "https://archive.ubuntu.com/ubuntu/pool/main/z/zlib/" + NAME,
    "https://launchpad.net/ubuntu/+archive/primary/+files/" + NAME,
)


if __name__ == "__main__":
    output = Path("dependency-probe-output")
    output.mkdir(exist_ok=False)
    results = []
    for index, url in enumerate(URLS):
        start = time.perf_counter()
        row = {"url": url, "expected_sha256": EXPECTED}
        try:
            request = Request(url, headers={"User-Agent": "hepta-checksum-diagnostic/1"})
            with urlopen(request, timeout=20) as response:
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise ValueError("dependency exceeds diagnostic size bound")
                actual = hashlib.sha256(raw).hexdigest()
                row.update({"status": response.status, "final_url": response.geturl(), "bytes": len(raw),
                            "sha256": actual, "matches_existing_pin": actual == EXPECTED})
                if actual == EXPECTED:
                    name = f"verified-source-{index}.deb"
                    (output / name).write_bytes(raw)
                    row["verified_payload"] = name
        except HTTPError as error:
            row.update({"status": error.code, "error": str(error), "matches_existing_pin": False})
        except Exception as error:
            row.update({"error_type": type(error).__name__, "error": str(error), "matches_existing_pin": False})
        row["wall_seconds"] = time.perf_counter() - start
        results.append(row)
    report = {"schema": "hepta.memory.v5.dependency-download-diagnostic.v1", "results": results,
              "any_payload_matches_existing_pin": any(row["matches_existing_pin"] for row in results),
              "dependency_version_or_checksum_changed": False, "bazel_success_claimed": False}
    (output / "DOWNLOADS.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))
