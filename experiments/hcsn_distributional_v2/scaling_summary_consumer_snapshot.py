"""Preserve the consumers bound by real normalization before a derived auditor."""

import hashlib
import json
from pathlib import Path


def main():
    package = Path(__file__).resolve().parent
    output = package / "results/scaling_summary_consumer005"
    before = output / "before"
    before.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in ("archive_closure.py", "final_bundle_plan.py", "lif_cost_receipts.py",
                 "ARCHIVE_CLOSURE.md", "FINAL_BUNDLE_PLAN.md"):
        raw = (package / name).read_bytes()
        (before / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    originals = {}
    for relative in ("results/lif_cost_receipts001/RECEIPTS.json", "results/lif_cost_normalization001/EXECUTION.json",
                     "SCALING002_PROTOCOL.json", "scaling_admission.py", "results/scaling002/SUITE_EXECUTION.json"):
        path = package / relative
        raw = path.read_bytes()
        originals[relative] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    record = dict(schema="hcsn-scaling-summary-consumer-before.v1", source_sha256=hashes,
                  original_sha256=originals,
                  reason="All 30 original scaling workers completed; original suite failed while computing a zero-denominator ratio. Add a derived final archive auditor for a separately measured summary repair without changing original consumers, normalization, measurements or failed-suite receipt.")
    with (output / "BEFORE.json").open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    (output / "snapshot_source.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
