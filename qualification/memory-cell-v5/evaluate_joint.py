"""Evaluate five frozen selected V5 routers over the four restored numeric domains."""

import argparse
import json
from pathlib import Path

from v5.joint_evaluation import evaluate_joint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routers", required=True, type=Path, help="JSON mapping seed strings to selected model directories")
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--held", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    args = parser.parse_args()
    routers = {int(seed): Path(path).resolve() for seed, path in json.loads(args.routers.read_bytes()).items()}
    result = evaluate_joint(routers, args.assets, args.held, args.output, args.freeze)
    print(json.dumps({key: result[key] for key in ("cases", "semantic_cases_pass", "parameter_oracle_cases_pass",
                     "composed_cases_pass", "all_preregistered_gates_pass", "actual_route_requests", "independent_authored_language_templates")}, sort_keys=True))
