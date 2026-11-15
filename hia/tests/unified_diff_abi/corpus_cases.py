#!/usr/bin/env python3
"""Compare the complete native unified-diff owner with fixed original transcripts."""
from concurrent.futures import ThreadPoolExecutor

from .transport import compare_outcome, sha256, validate_original_corpus

KNOWN = {}  # Fresh report identities; locked corpus bytes/counts stay fixed.


def verify(args, native, report):
    assert args.oracle_report, "complete original reference reports are required"
    fingerprints = [sha256(path) for path in args.oracle_report]
    assert len(set(fingerprints)) == len(fingerprints)
    assert all(value in KNOWN for value in fingerprints), "unreviewed original corpus identity"
    assert any(KNOWN[value][0] == 3732 for value in fingerprints), "independent corpus must not be dropped"
    if not args.development:
        assert set(fingerprints) == set(KNOWN), "formal full-owner gate retains both complete corpora"
    policies = args.policy or [0, 1, 2, 3]
    assert len(set(policies)) == len(policies)
    if not args.development:
        assert set(policies) == {0, 1, 2, 3}
    report["policies_exercised"] = policies
    report["full_compile_profile_binding_qualified"] = False
    report["original_corpora"] = []
    comparisons = 0
    coverage = {"triggered_cases": 0, "exactly_100_cases": 0, "exactly_101_cases": 0,
                "triggered_repeated_line_cases": 0, "triggered_unicode_cases": 0}
    concurrency_cases = []
    for corpus_index, path in enumerate(args.oracle_report):
        corpus = validate_original_corpus(path)
        cases, references = corpus["cases"], corpus["references"]
        count, case_hash = KNOWN[sha256(path)]
        assert len(cases) == count
        assert any(item["sha256"] == case_hash for item in corpus["bindings"])
        report["original_corpora"].append({
            "bindings": corpus["bindings"],
            "case_count": len(cases), "complete_original_files": corpus["complete_original_files"],
            "reference_transcripts_reused": True,
        })
        for case in cases:
            old, new = case["old"].encode(), case["new"].encode()
            original_tokens = references[0][case["id"]]
            counts = len(original_tokens["old_tokens"]), len(original_tokens["new_tokens"])
            coverage["exactly_100_cases"] += 100 in counts
            coverage["exactly_101_cases"] += 101 in counts
            if max(counts) > 100:
                coverage["triggered_cases"] += 1
                coverage["triggered_unicode_cases"] += any(byte >= 128 for byte in old + new)
                coverage["triggered_repeated_line_cases"] += any(
                    len(set(original_tokens[key])) < len(original_tokens[key])
                    for key in ("old_tokens", "new_tokens"))
            for policy in policies:
                original = references[policy][case["id"]]
                old_lines, new_lines = len(original["old_tokens"]), len(original["new_tokens"])
                results = []
                for trusted in (False, True):
                    label = f"corpus{corpus_index}:case{case['id']}:policy{policy}:trusted{trusted}"
                    query, result = native.valid_pair(
                        old, new, case["context"], policy, trusted, old_lines, new_lines,
                        label=label, extra_capacity=19 if case["id"] % 127 == 0 else 0,
                        guard=1 + case["id"] % 31)
                    compare_outcome(case, original, result)
                    results.append((query, result))
                    comparisons += 1
                assert results[0][0].output == results[1][0].output, ("strict/trusted inspect differs", case["id"])
                assert results[0][1].output == results[1][1].output, ("strict/trusted plan differs", case["id"])
                if len(concurrency_cases) < 512 and case["id"] % 13 == 0:
                    concurrency_cases.append((case, original, policy, old_lines, new_lines, corpus_index))
    assert len(concurrency_cases) >= 64

    def concurrent(item):
        case, original, policy, old_lines, new_lines, corpus_index = item
        query, result = native.valid_pair(
            case["old"].encode(), case["new"].encode(), case["context"], policy,
            bool(case["id"] % 2), old_lines, new_lines,
            label=f"concurrent:corpus{corpus_index}:case{case['id']}:policy{policy}",
            extra_capacity=7, guard=7)
        compare_outcome(case, original, result)
        return 1

    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent_pairs = sum(executor.map(concurrent, concurrency_cases))
    assert concurrent_pairs == len(concurrency_cases)
    report["frontend_interning_coverage_from_complete_original_tokens"] = coverage
    report["original_case_count"] = sum(item["case_count"] for item in report["original_corpora"])
    report["actual_native_plan_comparisons"] = comparisons
    report["strict_trusted_pairs"] = comparisons // 2
    report["additional_concurrent_pairs"] = concurrent_pairs
    report["unmodified_original_reference_algorithms"] = True
    report["public_fs_chunk_adapter_qualified"] = False
    report["whole_product_performance_qualified"] = False


