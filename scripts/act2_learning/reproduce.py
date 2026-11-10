"""Reproduce the retained audit in an isolated directory, without new trials."""

import argparse
import hashlib
import lzma
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve(strict=True)
    evidence = repository / "qualification/act2-learning-20261110"
    with tempfile.TemporaryDirectory(prefix="act2-reproduce-") as directory:
        root = Path(directory) / "project"
        retained = root / "qualification/act2-learning-20261110"
        shutil.copytree(
            evidence,
            retained,
            ignore=shutil.ignore_patterns("destination-databases.zip"),
        )
        source = root / "scripts/act2_learning"
        source.mkdir(parents=True)
        with zipfile.ZipFile(retained / "run2/source-postimages.zip") as frozen:
            for name in ("run.py", "models.py", "sqlite_destination.py"):
                (source / name).write_bytes(frozen.read(name))
        compressed = retained / "run2/destination-databases.zip.xz"
        if hashlib.sha256(compressed.read_bytes()).hexdigest() != "bc28ab9e28efcc1ab96883b73bab221c2ae10d6dfb35b005fd1c230b12410632":
            raise ValueError("compressed original database archive identity mismatch")
        original = lzma.decompress(compressed.read_bytes())
        if hashlib.sha256(original).hexdigest() != "b0ec17badc0595c18a876949f6bcfd07e42c37f825fb30c11ccdc79ec853d983":
            raise ValueError("restored original database archive identity mismatch")
        compressed.with_suffix("").write_bytes(original)
        audit = (evidence / "review/audit.py.txt").read_text()
        old_root = "ROOT = Path('/workspace/scratch/bea4b0a478f1/act2-closure-learning')"
        old_out = "OUT = Path('/workspace/scratch/bea4b0a478f1/act2-closure-learning-review')"
        if audit.count(old_root) != 1 or audit.count(old_out) != 1:
            raise ValueError("original audit path mapping does not match")
        output = Path(directory) / "review"
        audit = audit.replace(old_root, f"ROOT = Path({str(root)!r})")
        audit = audit.replace(old_out, f"OUT = Path({str(output)!r})")
        mapped = Path(directory) / "audit-path-mapped.py"
        mapped.write_text(audit)
        subprocess.run([sys.executable, str(mapped)], check=True)
        print((output / "REVIEW.json").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
