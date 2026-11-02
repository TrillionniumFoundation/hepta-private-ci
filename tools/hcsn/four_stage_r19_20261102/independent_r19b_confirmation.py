"""Five-family generator-cluster confirmation, reconstructed from saved records."""

import json

import numpy as np

from .independent_r19b_calibration import HERE, MODULE, archive, digest, load


def run():
    spec = load(MODULE / "protocol.json")
    frozen = load(MODULE / "POSTCALIBRATION_FREEZE.json")
    publication = load(MODULE / "CALIBRATION_PUBLICATION.json")
    assert publication["readback_verified"] and publication["postcalibration_freeze_sha256"] == digest(MODULE / "POSTCALIBRATION_FREEZE.json")
    directory = MODULE / "confirmation_01"
    saved, archives = load(directory / "SUMMARY.json"), load(directory / "ARCHIVES.json")
    rows = [row for item in archives for row in archive(item)]
    assert len(rows) == 5120
    identities = [(row["family"], row["generator"], row["index"]) for row in rows]
    assert len(set(identities)) == 5120
    delta = .05/20
    assert delta == saved["one_sided_confirmation_delta"]
    result, reads, maximum = {}, 0, 0.
    for family_index, family in enumerate(spec["all_families"]):
        current = [row for row in rows if row["family"] == family]
        assert len(current) == 1024 and {(r["generator"], r["index"]) for r in current} == {(g,i) for g in range(256) for i in range(4)}
        groups = np.array([row["generator"] for row in current])
        bootstrap = np.random.default_rng(19112991+family_index).integers(256, size=(4096, 256))
        summaries, totals_by_model, records_by_model = {}, {}, {}
        for model in spec["models"]:
            records = [next(iter(row["predictions"][model].values())) for row in current]
            assert all(list(row["predictions"][model]) == [str(frozen["selected"][model]["threshold"])] for row in current)
            assert not any(record["invalid"] for record in records)
            assert saved["families"][family]["models"][model]["invalid"] == 0
            values = {key:[] for key in ("before_brier", "after_brier", "payoff", "accepted", "errors", "fractional", "fractional_errors", "support", "reads", "netread", "before_log_loss", "after_log_loss", "admitted", "read_refused")}
            for row, record in zip(current, records, strict=True):
                p, before = np.array(record["probability"]), np.array(record["before"])
                accepted, fractional = record["accepted"], record["accepted"] and record["fractional"]
                correct = int(p.argmax() == row["target"])
                assert record["correct"] == correct and record["fractional"] == bool(p.max() < 1-1e-9)
                purchase = record["read_index"] is not None
                assert record["fee"] == (row["price"] if purchase else 0.)
                payoff = (2*correct-1 if accepted else 0)-record["fee"]
                assert abs(payoff-record["payoff"]) < 1e-12
                assert abs(record["before_brier"]-np.square(before-np.eye(4)[row["target"]]).sum()) < 2e-12
                assert abs(record["after_brier"]-np.square(p-np.eye(4)[row["target"]]).sum()) < 2e-12
                additions = dict(before_brier=record["before_brier"], after_brier=record["after_brier"], payoff=payoff,
                    accepted=accepted, errors=accepted and not correct, fractional=fractional,
                    fractional_errors=fractional and not correct, support=p[row["target"]] <= 0,
                    reads=purchase, netread=payoff-record["no_read_payoff"], before_log_loss=record["before_log_loss"],
                    after_log_loss=record["after_log_loss"], admitted=record["admitted"], read_refused=purchase and not accepted)
                for key, value in additions.items():
                    values[key].append(value)
                reads += purchase
            total = {key:np.bincount(groups, weights=values[key], minlength=256) for key in values}
            totals_by_model[model] = total
            counts = {key:int(total[key].sum()) for key in ("accepted", "errors", "fractional", "fractional_errors", "support", "reads", "admitted", "read_refused")}
            quality = dict(before_brier=float(total["before_brier"].mean()/4), after_brier=float(total["after_brier"].mean()/4),
                selective_payoff=float(total["payoff"].mean()/4), accepted=counts["accepted"], accepted_errors=counts["errors"],
                fractional_accepted=counts["fractional"], fractional_errors=counts["fractional_errors"], support_failures=counts["support"],
                actual_reads=counts["reads"], mean_read_net_effect=float(total["netread"].mean()/4),
                before_log_loss=float(total["before_log_loss"].mean()/4), after_log_loss=float(total["after_log_loss"].mean()/4),
                admitted=counts["admitted"], read_then_refused=counts["read_refused"],
                overall_error=counts["errors"]/counts["accepted"] if counts["accepted"] else None,
                fractional_error=counts["fractional_errors"]/counts["fractional"] if counts["fractional"] else None)
            for numerator, denominator, label in (("errors", "accepted", "overall"), ("fractional_errors", "fractional", "fractional")):
                error_draws, count_draws = total[numerator][bootstrap].sum(1), total[denominator][bootstrap].sum(1)
                ratios = np.ones(4096)
                positive = count_draws > 0
                ratios[positive] = error_draws[positive]/count_draws[positive]
                quality["simultaneous_upper_"+label+"_error"] = float(np.quantile(ratios, 1-delta))
            claimed = saved["families"][family]["models"][model]["whole_population_quality"]
            assert set(quality) == set(claimed)
            for key, value in quality.items():
                if value is None:
                    assert claimed[key] is None
                else:
                    maximum = max(maximum, abs(value-claimed[key]))
                    assert abs(value-claimed[key]) < 2e-12
            summaries[model] = quality
        main, static = totals_by_model["class_mixture"], totals_by_model["best_static"]
        brier = (static["before_brier"]-main["before_brier"])/4
        payoff = (main["payoff"]-static["payoff"])/4
        brier_ci = np.quantile(brier[bootstrap].mean(1), [delta, 1-delta])
        payoff_ci = np.quantile(payoff[bootstrap].mean(1), [delta, 1-delta])
        comparison = dict(independent_generator_units=256, before_read_brier_gain=float(brier.mean()),
            simultaneous_brier_gain_interval=brier_ci.tolist(), actual_selective_payoff_gain=float(payoff.mean()),
            simultaneous_payoff_gain_interval=payoff_ci.tolist())
        original = saved["families"][family]["comparison"]
        for key, value in comparison.items():
            assert np.max(abs(np.asarray(value)-np.asarray(original[key]))) < 2e-12
        primary = summaries["class_mixture"]
        passed = bool(frozen["selected"]["class_mixture"]["calibration_gate_passed"] and not primary["support_failures"] and
            primary["fractional_accepted"] >= 32 and primary["simultaneous_upper_overall_error"] <= .1 and
            primary["simultaneous_upper_fractional_error"] <= .1 and brier_ci[0] >= 0 and payoff_ci[0] >= 0)
        assert passed == saved["families"][family]["all_criteria_passed"]
        result[family] = dict(models=summaries, comparison=comparison, family_gate=passed)
    whole = all(value["family_gate"] for value in result.values())
    trained = all(result[family]["family_gate"] for family in spec["trained_families"])
    assert whole == saved["all_declared_processes_gate_passed"] == False
    assert trained == saved["trained_family_gate_passed"]
    switching = result["switching_rotor"]["models"]["class_mixture"]
    assert switching["fractional_errors"] == switching["accepted_errors"] == 18
    assert switching["fractional_accepted"] == 47 and switching["accepted"] == 854
    return dict(schema="hcsn-r19b-independent-confirmation-v1", all_checks_passed=True,
        original_all_five_family_gate_passed=whole, trained_family_gate_passed=trained,
        archives=len(archives), worlds=len(rows), decisions=2*len(rows), actual_read_decisions=reads,
        generators_per_family=256, worlds_per_generator=4, bootstrap_replicates=4096,
        primary_simultaneous_quantities=20, one_sided_delta=delta, maximum_summary_error=maximum,
        results=result, source_postcalibration_sha256=digest(MODULE / "POSTCALIBRATION_FREEZE.json"),
        key_negative="Switching-rotor18errors/47fractionalaccepted=38.30%, upper57.85%; same18errors/854allaccepted=2.11% does not certify uncertain answers.",
        scope="All80raw archives, generator identities, fees/scores and20primary cluster bounds reconstructed without campaign/statistics/world/model imports",
        limits=["Approximate generator-bootstrap bounds, not exact simultaneous coverage theorem", "All4dependentworlds retained per generator, including zero-answer clusters; zero bootstrap denominator maps to risk1",
                "Three trained-family calibration passes did not transfer to all5families; no postconfirmation repair or pooled rescue"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_r19b_confirmation.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key:value for key,value in report.items() if key not in ("results", "limits")}))
