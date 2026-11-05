"""Compare historical scoring semantics on pinned recorded V14 outputs only."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_v14 import REF, SOURCES
from typed_json import equal_json


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs, identities = {}, {}
    names = ["semantic_holdout.json"] + [f"semantic-{seed}.json" for seed in (17, 29, 43)]
    for name in names:
        raw = (args.input_dir / name).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != SOURCES[name][1]:
            raise ValueError("pinned input identity mismatch: " + name)
        identities[name] = {"git_blob": blob, "sha256": sha(raw), "bytes": len(raw)}
        inputs[name] = json.loads(raw)
    holdout = inputs["semantic_holdout.json"]
    counts = {"single_outputs": 0, "composition_outputs": 0}
    changes = []
    for seed in (17, 29, 43):
        for arm, report in inputs[f"semantic-{seed}.json"]["arms"].items():
            for kind, golds, observations in (
                ("single_outputs", holdout["rows"], report["holdout"]["outcomes"]),
                ("composition_outputs", holdout["compositions"], report["compositions"]),
            ):
                for gold, observed in zip(golds, observations, strict=True):
                    counts[kind] += 1
                    clean = (observed["error"] is None if kind == "single_outputs"
                             else not any(item.get("error") for item in observed["trace"]))
                    old = clean and observed["output"] == gold["expected"]
                    strict = clean and equal_json(observed["output"], gold["expected"])
                    if old != strict:
                        changes.append({"seed": seed, "arm": arm, "kind": kind,
                                        "id": gold["id"], "old": old, "strict": strict})
    report = {
        "schema": "hepta.memory.historical-type-audit.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "source_ref": REF,
        "inputs": identities, "counts": counts, "changes": changes,
        "type_comparison_changes": len(changes),
        "source_sha256": {name: sha((ROOT / name).read_bytes())
                          for name in ("typed_json.py", "audit_v14.py")},
        "audit_script_sha256": sha(Path(__file__).read_bytes()),
        "new_model_runs": 0, "new_executor_runs": 0, "new_independent_samples": 0,
        "scope": "Read-only rescoring of recorded outputs; no new model, executor, fixture or independent generalization evidence.",
        "production_activation_allowed": False,
    }
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"counts": counts, "type_comparison_changes": len(changes)}))


if __name__ == "__main__":
    main()
