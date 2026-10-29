"""Run original Torch reader, then independent readers after that process exits."""

import argparse
import json
from pathlib import Path
import sys

from processes import Ledger, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-snapshot", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    here, ledger = Path(__file__).resolve().parent, Ledger(args.output)
    ledger.run("original-torch", [sys.executable, str(here / "legacy_worker.py"),
                                 "--owner-snapshot", str(args.owner_snapshot), "--legacy-root", str(args.legacy_root),
                                 "--encoder-dir", str(args.encoder_dir), "--output", str(args.output)])
    old = json.loads((args.output / "LEGACY_TORCH.json").read_text())
    parity = {"schema": "hepta.memory.v10.legacy-fresh-reader.v1", "models": {},
              "original_torch_process_exited_before_readers": True, "native_rust_executed_by_this_script": False}
    for kind in ("semantic", "procedure"):
        ledger.run("read-" + kind, [sys.executable, str(here / "reference.py"),
                                    "--native", str(args.output / f"{kind}.json"),
                                    "--output", str(args.output / f"{kind}-reference.json")])
        reference = json.loads((args.output / f"{kind}-reference.json").read_text())
        original = sorted(old["models"][kind]["canonical_rows"], key=lambda row: row["address_sha256"])
        matches = all(a["address_sha256"] == b["address_sha256"] and a["value"] == b["value"]
                      for a, b in zip(original, reference["rows"], strict=True))
        parity["models"][kind] = {"original_torch_typed_equal": matches, "fresh_reference": reference}
    parity["processes"] = ledger.rows
    parity["artifacts_before_parity"] = inventory(args.output)
    (args.output / "PARITY.json").write_text(json.dumps(parity, indent=2, allow_nan=False) + "\n")
    if (any(not row["original_torch_typed_equal"] for row in parity["models"].values())
            or any(not row["torch_vs_scalar_within_tolerance"] for row in old["models"].values())):
        raise RuntimeError("original Torch and independent reader disagree; evidence retained")
    print(json.dumps({"output": str(args.output), "fresh_readers": 2, "training_performed": False}))


if __name__ == "__main__":
    main()
