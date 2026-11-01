"""Descriptive action differences and explicit cold/warm accounting totals."""

import gzip
import json
from pathlib import Path


def main():
    root = Path(__file__).parent / "run_confirm_01"
    summary = json.loads((root / "SUMMARY.json").read_text())
    contrasts = {}
    for result_path in sorted(root.glob("*/RESULT.json")):
        worker = json.loads(result_path.read_text())
        domain = worker["domain"]
        for archive in worker["archives"]:
            with gzip.open(result_path.parent / archive["file"], "rt") as stream:
                worlds = json.load(stream)
            for world in worlds:
                risk = world["arms"]["value_risk"]["queries"]
                for reference in ("state_confidence", "stop_value", "ordinary_dual"):
                    key = f"{domain}:value_risk-minus-{reference}"
                    item = contrasts.setdefault(key, dict(queries=0, first_actions_differ=0, answers_differ=0))
                    other = world["arms"][reference]["queries"]
                    for left, right in zip(risk, other, strict=True):
                        first = lambda row: row["actions"][0]["action"] if row["actions"] else "STOP"
                        item["queries"] += 1
                        item["first_actions_differ"] += first(left) != first(right)
                        item["answers_differ"] += left["answer"] != right["answer"]
    ratios = {}
    for domain, costs in summary["current_costs"].items():
        risk, ordinary = costs["value_risk"], costs["ordinary_dual"]
        ratios[domain] = dict(feature_ratio=risk["mean_feature_cpu_per_query"] / ordinary["mean_feature_cpu_per_query"],
                              warm_owner_ratio=risk["mean_online_cpu_seconds"] / ordinary["mean_online_cpu_seconds"],
                              current_1000_use_ratio=risk["reused_current_cpu"]["1000"] / ordinary["reused_current_cpu"]["1000"])
    receipts = json.loads((root / "PROCESS_RECEIPTS.json").read_text())
    stats = json.loads((root / "STATISTICS_PROCESS_RECEIPT.json").read_text())
    result = dict(schema="hcsn-r16-channel-descriptive-details-v1", contrasts=contrasts,
                  cpu_ratios_to_ordinary_dual=ratios,
                  confirmation_child_cpu_seconds=sum(row["child_cpu_seconds"] for row in receipts["receipts"]),
                  statistics_child_cpu_seconds=stats["child_cpu_seconds"],
                  maximum_raw_archive_bytes=max(path.stat().st_size for path in root.glob("*/raw_*.json.gz")),
                  scope="Predeclared descriptive action/answer and CPU summaries; no new efficacy test or primary-gate rescue.")
    with (root / "DESCRIPTIVE_DETAILS.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
