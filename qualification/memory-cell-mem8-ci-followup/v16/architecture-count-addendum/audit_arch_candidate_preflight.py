"""Count original raw-only candidate preflights separately from command receipts."""
import hashlib
import json
from pathlib import Path
import re

from audit_completed_records import identity, python_receipts, HEAD, TREE, MERGE

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CASE = re.compile(r"^test_\S+ \((scripts\.tests\.test_hepta_ci_candidate\.CandidatePlanTests\.[^)]+)\) \.\.\. ok$")

def audit_raw(path, source, tree, tested, lane, job_id, receipt_ids):
    raw = path.read_bytes()
    byte_lines = raw.splitlines(keepends=True)
    lines = [line.decode().rstrip("\r\n") for line in byte_lines]
    cleaned = [ANSI.sub("", re.sub(r"^\d{4}-\d\d-\d\dT\S+Z ", "", line)) for line in lines]
    calls = [i for i, line in enumerate(cleaned) if line == "python3 -m unittest -v scripts.tests.test_hepta_ci_candidate"]
    matches = [(i, CASE.fullmatch(line)) for i, line in enumerate(cleaned) if CASE.fullmatch(line)]
    assert len(calls) == 1 and len(matches) == 8
    ids = [match.group(1) for _, match in matches]
    assert len(set(ids)) == 8 and set(ids).isdisjoint(receipt_ids)
    first, last = matches[0][0], matches[-1][0]
    assert calls[0] < first and [i for i, _ in matches] == list(range(first, last + 1))
    summary = [i for i, line in enumerate(cleaned) if re.fullmatch(r"Ran 8 tests in [0-9.]+s", line)]
    assert len(summary) == 1 and last < summary[0] <= last + 4
    ok = summary[0] + 2
    assert cleaned[summary[0] + 1] == "" and cleaned[ok] == "OK"
    block = b"".join(byte_lines[first:ok + 1])
    expected = {"base_sha": "96038ccf0660154fac143ba6cbe4be81e00813e8", "lane": lane,
                "source_sha": source, "source_tree": tree, "tested_sha": tested, "tested_tree": tree}
    binding_rows = []
    for number, line in enumerate(cleaned):
        if not line.startswith('{"base_sha"') or '"native_execution_required"' not in line:
            continue
        obj = json.loads(line)
        assert all(obj.get(key) == value for key, value in expected.items())
        binding_rows.append((number, obj))
    assert len(binding_rows) == 1 and binding_rows[0][0] > ok
    number, binding = binding_rows[0]
    return {"raw_file": str(path), "full_raw": identity(raw), "job_id": job_id, "lane": lane,
            "source_commit": source, "source_tree": tree, "tested_commit": tested,
            "literal_invocation": {"line": calls[0] + 1, "text": lines[calls[0]], "sha256_including_line_ending": hashlib.sha256(byte_lines[calls[0]]).hexdigest()},
            "case_results": [{"line": i + 1, "case_id": match.group(1), "status": "PASS", "text": lines[i],
                              "sha256_including_line_ending": hashlib.sha256(byte_lines[i]).hexdigest()} for i, match in matches],
            "original_result_block": {"first_line": first + 1, "last_line": ok + 1, **identity(block), "text": block.decode()},
            "summary": {"line": summary[0] + 1, "text": lines[summary[0]]},
            "source_binding": {"line": number + 1, "text": lines[number], "sha256_including_line_ending": hashlib.sha256(byte_lines[number]).hexdigest(), "parsed": binding},
            "raw_only_case_ids": ids, "raw_only_passed": 8, "qualification_receipt_unique_ids": len(receipt_ids),
            "raw_only_ids_disjoint_from_qualification_receipt_ids": True,
            "all_python_execution_case_ids": sorted(set(ids) | receipt_ids),
            "all_python_executions_in_this_lane": len(ids) + len(receipt_ids),
            "structured_command_receipt_for_this_preflight": False}

def main():
    old = json.loads((WORK / "mem-ci-b054-memarch-root/AUDIT.json").read_bytes())
    old_source = "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b"
    old_tree = "3f89ddeff13d0af85f4abe2690699107357f1038"
    assert old["source_commit"] == old_source and old["source_tree"] == old_tree
    configurations = [
        (old_source, old_tree, "source-head", old_source, 130573424803, WORK / "mem-ci-b054-memarch-root/original/job-130573424803.log", [r for r in old["groups"] if r["artifact_id"] == 13862859146]),
        (old_source, old_tree, "base-merge", "52c1eb3eba7e58a09f262bd2bfec5440fa3e3d41", 130573424857, WORK / "mem-ci-b054-memarch-root/original/job-130573424857.log", [r for r in old["groups"] if r["artifact_id"] == 13862932588]),
        (HEAD, TREE, "source-head", HEAD, 130619111897, HERE / "original/job-130619111897.log", python_receipts(13867509444, 43048568183, "source-head", HEAD)),
        (HEAD, TREE, "base-merge", MERGE, 130619111431, HERE / "original/job-130619111431.log", python_receipts(13867373162, 43048568183, "base-merge", MERGE)),
    ]
    rows = []
    for source, tree, lane, tested, job, path, receipts in configurations:
        ids = [name for row in receipts for name in row["case_ids"]]
        assert len(ids) == len(set(ids)) == 136
        rows.append(audit_raw(path, source, tree, tested, lane, job, set(ids)))
    assert all(row["raw_only_case_ids"] == rows[0]["raw_only_case_ids"] for row in rows)
    assert all(row["all_python_execution_case_ids"] == rows[0]["all_python_execution_case_ids"] for row in rows)
    all_ids = rows[0]["all_python_execution_case_ids"]
    all_ids_digest = hashlib.sha256(json.dumps(all_ids, separators=(",", ":")).encode()).hexdigest()
    for row in rows:
        del row["all_python_execution_case_ids"]
        row["all_python_case_ids_canonical_json_sha256"] = all_ids_digest
    result = {"schema": "mem8.architecture.raw-preflight-count-addendum.v1",
              "correction": "136 per lane denotes hepta_ci_exec qualification-receipted Python cases, not every Python execution. Each original lane additionally executed 8 distinct CandidatePlanTests visible in complete raw, with their own invocation and successful summary.",
              "per_source_counts": [{"source_commit": source, "qualification_receipted_executions": 272,
                                     "additional_raw_only_executions": 16, "all_python_executions": 288,
                                     "distinct_python_case_ids": 144, "each_lane": {"receipted": 136, "raw_only": 8, "total": 144}}
                                    for source in (old_source, HEAD)],
              "identical_8_raw_only_ids_across_all_four_original_jobs": True,
              "identical_144_case_id_union_across_all_four_original_jobs": True,
              "all_144_case_ids": all_ids,
              "case_ids_digest_serialization": "JSON array in listed order, ensure_ascii=True, separators=(',', ':'), UTF-8, no trailing newline",
              "original_raw_bytes_modified": False, "new_tests_models_or_CI_runs": 0,
              "old_audit_preserved_as_historical_receipt_scope": True,
              "limits": "Raw-only preflight outcomes do not create missing per-command source-before/after receipts or native success; no result is transferred between source heads.",
              "jobs": rows}
    (HERE / "ARCH_CANDIDATE_RAW_ONLY_COUNT_ADDENDUM.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "jobs"}, indent=2))

if __name__ == "__main__":
    main()
