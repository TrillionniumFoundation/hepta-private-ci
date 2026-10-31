"""Read-only integrity check of explicitly delivered R9 files, not efficacy."""

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def verify(root, manifest):
    source = json.loads(manifest.read_text())
    failures, checked, total = [], 0, 0
    for relative, expected in source["files"].items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            failures.append({"path": relative, "reason": "unsafe or symlink path"})
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            failures.append({"path": relative, "reason": str(error)})
            continue
        observed = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
        if observed != expected:
            failures.append({"path": relative, "reason": "content differs", "observed": observed})
        checked += 1
        total += len(data)
    return {"schema": "hepta.r9.delivery-integrity.v1", "integrity_passed": not failures,
            "checked_files": checked, "expected_files": len(source["files"]),
            "checked_bytes": total, "failures": failures,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "scientific_gates_reinterpreted": False,
            "scope": "Checks explicitly listed delivered files only; parent bundles, training, numerical qualification and native rebuild are separate gates."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=HERE / "DELIVERY_MANIFEST.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.root, args.manifest)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as stream:
            stream.write(rendered)
    print(rendered, end="")
    if not result["integrity_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
