"""Post-run bookkeeping correction; never changes samples, models or decisions."""
import json
from identity import HERE, protocol, save, sha, verify


def build():
    verify()
    development = json.loads((HERE / "development_results.json").read_text())
    heldout = json.loads((HERE / "heldout_manifest.json").read_text())
    confirmation = json.loads((HERE / "confirmation.json").read_text())
    completion = json.loads((HERE / "completion.json").read_text())
    p = protocol()
    fits = {name: sum(r["total_wall_seconds"] for r in development["runs"] if r["family"] == name)
            for name in p["families"]}
    fits["model_dp"] = 0.
    all_fit = sum(fits.values())
    owner_wall = sum(r["total_wall_seconds"] for r in confirmation["rows"])
    owner_cpu = sum(r["total_cpu_seconds"] for r in confirmation["rows"])
    runner_residual = (completion["total_wall_seconds"]-development["development_wall_seconds"]
                       -heldout["wall_seconds"]-owner_wall)
    assert runner_residual >= 0.
    # Complete experimental setup allocation: common work is shared, each arm is
    # charged its own five fits. This is deliberately not a production minimum.
    common = (development["development_wall_seconds"]-all_fit
              +development["source_import_wall_seconds"]+heldout["wall_seconds"]+runner_residual)
    components = dict(source_import_wall_seconds=development["source_import_wall_seconds"],
        runner_wall_seconds=completion["total_wall_seconds"],
        runner_cpu_seconds=completion["total_cpu_seconds"],
        import_plus_runner_wall_seconds=completion["total_wall_seconds"]+development["source_import_wall_seconds"],
        development_wall_seconds=development["development_wall_seconds"],
        development_cpu_seconds=development["development_cpu_seconds"],
        development_data_wall_seconds=development["data"]["generation_wall_seconds"],
        heldout_data_wall_seconds=heldout["wall_seconds"], heldout_data_cpu_seconds=heldout["cpu_seconds"],
        frozen_content_load_wall_seconds=development["adapter_setup"]["load_wall_seconds"],
        calibration_wall_seconds=sum(r["calibration_wall_seconds"] for r in development["seed_costs"]),
        oracle_labels_and_state_serialization_wall_seconds=sum(r["oracle_state_and_serialization_wall_seconds"] for r in development["seed_costs"]),
        numerical_validation_wall_seconds=development["numerical_validation"]["wall_seconds"],
        all_controller_fits_wall_seconds=all_fit, family_fits_wall_seconds=fits,
        owner_sessions_wall_seconds=owner_wall, owner_sessions_cpu_seconds=owner_cpu,
        runner_residual_wall_seconds=runner_residual,
        runner_residual_meaning="Gate/checkpoint loading, scoring, orchestration and result serialization outside measured components; included in the actual runner total",
        component_overlap="Development includes calibration, labels, numerical checks and all fits; do not add those components to development again")
    summaries, sensitivity = [], []
    for item in confirmation["summaries"]:
        name = item["family"]
        rows = [r for r in confirmation["rows"] if r["family"] == name]
        row = dict(item)
        row.update(setup_wall_seconds=common+fits[name],
            mean_controller_wall_seconds=sum(r["decision_wall_seconds"] for r in rows)/len(rows),
            mean_metadata_wall_seconds=sum(r["metadata_wall_seconds"] for r in rows)/len(rows),
            mean_io_wall_seconds=sum(r["components"]["io_wall_seconds"] for r in rows)/len(rows),
            mean_feature_wall_seconds=sum(r["components"]["feature_wall_seconds"] for r in rows)/len(rows),
            mean_content_wall_seconds=sum(r["components"]["content_wall_seconds"] for r in rows)/len(rows),
            counts={key: sum(r["counts"][key] for r in rows) for key in rows[0]["counts"]})
        summaries.append(row)
        for sessions in p["setup_amortization_sessions"]:
            for penalty in p["runtime_penalty_per_second"]:
                sensitivity.append(dict(family=name, sessions=sessions, penalty=penalty,
                    setup_wall_seconds=row["setup_wall_seconds"],
                    mean_runtime_plus_amortized_setup_seconds=item["mean_wall_seconds"]+row["setup_wall_seconds"]/sessions,
                    utility=item["mean_utility"]-penalty*(item["mean_wall_seconds"]+row["setup_wall_seconds"]/sessions)))
    result = dict(schema="hcsn.control.v2.post-run-complete-cost-accounting", components=components,
        summaries=summaries, runtime_and_setup_sensitivity=sensitivity,
        correction="Frozen confirmation.json's derived setup grid omitted heldout data generation; the actual total runner time already includes it. This separate ledger also allocates measured runner overhead. No scientific results or decisions changed.",
        allocation="Each family is assigned all shared experimental setup plus its own five controller fits. DP conservatively includes oracle-label generation although deployment does not require supervised labels. Costs are study-reproduction scenarios, not minimal production costs. All-family total is the measured runner, not the sum of overlapping family allocations.",
        interpretation="Wall and CPU timings are one run on one shared CPU host. No energy, GPU or native Rust claim. All timings include actual local files/content computation; OS caches are not flushed. Evaluation labels are read only after owner terminal state, outside timed owner runtime but inside the measured full runner.",
        inputs_sha256={name: sha(HERE / name) for name in ("development_results.json", "heldout_manifest.json", "confirmation.json", "completion.json")})
    save(HERE / "cost_accounting.json", result)
    print(json.dumps(dict(complete=True, components=components), indent=2))


if __name__ == "__main__":
    build()
