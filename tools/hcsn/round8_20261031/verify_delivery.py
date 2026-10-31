"""Read-only verification of the delivered Git files and frozen dependencies.

Run in a checkout pinned to the delivered commit. This manifest does not
authenticate itself; Git provides that identity. Evidence restoration has its
own per-volume and per-member checks in bundles.py.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent


def verify(repo, manifest):
    report = {"schema": "hepta.hcsn.delivery-file-check.v1", "passed": False,
        "delivered_files": 0, "frozen_dependencies": 0,
        "scientific_tests_repeated": False, "errors": []}
    seen = set()
    for group in ("delivered_files", "frozen_dependencies"):
        for row in manifest[group]:
            relative = PurePosixPath(row["path"])
            if relative.is_absolute() or ".." in relative.parts or row["path"] in seen:
                raise ValueError("Invalid or duplicate manifest path: " + row["path"])
            seen.add(row["path"])
            path = repo.joinpath(*relative.parts)
            try:
                size = path.stat().st_size
                sha256 = hashlib.sha256()
                git_blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
                with path.open("rb") as stream:
                    for data in iter(lambda: stream.read(1024 * 1024), b""):
                        sha256.update(data)
                        git_blob.update(data)
                actual = {"bytes": size, "sha256": sha256.hexdigest(),
                    "git_blob_sha": git_blob.hexdigest()}
                wrong = [key for key, value in actual.items() if row[key] != value]
                if wrong:
                    report["errors"].append({"path": row["path"], "mismatch": wrong})
                else:
                    report[group] += 1
            except OSError as error:
                report["errors"].append({"path": row["path"], "error": str(error)})
    report["passed"] = not report["errors"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=HERE.parents[2])
    parser.add_argument("--manifest", type=Path, default=HERE / "DELIVERY_MANIFEST.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.repo.resolve(), json.loads(args.manifest.read_text()))
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
