"""Verify the active package and replay its unchanged frozen-source checks."""

import hashlib
import json
from pathlib import Path
import runpy
import tempfile


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
PACKAGE = ROOT.relative_to(REPOSITORY)
WORKFLOW = ".github/workflows/hcsn-currentstate-n256-fp64-input-conversion.yml"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"
FREEZE_SHA256 = "30504227ee6145151f7fb3aaa0a89122e3424d879b0f092920f97c1c185c41a1"
SEALED_VIEWS = {
    "README.md", "REQUEST.json", "__init__.py", "fp64_exact.py", "test_fp64_exact.py",
    "verify_source.py",
}


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    read_regular = restore["read_regular"]
    freeze_bytes = read_regular(REPOSITORY, str(PACKAGE / "SOURCE_FREEZE.json"), 8192)
    if hashlib.sha256(freeze_bytes).hexdigest() != FREEZE_SHA256:
        raise ValueError("historical N256 conversion freeze changed")
    freeze = json.loads(freeze_bytes)
    if set(freeze["sha256"]) != SEALED_VIEWS:
        raise ValueError("historical N256 conversion inventory changed")
    workflow = read_regular(REPOSITORY, WORKFLOW, 65536)
    if hashlib.sha256(workflow).hexdigest() != freeze["workflow_sha256"]:
        raise ValueError("historical N256 conversion workflow changed")

    index = restore["entries"](REPOSITORY)
    with tempfile.TemporaryDirectory(prefix="hcsn-n256-fp64-input-original-") as temp:
        original = Path(temp)
        (original / "SOURCE_FREEZE.json").write_bytes(freeze_bytes)
        for filename, expected in freeze["sha256"].items():
            relative = str(PACKAGE / filename)
            active = read_regular(REPOSITORY, relative, 8192)
            if hashlib.sha256(active).hexdigest() != restore["ARCHIVE_NOTICE_SHA256"][relative]:
                raise ValueError(f"active N256 conversion source changed: {filename}")
            entry = index[relative]
            raw = restore["read_verified"](
                REPOSITORY, relative, entry["original_bytes"], expected,
            )
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"historical N256 conversion source changed: {filename}")
            (original / filename).write_bytes(raw)
        runpy.run_path(str(original / "verify_source.py"), run_name="__main__")


if __name__ == "__main__":
    main()
