#!/usr/bin/env python3
"""Independently recalculate frozen C4 timing records; never run a native sample."""

import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path


COMMIT = "8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE = "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
ELF = "39a2d4f3e2cc62b799a8871846d3303537b67badc67f662dd5dadd9601e7b959"
KERNELS = ("retained-transposed", "scalar-reference", "limb-transcript", "production-full-limb")
VARIANTS = ("legal", "transcript", "product-last-cell")
CLASSES = ("dense", "zero", "rank-one", "sparse")
TARGETS = ("7f" + "ff" * 31, "07" + "ff" * 31)
FLAGS = ("fastest_adversary_qualified", "work_hardness_accepted", "worst_case_rejection_qualified", "public_service_measured", "production_activation")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse(data):
    return json.loads(data, object_pairs_hook=pairs)


def number(value):
    assert type(value) is int and value >= 0
    return value


def rational(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator, "value": float(value)}


def ratio(numerator, denominator):
    assert denominator > 0
    return rational(Fraction(numerator, denominator))


def stats(values):
    values = sorted(Fraction(value) for value in values)
    count = len(values)
    assert count
    median = values[count // 2] if count % 2 else (values[count // 2 - 1] + values[count // 2]) / 2
    return {"n": count, "min": rational(values[0]), "median": rational(median),
            "p95": rational(values[(95 * count + 99) // 100 - 1]),
            "max": rational(values[-1]), "sum": rational(sum(values))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--expected-native-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    folder = args.receipt_dir.resolve(strict=True)
    raw_bytes = (folder / "native.stdout").read_bytes()
    manifest_bytes = (folder / "manifest.json").read_bytes()
    summary_bytes = (folder / "summary.json").read_bytes()
    assert digest(raw_bytes) == args.expected_native_sha256
    assert digest(manifest_bytes) == args.expected_manifest_sha256
    manifest, summary, raw = map(parse, (manifest_bytes, summary_bytes, raw_bytes))
    assert manifest["artifact_sha256"]["native.stdout"] == digest(raw_bytes)
    assert manifest["result"] == "PASS" and manifest["source_before"] == manifest["source_after"]
    assert manifest["source_before"]["commit"] == COMMIT and manifest["source_before"]["tree"] == TREE
    assert manifest["binary_sha256_after"] == ELF
    image = (folder / "pon_rejection_cost").read_bytes()
    assert len(image) == 707216 and image[:4] == b"\x7fELF" and digest(image) == ELF
    assert manifest["binary_sha256_before"] == ELF
    assert raw["schema"] == "pon-work-rejection-cost-v2"
    assert raw["producer"] == "prepared-task-full-transcript" and raw["kernels"] == list(KERNELS)
    assert len(raw["samples"]) == summary["cohorts"] == 96
    assert summary["timed_verifications"] == 1152
    assert summary["independent_winning_transcript_replays"] == 96
    assert all(record[flag] is False for record in (raw, manifest, summary) for flag in FLAGS)

    groups = defaultdict(list)
    seen = set()
    for row in raw["samples"]:
        key = (row["class"], row["target"], row["sample"])
        assert key not in seen
        seen.add(key)
        assert row["class"] in CLASSES and row["target"] in TARGETS
        assert type(row["sample"]) is int and 0 <= row["sample"] < 12
        assert row["honest_search"]["outcome"] == "winner"
        assert row["honest_search"]["attempts"]
        attempts = row["honest_search"]["attempts"]
        assert [attempt["nonce"] for attempt in attempts] == list(range(len(attempts)))
        assert [attempt["selected"] for attempt in attempts] == [False] * (len(attempts) - 1) + [True]
        assert row["setup"]["total_ns"] == sum(number(row["setup"][field]) for field in ("material_ns", "task_binding_ns", "reusable_preprocessing_ns"))
        assert row["honest_search"]["wall_ns"] == sum(number(row["honest_search"][field]) for field in ("challenge_ns", "proof_construction_ns", "ticket_ns", "diagnostic_overhead_ns"))
        for field in ("challenge_ns", "proof_construction_ns", "ticket_ns"):
            assert row["honest_search"][field] == sum(number(attempt[field]) for attempt in attempts)
        assert number(row["honest_acquisition_ns"]) == number(row["setup"]["total_ns"]) + number(row["honest_search"]["wall_ns"])
        arms = {(arm["variant"], arm["kernel"]): arm for arm in row["measurements"]}
        assert len(arms) == len(row["measurements"]) == 12
        assert set(arms) == {(variant, kernel) for variant in VARIANTS for kernel in KERNELS}
        assert all(number(arm["elapsed_ns"]) > 0 for arm in arms.values())
        mutations = {mutation["id"]: mutation for mutation in row["mutations"]}
        assert len(mutations) == len(row["mutations"]) == 2
        assert set(mutations) == set(VARIANTS[1:])
        assert all(mutation["outcome"] == "ready" for mutation in mutations.values())
        assert {arm["position"] for arm in arms.values()} == set(range(12))
        expected_results = {"legal": "Accepted", "transcript": "Transcript", "product-last-cell": "Product"}
        for variant in VARIANTS:
            variant_arms = [arms[(variant, kernel)] for kernel in KERNELS]
            proof_hash = attempts[-1]["proof_sha256"] if variant == "legal" else mutations[variant]["proof_sha256"]
            for arm in variant_arms:
                assert arm["actual_result"] == arm["probe"]["actual_result"] == expected_results[variant]
                assert arm["proof_sha256"] == proof_hash
                assert arm["probe"]["timed"] is False
                assert (arm["returned_product_sha256"] is not None) == (variant == "legal")
            assert all(arm["probe"] == variant_arms[0]["probe"] for arm in variant_arms)
            assert len({arm["returned_product_sha256"] for arm in variant_arms}) == 1
        for mutation in mutations.values():
            assert mutation["source_proof_sha256"] == attempts[-1]["proof_sha256"]
            assert mutation["construction_ns"] == sum(number(mutation[key]) for key in ("clone_ns", "mutation_ns", "ticket_search_wall_ns", "construction_overhead_ns"))
            assert mutation["ticket_search_wall_ns"] == sum(number(mutation[key]) for key in ("ticket_candidate_ns", "ticket_hash_ns", "ticket_recording_overhead_ns"))
        groups[key[:2]].append((row, arms, mutations))
    assert set(groups) == {(material, target) for material in CLASSES for target in TARGETS}

    verification, production, mutations = [], [], []
    for material in CLASSES:
        for target in TARGETS:
            members = sorted(groups[(material, target)], key=lambda member: member[0]["sample"])
            assert len(members) == 12
            assert [member[0]["sample"] for member in members] == list(range(12))
            for variant in VARIANTS:
                for kernel in KERNELS:
                    assert sorted(arm[(variant, kernel)]["position"] for _, arm, _ in members) == list(range(12))
            base = {"matrix_class": material, "target": target, "cohorts": 12}
            attempts = [len(row["honest_search"]["attempts"]) for row, _, _ in members]
            producer = dict(base, actual_nonce_attempts=stats(attempts), total_nonce_attempts=sum(attempts),
                            unsuccessful_nonce_attempts=sum(attempts) - 12, fresh_setups=12, winners=12)
            for field in ("material_ns", "task_binding_ns", "reusable_preprocessing_ns", "total_ns"):
                producer["setup_" + field] = stats(number(row["setup"][field]) for row, _, _ in members)
            for field in ("wall_ns", "challenge_ns", "proof_construction_ns", "ticket_ns", "diagnostic_overhead_ns"):
                producer["search_" + field] = stats(number(row["honest_search"][field]) for row, _, _ in members)
            acquisition = [row["honest_acquisition_ns"] for row, _, _ in members]
            producer["honest_acquisition_ns"] = stats(acquisition)
            production.append(producer)
            for variant in VARIANTS[1:]:
                mutation = dict(base, variant=variant)
                for field in ("clone_ns", "mutation_ns", "ticket_search_wall_ns", "ticket_candidate_ns", "ticket_hash_ns", "ticket_recording_overhead_ns", "construction_ns", "construction_overhead_ns"):
                    mutation[field] = stats(number(change[variant][field]) for _, _, change in members)
                mutation["ticket_attempts"] = stats(len(change[variant]["ticket_attempts"]) for _, _, change in members)
                mutation["acquisition_plus_mutation_ns"] = stats(row["honest_acquisition_ns"] + change[variant]["construction_ns"] for row, _, change in members)
                mutations.append(mutation)
            for kernel in KERNELS:
                for variant in VARIANTS:
                    times = [arm[(variant, kernel)]["elapsed_ns"] for _, arm, _ in members]
                    legal = [arm[("legal", kernel)]["elapsed_ns"] for _, arm, _ in members]
                    full_limb = [arm[(variant, "production-full-limb")]["elapsed_ns"] for _, arm, _ in members]
                    entry = dict(base, kernel=kernel, variant=variant, elapsed_ns=stats(times), total_elapsed_ns=sum(times),
                                 ratio_of_totals_to_same_kernel_legal=ratio(sum(times), sum(legal)),
                                 paired_ratios_to_same_kernel_legal=stats(Fraction(a, b) for a, b in zip(times, legal)),
                                 ratio_of_totals_to_full_limb_same_variant=ratio(sum(times), sum(full_limb)))
                    if variant == "legal":
                        entry["acquisition_to_verification_ratio_of_totals"] = ratio(sum(acquisition), sum(times))
                    else:
                        construction = [change[variant]["construction_ns"] for _, _, change in members]
                        entry["reject_to_existing_winner_mutation_ratio_of_totals"] = ratio(sum(times), sum(construction))
                        entry["reject_to_acquisition_plus_mutation_ratio_of_totals"] = ratio(sum(times), sum(acquisition) + sum(construction))
                    verification.append(entry)
    assert len(verification) == 96 and sum(row["elapsed_ns"]["n"] for row in verification) == 1152
    comparison_count = 0
    for group in summary["groups"]:
        assert group["complete_balanced_group"] and group["honest_winners"] == 12
        for key, original in group["variants"].items():
            variant, kernel = key.split("/")
            selected = [row for row in verification if (row["matrix_class"], row["target"], row["variant"], row["kernel"]) == (group["class"], group["target"], variant, kernel)]
            assert len(selected) == 1
            assert selected[0]["total_elapsed_ns"] == original["verification_total_ns"]
            assert selected[0]["elapsed_ns"]["n"] == original["verifications"]
            comparison_count += 1
    assert comparison_count == 96

    overview = []
    for kernel in KERNELS:
        entry = {"kernel": kernel}
        for variant in VARIANTS:
            cells = [row for row in verification if row["kernel"] == kernel and row["variant"] == variant]
            entry[variant] = {
                "median_ns_range": [min(row["elapsed_ns"]["median"]["value"] for row in cells), max(row["elapsed_ns"]["median"]["value"] for row in cells)],
                "largest_observed_p95_ns": max(row["elapsed_ns"]["p95"]["value"] for row in cells),
                "ratio_of_totals_to_legal_range": [min(row["ratio_of_totals_to_same_kernel_legal"]["value"] for row in cells), max(row["ratio_of_totals_to_same_kernel_legal"]["value"] for row in cells)]}
        overview.append(entry)
    report = {
        "schema": "root-C4-independent-four-kernel-cost-recalculation-v1", "commit": COMMIT, "tree": TREE,
        "native_raw_sha256": digest(raw_bytes), "native_manifest_sha256": digest(manifest_bytes),
        "original_summary_sha256": digest(summary_bytes), "analysis_script_sha256": digest(Path(__file__).read_bytes()),
        "reported_retained_elf_sha256": ELF, "actual_retained_ELF_bytes_hashed": True,
        "every_recorded_verdict_and_untimed_probe_checked": True,
        "balanced_twelve_position_rotation_checked": True,
        "cohorts": 96, "timed_verifications": 1152,
        "original_reader_reports_transcript_replays": 96, "transcripts_reexecuted_by_this_analysis": False,
        "summary_cells_independently_matched": comparison_count, "actual_nonce_attempts": sum(row["total_nonce_attempts"] for row in production),
        "unsuccessful_nonce_attempts": sum(row["unsuccessful_nonce_attempts"] for row in production),
        "verification": verification, "production": production, "mutations": mutations, "kernel_overview": overview,
        "clock": "monotonic wall time, not CPU time, energy, currency or public request latency",
        "quantiles": "per class/target/kernel/variant, n=12; median averages middle two; nearest-rank p95 equals this sample's maximum",
        "ratio_definition": "ratio of paired totals; exact rational numerators/denominators retained, not ratio of separate medians",
        "additional_native_samples": 0, "public_service_gate_closed": False, "global_minimum_claimed": False,
        "worst_case_bound_claimed": False, "joint_gate_status": "HOLD",
        "limitations": [
            "Only one PreparedTask producer and H=1 accepted proof per fresh setup in this component.",
            "Four verifier kernels are not four independent producers.",
            "Both mutations start from an already acquired valid winner; from-zero costs belong to a different component.",
            "Acquisition includes setup and every actual failed/successful nonce search; acquisition is not an attack lower bound.",
            "Only transcript and last-product-cell rejection paths are timed, not all invalid inputs or whole-node behavior.",
            "No population-tail confidence, independent-hardware or network-eligibility conclusion follows from these finite samples."]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "root-four-kernel-cost-recalculation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = ["# C4 四种验算内核：独立原始成本重算", "", "**该组件的 96 个 proof flow、1,152 次计时验算已从完整 raw 逐项重算；W1 与公开服务联合门禁仍为 HOLD。**", "",
             f"源码 `{COMMIT}`；原始输出 SHA256 `{digest(raw_bytes)}`。本程序不新增采样、不重建二进制。", "",
             "每格含 12 个样本，中位数取中间两项均值；nearest-rank p95 在此就是样本最大值。所有时间均为单调墙钟时间。下表分别统计八个 class/target 分组，列出其中位数范围及其中最大的样本 p95；共享证明、材料或搜索前缀不构成统计独立性。", "",
             "| 验算内核 | 合法 median 范围 / 最大样本 p95（ms） | Transcript 拒绝（ms） | 最后乘积格拒绝（ms） |", "|---|---:|---:|---:|"]
    for entry in overview:
        cells = []
        for variant in VARIANTS:
            value = entry[variant]
            low, high = value["median_ns_range"]
            cells.append(f"{low / 1e6:.6f}–{high / 1e6:.6f} / {value['largest_observed_p95_ns'] / 1e6:.6f}")
        lines.append("| " + entry["kernel"] + " | " + " | ".join(cells) + " |")
    lines += ["", f"实际 nonce 尝试共 {report['actual_nonce_attempts']} 次，包括 {report['unsuccessful_nonce_attempts']} 次未获胜尝试和 96 个 winner。setup、全部 search 与变造阶段分别保留；不把尝试数当作接受证明数。", "",
              "JSON 保存全部 96 个 class/target/kernel/variant 格、精确有理数分子/分母，以及拒绝成本相对于“已有 winner 的增量变造”和“本次合法 acquisition 加变造”的两个分母。四个 verifier 共用同一个证明，不能据此把生产成本除以四。", "",
              "该组件只有一个合法生产实现，跨已接受证明的 horizon 为 H=1。两个 invalid 变造均从完整合法 winner 开始；独立从零伪造、13/15 策略、H=8/64 等比较必须使用各自完整 raw 与计时范围。所有有限样本值都不是攻击者的必付成本或全局最低成本。", "",
              "该分析独立重算计时与计数，并核对原 reader 的 96 格总额；它没有另行执行完整 transcript 验证。原 reader 的实际验证与实际 ELF 字节完整性由各自执行/导出证据支持。", ""]
    (args.output_dir / "root-four-kernel-cost-recalculation.md").write_text("\n".join(lines))
    print(json.dumps({"result": "PASS_RAW_RECALCULATION", "cells": 96, "timings": 1152,
                      "native_raw_sha256": digest(raw_bytes), "kernel_overview": overview}, indent=2))


if __name__ == "__main__":
    main()
