"""Extract formal typed findings from sealed evidence; no fitting or inference."""

import argparse
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
RUN = BASE / "results/20261026-v4-frozen"
SOURCE_COMMIT = "6206dfba0a3219534dd1a0274431bf48fd23673c"
MANIFEST = "ec975d0e9afc53903ba2d26129446e263d06ebea0abb8b9e729e556546eca3ff"
FIELDS = ("quantity", "unit_price_pence", "stock_code", "country", "invoice_no")
SEEDS = [401, 409, 419, 421, 431]


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric(rows):
    count = sum(row["queries"] for row in rows)
    tolerances = {row["absolute_tolerance"] for row in rows}
    assert len(tolerances) == 1
    within = sum(round(row["queries"] * row["within_absolute_tolerance"]) for row in rows)
    exact = sum(round(row["queries"] * row["exact_float64"]) for row in rows)
    return {"queries": count, "within_absolute_tolerance_count": within,
            "within_absolute_tolerance_fraction": within / count,
            "absolute_tolerance": tolerances.pop(), "literal_float64_exact_count": exact,
            "literal_float64_exact_fraction": exact / count,
            "mae": sum(row["queries"] * row["mae"] for row in rows) / count,
            "mse": sum(row["queries"] * row["mse"] for row in rows) / count,
            "max_absolute_error": max(row["max_absolute_error"] for row in rows)}


def facts(rows):
    count = sum(row["queries"] for row in rows)
    correct = sum(row["exact"] for row in rows)
    fields = {}
    for field in FIELDS:
        items = [row["fields"][field] for row in rows]
        n = sum(item["queries"] for item in items)
        accepted = sum(item["accepted"] for item in items)
        exact = sum(item["exact"] for item in items)
        value = {"queries": n, "accepted": accepted, "exact": exact,
                 "exact_fraction": exact / n, "accepted_wrong": accepted - exact,
                 "abstained": n - accepted, "coverage": accepted / n}
        if field in FIELDS[:2]:
            for name in ("accepted_mae", "accepted_mse"):
                value[name] = sum(item[name] * item["accepted"] for item in items) / accepted
        fields[field] = value
    return {"queries": count, "exact": correct, "exact_fraction": correct / count,
            "accepted": sum(row["accepted"] for row in fields.values()), "fields": fields}


def compute():
    audit_path = BASE / "validation/formal-transfer-audit.json"
    audit = read(audit_path)
    report = read(RUN / "transfer/transfer-summary.json")
    protocol = read(RUN / "protocol.json")
    outer = read(RUN / "results.json")
    assert sha(RUN / "MANIFEST.json") == MANIFEST
    assert audit["passed"] and audit["failures"] == []
    assert audit["unified_verification"]["source_commit"] == SOURCE_COMMIT
    assert not audit["unified_verification"]["development"]
    assert report["seeds"] == SEEDS and report["mode"] == "formal"
    assert protocol["frozen_before_formal_execution"] is True
    runs = report["results"]
    unique = {field: set() for field in FIELDS}
    chain_ids, function_inputs = set(), set()
    per_seed, storage = [], []
    model_shas = {arm: {field: set() for field in FIELDS} for arm in ("full_rank", "rank_2")}
    runtime = []
    for row in runs:
        seed = row["seed"]
        folder = RUN / "transfer" / f"seed-{seed}"
        queries = read(folder / "event-queries-and-grader-targets.json")
        for query in queries["queries"]:
            unique[query["field"]].add(query["record_id"])
        chain_ids.update(queries["chain_ids"])
        hidden = read(folder / "procedures/hidden-inputs-and-grader-targets.json")
        function_inputs.update(tuple(value) for value in hidden["inputs"])
        procedure = row["procedure"]
        per_seed.append({"seed": seed, "queries_per_field": {field: sum(q["field"] == field for q in queries["queries"]) for field in FIELDS},
                         "event_reads": {arm: {mode: value["events"] for mode, value in data["modes"].items()} for arm, data in row["event_arms"].items()},
                         "parameter_procedure": procedure["parameter"], "ordinary_ols": procedure["ordinary_ols"],
                         "interpolation": procedure["interpolation"], "extrapolation": procedure["extrapolation"],
                         "nearest_demo": procedure["memorized_example_nearest_neighbor"],
                         "nonlinear_negative": {key: value for key, value in procedure["nonlinear_negative"].items() if key != "write"},
                         "parameter_vs_ols_max_difference": procedure["parameter_and_ols_prediction_max_difference"],
                         "event_procedure_chain": row["event_arms"]["full_rank"]["modes"]["parameter"]["event_procedure_chain"],
                         "work": row["work"]})
        best = min(row["exact_controls"], key=lambda name: (row["exact_controls"][name]["bytes"], name))
        assert best == row["best_traditional_control"]
        for arm_name, arm in row["event_arms"].items():
            metadata = read(folder / arm_name / "memory/parameters/schema.json")
            for field, info in metadata["models"].items():
                model_shas[arm_name][field].add(info["sha256"])
            write = arm["write"]
            baseline = row["exact_controls"][best]["bytes"]
            whole_baseline = row["traditional_events_and_ordinary_ols_deployment_bytes"]
            durable_baseline = row["traditional_events_ols_and_procedure_replay_bytes"]
            storage.append({"seed": seed, "arm": arm_name,
                            "event_parameter_bytes": write["parameter_deployment_bytes"],
                            "parameter_weights_bytes": write["parameter_artifact_bytes"],
                            "address_schema_binding_bytes": write["address_schema_binding_bytes"],
                            "timestamp_address_bytes_included": write["timestamp_address_json_bytes_included"],
                            "event_exact_bytes": write["exact_deployment_bytes"], "residual_bytes": write["residual_bytes"],
                            "residual_binding_bytes": write["residual_binding_bytes"],
                            "best_traditional_event_codec": best, "best_traditional_event_bytes": baseline,
                            "event_exact_storage_ratio": write["exact_deployment_bytes"] / baseline,
                            "event_exact_saving_fraction": 1 - write["exact_deployment_bytes"] / baseline,
                            "event_parameter_plus_programs_and_chain_bytes": arm["parameter_event_and_procedure_deployment_bytes"],
                            "event_exact_plus_programs_and_chain_bytes": arm["exact_event_and_procedure_deployment_bytes"],
                            "event_exact_programs_chain_and_program_demo_replay_bytes": arm["parameters_exact_replay_and_procedure_replay_bytes"],
                            "traditional_event_ordinary_ols_and_same_chain_bytes": whole_baseline,
                            "traditional_event_ols_chain_and_same_demo_replay_bytes": durable_baseline,
                            "complete_exact_serving_ratio": arm["exact_event_and_procedure_deployment_bytes"] / whole_baseline,
                            "complete_exact_serving_and_replay_ratio": arm["parameters_exact_replay_and_procedure_replay_bytes"] / durable_baseline,
                            "category_answer_dictionary_bytes": write["category_answer_dictionary_bytes"],
                            "target_byte_strings_stored_in_parameter_metadata": write["target_byte_strings_stored_in_parameter_metadata"]})
            for mode, metrics in arm["modes"].items():
                runtime.append({"seed": seed, "arm": arm_name, "mode": mode,
                                **{key: metrics[key] for key in ("process_wall_seconds", "read_wall_seconds", "process_cpu_seconds_including_imports",
                                   "process_peak_rss_bytes_including_shared_runtime", "resident_parameter_numpy_bytes", "event_runtime_exact_array_bytes",
                                   "source_paths_in_request", "target_values_in_request")}})
    arms = {}
    for arm in ("full_rank", "rank_2"):
        arms[arm] = {}
        for mode in ("parameter", "residual_exact"):
            rows = [row["event_arms"][arm]["modes"][mode] for row in runs]
            chain = numeric([row["event_procedure_chain"] for row in rows])
            chain.update(requested_queries=sum(row["chain_queries"] for row in rows),
                         accepted_queries=sum(row["chain_accepted"] for row in rows),
                         correct_provenance_all_seeds=all(row["chain_provenance_correct"] for row in rows),
                         fields_used=["quantity", "unit_price_pence"], tests_text_composition=False)
            arms[arm][mode] = {"events": facts([row["events"] for row in rows]), "event_procedure_chain": chain}
    procedure = {name: numeric([row["procedure"][name] for row in runs]) for name in (
        "parameter", "ordinary_ols", "interpolation", "extrapolation", "memorized_example_nearest_neighbor", "nonlinear_negative")}
    keys = ("event_svd_calls", "event_svd_work_proxy", "affine_least_squares_solves_including_ordinary_and_negative",
            "affine_work_proxy_including_ordinary_and_negative", "fresh_processes")
    totals = {key: sum(row["work"][key] for row in runs) for key in keys}
    factor_hash_counts = {arm: {field: len(values) for field, values in fields.items()} for arm, fields in model_shas.items()}
    gate = protocol["gates"]["new_type_exact_hidden_reads_min"]
    source = read(BASE / "sources/retail" / report["source_file"])
    snapshot_file = RUN / "transfer/transfer-summary.json"
    return {
        "schema": "memory-cell-v4.formal-typed-findings.v1",
        "evidence": {"run": str(RUN.relative_to(BASE)), "source_commit": SOURCE_COMMIT, "manifest_sha256": MANIFEST,
                     "transfer_summary_sha256": sha(snapshot_file), "audit": str(audit_path.relative_to(BASE)),
                     "audit_sha256": sha(audit_path), "audit_passed": True, "audit_checks": audit["checks"],
                     "analysis_generator_sha256": sha(__file__), "training_or_threshold_changes_by_analysis": 0},
        "seeds": SEEDS, "source": {"name": "UCI Online Retail", "file": report["source_file"], "sha256": report["source_sha256"],
                                     "events": report["source_events"], "target_fields": list(FIELDS),
                                     "written_typed_facts": report["source_events"] * len(FIELDS),
                                     "time_address_range": [min(row["invoice_at"] for row in source["records"]), max(row["invoice_at"] for row in source["records"])],
                                     "explicit_address_fields_not_parameter_recall_targets": ["record_id", "source_row", "invoice_at"],
                                     "raw_source_archive_bytes": report["code_and_shared_runtime"]["raw_source_archive_retained_bytes"],
                                     "canonical_source_bytes": report["code_and_shared_runtime"]["canonical_source_retained_bytes"]},
        "denominators": {"distinct_event_training_datasets": 1, "event_queries_per_seed_per_arm_per_mode": 320,
                         "event_queries_per_field_per_seed": 64, "event_queries_all_seeds_per_arm_per_mode": 1600,
                         "unique_queried_event_field_coordinates": sum(len(values) for values in unique.values()),
                         "unique_queried_event_ids_per_field": {field: len(values) for field, values in unique.items()},
                         "event_chain_queries_per_seed_per_arm_per_mode": 128, "event_chain_queries_all_seeds_per_arm_per_mode": 640,
                         "unique_event_chain_addresses": len(chain_ids), "learned_affine_programs_per_seed": 3,
                         "demonstrations_per_learned_program": 24, "new_demonstration_pairs_for_main_programs": 3 * 24 * len(SEEDS),
                         "distinct_procedural_chains": 5, "novel_procedure_input_queries": 640, "unique_original_function_inputs": len(function_inputs),
                         "interpolation_input_queries": 480, "extrapolation_input_queries": 160,
                         "fresh_processes_repeat_same_per_seed_inputs_in_two_arms_and_two_modes": True,
                         "event_model_unique_artifact_hash_counts_across_seeds": factor_hash_counts,
                         "confidence_interval_claimed": False,
                         "reason": "One held retail sample; overlapping address samples and deterministic event models are not five independent domains."},
        "arms": arms, "procedures": procedure, "per_seed": per_seed,
        "storage_per_seed": storage, "traditional_event_codecs": {name: value["bytes"] for name, value in runs[0]["exact_controls"].items()},
        "cost_scope": {"source_and_shared_runtime": report["code_and_shared_runtime"],
                       "transfer_research_bytes_including_summary": report["research_retained_bytes_before_summary"] + snapshot_file.stat().st_size,
                       "unified_run_bytes_including_manifest": audit["unified_verification"]["output_bytes"] + (RUN / "MANIFEST.json").stat().st_size,
                       "shared_source_and_runtime_are_not_silently_zero": True,
                       "incremental_state_ratios_exclude_shared_runtime_and_retained_raw_source": True,
                       "full_work_includes_both_rank_arms_ordinary_controls_and_nonlinear_negative": True},
        "work": {"totals": totals, "per_seed": [{"seed": row["seed"], **row["work"]} for row in runs],
                 "main_learned_program_solves": 15, "ordinary_ols_solves": 15, "negative_family_solves": 5,
                 "transfer_stage_wall_seconds": outer["transfer"]["wall_seconds"],
                 "sum_recorded_fresh_process_wall_seconds": sum(row["process_wall_seconds"] for row in runtime),
                 "sum_recorded_fresh_process_cpu_seconds": sum(row["process_cpu_seconds_including_imports"] for row in runtime),
                 "max_observed_reader_process_peak_rss_bytes_including_shared_runtime": max(row["process_peak_rss_bytes_including_shared_runtime"] for row in runtime),
                 "work_proxy_is_not_measured_flops": True, "timings_are_sealed_historical_receipts_not_independent_retiming": True,
                 "runtime_receipts": runtime},
        "qualification": {"declared_new_type_exact_hidden_read_threshold": gate,
                          "full_rank_parameter_seeds_meeting_threshold": sum(row["event_arms"]["full_rank"]["modes"]["parameter"]["events"]["exact_fraction"] >= gate for row in runs),
                          "rank2_parameter_seeds_meeting_threshold": sum(row["event_arms"]["rank_2"]["modes"]["parameter"]["events"]["exact_fraction"] >= gate for row in runs),
                          "fresh_process_count": len(runtime), "fresh_requests_with_source_or_target_payload": sum(bool(row["source_paths_in_request"] or row["target_values_in_request"]) for row in runtime),
                          "affine_and_ordinary_ols_both_meet_declared_tolerance": procedure["parameter"]["within_absolute_tolerance_count"] == 640 and procedure["ordinary_ols"]["within_absolute_tolerance_count"] == 640,
                          "storage_advantage_over_strong_exact_baseline": all(row["complete_exact_serving_ratio"] < 1 for row in storage),
                          "new_algorithm_family_discovery_established": False, "advantage_over_ordinary_ols_established": False,
                          "new_memory_type_relative_to_v3_not_unseen_type_at_formal_time": True,
                          "natural_language_routing_or_learned_graph_result_inferred_here": False,
                          "universal_memory_system_established_by_typed_transfer": False},
        "limits": ["Formal held records share the UCI retail source family used for development; only one event training dataset is evaluated.",
                   "Full-rank parameter exactness is reported on the declared hidden read samples, not asserted as a proof of lossless reconstruction for every unqueried value.",
                   "Lossless model-plus-residual and conventional codec roundtrips cover all 640 selected records; the original entire workbook is not reconstructed.",
                   "The 1e-7 affine tolerance is not literal float64 equality. Ordinary OLS passes the same tolerance.",
                   "The event-to-program chain uses the two numeric fields; it cannot establish successful text-field composition.",
                   "Rank-2 valid UTF-8 outputs may be wrong. Type validation does not establish factual correctness.",
                   "Maintenance version rejection is qualified in a separate experiment, not implied by these static transfer readers."]}


def markdown(data):
    arms, procedures = data["arms"], data["procedures"]
    lines = ["# Formal typed-memory findings", "",
             "Full-rank parameter recall passes the declared held-read gate. Compression advantage fails; ordinary OLS matches the learned affine family at the declared tolerance. Rank-2 text recall fails completely. No general-memory or algorithm-discovery claim follows.", "",
             "## Evidence and denominators", "",
             f"Source commit: `{SOURCE_COMMIT}`. Formal seal: `{MANIFEST}`.", "",
             f"Independent transfer audit: **{data['evidence']['audit_checks']:,} checks, zero failures**; see `../validation/formal-transfer-audit.json` and the complete companion `formal-typed-findings.json`.", "",
             "One held UCI retail sample contains **640 events / 3,200 written target fields**. The five seeds vary affine programs, demonstrations, and queried addresses. Event models are byte-identical across seeds within each rank arm.", "",
             f"Each arm and read mode has **64 queries per field per seed**, or **1,600 queries** across five seeds, covering **{data['denominators']['unique_queried_event_field_coordinates']:,} unique event-field coordinates**. Repeated process reads and overlapping addresses are not independent domains. There are **640 novel procedural input queries**, including **480 interpolation / 160 extrapolation** inputs; the latter grouping refers to the first program's input range.", "",
             "## Event recall and low-rank distortion", "",
             "| Field | Full-rank parameter correct / queries | Rank-2 parameter correct / queries | Rank-2 non-null wrong | Rank-2 abstained |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for field in FIELDS:
        full = arms["full_rank"]["parameter"]["events"]["fields"][field]
        low = arms["rank_2"]["parameter"]["events"]["fields"][field]
        lines.append(f"| {field} | {full['exact']}/{full['queries']} | {low['exact']}/{low['queries']} | {low['accepted_wrong']} | {low['abstained']} |")
    lines.extend(["", "Overall parameter recall is **1,600/1,600** at full rank and **640/1,600 (40%)** at rank 2. Numeric MAE and MSE are zero in both arms. Rank-2 text recall is **0/960**, including **921 non-null wrong strings** and **39 abstentions**. A format-valid string is not evidence of a correct memory.", "",
                  "Explicit-residual reads are **1,600/1,600** for each arm. Independent codec roundtrips also reproduce all 640 selected records. These are explicit exact codecs, not parameter-only reads.", "",
                  "## Procedural family and controls", "",
                  "Each seed fits three affine programs from 24 demonstrations each. The family and chain are supplied; coefficients are learned. The main procedural query denominator is 128 per seed, not four times that number when reused in fresh readers.", "",
                  "| Seed | Learned affine within 1e-7 | Ordinary OLS within 1e-7 | Affine maximum error | Nearest-demo MSE | Quadratic negative MSE |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for row in data["per_seed"]:
        p, ols = row["parameter_procedure"], row["ordinary_ols"]
        lines.append(f"| {row['seed']} | {round(p['queries'] * p['within_absolute_tolerance'])}/{p['queries']} | {round(ols['queries'] * ols['within_absolute_tolerance'])}/{ols['queries']} | {p['max_absolute_error']:.6g} | {row['nearest_demo']['mse']:.6g} | {row['nonlinear_negative']['mse']:.6g} |")
    lines.extend(["", f"Both learned affine and ordinary OLS pass **640/640** queries at the fixed tolerance. Literal float64 equality is only **{procedures['parameter']['literal_float64_exact_count']}/640** and **{procedures['ordinary_ols']['literal_float64_exact_count']}/640**, respectively. Nearest-demo and affine-on-quadratic controls each pass **0/640**. The latter exposes the supplied family's limitation; it does not show algorithm discovery.", "",
                  "Event-to-procedure composition passes **640/640** requests per arm/mode within 0.005, with correct provenance. That chain reads only quantity and unit price, so its success does not repair rank-2 text failure.", "",
                  "## Storage: every model, address, schema, program and replay is charged", "",
                  "The strongest traditional event control is `columns_lzma`, **8,677 B**. The table below compares the same selected event fields and addresses; ratios in this table are event-only.", "",
                  "| Arm | Parameter event bytes | Model + residual event bytes | Exact / strongest traditional |",
                  "| --- | ---: | ---: | ---: |"])
    for arm in ("full_rank", "rank_2"):
        row = next(item for item in data["storage_per_seed"] if item["arm"] == arm)
        lines.append(f"| {arm} | {row['event_parameter_bytes']:,} | {row['event_exact_bytes']:,} | {row['event_exact_storage_ratio']:.6f}× |")
    lines.extend(["", "Complete event + procedure serving and replay costs differ from the event-only ratio:", "",
                  "| Seed | Full parameter serving | Full exact serving | Full exact + demo replay | Rank-2 exact serving | Rank-2 exact + demo replay | Traditional exact + OLS | Traditional + same demo replay |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for seed in SEEDS:
        full = next(row for row in data["storage_per_seed"] if row["seed"] == seed and row["arm"] == "full_rank")
        low = next(row for row in data["storage_per_seed"] if row["seed"] == seed and row["arm"] == "rank_2")
        values = [full["event_parameter_plus_programs_and_chain_bytes"], full["event_exact_plus_programs_and_chain_bytes"], full["event_exact_programs_chain_and_program_demo_replay_bytes"], low["event_exact_plus_programs_and_chain_bytes"], low["event_exact_programs_chain_and_program_demo_replay_bytes"], full["traditional_event_ordinary_ols_and_same_chain_bytes"], full["traditional_event_ols_chain_and_same_demo_replay_bytes"]]
        lines.append("| " + str(seed) + " | " + " | ".join(f"{value:,}" for value in values) + " |")
    source = data["cost_scope"]["source_and_shared_runtime"]
    lines.extend(["", f"Required inference Python source is separately reported as **{source['inference_python_source_bytes']:,} B**, versus **{source['traditional_event_decoder_python_source_bytes']:,} B** for the traditional decoder dependency set. The retained official archive is **{source['raw_source_archive_retained_bytes']:,} B** and the selected canonical source is **{source['canonical_source_retained_bytes']:,} B**. Python/NumPy runtime is shared infrastructure; it is excluded from incremental serialized-state ratios and included in observed process cost. Transfer research artifacts including their summary total **{data['cost_scope']['transfer_research_bytes_including_summary']:,} B**. No storage advantage is demonstrated under the strong baseline.", "",
                  "## Work and interpretation", "",
                  "Each seed pays for **10 SVD calls** (work proxy **609,280**) and **seven least-squares solves** (proxy **1,008**): three learned affine programs, three ordinary OLS controls, and one nonlinear negative. Across five seeds this is **50 SVD / 35 least-squares solves**, proxies **3,046,400 / 5,040**, plus **20 actual fresh reader processes**. All predeclared arms and negative controls are included; deterministic repeated fits are still charged.", "",
                  f"The sealed transfer-stage wall time is **{data['work']['transfer_stage_wall_seconds']:.6f} s**. The largest observed reader process peak RSS, including shared runtime, is **{data['work']['max_observed_reader_process_peak_rss_bytes_including_shared_runtime']:,} B**. These are historical receipts, not independently retimed benchmarks; nested timings are not additive.", "",
                  "The 95% full-rank hidden-read gate passes 5/5 seeds; the rank-2 diagnostic passes 0/5. Fresh readers receive no source/target payload. This qualifies explicit-address writes and reads for this retail type and coefficients in a predeclared affine family. It does not establish a new unseen type at formal time, natural-language routing, learned graph topology, superiority over OLS, physical unlearning, or a universal memory system. Maintenance version propagation is reported separately.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-prefix", type=Path, default=BASE / "analyses/formal-typed-findings")
    args = parser.parse_args()
    output_json = args.output_prefix.with_suffix(".json")
    output_md = args.output_prefix.with_suffix(".md")
    if output_json.exists() or output_md.exists():
        raise FileExistsError("preserve existing analysis; use a new output prefix")
    result = compute()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    with output_md.open("x") as stream:
        stream.write(markdown(result))
    print(json.dumps({"json": str(output_json), "json_sha256": sha(output_json),
                      "markdown": str(output_md), "markdown_sha256": sha(output_md),
                      "denominators": result["denominators"], "qualification": result["qualification"],
                      "procedures": result["procedures"], "work_totals": result["work"]["totals"]}, separators=(",", ":")))


if __name__ == "__main__":
    main()
