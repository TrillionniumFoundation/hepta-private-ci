"""Separate model-free source/accounting reviewer for REAL original MiniLM receipts.

Checks original public source SHA and complete bounded shape/counting; does not
independently attest hardware timings, trained reasoning or model computation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

MODEL = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"
LOCOMO = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ARCHIVE = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
SIZES = (64, 256, 1024, 4096)


def must(cond, desc):
    if not cond:
        raise ValueError(desc)


def check_receipt(root: Path, receipt: dict) -> dict:
    must(type(receipt) is dict and len(json.dumps(receipt)) < 250000, "bad receipt envelope")
    must(receipt.get("schema") == "hepta.hdsi.real-minilm-original-cpu.local-shadow.v1", "schema")
    must(receipt.get("original_model_sha256") == MODEL and receipt.get("original_locomo_sha256") == LOCOMO
         and receipt.get("archive_sha256") == ARCHIVE, "original material fingerprints")
    for flag in ("production_authorized", "natural_reasoning_verified",
                 "ndu_incremental_utility_verified", "future_task_improvement_verified"):
        must(receipt.get(flag) is False, "false authority/task claim " + flag)
    must(receipt.get("disposition") == "HOLD_NO_GO" and
         receipt.get("model_reference_mode") == "original-six-layer-custom-fp32-no-official-hf-parity", "model-mode")
    must(receipt.get("identical_input_rerun_fp32_parity") is True, "cache/reference parity")
    must(receipt.get("no_cache_reference_32_fresh_forwards") == 32 and
         receipt.get("total_actual_full_model_forwards") == 160, "original full-forward arithmetic")
    must(receipt.get("source_root_count_available") == 10, "original roots")
    p = root / "locomo.json"
    must(p.is_file() and not p.is_symlink() and p.stat().st_size <= 4_000_000, "original source missing")
    blob = p.read_bytes()
    must(hashlib.sha256(blob).hexdigest() == LOCOMO, "wrong original source bytes")
    items = json.loads(blob)
    must(type(items) is list and len(items) == 10, "wrong roots")
    seen_root, source_map = set(), {}
    for item in items:
        group = item["sample_id"]
        must(group not in seen_root, "duplicate original root")
        seen_root.add(group)
        for groupkey, turns in item["conversation"].items():
            if not groupkey.startswith("session_") or not isinstance(turns,list):
                continue
            for line in turns:
                t = line.get("text")
                if not isinstance(t,str) or not 15 <= len(t) <= 180:
                    continue
                s = str(line["speaker"]) + ": " + t
                if len(s.encode()) > 300:
                    continue
                h = hashlib.sha256(s.encode()).hexdigest()
                previous = source_map.get(h)
                current = (group,str(line["dia_id"]))
                # Repeated exact text is deduplicated deterministically.
                if previous is None or current < previous:
                    source_map[h] = current
    selected = sorted(source_map)[:32]
    must(receipt.get("source_sha256") == selected, "unmatched source-first selection")
    must(receipt.get("actual_source_roots_selected") == len({source_map[k][0] for k in selected}),
         "wrong original family count")
    cohorts = receipt.get("cohorts")
    must(type(cohorts) is list and len(cohorts) == 4, "incomplete physical fleet")
    accumulated = 0
    rss_previous = 0
    for size, cohort in zip(SIZES,cohorts):
        must(type(cohort) is dict and cohort.get("resident_cells") == size and cohort.get("active_heads") == 32,
             "cohort identity")
        must(cohort.get("actual_original_encoder_full_forwards") == 32 and
             cohort.get("source_feature_identity_parity") == 32 and
             cohort.get("logical_fanout") == size, "false reuse census")
        must(cohort.get("original_pretrained_sequence_calls_if_unshared") == size, "baseline scope")
        must(cohort.get("resident_scalar_head_count") == 6914*size and
             cohort.get("head_weight_bytes_fp32") == 4*6914*size, "physical Head budget")
        output_sha = cohort.get("head_output_sha256")
        must(type(output_sha) is str and len(output_sha) == 64 and
             all(c in "0123456789abcdef" for c in output_sha), "output sha")
        for t in ("actual_feature_cost_wall_seconds","cohort_wall_seconds","cohort_cpu_seconds"):
            number = cohort.get(t)
            must(type(number) in (float,int) and math.isfinite(number) and number > 0, "invalid meter")
        rss = cohort.get("maxrss_bytes_whole_process_unattested")
        must(type(rss) is int and 0 < rss < 50_000_000_000 and rss >= rss_previous, "invalid whole-process RSS")
        rss_previous = rss
        must(cohort["cohort_wall_seconds"] >= cohort["actual_feature_cost_wall_seconds"],
             "overlapping scope misreported")
        accumulated += cohort["actual_original_encoder_full_forwards"]
    must(accumulated+receipt["no_cache_reference_32_fresh_forwards"] ==
         receipt["total_actual_full_model_forwards"], "incomplete computation census")
    must(receipt.get("total_original_tokens",0) > 0, "missing real forward token volume")
    for k in ("model_load_wall_seconds","no_cache_reference_wall_seconds",
              "end_to_end_wall_seconds","end_to_end_cpu_seconds"):
        v = receipt.get(k)
        must(type(v) in (float,int) and math.isfinite(v) and v > 0, "invalid lifecycle meter")
    return {"schema": "hepta.hdsi.minilm.independent-source-review.v1",
            "original_source_sha_reverified": True, "source_case_roster_independently_recomputed": True,
            "all_fleet_cost_counters_conserved": True,
            "original_input_families_in_current_panel": receipt["actual_source_roots_selected"],
            "real_original_encoder_execution_attested_by_independent_host": False,
            "real_model_numeric_predictions_independently_replayed": False,
            "physical_host_cost_attested": False,
            "independent_human_task_efficacy": False,
            "production_authorized": False, "disposition": "HOLD_NO_GO"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    arg = p.parse_args()
    with arg.receipt.open("rb") as f:
        raw = f.read(250_001)
    must(0 < len(raw) <= 250_000, "oversize receipt")
    def no_duplicate_keys(pairs):
        d = {}
        for k,v in pairs:
            must(k not in d, "duplicate JSON key")
            d[k] = v
        return d
    receipt = json.loads(raw, object_pairs_hook=no_duplicate_keys)
    summary = check_receipt(arg.root, receipt)
    with arg.output.open("xb") as out:
        out.write(json.dumps(summary,sort_keys=True,separators=(",", ":")).encode()+b"\n")
        out.flush()
    print(json.dumps(summary,sort_keys=True))


if __name__ == "__main__":
    main()
