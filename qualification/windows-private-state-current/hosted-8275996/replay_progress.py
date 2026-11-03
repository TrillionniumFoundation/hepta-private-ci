#!/usr/bin/env python3
"""Replay the original Windows log through old and current acquisition readers."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import types

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = "8275996f2c589a96843e116ac6f2c1d194ef3d2b"
SCRIPT = ".github/scripts/check_windows_private_state_acquisition.py"


def main():
    raw = gzip.decompress((HERE / "windows-positive.log.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == "d9af475c470a98727da41ae78bb04d2eed121d176df7a31ae54ec62351879223"
    old = subprocess.check_output(["git", "--no-replace-objects", "show", BASE + ":" + SCRIPT], cwd=ROOT)
    assert hashlib.sha256(old).hexdigest() == "b116a2747ac848ec6e3d9b16204151a2f51e136e94ec443e7709efa14b5bd204"
    new = (ROOT / SCRIPT).read_bytes()
    result = {}
    for name, source in [("baseline", old), ("candidate", new)]:
        module = types.ModuleType(name)
        module.__file__ = str(ROOT / SCRIPT)
        exec(compile(source, str(ROOT / SCRIPT), "exec"), module.__dict__)
        try:
            actual = module.check_result("positive", 0, raw.decode("utf-8", "replace"))
            result[name] = {"accepted": True, "result": actual}
        except RuntimeError as error:
            result[name] = {"accepted": False, "error": str(error)}
    assert result["baseline"] == {"accepted": False, "error": "wrong exact test outcomes: {}"}
    assert result["candidate"]["accepted"] is True
    print(json.dumps({"source_commit": BASE, "workflow_run": 41713496978,
                      "job": 126187377199, "original_positive_process_exit": 0,
                      "raw_log_sha256": hashlib.sha256(raw).hexdigest(),
                      "candidate_reader_sha256": hashlib.sha256(new).hexdigest(),
                      "result": result, "native_reexecution": False,
                      "mutant_execution_in_original_run": False}, indent=2))


if __name__ == "__main__":
    main()
