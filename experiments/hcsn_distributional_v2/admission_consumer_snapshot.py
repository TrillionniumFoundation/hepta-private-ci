"""Preserve the pre-supplement archive consumers before their explicit revision."""

import hashlib
import json
from pathlib import Path


def main():
    package = Path(__file__).resolve().parent
    output = package / "results/admission_consumer004"
    before = output / "before"
    before.mkdir(parents=True, exist_ok=False)
    names = ("archive_closure.py", "final_bundle_plan.py", "lif_cost_receipts.py",
             "ARCHIVE_CLOSURE.md", "FINAL_BUNDLE_PLAN.md", "LIF_COST_BINDINGS_TEMPLATE.json")
    hashes = {}
    for name in names:
        raw = (package / name).read_bytes()
        (before / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    original = {}
    for name in ("results/content_analysis002/ANALYSIS.json", "results/content_analysis002/EXECUTION.json",
                 "SCALING001_PROTOCOL.json", "scaling_eval.py",
                 "results/lif_cost_receipts001/BINDINGS.json"):
        raw = (package / name).read_bytes()
        original[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    record = dict(schema="hcsn-admission-consumer-before.v1", source_sha256=hashes,
                  original_sha256=original,
                  reason="Explicit engineering revision: preserve strict 175 valid / 1 invalid, require an independent complete producer-exact supplement, and bind separately registered scaling002; no frozen training source or original result changes")
    with (output / "BEFORE.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    (output / "snapshot_source.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
