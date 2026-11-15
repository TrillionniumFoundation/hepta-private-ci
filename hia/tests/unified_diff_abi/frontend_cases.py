#!/usr/bin/env python3
"""Actual complete-original/native front-end comparisons at the interning boundary."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from .transport import MAX, binding, compare_outcome, sha256, validate_binding, validate_original_corpus

def line_hash(value):
    # Fixture premise only: no diff, line tokenization, grouping or formatter.
    result = 14695981039346656037 ^ len(value)
    cursor = 0
    while len(value) - cursor >= 8:
        result = ((result ^ int.from_bytes(value[cursor:cursor + 8], "little")) * 1099511628211) & MAX
        cursor += 8
    for byte in value[cursor:]:
        result = ((result ^ byte) * 1099511628211) & MAX
    result = ((result ^ (result >> 30)) * 13787848793156543929) & MAX
    result = ((result ^ (result >> 27)) * 10723151780598845931) & MAX
    return result ^ (result >> 31)

def verify(args, native, report):
    assert len(args.oracle_report) == 1
    assert sha256(args.oracle_report[0]) == args.original_report_sha
    original = validate_original_corpus(args.oracle_report[0])
    report["original_reference_provenance"] = original["bindings"]
    left = bytes.fromhex("000000000000000000000000000000000a")
    right = bytes.fromhex("010000000000000053020000000100000a")
    assert left != right and len(left) == len(right) == 17
    assert line_hash(left) == line_hash(right) == 0xd044fd35e91d8386
    left, right = left.decode(), right.decode()
    cases = []
    def add(name, old, new):
        for context in (0, 1, 3, MAX // 2 + 1, MAX):
            cases.append({"id": len(cases), "name": name, "old": old, "new": new, "context": context})
    for count in (100, 101, 102, 127, 128, 257):
        unique = [f"汉🙂e\u0301\0-{i:04x}\n" for i in range(count)]
        add(f"distinct-unicode-{count}", "".join(unique), "".join(unique[1:] + unique[:1]))
        add(f"distinct-unicode-reverse-{count}", "".join(unique), "".join(reversed(unique)))
        repeated = [("é🙂\0\n", "👩\u200d💻\r\n", "汉e\u0301\r")[i % 3] for i in range(count)]
        add(f"repeated-unicode-{count}", "".join(repeated), "".join(repeated[1:] + repeated[:1]))
        add(f"one-sided-unicode-{count}", "", "".join(unique))
        add(f"collision-fill-{count}", "filler\n" * (count - 1) + left, "filler\n" * (count - 1) + right)
        add(f"collision-alternate-{count}", "".join((left, right)[i % 2] for i in range(count)),
            "".join((right, left)[i % 2] for i in range(count)))
    directory = args.report.with_name(args.report.stem + ".original")
    directory.mkdir(exist_ok=False)
    case_path, input_path = directory / "cases.json", directory / "cases.bin"
    case_path.write_text(json.dumps(cases, ensure_ascii=True) + "\n")
    input_path.write_bytes(b"".join(struct.pack("<4Q", c["id"], c["context"], len(c["old"].encode()), len(c["new"].encode()))
                                    + c["old"].encode() + c["new"].encode() for c in cases))
    report["cases"] = binding(case_path)
    report["input"] = binding(input_path)
    report["original_commands"] = []
    references = {}
    for policy in range(4):
        command = original["commands"][policy]
        binary = validate_binding(command["binary"])
        validate_binding(command["rlib"])
        stdout, stderr = directory / f"policy-{policy}.stdout", directory / f"policy-{policy}.stderr"
        with input_path.open("rb") as stdin, stdout.open("xb") as out, stderr.open("xb") as err:
            result = subprocess.run([str(binary)], stdin=stdin, stdout=out, stderr=err, timeout=60)
        record = {"policy": policy, "argv": [str(binary)], "returncode": result.returncode,
                  "binary": binding(binary), "rlib": command["rlib"], "stdout": binding(stdout), "stderr": binding(stderr)}
        report["original_commands"].append(record)
        assert result.returncode == 0 and stderr.stat().st_size == 0, record
        rows = [json.loads(line) for line in stdout.read_text().splitlines()]
        assert len(rows) == len(cases) and [x["id"] for x in rows] == list(range(len(cases)))
        assert all("construction_panic_hex" not in x for x in rows)
        references[policy] = rows
    coverage = {"triggered": 0, "exactly_100": 0, "exactly_101": 0,
                "triggered_unicode": 0, "triggered_distinct_unicode": 0, "triggered_actual_hash_collision": 0}
    for case in cases:
        row = references[0][case["id"]]
        counts = len(row["old_tokens"]), len(row["new_tokens"])
        coverage["exactly_100"] += 100 in counts
        coverage["exactly_101"] += 101 in counts
        if max(counts) > 100:
            coverage["triggered"] += 1
            unicode = any(byte >= 128 for byte in (case["old"] + case["new"]).encode())
            coverage["triggered_unicode"] += unicode
            coverage["triggered_distinct_unicode"] += unicode and any(
                len(set(row[key])) > 100 for key in ("old_tokens", "new_tokens"))
            coverage["triggered_actual_hash_collision"] += "collision" in case["name"]
        for policy in range(4):
            expected = references[policy][case["id"]]
            pairs = []
            for trusted in (False, True):
                query, result = native.valid_pair(case["old"].encode(), case["new"].encode(), case["context"],
                    policy, trusted, len(expected["old_tokens"]), len(expected["new_tokens"]),
                    extra_capacity=29, guard=1 + case["id"] % 31,
                    label=f"intern-{case['id']}-{policy}-{trusted}")
                compare_outcome(case, expected, result)
                pairs.append((query.output, result.output))
            assert pairs[0] == pairs[1]
    def concurrent(index):
        case = cases[index % len(cases)]
        policy = index % 4
        expected = references[policy][case["id"]]
        _, result = native.valid_pair(case["old"].encode(), case["new"].encode(), case["context"],
            policy, bool(index % 2), len(expected["old_tokens"]), len(expected["new_tokens"]),
            label=f"concurrent-intern-{index}")
        compare_outcome(case, expected, result)
        return 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        report["concurrent_pairs"] = sum(pool.map(concurrent, range(128)))
    assert coverage["triggered_distinct_unicode"] >= 1 and coverage["triggered_actual_hash_collision"] >= 1
    report["frontend_coverage_from_complete_original_tokens"] = coverage
    report["case_count"] = len(cases)
    report["native_plan_comparisons"] = len(cases) * 4 * 2
    report["strict_trusted_pairs"] = len(cases) * 4
    hepta = native.source_path.read_text()
    excerpt = hepta[hepta.index("fn hash_line("):hepta.index("fn intern_lines(")]
    report["collision_premise"] = {"left_hex": left.encode().hex(), "right_hex": right.encode().hex(),
        "length": 17, "hash_hex": "d044fd35e91d8386", "hash_function_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        "numerically_verified_against_reviewed_hia_hash_function": True,
        "actual_complete_original_and_native_inputs_executed": True}
    report["policies_exercised"] = [0, 1, 2, 3]
    report["mixed_compile_profile_mapping_qualified"] = False
    report["u32_id_overflow_scale_executed"] = False

