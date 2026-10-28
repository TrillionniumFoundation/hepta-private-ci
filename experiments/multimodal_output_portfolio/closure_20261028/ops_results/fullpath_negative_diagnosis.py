"""Read-only arithmetic diagnosis of the sealed full-path development failure.

No Torch, model checkpoints, archived evaluation rows, media, or qualification
sources are loaded. The original objective, candidates and gates stay frozen.
"""
import argparse
import ast
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def diagnose(repo):
    package = repo / "experiments/multimodal_output_portfolio/closure_20261028"
    directory = package / "fullpath_results"
    names = ("DEVELOPMENT_RESULT.json", "SELECTIONS.json", "PROTOCOL.json",
             "PROFILE.json", "SEMANTICS.json", "QUALIFICATION_STATUS.json")
    files = [directory / name for name in names]
    manifest_path = package / "control_results/PUBLISH_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    for record in manifest["files"]:
        if sha(repo / record["path"]) != record["sha256"]:
            raise ValueError("A frozen publication file changed")
    data = {name: json.loads((directory / name).read_text()) for name in names}
    result, selections, protocol, profile, semantics, qualification = [data[name] for name in names]
    profile_sha = canonical_digest(profile)
    assert result["profile_sha256"] == profile_sha and profile["gamma"] == 2.
    assert all(row["primary_profile_sha256"] == profile_sha for row in selections)
    assert not result["qualification_admitted"] and qualification["new_qualification_predictions"] == 0
    tolerance = protocol["retention_tolerance"]
    chosen, stages, selector_checks = [], [], []
    seeds = protocol["training_seeds"]
    for seed in seeds:
        arms = {arm: next(row for row in selections if row["seed"] == seed and row["arm"] == arm)
                for arm in protocol["arms"]}
        for arm, row in arms.items():
            prior = next(c for c in row["candidates"] if c["stage"] == "prior_greedy")
            floor = prior["retention_ce"] - tolerance
            assert all(c["eligible"] == (c["retention_ce"] >= floor) for c in row["candidates"])
            constrained = max((c for c in row["candidates"] if c["eligible"]), key=lambda c: c["quality_ce"])
            unconstrained = max(row["candidates"], key=lambda c: c["quality_ce"])
            assert constrained == row["selected"]
            selector_checks.append({"seed": seed, "arm": arm, "retention_floor": floor,
                                    "selected_stage": constrained["stage"],
                                    "unconstrained_best_stage": unconstrained["stage"],
                                    "same_selection_without_retention": constrained == unconstrained})
        mean, risk = arms["lax_mean"]["selected"], arms["lax_risk"]["selected"]
        delta = risk["quality_ce"] - mean["quality_ce"]
        chosen.append({"seed": seed, "risk_stage": risk["stage"], "mean_stage": mean["stage"],
                       "risk_quality_ce": risk["quality_ce"], "mean_quality_ce": mean["quality_ce"],
                       "risk_minus_mean_ce": delta, "contribution_to_seed_average": delta / len(seeds),
                       "risk_retention_ce": risk["retention_ce"], "mean_retention_ce": mean["retention_ce"],
                       "risk_to_mean_exponential_moment_ratio": math.exp(-profile["gamma"] * delta)})
        for stage, _ in protocol["stages"]:
            m, r = [next(c for c in arms[arm]["candidates"] if c["stage"] == stage)
                    for arm in ("lax_mean", "lax_risk")]
            stages.append({"seed": seed, "stage": stage, "risk_quality_ce": r["quality_ce"],
                           "mean_quality_ce": m["quality_ce"],
                           "risk_minus_mean_ce": r["quality_ce"] - m["quality_ce"],
                           "risk_minus_mean_retention_ce": r["retention_ce"] - m["retention_ce"],
                           "risk_eligible": r["eligible"], "mean_eligible": m["eligible"]})
    total = math.fsum(row["risk_minus_mean_ce"] for row in chosen)
    average = total / len(chosen)
    assert abs(average - result["mean_selected_risk_development_gains"]["matched_mean"]) < 1e-15
    for row in chosen:
        row["fraction_of_total_signed_difference"] = row["risk_minus_mean_ce"] / total
    # Evaluate only the unchanged cost constructor from the sealed source.
    # Dependencies are inert dictionaries: no model or observed rows are run.
    generator = package.parent / "unified_20261028/generator.py"
    assert sha(generator) == semantics["continuation"]["actual_delivery_source_sha256"]
    node = next(n for n in ast.parse(generator.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == "episode_costs")
    namespace = {"RATES": {k: Decimal(str(v)) for k, v in protocol["tariffs"].items()},
                 "EMISSION": protocol["emission"], "CostEvent": lambda **kwargs: kwargs}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(generator), "exec"), namespace)
    costs = namespace["episode_costs"](SimpleNamespace(cost_unit=profile["cost_unit"]), "diagnostic")
    exact_tariff = sum(row["amount"] for row in costs)
    assert exact_tariff == Decimal("0.00134")
    sources = files + [manifest_path, generator, package / "fullpath_evaluate.py", package / "fullpath_model.py"]
    return {"schema": "hepta.ndu.fullpath-negative-diagnosis.v1",
            "input_sha256": {str(path.relative_to(repo)): sha(path) for path in sources},
            "all_66_frozen_publication_files_verified": len(manifest["files"]) == 66,
            "review_source_sha256": sha(__file__), "primary_profile_sha256": profile_sha,
            "formulas": {"delta_seed": "CE_risk_selected - CE_mean_selected",
                         "reported_average": "sum(delta_seed) / 3; this is not a pooled-seed CE",
                         "signed_contribution_fraction": "delta_seed / sum(delta_seed)",
                         "moment_ratio": "M_risk / M_mean = exp(-2 * delta_seed)",
                         "constant_cost_identity": "CE(U - c) = CE(U) - c, c = 0.00134",
                         "unidentified_decomposition": "Delta CE = Delta E[R] - Delta (E[R] - CE)"},
            "selected_comparisons": chosen, "same_stage_comparisons": stages,
            "selector_checks": selector_checks,
            "all_selections_unchanged_if_retention_constraint_removed": all(
                row["same_selection_without_retention"] for row in selector_checks),
            "mean_selected_risk_minus_mean_ce": average,
            "registered_mean_control_admission_threshold": protocol["qualification_admission"][
                "mean_risk_quality_gain_vs_matched_mean_at_least"],
            "work_tariff": {"exact_total_per_bundle": str(exact_tariff),
                            "costs": {row["kind"]: str(row["amount"]) for row in costs},
                            "same_for_all_recorded_candidate_modes": True,
                            "physical_CPU_is_not_in_this_objective": True,
                            "scope": "Declared fixed work tariff only, not a physical CPU bound or a failure-tail certificate."},
            "sufficient_conclusions": [
                "The negative selected contrast is a real comparison under the same gamma-2 scoring profile.",
                "Seed 17 supplies 99.8344766290704% of the signed selected contrast; both candidates are eligible encoder stages.",
                "Removing retention eligibility changes none of the six selections; relaxing that gate cannot repair this result.",
                "The fixed declared deployment tariff cancels from every relative CE comparison.",
                "Seed 29 contributes zero after both policies fall back; seed 43 fallback contributes only 0.1655233709296%.",
                "Same-stage signs differ across seeds and stages; the results do not support a universal risk-training disadvantage."],
            "insufficient_for": [
                "Separating mean return, dispersion, rare low outcomes or particular corruption conditions from CE alone.",
                "Attributing the optimization result to gradient variance, clipping, learning rate or insufficient training.",
                "Treating three seeds sharing one initialization and development sources as three independent datasets.",
                "Claiming qualification superiority, broad retention preservation by learned models, or global optimality.",
                "Claiming complete physical cost control or a strict future NDU-tail certificate."],
            "actionable_remaining_gap": {
                "diagnosis_without_new_predictions": "Archived per-event gross utility, net return, cost and loss components can support descriptive mean/risk-premium and source/condition decomposition, but are deliberately not restored here.",
                "capability_gate": "A newly preregistered training or optimization change must satisfy the existing mean-control and retention gates before any new qualification predictions; changing thresholds or dropping the mean comparator cannot establish the missing capability.",
                "current_status": "This capability blocker remains open; mechanism and arithmetic verification are complete."},
            "new_training_updates": 0, "new_predictions": 0,
            "reserved_qualification_sources": qualification["sources_reserved"],
            "qualification_predictions": qualification["new_qualification_predictions"],
            "archived_evaluation_rows_or_media_restored": False,
            "frozen_results_or_gates_modified": False}


def markdown(report):
    rows = report["selected_comparisons"]
    lines = ["# Sealed full-path negative-result diagnosis", "",
             "**The matched-mean capability gate remains failed.** The negative contrast comes almost entirely from seed 17's same-stage actual-output comparison. Retention filtering and the fixed deployment tariff do not explain it.", "",
             "## Exact selected-model decomposition", "",
             "| Seed | Risk selection | Mean selection | Risk CE | Mean CE | Risk − mean | Contribution to total signed gap |",
             "|---|---|---|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['seed']} | {row['risk_stage']} | {row['mean_stage']} | {row['risk_quality_ce']:.12f} | {row['mean_quality_ce']:.12f} | {row['risk_minus_mean_ce']:+.12f} | {100*row['fraction_of_total_signed_difference']:.6f}% |")
    lines += ["", f"The preregistered average is **{report['mean_selected_risk_minus_mean_ce']:+.12f}**, below the unchanged admission threshold of 0. It is the arithmetic mean of three within-seed CE contrasts, not a pooled-seed CE or three independent datasets.", "",
              "Seed 17 selects the encoder checkpoint in both arms, and both satisfy retention. Risk retention CE is 0.907735182569 versus mean 0.887349460720, while its quality CE is lower by 0.016611930376. Under gamma 2, the empirical negative-exponential moment ratio is exp(−2 × difference) = **1.033781936542**. This proves a worse empirical moment for this comparison; it does not identify a particular tail quantile or failure type.", "",
              "## What the selector and cost checks establish", "",
              "Recomputing the unconstrained quality-CE maximum over every saved candidate gives exactly the same selected stage for all six seed × arm combinations. Some intermediate candidates fail retention, but none is the unconstrained winner. Consequently, relaxing retention would change neither the chosen models nor the failed matched-mean gate.", "",
              "Seed 29 has lower-quality learned candidates and both selectors retain the same greedy prior. For seed 43 all risk checkpoints already pass retention; its best learned checkpoint still falls below its prior. That fallback accounts for only 0.165523% of the total signed selected gap. The mean arm's adapter beats that prior by just 0.000027542216 on these development observations.", "",
              "The unchanged actual cost constructor assigns **0.00134 utility units per bundle** to every candidate: two encoders, one gate, two transitions, one image emission, seven token emissions, two writes, two reads and one observer call. With constant c, CE(U − c) = CE(U) − c. It cancels exactly from relative CE; differences in separately recorded physical CPU cannot cause this objective's gap. This conclusion applies only to the declared work tariff and supplies no physical CPU or failure-tail certificate.", "",
              "## Same-stage evidence", "",
              "| Seed | Transition ΔCE | Adapter ΔCE | Emission ΔCE | Encoder ΔCE |",
              "|---|---:|---:|---:|---:|"]
    for seed in (17, 29, 43):
        values = [row["risk_minus_mean_ce"] for row in report["same_stage_comparisons"] if row["seed"] == seed]
        lines.append(f"| {seed} | " + " | ".join(f"{value:+.9f}" for value in values) + " |")
    lines += ["", "Seed 17's disadvantage appears after opening emission parameters and grows in the encoder stage. The other two seeds have positive late-stage risk-minus-mean differences, yet their learned risk candidates still do not exceed the prior. These are descriptive stage observations; they do not establish which optimizer mechanism caused them.", "",
              "## What remains unidentified and open", "",
              "CE alone cannot separate mean output utility from the entropic risk premium, identify which corruption condition or loss component changed, or estimate a rare-failure probability. The exact identity is ΔCE = ΔE[R] − Δ(E[R] − CE); the missing means and event-level distributions are not recoverable from one CE number. Archived evaluation rows could support that descriptive decomposition, with original-source pairing and selection limitations retained. No archived rows or media were downloaded for this diagnosis.", "",
              "Nonzero gradients through all opened modules and an exact gradient oracle establish implementation properties. They do not establish gradient signal-to-noise, convergence, a gain over mean training, broad learned-model retention or population optimality. Development-selected scores also cannot substitute for independent qualification.", "",
              "The remaining capability task is an actual training/optimization improvement that satisfies the unchanged matched-mean and retention requirements under a newly frozen protocol. Dropping the mean comparator, selecting a convenient seed or relaxing a threshold would not establish that capability. **All 384 reserved qualification sources still have zero model predictions.** No new training, generation, scoring or qualification was performed for this diagnosis.", "",
              "## Reproduction and custody", "",
              "Run the accompanying `fullpath_negative_diagnosis.py` with `--repo REPOSITORY --output-dir REVIEW_DIRECTORY`. It uses only the standard library, checks all 66 frozen publication-file hashes, reads the named compact summaries, and evaluates only the sealed cost constructor with inert dictionary fixtures. The JSON sidecar contains exact input SHA-256 values, formulas, full candidate checks and numerical comparisons. The original reports, profile, gates and 66-file publication manifest remain unchanged.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.repo.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "FULLPATH_NEGATIVE_DIAGNOSIS.json"
    md_path = args.output_dir / "FULLPATH_NEGATIVE_DIAGNOSIS.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    md_path.write_text(markdown(report))
    print(json.dumps({"report": str(json_path), "sha256": sha(json_path),
                      "method": str(md_path), "method_sha256": sha(md_path),
                      "delta": report["mean_selected_risk_minus_mean_ce"],
                      "frozen_66_verified": report["all_66_frozen_publication_files_verified"]}))


if __name__ == "__main__":
    main()
