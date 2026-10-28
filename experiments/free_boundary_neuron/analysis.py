"""Predeclared secondary factorial summaries from saved learning outcomes."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics

from scipy.stats import t as student_t

from .provenance import verify


ARMS = tuple(
    f"{boundary}:{gradient}"
    for boundary in ("fixed", "direct", "free")
    for gradient in ("standard", "first_passage")
)
METRICS = (
    "mean_utility",
    "coverage",
    "mean_observations",
    "active_cell_updates_until_decision",
    "actual_dense_neural_cell_updates",
    "active_spikes_until_decision",
    "inference_seconds",
)


def contrast(values):
    """Seed, not event, is the independent unit; intervals are descriptive."""
    count = len(values)
    mean = statistics.mean(values)
    error = statistics.stdev(values) / count**0.5 if count > 1 else None
    radius = (
        float(student_t.ppf(0.975, count - 1) * error) if error is not None else None
    )
    return {
        "n_independent_seeds": count,
        "paired_differences": values,
        "mean_difference": mean,
        "descriptive_95_ci": [mean - radius, mean + radius]
        if radius is not None
        else None,
        "confirmatory_claim": False,
    }


def summarize(result_path, source_seal):
    source = verify(source_seal)
    result_path = Path(result_path)
    result = json.loads(result_path.read_text())
    phase, records = result["phase"], result["records"]
    if phase not in {"screening", "confirmation"}:
        raise ValueError("Only registered scientific phases have factorial summaries")
    if result["source"]["seal_sha256"] != source["seal_sha256"]:
        raise ValueError("Outcome source seal differs")
    if [row["seed"] for row in records] != result["protocol"][f"{phase}_seeds"]:
        raise ValueError("Seed roster mismatch")
    if any(set(row["arms"]) != set(ARMS) for row in records):
        raise ValueError("Six-arm roster mismatch")
    summary = {}
    contrasts = {}
    references = {}
    for split in ("id_test", "ood_test"):
        summary[split] = {
            arm: {
                metric: statistics.mean(
                    row["arms"][arm][split][metric] for row in records
                )
                for metric in METRICS
            }
            for arm in ARMS
        }
        references[split] = {
            name: {
                metric: statistics.mean(
                    row["references"][split][name][metric] for row in records
                )
                for metric in (
                    "mean_utility",
                    "coverage",
                    "mean_observations",
                    "inference_seconds",
                )
            }
            for name in ("raw_belief_dp", "raw_belief_myopic_voc")
        }
        differences = {}
        for gradient in ("standard", "first_passage"):
            for comparator in ("fixed", "direct"):
                name = f"free_minus_{comparator}:{gradient}"
                values = [
                    row["arms"][f"free:{gradient}"][split]["mean_utility"]
                    - row["arms"][f"{comparator}:{gradient}"][split]["mean_utility"]
                    for row in records
                ]
                differences[name] = contrast(values)
            values = [
                row["arms"][f"free:{gradient}"][split]["mean_utility"]
                - row["references"][split]["raw_belief_dp"]["mean_utility"]
                for row in records
            ]
            differences[f"neural_free_minus_raw_belief_dp:{gradient}"] = contrast(
                values
            )
        for boundary in ("fixed", "direct", "free"):
            values = [
                row["arms"][f"{boundary}:first_passage"][split]["mean_utility"]
                - row["arms"][f"{boundary}:standard"][split]["mean_utility"]
                for row in records
            ]
            differences[f"fpt_minus_standard:{boundary}"] = contrast(values)
        values = [
            row["arms"]["free:first_passage"][split]["mean_utility"]
            - row["arms"]["free:standard"][split]["mean_utility"]
            - row["arms"]["direct:first_passage"][split]["mean_utility"]
            + row["arms"]["direct:standard"][split]["mean_utility"]
            for row in records
        ]
        differences["boundary_gradient_interaction_free_vs_direct"] = contrast(values)
        contrasts[split] = differences
    # Independently check the registered primary interval using stdlib seed
    # aggregation, rather than copying the runner's statistical result.
    for primary in result["statistics"]["primary_comparisons"]:
        values = contrasts["ood_test"][f"free_minus_direct:{primary['gradient']}"][
            "paired_differences"
        ]
        mean = statistics.mean(values)
        radius = float(
            student_t.ppf(0.9875, len(values) - 1)
            * statistics.stdev(values)
            / len(values) ** 0.5
        )
        expected = [mean - radius, mean + radius]
        if (
            max(
                abs(a - b) for a, b in zip(expected, primary["family_adjusted_97_5_ci"])
            )
            > 1e-12
        ):
            raise ValueError("Independent primary interval differs")
    return {
        "schema": "hepta.free-boundary.factorial-summary.v1",
        "phase": phase,
        "source": source,
        "results_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "arm_means": summary,
        "same_information_model_informed_references": references,
        "predeclared_secondary_contrasts": contrasts,
        "registered_primary": result["statistics"],
        "limits": [
            "Secondary intervals are descriptive and are not extra confirmatory tests.",
            "The neural free-boundary arm uses a known task model; raw-belief DP isolates this advantage.",
            "Dense measured inference work is separate from hypothetical stopped-prefix work.",
            "Surrogate parameters stay fixed to isolate the six-arm comparison.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--source-seal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = summarize(args.results, args.source_seal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(payload, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "phase": payload["phase"]}))


if __name__ == "__main__":
    main()
