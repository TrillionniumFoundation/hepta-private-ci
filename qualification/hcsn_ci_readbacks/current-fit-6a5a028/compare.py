"""Compare the full two-scalar fit trajectories in verified original archives."""
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path


def archive(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"ZIP digest mismatch for {path}")
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip() is not None:
            raise ValueError(f"duplicate or damaged members in {path}")
        lines = z.read("TEST.stdout").decode().splitlines()
        summary = json.loads(z.read("RESULT.json"))
    prefix = "NATIVE_ALIGNED_EVIDENCE "
    record, = [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
    fit, = [row for row in record["records"] if row["case"] == "synthetic_known_physics_fit"]
    if (summary["tests_passed"] != 45 or summary["skips"] != 0 or summary["optimizer_updates"] != 120
            or [r["step"] for r in fit["records"]] != list(range(121))):
        raise ValueError("incomplete fit")
    return fit["records"]


def scalars(row):
    return row["relative_mse"], row["reset"], row["mark"], *row["gradients"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reference", type=Path)
    p.add_argument("reference_sha256")
    p.add_argument("candidate", type=Path)
    p.add_argument("candidate_sha256")
    args = p.parse_args()
    old = archive(args.reference, args.reference_sha256)
    new = archive(args.candidate, args.candidate_sha256)
    pairs = [pair for a, b in zip(old, new, strict=True) for pair in zip(scalars(a), scalars(b), strict=True)]
    equal = sum(struct.pack(">d", a) == struct.pack(">d", b) for a, b in pairs)
    print(json.dumps(dict(points=len(old), scalar_pairs=len(pairs), binary64_exact=equal,
                          max_absolute_error=max(abs(a-b) for a,b in pairs))))


if __name__ == "__main__":
    main()
