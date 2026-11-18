"""Replay the existing E5 source/budget accounting on retained Run02 identities."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from cell_experiments.source_metrics_v3 import source_growth_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    raw = (here / "SOURCE_RECORDS_PROJECTION.json").read_bytes()
    projection_sha = hashlib.sha256(raw).hexdigest()
    if (
        projection_sha
        != "272b97b06c8c6d08e22c3e8c5c8522e18edefab2d40589e1d69abe0c67ca9126"
    ):
        raise ValueError("retained identity projection differs")
    projection = json.loads(raw)
    rows = [row for row in projection["projection"] if row["split"] == "train"]
    if not all(row["authorization"]["training_allowed"] is True for row in rows):
        raise ValueError("training permission absent from selected record")
    result = {
        "schema": "hepta.e5-existing-material-readout.20261118",
        "status": "BLOCKED_INDEPENDENT_SOURCE_GROWTH",
        "source_commit": projection["source_commit"],
        "source_projection_sha256": projection_sha,
        "training_records": len(rows),
        "selection_records_excluded": len(projection["projection"]) - len(rows),
        "project_grouping": source_growth_metrics(rows, unit_field="project_id"),
        "file_source_grouping": source_growth_metrics(rows, unit_field="source_id"),
        "new_independent_sources": 0,
        "new_users": 0,
        "new_task_executions": 0,
        "reason": "Six retained authored training tasks from one project do not authenticate independent users or supply a future-task curve.",
    }
    if args.check:
        expected = json.loads((here / "E5_SOURCE_GROWTH_READOUT.json").read_text())
        if result != expected:
            raise ValueError("source/budget readout differs")
        print(
            json.dumps(
                {
                    "status": "MATCH",
                    "project_groups": result["project_grouping"]["available_groups"],
                    "file_groups": result["file_source_grouping"]["available_groups"],
                    "new_task_executions": 0,
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
