"""Missing-fit, duplicate, precision and independent interval references."""
import copy
import json
import math
import statistics

from scipy.stats import t

from .statistics import PRIMARY, analyze, planning


def rows_for(differences, splits):
    rows = []
    for fit, difference in enumerate(differences, 1001):
        for split in splits:
            for _, weights in PRIMARY:
                for candidate, weight in weights.items():
                    rows.append(dict(fit=fit, split=split, candidate=candidate,
                                     metrics=dict(utility=.2 + difference if weight > 0 else .2)))
    return rows


def run_checks():
    differences = [-.02, .01, .04, .06, .09, .12]
    fits = list(range(1001, 1007))
    rows = rows_for(differences, ("iid", "ood"))
    result = analyze(rows, dict(fits=fits))
    mean = statistics.mean(differences)
    sd = statistics.stdev(differences)
    half = float(t.ppf(1 - .05 / 8, 5)) * sd / math.sqrt(6)
    for entry in result["primary"]:
        assert entry["valid"]
        interval = entry["inference"]["confidence_interval"]
        assert abs(interval[0] - (mean - half)) < 1e-15
        assert abs(interval[1] - (mean + half)) < 1e-15
    missing = analyze(rows[1:], dict(fits=fits))
    affected = next(row for row in missing["primary"] if row["split"] == "iid" and row["contrast"] == "fpt_feedback")
    assert affected["inference"] is None and affected["benefit_gate"] is None
    assert len(affected["fit_differences"]) == 5
    invalid = copy.deepcopy(rows)
    invalid[0]["valid"] = False
    assert not analyze(invalid, dict(fits=fits))["all_primary_valid"]
    for bad in (rows + [rows[0]],):
        try:
            analyze(bad, dict(fits=fits))
        except ValueError as error:
            assert "duplicate" in str(error)
        else:
            raise AssertionError("duplicate fit accepted")
    development = rows_for(differences, ("validation", "validation_ood"))
    plan = planning(development, expected_fits=fits)
    wide = planning(rows_for([x * 5 for x in differences], ("validation", "validation_ood")), expected_fits=fits)
    for narrow_row, wide_row in zip(plan["contrasts"], wide["contrasts"]):
        assert wide_row["sd_upper90"] > narrow_row["sd_upper90"]
        assert wide_row["required_n"] > narrow_row["required_n"]
        assert wide_row["power_at_selected"] < narrow_row["power_at_selected"]
    assert wide["resource_cap_binds"] and not wide["planned_power_claim"]
    absent = planning(development[1:], expected_fits=fits)
    assert not absent["design_ready"] and not absent["planned_power_claim"]
    assert absent["contrasts"][0]["required_n"] is None
    # Very large variation must not be silently replaced by the search cap.
    unbounded = planning(rows_for([x * 100 for x in differences], ("validation", "validation_ood")), expected_fits=fits)
    assert unbounded["maximum_requested_fits"] is None and unbounded["resource_cap_binds"]
    assert all(row["required_n_exceeds_search_limit"] for row in unbounded["contrasts"])
    return dict(schema="digital-feedback-statistics-checks-v1", passed=True,
                checked=["independent mean/SD/interval formula", "missing-fit null inference",
                         "invalid-fit null inference", "duplicate rejection", "variance monotonicity",
                         "cap shortfall", "missing planning fit", "search-limit shortfall"],
                narrow_required_fits=plan["maximum_requested_fits"],
                wide_required_fits=wide["maximum_requested_fits"])


if __name__ == "__main__":
    print(json.dumps(run_checks(), sort_keys=True))
