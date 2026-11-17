"""Prepare authorized train-only input using the existing data.py contract.

This example never selects B/C, runs a model, executes a verifier, or authenticates
provenance. A missing trajectory input produces INPUT_REQUIRED and exit code 2.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--train-records", type=Path)
    parser.add_argument("--mode", choices=("final_answer", "trajectory"), default="final_answer")
    parser.add_argument("--output-new", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    rows = [json.loads(line) for line in args.observations.read_text().splitlines()]
    issues = [r for r in rows if r["record_type"] == "issue_or_pr_metadata" and not r["is_pull_request"]]
    prs = [r for r in rows if r["record_type"] == "issue_or_pr_metadata" and r["is_pull_request"]]
    module_path = args.repository_root / inventory["intake"]["authoritative_module"]
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    if module_sha != inventory["intake"]["authoritative_module_sha256"]:
        raise ValueError("existing data.py differs from the reviewed intake contract")
    report = {
        "schema": "hepta.source-intake-operation.v1",
        "status": "INPUT_REQUIRED",
        "inventory_sha256": hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
        "observations_sha256": hashlib.sha256(args.observations.read_bytes()).hexdigest(),
        "data_module_sha256": module_sha,
        "issue_metadata_records": len(issues),
        "unique_issue_urls": len({r["url"] for r in issues}),
        "distinct_issue_author_accounts": len({r["user"]["id"] for r in issues}),
        "nonbot_issue_author_accounts": len({r["user"]["id"] for r in issues if not r["user"]["login"].endswith("[bot]")}),
        "PR_metadata_records": len(prs),
        "unique_PR_urls": len({r["url"] for r in prs}),
        "PRs_counted_as_independent_tasks": 0,
        "historical_requirement_candidates": sum(r["source_status"] == "NEWLY_RETRIEVED_HISTORICAL_REQUIREMENT" for r in inventory["source_candidates"]),
        "admitted_training_records": 0,
        "new_independent_sources_authenticated": 0,
        "authenticated_independent_human_users": None,
        "model_calls": 0,
        "training_calls": 0,
        "business_verifier_calls": 0,
        "provenance_authenticated": False,
        "scientific_qualification": False,
        "production_adoption": False,
        "mode": args.mode,
        "examples": [],
    }
    exit_code = 2
    if args.train_records is not None:
        try:
            if args.train_records.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("this bounded intake example accepts at most 16 MiB")
            spec = importlib.util.spec_from_file_location("reviewed_intake_data", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            records = module.load_records(args.train_records, independent=False)
            if any(record["split"] != "train" for record in records):
                raise ValueError("provide a separately approved train-only artifact; B/C is not intake input")
            examples = module.build_sft_examples(records, mode=args.mode)
            report.update(
                status="TRAINING_RECORD_STRUCTURE_READY",
                admitted_training_records=len(records),
                declared_task_count=len({r["task_id"] for r in records}),
                declared_lineage_count=len({r["lineage_id"] for r in records}),
                declared_project_count=len({r["project_id"] for r in records}),
                train_records_sha256=hashlib.sha256(args.train_records.read_bytes()).hexdigest(),
                record_digest=module.digest(records),
                examples=examples,
            )
            exit_code = 0
        except (ValueError, OSError, TypeError, KeyError) as error:
            report.update(status="INPUT_REJECTED", error=str(error))
            exit_code = 1
    else:
        report["missing_input"] = "Original authorized visible trajectories with retained teacher/action/environment and semantic-result evidence."
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with args.output_new.open("x") as destination:
        destination.write(raw)
    print(json.dumps({key: value for key, value in report.items() if key != "examples"}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
