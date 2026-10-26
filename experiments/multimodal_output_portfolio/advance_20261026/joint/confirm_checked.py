"""Run the frozen collector and require the additional preregistered custody audit."""

import argparse
import json
from pathlib import Path
import traceback

from ...abc_recovery.base_recovery import write_json
from .audit_confirm import audit, sha
from .confirm import main as collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect()
    try:
        checked = audit(args.protocol, args.output)
        write_json(args.output / "COMPLETENESS_AUDIT.json", checked)
        collected = json.loads((args.output / "RESULTS.json").read_text())
        verdict = {"schema": "hepta.advance.joint-audited-verdict.v1", "audit_passed": checked["passed"],
                   "primary_gate": collected["analysis"]["primary_gate"],
                   "results_sha256": sha(args.output / "RESULTS.json"),
                   "audit_sha256": sha(args.output / "COMPLETENESS_AUDIT.json"),
                   "passed": checked["passed"] and collected["analysis"]["primary_gate"].get("passed", False)}
        write_json(args.output / "CHECKED_RESULT.json", verdict)
        print(json.dumps(verdict), flush=True)
    except Exception:
        write_json(args.output / "AUDIT_FAILURE.json", {"traceback": traceback.format_exc(),
                                                       "all_actual_outputs_preserved": True})
        raise


if __name__ == "__main__":
    main()
