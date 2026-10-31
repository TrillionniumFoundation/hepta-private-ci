"""Bind the reviewed completeness audit before opening any new input to a model."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from .freeze_confirm import sha, source_closure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-result", type=Path, required=True)
    parser.add_argument("--smoke-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    baseline = args.output.with_name(args.output.stem + "_BASE.json")
    subprocess.run([sys.executable, "-B", "-m", "experiments.multimodal_output_portfolio.advance_20261026.joint.freeze_confirm",
                    "--stage", "confirmation", "--smoke-result", str(args.smoke_result), "--output", str(baseline)], check=True)
    spec = json.loads(baseline.read_text())
    smoke = json.loads(args.smoke_audit.read_text())
    if not smoke["passed"] or smoke["complete_registered_cases"] != 256:
        raise ValueError("Full old-source technical smoke audit is required")
    pins = {str(path): sha(path) for path in source_closure(directory / "confirm_checked.py")}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    spec["frozen_candidate_sha256"].update(pins)
    spec.update(schema="hepta.advance.joint-confirmation-protocol.v2", registered_unix_ns=time.time_ns(),
                executable_module="experiments.multimodal_output_portfolio.advance_20261026.joint.confirm_checked",
                parent_registration={"path": str(baseline.resolve()), "sha256": sha(baseline)},
                old_smoke_audit={"path": str(args.smoke_audit.resolve()), "sha256": sha(args.smoke_audit)},
                required_post_run_audit="Complete (case,route,arm) Cartesian set; all eight tasks per arm/cluster; independent scalar scores; exact actual media SHA; input-video receipts; actual balanced execution order. Failure invalidates the primary result.")
    with args.output.open("x") as stream:
        json.dump(spec, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"protocol": str(args.output.resolve()), "sha256": sha(args.output),
                      "frozen_dependencies": len(spec["frozen_candidate_sha256"])}))


if __name__ == "__main__":
    main()
