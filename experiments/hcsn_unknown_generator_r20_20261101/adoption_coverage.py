"""Read-only prospective coverage subgate, separate from every frozen scientific gate."""

import json
from pathlib import Path

ROOT = Path(__file__).parent


def evaluate(summary, spec):
    result = dict(schema="hcsn.r20.adoption-coverage-evaluation.v1", panels={},
        reference_scope=spec["reference"]["scope_flag"], original_registered_gates_modified=False,
        all_blockers_closed=False, full_model_adoption=False, production_activation=False)
    for panel in spec["panels"]:
        records = summary["panels"][panel]
        result["panels"][panel] = {}
        for name in spec["arms"]:
            record = records["models"][name]
            quality, worlds = record["quality"], record["attempts"]
            if quality is None:
                result["panels"][panel][name] = dict(quality=None, coverage_risk_subgate=False)
                continue
            fractional_rate = quality["fractional"] / worlds
            reconstructed_research = (record["calibration"]["calibration_gate_passed"] and not record["invalid"]
                and not quality["support_losses"] and quality["fractional"] >= spec["minimum_fractional_count"]
                and max(quality["upper95_fractional"], quality["upper95_overall"]) <= spec["risk_limit"])
            if quality["gate"] != reconstructed_research:
                raise ValueError("Registered-gate record mismatch")
            result["panels"][panel][name] = dict(worlds=worlds, accepted=quality["accepted"],
                total_answer_rate=quality["accepted"] / worlds, fractional_accepted=quality["fractional"],
                fractional_rate=fractional_rate, fractional_rate_floor=spec["fractional_rate_floor"],
                upper95_fractional_risk=quality["upper95_fractional"], upper95_overall_risk=quality["upper95_overall"],
                registered_count_risk_gate=quality["gate"],
                coverage_risk_subgate=bool(reconstructed_research and fractional_rate >= spec["fractional_rate_floor"]))
    result["context_all_five_coverage_risk_subgates"] = all(
        result["panels"][panel]["context_orbit"]["coverage_risk_subgate"] for panel in spec["panels"])
    return result


if __name__ == "__main__":
    summary = json.loads((ROOT / "confirm_v2_01/SUMMARY.json").read_text())
    spec = json.loads((ROOT / "ADOPTION_COVERAGE.json").read_text())
    print(json.dumps(evaluate(summary, spec), sort_keys=True))
