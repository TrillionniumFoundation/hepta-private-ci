"""Research-only base/shuffled read entrypoint, separate from production RPC."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory_cell"))
from parametric_worker import run


if __name__ == "__main__":
    root, control = Path(sys.argv[1]).resolve(), sys.argv[2]
    if control not in ("base", "shuffled"):
        raise ValueError("only separately labelled research controls")
    config = json.loads((root / "native_config.json").read_text())
    query = json.loads((root / "read_query.json").read_text())
    result = run(
        {
            "model": config["model"],
            "snapshot": config["checkpoint"],
            "manifest_sha256": config["pins"]["manifest_sha256"],
            "scope": config["scope"],
            "allowed_roots": [query["source_root"]],
            "rank": config["rank"],
            "seed": config["seed"],
            "control": control,
            "questions": [query["question"]],
        }
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
