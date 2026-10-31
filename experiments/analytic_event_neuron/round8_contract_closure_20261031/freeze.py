"""Bind unchanged R7 inputs, complete candidate bytes and confirmation source."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ..round7.study import verify_freeze


def prepare(root):
    root = Path(root).resolve()
    baseline = verify_freeze(root.parent / "round7")
    models = sorted((root / "evidence/calibration_models").glob("*.json"))
    if len(models) != 60:
        raise ValueError("all sixty predeclared stage checkpoints must exist")
    files = list(root.glob("*.py")) + list((root / "native").glob("*.rs")) + models
    files += [root / name for name in ("PROTOCOL.json", "native/build.py", "native/workflow.py")]
    files += list((root.parent / "round7").glob("*.py"))
    files += list((root.parent / "round7/posthoc").glob("*.py"))
    files += [root.parent / name for name in ("analytic.py", "reference.py", "__init__.py")]
    files += [root / "evidence/native_build/BUILD_ATTEMPT03.json"]
    import os
    records = {os.path.relpath(path, root): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(set(files))}
    record = {"schema": "hepta.contract-closure.freeze.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "confirmation_started": False, "files": records, "candidates": 60,
              "baseline_manifest_sha256": baseline["sha256"],
              "protocol_commit": "13f3bcb9397a38301c9762c4f0bbe7cdacf59cb9",
              "multiplicity_amendment_commit": "106884ccd1aedac3ac49171bd554b2de1ff5b80a",
              "selection": "All final fixed-budget stages retained; fresh heldout and confirmation not yet executed"}
    path = root / "FREEZE.json"
    with path.open("x", encoding="utf8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files": len(records), "candidates": len(models)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    print(json.dumps(prepare(parser.parse_args().root)))
