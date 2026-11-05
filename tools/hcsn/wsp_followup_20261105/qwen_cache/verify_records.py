#!/usr/bin/env python3
"""Check frozen receipt consistency and source identities, without loading a model."""
from pathlib import Path
import hashlib
import json
import math
import re


def require(value, name):
    if not value:
        raise RuntimeError(name)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    read = lambda name: json.loads((root / name).read_bytes())
    protocol, pins, receipt = read("protocol.json"), read("runtime_pins.json"), read("receipt.json")
    require(receipt["protocol_sha256"] == sha(root / "protocol.json"), "protocol bytes")
    require(receipt["runtime_pins_sha256"] == sha(root / "runtime_pins.json"), "runtime pin bytes")
    require(receipt["source_sha256"] == sha(root / "qualify_cache.py"), "executed source bytes")
    require(receipt["protocol"] == protocol, "protocol content")
    require(receipt["status"] == "PASS_F32_SHORT_CACHE_QUALIFICATION", "completed qualification")
    require(receipt["original_exports_unchanged"] is True, "original export immutability")
    require(receipt["named_runtime_sources_and_dependency_metadata_unchanged"] is True, "runtime identity")
    require(receipt["runtime_identity"]["dependencies"] == pins["dependencies"], "dependency records")
    require(receipt["runtime_identity"]["transformers_sources"] == pins["transformers_sources"], "named sources")
    require(receipt["original_loader_sha256"] == pins["original_loader_sha256"], "loader identity")
    require(receipt["original_forward_receipt_sha256"] == pins["original_forward_receipt_sha256"], "prior receipt")
    require(all(receipt["input_sha256"][k] == v for k, v in pins["export_sha256"].items()), "export hashes")
    require(protocol["comparator"]["atol"] == protocol["comparator"]["rtol"] == .001, "fixed tolerance")
    require(protocol["input_ids"] == [[32, 11012, 6353, 12077, 2708, 3000, 13]], "fixed input")
    require(protocol["comparison_prefix_lengths"] == list(range(7, 16)), "fixed prefixes")
    require(protocol["execution_dtype"] == "float32" and protocol["attempts"] == 1, "fixed format/attempt")
    require(receipt["measurement"]["wall_seconds"] < protocol["budgets"]["wall_seconds_total"], "wall budget")
    require(receipt["execution_cpu_affinity_count"] == 1, "one logical CPU")
    require(receipt["capability_score_computed"] is False, "no capability claim")
    require(receipt["original_bf16_or_vllm_benchmark_qualified"] is False, "no BF16 benchmark claim")
    count, tokens, forwards, maximum = 0, 0, 0, 0.0
    process_map = {x["variant"]: x for x in receipt["processes"]}
    require(set(process_map) == set(protocol["variants"]), "both completed worker processes")
    for variant in protocol["variants"]:
        v = read(variant + ".json")
        require(v == receipt["variants"][variant], "standalone/nested receipt identity")
        require(v["status"] == "PASS_F32_CACHE_CONSISTENCY", "variant pass")
        require(v["source_sha256"] == receipt["source_sha256"], "worker source identity")
        require(v["protocol_sha256"] == receipt["protocol_sha256"], "worker protocol identity")
        require(v["runtime_pins_sha256"] == receipt["runtime_pins_sha256"], "worker runtime identity")
        require(v["input_ids"] == protocol["input_ids"], "variant fixed input")
        require(v["forwards"] == {"cached_prefill": 1, "incremental_cached": 8, "full_prefix_reference": 9},
                "actual forward counts")
        require(len(v["comparisons"]) == 9 and len(v["appended_tokens"]) == 8, "fixed observations")
        require([c["prefix_tokens"] for c in v["comparisons"]] == list(range(7, 16)), "all prefixes compared")
        require(v["appended_tokens"] == [c["cached_argmax"] for c in v["comparisons"][:-1]],
                "same observed prefix trajectory")
        require(v["execution"]["device"] == "cpu" and v["execution"]["learned_dtype"] == "torch.float32",
                "CPU F32 execution")
        require(v["execution"]["cpu_threads"] == v["execution"]["interop_threads"] == 1, "thread limits")
        require(v["checks"]["learned_f32_parameters_unchanged"] and v["checks"]["source_parameter_values_exactly_lifted"],
                "exact lifting and parameter preservation")
        require(v["strict_load"]["source_language_tensors_verified"] == 320 and
                v["strict_load"]["lifted_parameter_hashes_verified"] == 320, "all language tensors")
        require(v["strict_load"]["missing_keys"] == v["strict_load"]["unexpected_keys"] == [], "strict load")
        require(v["measurement"]["peak_rss_kib_linux"] * 1024 <= protocol["budgets"]["rss_monitor_threshold_bytes"],
                "worker final HWM budget")
        for step, c in enumerate(v["comparisons"]):
            require(c["step"] == step and c["cache_sequence_length"] == c["prefix_tokens"], "cache position")
            require(c["finite"] and c["allclose"] and c["greedy_equal"], "numeric conditions")
            require(c["cached_argmax"] == c["reference_argmax"], "greedy equality")
            ratio = c["maximum_ratio_to_fixed_tolerance"]
            require(math.isfinite(ratio) and 0 <= ratio <= 1, "reported tolerance ratio")
            require(math.isfinite(c["maximum_absolute_logit_difference"]) and c["maximum_absolute_logit_difference"] >= 0,
                    "finite nonnegative difference")
            for k in ["cached_f32_logits_sha256", "reference_f32_logits_sha256"]:
                require(re.fullmatch("[0-9a-f]{64}", c[k]) is not None, "logit commitment")
            maximum = max(maximum, c["maximum_absolute_logit_difference"])
            count += 1
        p = process_map[variant]
        require(p["exit_code"] == 0 and p["termination_reason"] is None, "process terminal status")
        require(max(p["observed_peak_rss_sum_bytes"], p["observed_peak_hwm_sum_bytes"]) <=
                protocol["budgets"]["rss_monitor_threshold_bytes"], "monitored resource limit")
        tokens += len(v["appended_tokens"])
        forwards += sum(v["forwards"].values())
    require(count == 18 and tokens == 16 and forwards == 36, "aggregate execution counts")
    print(json.dumps({
        "status": "PASS_FROZEN_RECORD_VERIFICATION",
        "source_and_receipt_identities_verified": True,
        "recorded_comparisons": count, "recorded_appended_tokens": tokens,
        "recorded_actual_forwards": forwards, "recorded_maximum_logit_difference": maximum,
        "new_forward_or_model_load_executed": False,
        "full_vocab_arrays_independently_recomputed_by_this_verifier": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
