"""Run only a remotely frozen formal grid, retaining all subprocess evidence."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from export_native import canonical, sha
from freeze_source import verify
from processes import Ledger, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.freeze_commit):
        raise ValueError("the published frozen source commit is required")
    here = Path(__file__).resolve().parent
    manifest = verify(here / "SOURCE_MANIFEST.json")
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((here / "PROTOCOL.json").read_text())
    (args.output / "SOURCE_MANIFEST.json").write_bytes((here / "SOURCE_MANIFEST.json").read_bytes())
    (args.output / "PROTOCOL.json").write_bytes((here / "PROTOCOL.json").read_bytes())
    freeze = {"schema": "hepta.memory.v10.run-freeze.v1", "declared_published_source_commit": args.freeze_commit,
              "source_manifest_sha256": sha((here / "SOURCE_MANIFEST.json").read_bytes()),
              "protocol_sha256": sha((here / "PROTOCOL.json").read_bytes()), "python": sys.version,
              "runner_network_verified_remote_commit": False,
              "remote_publication_verification": "controller must bind its independently observed repository commit",
              "seeds": protocol["seeds"], "capacities": protocol["capacities"]}
    (args.output / "RUN_FREEZE.json").write_bytes(canonical(freeze))
    (args.output / "DEPENDENCIES.actual.txt").write_bytes(subprocess.check_output([sys.executable, "-m", "pip", "freeze", "--all"]))
    ledger = Ledger(args.output)
    ledger.run("prepare-train-calibration", [sys.executable, str(here / "research_prepare.py"),
                                            "--output", str(args.output / "data"), "--encoder-dir", str(args.encoder_dir)])
    for capacity in protocol["capacities"]:
        for seed in protocol["seeds"]:
            name = f"capacity-{capacity}-seed-{seed}"
            ledger.run("fit-" + name, [sys.executable, str(here / "research_fit.py"),
                                       "--data", str(args.output / "data" / f"capacity-{capacity}"),
                                       "--output", str(args.output / "models" / name),
                                       "--capacity", str(capacity), "--seed", str(seed)])
    # No fitting process remains when held text is first opened and encoded.
    verify(here / "SOURCE_MANIFEST.json")
    ledger.run("prepare-held-after-all-fits", [sys.executable, str(here / "research_prepare.py"),
                                              "--output", str(args.output / "data"), "--encoder-dir", str(args.encoder_dir), "--held-only"])
    for capacity in protocol["capacities"]:
        for seed in protocol["seeds"]:
            name = f"capacity-{capacity}-seed-{seed}"
            ledger.run("read-" + name, [sys.executable, str(here / "research_evaluate.py"),
                                        "--data", str(args.output / "data" / f"capacity-{capacity}"),
                                        "--models", str(args.output / "models" / name),
                                        "--output", str(args.output / "evaluation" / name)])
    ledger.run("summarize", [sys.executable, str(here / "summarize.py"), "--run", str(args.output)])
    (args.output / "ARTIFACTS.json").write_bytes(canonical(inventory(args.output)))
    print(json.dumps({"run": str(args.output), "subprocesses": len(ledger.rows), "all_returned_success": True,
                      "scientific_win_claimed_by_runner": False}))


if __name__ == "__main__":
    main()
