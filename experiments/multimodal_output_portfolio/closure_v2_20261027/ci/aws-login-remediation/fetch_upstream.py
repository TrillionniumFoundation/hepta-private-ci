"""Fetch official crate sources with the already-recorded registry/lock hashes."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request


CRATES = (
    ("aws-config", "1.8.12", "96571e6996817bf3d58f6b569e4b9fd2e9d2fcf9f7424eed07b2ce9bb87535e5"),
    ("p256", "0.14.0", "d2c9239b2dbc807adbbe147e8cf72ea7450c3a0aabe62cb8e75ff4ec22e1f72a"),
    ("elliptic-curve", "0.14.3", "900f37e7e18d74a2347389af6cd69e3a30d5cc9e697f40004865679aa75e9c7c"),
    ("crypto-bigint", "0.7.10", "9c035cb64cba03dad2fb921f3e218785e8cf9a41790da5eb3a1400f62fa2be11"),
)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    receipts = []
    for name, version, expected in CRATES:
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        path = output / f"{name}-{version}.crate"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"Official crate hash mismatch: {name} {version}")
        with path.open("xb") as stream:
            stream.write(data)
        with tarfile.open(path, "r:gz") as archive:
            archive.extractall(output / "source", filter="data")
        receipt = {"name": name, "version": version, "url": url,
            "sha256": actual, "bytes": len(data)}
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
    (output / "FETCH_RECEIPTS.json").write_text(json.dumps(receipts, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
