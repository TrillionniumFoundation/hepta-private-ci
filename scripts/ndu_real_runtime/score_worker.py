"""Small explicit entry point for the separately executed frozen evaluator."""

import argparse
import json
from pathlib import Path

from ndu_real_materials.common import write_json
from ndu_real_materials.evaluator import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--delivery-root", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--reference-index-sha256", required=True)
    parser.add_argument("--rubric-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root, args.case_id, args.delivery_root, args.delivery,
                      expected_index_sha256=args.reference_index_sha256,
                      expected_rubric_sha256=args.rubric_sha256)
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0
