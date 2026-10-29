"""Aggregate the fixed grid without changing thresholds, models or gates."""

import argparse
import json
from pathlib import Path
import statistics


def percent(correct, count):
    return 100 * correct / count if count else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    results = [json.loads(path.read_text()) for path in sorted((args.run / "evaluation").glob("*/RESULTS.json"))]
    protocol = json.loads((args.run / "PROTOCOL.json").read_text())
    if len(results) != len(protocol["seeds"]) * len(protocol["capacities"]):
        raise ValueError("incomplete formal grid cannot be summarized as complete")
    lines = ["# V10 fixed comparison", "", "This is a finite authored inventory experiment with frozen MiniLM representations and learned affine heads/residuals. It does not fine-tune a Transformer or establish a general memory system.", "",
             "Three declared optimization seeds are descriptive replications, not independent real-world task distributions. Every held score below comes from a process launched after all fit workers exited.", "",
             "## Content at oracle canonical addresses", "", "| Capacity | Type | Independently trained linear | Rank-4 residual | Untrained | Exact SQL |", "|---:|---|---:|---:|---:|---:|"]
    for capacity in protocol["capacities"]:
        group = [row for row in results if row["capacity"] == capacity]
        for kind in ("semantic", "procedure"):
            scores = []
            for arm in ("linear", "residual", "untrained", "exact_sql"):
                metrics = [row["content"][f"{kind}-{arm}"] for row in group]
                scores.append(percent(sum(row["canonical_correct"] for row in metrics), sum(row["canonical_count"] for row in metrics)))
            lines.append(f"| {capacity} | {kind} | " + " | ".join(f"{value:.2f}%" for value in scores) + " |")
    lines += ["", "## New typed combinations", "", "All learned composition arms receive the same pair features, target groups and exact row schedule. Typed and block-head joint have equal parameter counts; dense joint is larger and charged separately. The SQL planner retains the same information and uses the same bounded interpreter.", "", "| Capacity | Arm | Exact non-held execution | Both stored parameter values exact |", "|---:|---|---:|---:|"]
    for capacity in protocol["capacities"]:
        group = [row for row in results if row["capacity"] == capacity]
        for arm in ("typed", "joint", "dense_joint", "exact_sql"):
            metrics = [row["composition"][arm] for row in group]
            execution = percent(sum(row["nonheld_exact"] for row in metrics), sum(row["nonheld_count"] for row in metrics))
            parameters = percent(sum(row["both_parameter_values_exact"] for row in metrics), sum(row["count"] for row in metrics))
            lines.append(f"| {capacity} | {arm} | {execution:.2f}% | {parameters:.2f}% |")
    lines += ["", "## Addressing on unseen wording and unknown requests", "",
              "Known coverage is `known_accepted / known_count`. Precision among accepted known requests is `known_correct_accepted / known_accepted`; it is undefined (NA) when no known requests are accepted. Correct known acceptance is `known_correct_accepted / known_count`. Counts are pooled across seeds before forming these ratios; unknown acceptance is reported separately.", "",
              "| Capacity | Router | Known accepted / total | Known coverage | Accepted-known precision | Correct known acceptance | Unknown acceptance |",
              "|---:|---|---:|---:|---:|---:|---:|"]
    for capacity in protocol["capacities"]:
        group = [row for row in results if row["capacity"] == capacity]
        for arm in ("oracle", "deterministic", "learned", "nearest"):
            metrics = [row["routing"][arm] for row in group]
            correct = sum(row["known_correct_accepted"] for row in metrics)
            known_count = sum(row["known_count"] for row in metrics)
            known_accepted = sum(row["known_accepted"] for row in metrics)
            known = percent(correct, known_count)
            coverage = percent(known_accepted, known_count)
            precision = f"{percent(correct, known_accepted):.2f}%" if known_accepted else "NA (no accepted known requests)"
            unknown = percent(sum(row["unknown_accepted"] for row in metrics), sum(row["unknown_count"] for row in metrics))
            lines.append(f"| {capacity} | {arm} | {known_accepted}/{known_count} | {coverage:.2f}% | {precision} | {known:.2f}% | {unknown:.2f}% |")
    lines += ["", "## Lifecycle and promotion", "", "No split or merge is promoted. Gradient-driven children, fixed experts, rank expansion, merge distillation and release/reload are retained as candidates with exact checkpoints. Structural worded reads use the true registry address to select saved cluster membership, so these results are conditional on oracle addressing. A closed cost-completeness gate prevents a quality result from being relabeled a full lifecycle win.", "",
              "The compatibility arm name `reservoir16` means 16-record replay sampling: each ordinary cycle samples 15 records afresh from the full active list and includes the corrected or inserted record. It does not model a persistent streaming reservoir. Both arms rebuild on all retained records after deletion.", "",
              "| Seed | Maintenance arm | Final retained correct | Worst-cycle retained correct | Deleted/stopped reads entered model |", "|---:|---|---:|---:|---:|"]
    for seed in protocol["seeds"]:
        path = args.run / "evaluation" / f"capacity-64-seed-{seed}" / "MAINTENANCE.json"
        maintenance = json.loads(path.read_text())
        for arm in ("full_replay", "reservoir16"):
            metrics = [row["arms"][arm] for row in maintenance["cycles"]]
            final = metrics[-1]
            worst = min(percent(row["retained_correct"], row["retained_count"]) for row in metrics)
            lines.append(f"| {seed} | {arm} | {percent(final['retained_correct'], final['retained_count']):.2f}% | {worst:.2f}% | {sum(row['model_reads_during_denials'] for row in metrics)} |")
    process_rows = json.loads((args.run / "PROCESSES.json").read_text())
    lines += ["", "## Cost accounting scope", "", f"Completed child processes before report generation: {len(process_rows)}. Sum of non-overlapping child wall scopes: {sum(row['wall_seconds'] for row in process_rows):.3f} s. Child CPU: {sum(row['child_user_cpu_seconds'] + row['child_system_cpu_seconds'] for row in process_rows):.3f} s. Peak cumulative child RSS: {max(row['cumulative_child_maxrss_kib'] for row in process_rows)} KiB.", "",
              "The process ledger includes encoding, fitting, checkpoint I/O and fresh evaluation. Per-fit receipts are nested measurements and must not be added again. Pipeline timing includes reference lookup and evidence serialization, so it is not isolated serving latency. Artifact inventory separates weights, source database, feature caches, schedules and retained history. Package installation, uploads, external host execution and energy are not measured here; no complete lifecycle cost advantage is claimed.", "",
              "Read-arm order uses only offsets 0, 1 and 2 of six arms across the three seeds. This partial rotation does not fully counterbalance order effects.", "",
              "Python deletion guards and explicit array release/reload are research mechanisms. Durable owner source authentication, true control sockets, live source invalidation and process stops are established only by the separate native integration evidence. Historical files remain for audit; service revocation and clean rebuilding do not imply physical erasure of all historical information.", ""]
    (args.run / "SUMMARY.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
