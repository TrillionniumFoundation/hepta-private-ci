"""Normalize pinned historical cost JSON; never run a model, test, or benchmark."""

import argparse
import hashlib
import json
from pathlib import Path


COMMIT = "25c2cb2b60446a5f7692945bd154b0d8deb485f3"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PREFIX = "qualification/pft_six_experiments_20261125/"
MAX_FILE_BYTES = 500_000
SOURCES = {
    "pft6": ("pft6.original.json", "results/pft6.json", None,
             "7d2f4f9c0e19b59d97c7471d3aa2203aa960753cb24f8f583b43c2734979ac0d"),
    "hcsn_training": ("actual_hcsn_v2/TRAINING_SUMMARY.json", "actual_hcsn_v2/TRAINING_SUMMARY.json",
                      "d0bc46217430afc2de2efffdb47f83059e8a42d0", None),
    "hcsn_evaluation": ("actual_hcsn_v2/FINAL_SUMMARY.json", "actual_hcsn_v2/FINAL_SUMMARY.json",
                        "b65b02cd418274abda3f9e480bc2a5061af6e821", None),
    "p2p_summary": ("actual_p2p_v2/SUMMARY.json", "actual_p2p_v2/SUMMARY.json",
                    "cda0f1505f81da2d216a0cd67d8212afe589c279", None),
    "p2p_actual": ("p2p_real_hcsn_pretest_audit.json", "p2p_closure_v2/results/pft2_real_hcsn_pretest_audit.json",
                   "c69a75305976dd01c3221991a0c8919e2ec38478", None),
    "p2p_numeric": ("p2p_closure_v2/results/pft2_direct_peer_ssh.json", "p2p_closure_v2/results/pft2_direct_peer_ssh.json",
                    "7f93e355c7407c5a96b399f619cda5bceac4fe4e", None),
    "p2p_failed": ("results/pft2_multihost.json", "results/pft2_multihost.json",
                   "d60cb1e6a8f316dfa2ad287662aef16ff6570201", None),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field: " + key)
        result[key] = value
    return result


def reject_nonfinite(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def load_sources(root):
    documents, identities = {}, {}
    for key, (local, original, expected_blob, expected_sha) in SOURCES.items():
        raw = (root / local).read_bytes()
        require(0 < len(raw) <= 1_000_000, "Historical source size bound: " + key)
        content_sha = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        require(expected_blob is None or blob == expected_blob, "Source Git blob differs: " + key)
        require(expected_sha is None or content_sha == expected_sha, "Source content hash differs: " + key)
        documents[key] = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_nonfinite)
        identities[key] = {"repository": REPOSITORY, "commit": COMMIT,
                           "source_path": PREFIX + original, "bytes": len(raw),
                           "sha256": content_sha, "git_blob_sha1_computed": blob}
        if key == "pft6":
            identities[key]["retained_in_archive"] = PREFIX + "evidence/archives/pft6.tar.xz"
            identities[key]["archive_sha256"] = "c2711a6ae6174cf789a9e81aa757bf6d5c5e4f7fd7d792ca017d712ec4b5f5e4"
            identities[key]["original_member_sha256_pin"] = expected_sha
    return documents, identities


def measurement(source, pointer, value, unit, boundary):
    return {"source_id": source, "source_pointer": pointer, "value": value,
            "unit": unit, "measurement_boundary": boundary}


def export_pft6(source):
    rows = source["results"]
    require(len(rows) == 120, "Expected all 120 original PFT6 rows")
    identities = [(row["mode"], row["method"], row["width"], row["seed"]) for row in rows]
    require(len(set(identities)) == len(rows), "Duplicate PFT6 case identity")
    records = []
    for index, (identity, row) in enumerate(zip(identities, rows)):
        mode, method, width, seed = identity
        records.append({"record_id": f"{mode}:{method}:w{width}:s{seed}",
                        "source_id": "pft6", "source_pointer": f"/results/{index}",
                        "retained_record": row})
    return {
        "campaign_id": "pft6_local_synthetic",
        "source_id": "pft6", "row_count": len(records), "records": records,
        "original_protocol": source["protocol"], "original_summary": source["summary"],
        "original_gate": source["real_distributed_cost_gate"],
        "original_conclusion": source["conclusion"],
        "metric_units": {"process_cpu_s": "seconds of process CPU", "local_end_to_end_s": "elapsed seconds",
                         "fit_wall_s": "elapsed seconds nested within local end-to-end",
                         "stages.*_s": "elapsed seconds", "candidate_bytes": "bytes",
                         "remote_transfer_s": "elapsed seconds or original null",
                         "energy_joules": "joules or original null"},
        "aggregation_policy": "No filtering, new speed ratios, or time aggregation. Preserve failures and nulls. Fit time overlaps stage measurements. Local end-to-end includes stages plus unattributed overhead.",
    }


def export_hcsn(training, evaluation):
    values = []
    for key, value in training["sum_case_costs"].items():
        values.append(measurement("hcsn_training", "/sum_case_costs/" + key, value, "seconds",
                                  "original summed per-case CPU or elapsed measurement; inspect metric name"))
    values.extend([
        measurement("hcsn_training", "/sum_worker_child_cpu_s", training["sum_worker_child_cpu_s"],
                    "CPU seconds", "worker children; includes case work, do not add to case CPU"),
        measurement("hcsn_training", "/campaign_wall_span_s", training["campaign_wall_span_s"],
                    "elapsed seconds", "concurrent campaign span; do not add to summed case wall"),
        measurement("hcsn_evaluation", "/test_total_cpu_s", evaluation["test_total_cpu_s"],
                    "CPU seconds", "later held-out evaluation phase"),
        measurement("hcsn_evaluation", "/test_total_wall_s", evaluation["test_total_wall_s"],
                    "elapsed seconds", "summed evaluation measurements as reported in original summary"),
    ])
    for index, value in enumerate(training["worker_peak_rss_kib"]):
        values.append(measurement("hcsn_training", f"/worker_peak_rss_kib/{index}", value,
                                  "KiB", "one worker peak, not a campaign simultaneous-memory total"))
    return {"campaign_id": "actual_hcsn_v2_formal", "measurements": values,
            "original_training_summary": training,
            "evaluation_context": {key: evaluation[key] for key in
                ("scope", "statuses", "protocol_sha256", "training_summary_sha256",
                 "evaluation_sha256", "inferential_limit", "no_real_cross_user_or_full_LLM_inversion_claim")},
            "aggregation_policy": "Only original within-campaign totals are retained. Optimization CPU is nested in case CPU, which is nested in worker CPU. Parallel elapsed durations and RSS peaks are not added."}


def export_p2p(summary, actual):
    values = [measurement("p2p_summary", "/measured_component_wall_s/" + key, value, "elapsed seconds",
                           "separate component; concurrent or nested components must not be added")
              for key, value in summary["measured_component_wall_s"].items()]
    for key, unit in (("protocol_supervisor_wall_seconds", "elapsed seconds"),
                      ("audit_wall_seconds", "elapsed seconds"), ("total_application_bytes", "bytes")):
        values.append(measurement("p2p_actual", "/" + key, actual[key], unit,
                                  "protocol, audit, or application-byte measurement as named"))
    for host, value in actual["provider_wall_seconds_by_host"].items():
        values.append(measurement("p2p_actual", "/provider_wall_seconds_by_host/" + host, value,
                                  "elapsed seconds", "provider duration nested in concurrent protocol activity"))
    values.extend([
        measurement("p2p_summary", "/runtime_initialization/ai395_environment_setup_wall_s",
                    summary["runtime_initialization"]["ai395_environment_setup_wall_s"], "elapsed seconds", "one environment setup"),
        measurement("p2p_summary", "/actual_observed_window_to_heldout_evaluation/wall_s",
                    summary["actual_observed_window_to_heldout_evaluation"]["wall_s"], "elapsed seconds",
                    "observed window including waits and concurrent work; excludes later replay and packaging"),
    ])
    for key in ("child_cpu_s", "launcher_wall_s", "supervisor_wall_s"):
        values.append(measurement("p2p_summary", "/cold_forward_replay/" + key,
                                  summary["cold_forward_replay"][key], "CPU seconds" if key == "child_cpu_s" else "elapsed seconds",
                                  "cold replay; launcher/supervisor/child measurements overlap"))
    return {"campaign_id": "actual_smallhcsn_p2p_v2", "measurements": values,
            "original_summary": summary, "original_case_records": actual["records"],
            "original_audit_scope": actual["scope"],
            "aggregation_policy": summary["timing_rule"]}


def export_failed(source):
    attempts = source["network_attempts"]
    require(len(attempts) == 4, "Expected all four original failed direct-network attempts")
    return {"campaign_id": "earlier_multihost_direct_network_failures", "source_id": "p2p_failed",
            "records": [{"source_pointer": f"/network_attempts/{index}", "retained_record": row}
                        for index, row in enumerate(attempts)],
            "original_status": source["status"], "original_summary": source["summary"],
            "original_summary_scope": source["summary_scope"], "original_record_scope": source["record_scope"],
            "limitations": source["limitations"],
            "aggregation_policy": "Retain all failures. A recorded zero exchange counter is not zero total receiver elapsed time or CPU. Do not replace absent metrics with zero."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True, help="Pinned inert JSON cache directory")
    parser.add_argument("--out", type=Path, required=True, help="A new output directory")
    args = parser.parse_args()
    sources, identities = load_sources(args.sources)
    documents = {
        "pft6.json": export_pft6(sources["pft6"]),
        "actual_hcsn_v2.json": export_hcsn(sources["hcsn_training"], sources["hcsn_evaluation"]),
        "actual_p2p_v2.json": export_p2p(sources["p2p_summary"], sources["p2p_actual"]),
        "earlier_network_failures.json": export_failed(sources["p2p_failed"]),
        "numeric_peer_protocol.json": {"campaign_id": "numeric_peer_protocol_v2", "source_id": "p2p_numeric",
                                      "retained_document": sources["p2p_numeric"],
                                      "aggregation_policy": "Separate numeric protocol campaign; do not add its measurements to actual SmallHCSN or local PFT6 comparisons."},
    }
    output = {name: encoded({"schema": "hepta.retained-cost-ledger.campaign.v1", **value})
              for name, value in documents.items()}
    manifest = {"schema": "hepta.retained-cost-ledger.index.v1", "source_commit": COMMIT,
                "sources": identities, "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                          for name, raw in sorted(output.items())],
                "cross_campaign_totals": None, "new_model_execution": False, "new_scientific_measurements": False,
                "missing_values_preserved": True, "full_system_same_quality_speedup_established": False}
    output["INDEX.json"] = encoded(manifest)
    require(all(0 < len(raw) <= MAX_FILE_BYTES for raw in output.values()), "An export exceeds the repository blob limit")
    args.out.mkdir(parents=True, exist_ok=False)
    for name, raw in output.items():
        with (args.out / name).open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"status": "EXPORTED_ORIGINAL_COSTS_ONLY", "files": manifest["files"],
                      "cross_campaign_totals": None, "new_scientific_measurements": False}, indent=2))


if __name__ == "__main__":
    main()
