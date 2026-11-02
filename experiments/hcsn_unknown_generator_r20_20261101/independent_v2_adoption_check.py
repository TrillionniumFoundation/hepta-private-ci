"""Independent exact-fraction check of the separate prospective coverage subgate."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    spec = json.loads((ROOT / "ADOPTION_COVERAGE.json").read_text())
    summary = json.loads((ROOT / "confirm_v2_01/SUMMARY.json").read_text())
    recorded = json.loads((ROOT / "ADOPTION_COVERAGE_EVALUATION.json").read_text())
    freeze_bytes = (ROOT / "POSTCALIBRATION_V2_FREEZE.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    publication = json.loads((ROOT / "CALIBRATION_V2_PUBLICATION.json").read_text())
    assert publication["readback_verified"] and publication["freeze_sha256"] == hashlib.sha256(freeze_bytes).hexdigest()
    for name in ("ADOPTION_COVERAGE.json", "adoption_coverage.py"):
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == freeze["files"][name]
    assert spec["declared_before_new_formal_worlds"] and spec["registered_v2_count_risk_gate_unchanged"]
    floor = Fraction(str(spec["fractional_rate_floor"]))
    assert floor == Fraction(spec["reference"]["minimum_registered_fractional_answers"],
                             spec["reference"]["registered_confirmation_worlds"])
    rows, research_passes, coverage_passes = {}, 0, 0
    for panel in spec["panels"]:
        rows[panel] = {}
        for name in spec["arms"]:
            model = summary["panels"][panel]["models"][name]
            q, actual = model["quality"], recorded["panels"][panel][name]
            if q is None:
                assert actual == dict(quality=None, coverage_risk_subgate=False)
                rows[panel][name] = dict(coverage_risk_subgate=False)
                continue
            worlds = model["attempts"]
            assert worlds > 0
            research = (model["calibration"]["calibration_gate_passed"] and model["invalid"] == 0
                and q["support_losses"] == 0 and q["fractional"] >= spec["minimum_fractional_count"]
                and q["upper95_fractional"] <= spec["risk_limit"] and q["upper95_overall"] <= spec["risk_limit"])
            assert bool(research) == q["gate"] == actual["registered_count_risk_gate"]
            fractional_rate = Fraction(q["fractional"], worlds)
            answer_rate = Fraction(q["accepted"], worlds)
            passed = bool(research and fractional_rate >= floor)
            assert actual["coverage_risk_subgate"] == passed
            assert actual["worlds"] == worlds and actual["fractional_accepted"] == q["fractional"]
            assert actual["accepted"] == q["accepted"]
            assert actual["fractional_rate"] == float(fractional_rate)
            assert actual["total_answer_rate"] == float(answer_rate)
            assert actual["fractional_rate_floor"] == float(floor)
            assert actual["upper95_fractional_risk"] == q["upper95_fractional"]
            assert actual["upper95_overall_risk"] == q["upper95_overall"]
            research_passes += research
            coverage_passes += passed
            rows[panel][name] = dict(registered_count_risk_gate=bool(research), coverage_risk_subgate=passed,
                fractional_count=q["fractional"], worlds=worlds, fractional_rate_exact=str(fractional_rate),
                fractional_rate=float(fractional_rate), total_answer_rate=float(answer_rate))
    context_all = all(rows[panel]["context_orbit"]["coverage_risk_subgate"] for panel in spec["panels"])
    assert recorded["context_all_five_coverage_risk_subgates"] == context_all
    assert not recorded["original_registered_gates_modified"] and not recorded["full_model_adoption"]
    assert not recorded["all_blockers_closed"] and not recorded["production_activation"]
    print(json.dumps(dict(passed=True, checked_panel_arms=len(spec["panels"]) * len(spec["arms"]),
        rate_floor_exact=str(floor), new_prospective_rate_floor=True, reference_scope_flag=spec["reference"]["scope_flag"],
        registered_research_passes=int(research_passes),
        separate_coverage_passes=int(coverage_passes), context_all_five_coverage_risk_subgates=context_all,
        panels=rows, published_auxiliary_hashes_verified=True, original_registered_gates_modified=False,
        full_model_adoption=False, all_blockers_closed=False, production_activation=False,
        scope="Exact rational rate comparison and independently reconstructed risk/count conjunction; readonlyderivedsummary, afterfull raw-stat audit"), sort_keys=True))


if __name__ == "__main__":
    main()
