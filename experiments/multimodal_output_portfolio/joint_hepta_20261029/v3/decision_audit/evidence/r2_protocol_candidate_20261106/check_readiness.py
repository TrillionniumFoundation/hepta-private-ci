"""Report missing real R2 prerequisites without opening data or starting work."""

import argparse
import json
from pathlib import Path

from r2_capture import digest, hash_string, require


ROOT = Path(__file__).resolve().parent
GATES = ("NEW_DATA", "EVALUATOR_CUSTODY", "REAL_TRAINER", "BUDGET_AND_BASELINES", "QUALITY_AND_POWER", "CANDIDATE_IDENTITY")


def readiness(protocol, state):
    require(state["protocol_sha256"] == digest(protocol), "readiness belongs to another protocol")
    require(set(state["actual_gates"]) == set(GATES), "missing/unregistered readiness gate")
    open_gates = []
    for name in GATES:
        item = state["actual_gates"][name]
        require(item["status"] in ("OPEN", "EVIDENCE_SUPPLIED_FOR_REVIEW"), "a JSON gate cannot grant scientific authority")
        if item["status"] == "OPEN":
            open_gates.append(name)
        else:
            hash_string(item["evidence_sha256"], name)
    return {"schema": "hepta.r2.readiness-report.v1", "protocol_sha256": digest(protocol),
            "status": "BLOCKED" if open_gates else "EXTERNAL_REVIEW_REQUIRED",
            "open_gates": open_gates, "evidence_is_not_self_authenticating": True,
            "test_dispatch_allowed": False, "training_started": False,
            "model_update_allowed": False, "no_update": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(ROOT / "PROTOCOL.json"))
    parser.add_argument("--state", default=str(ROOT / "READINESS_INPUT.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = readiness(json.loads(Path(args.protocol).read_bytes()), json.loads(Path(args.state).read_bytes()))
    raw = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        with Path(args.output).open("x") as out:
            out.write(raw)
    print(raw, end="")
    raise SystemExit(2 if result["status"] == "BLOCKED" else 3)


if __name__ == "__main__":
    main()
