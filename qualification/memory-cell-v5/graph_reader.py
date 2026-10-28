"""Fresh-process Router -> real numeric graph or independent strong planner."""

import argparse
from pathlib import Path

from legacy_v3.semantic_router import strict_json
from v5.graph_process import execute_request
from v5.joint_io import write_document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = execute_request(strict_json(args.request.read_bytes()))
    write_document(args.output, result)
