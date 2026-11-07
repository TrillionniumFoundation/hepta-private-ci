"""Read only two source-fixed native assertion grammars; never export context."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
RAW_SHA = "afc8e0e074eb2243ad53db45a0832f93d9c496c3cb38bfece3f094522c4297cb"
SAFE_SHA = "da2b21954d83b2ef840d63368598a5c819411be8061f63688d955b17a478f107"
BROAD = "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces"
LEGACY = (
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots"
)
ALLOWED = re.compile(
    r'\s*(?:\[|\]|\(|\),?|Some\(|PermissionDenied,|None,|true,|false,|"outside",|-?\d+,)\s*'
)


def need(value, reason):
    if not value:
        raise ValueError(reason)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def array(value):
    fields = re.findall(r"Some\(PermissionDenied,\)|None", value)
    need(
        len(fields) == 4 and value == "[" + ",".join(fields) + ",]",
        "FOUR_OPERATION_RESULTS",
    )
    return [
        "PermissionDenied" if field.startswith("Some") else None for field in fields
    ]


def tuple_value(value):
    match = re.fullmatch(
        r'\((-?\d+),(true|false),(true|false),(true|false),(None|Some\("outside",\)),(true|false),\)',
        value,
    )
    need(match is not None, "EXACT_LEGACY_SIX_FIELD_TUPLE")
    return [
        int(match[1]),
        match[2] == "true",
        match[3] == "true",
        match[4] == "true",
        None if match[5] == "None" else "outside",
        match[6] == "true",
    ]


def parse_case(lines, case, header, stop):
    labels = [
        i
        for i in range(header + 1, stop)
        if lines[i].strip() == "Diff < left / right > :"
    ]
    need(len(labels) == 1, "EXACTLY_ONE_FIXED_DIFF_LABEL")
    label = labels[0]
    left, right = [], []
    end = label + 1
    while end < stop:
        line = lines[end]
        if not line or line[:1] not in (" ", "<", ">"):
            break
        if ALLOWED.fullmatch(line[1:]) is None:
            break
        if line[0] != ">":
            left.append(line[1:])
        if line[0] != "<":
            right.append(line[1:])
        end += 1
    need(left and right, "MISSING_FIXED_ASSERTION")
    left, right = [re.sub(r"\s+", "", "".join(value)) for value in (left, right)]
    if case == BROAD:
        actual, expected = array(left), array(right)
        need(expected == ["PermissionDenied"] * 4, "ORIGINAL_FOUR_DENIAL_ASSERTION")
        fields = [
            "outside_overwrite_error",
            "outside_create_error",
            "outside_file_delete_error",
            "outside_directory_delete_error",
        ]
    else:
        actual, expected = tuple_value(left), tuple_value(right)
        need(
            expected == [0, False, False, False, "outside", True],
            "ORIGINAL_LEGACY_EXPECTATION",
        )
        fields = [
            "exit_code",
            "workspace_file_exists",
            "temp_file_exists",
            "tmp_file_exists",
            "outside_file_read_ok",
            "protected_git_directory_exists",
        ]
    return {
        "case": case,
        "header_line": header + 1,
        "label_line": label + 1,
        "diff_lines": [label + 2, end],
        "fields": fields,
        "actual": actual,
        "expected": expected,
    }


def duplicate_span(lines, first, second):
    need(0 <= first < second < len(lines), "DUPLICATE_ANCHORS")
    need(lines[first] == lines[second], "DUPLICATE_ANCHOR_VALUES")
    gap = second - first
    before = 0
    while (
        first - before > 0 and lines[first - before - 1] == lines[second - before - 1]
    ):
        before += 1
    after = 1
    while second + after < len(lines) and lines[first + after] == lines[second + after]:
        after += 1
    need(before + after <= gap, "OVERLAPPING_DUPLICATE_RANGES")
    return {
        "first_range": [first - before + 1, first + after],
        "second_range": [second - before + 1, second + after],
        "normalized_line_count": before + after,
        "normalized_payload_lines_equal": True,
        "timestamp_bytes_compared": False,
        "unrecognized_content_exported": False,
        "independent_execution_inferred": False,
    }


def main():
    need(sys.dont_write_bytecode and len(sys.argv) == 1, "READ_ONLY_ENTRY")
    path = HERE / "job_128343024490.log"
    mode = path.lstat()
    need(
        stat.S_ISREG(mode.st_mode)
        and stat.S_IMODE(mode.st_mode) == 0o600
        and mode.st_nlink == 1,
        "PRIVATE_ORIGINAL_MODE",
    )
    raw = path.read_bytes()
    need(identity(raw) == {"bytes": 532020, "sha256": RAW_SHA}, "RAW_IDENTITY")
    safe_raw = (HERE / "SAFE_NATIVE_OBSERVATIONS.json").read_bytes()
    need(identity(safe_raw)["sha256"] == SAFE_SHA, "SOURCE_RECEIPT_IDENTITY")
    safe = json.loads(safe_raw)
    source_pins = safe["source"]["source_leaves"]
    for row in source_pins:
        body = Path(row["local_path"]).read_bytes()
        need(identity(body) == {k: row[k] for k in ("bytes", "sha256")}, "SOURCE_PIN")
    lines = [
        re.sub(r"^\d{4}-\d{2}-\d{2}T\S+ ", "", x) for x in raw.decode().splitlines()
    ]
    boundaries = [
        i
        for i, line in enumerate(lines)
        if (line.startswith("---- ") and line.endswith(" stdout ----"))
        or line == "failures:"
    ]
    records = []
    for case in (BROAD, LEGACY):
        headers = [
            i for i, line in enumerate(lines) if line == "---- " + case + " stdout ----"
        ]
        need(headers, "MISSING_FIXED_CASE_HEADER")
        header = headers[0]
        stop = min((i for i in boundaries if i > header), default=len(lines))
        record = parse_case(lines, case, header, stop)
        record["additional_header_lines"] = [i + 1 for i in headers[1:]]
        record["additional_header_values"] = "NOT_PARSED"
        records.append(record)
    spans = []
    for rows in safe["fixed_case_results"].values():
        need(
            len(rows) == 2 and rows[0]["result"] == rows[1]["result"],
            "TWO_PRINTED_CASE_LINES",
        )
        span = duplicate_span(lines, rows[0]["line"] - 1, rows[1]["line"] - 1)
        if span not in spans:
            spans.append(span)
    run = json.loads((HERE / "RUN_OBSERVATION2_API.json").read_bytes())
    jobs = json.loads((HERE / "JOBS_OBSERVATION2_API.json").read_bytes())
    need(
        run["id"] == 42352197933
        and run["run_attempt"] == 1
        and run["head_sha"] == safe["source"]["head"]
        and run["status"] == "completed",
        "TERMINAL_RUN",
    )
    need(
        jobs["total_count"] == len(jobs["jobs"])
        and len({x["id"] for x in jobs["jobs"]}) == len(jobs["jobs"]),
        "FULL_JOB_PAGE",
    )
    owning = next(x for x in jobs["jobs"] if x["id"] == 128343024490)
    need(
        owning["run_attempt"] == 1
        and owning["head_sha"] == safe["source"]["head"]
        and owning["conclusion"] == "failure",
        "OWNING_TERMINAL",
    )
    result = {
        "schema": "windows44-two-original-assertions-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": run["id"],
        "job": owning["id"],
        "attempt": 1,
        "source": {k: safe["source"][k] for k in ("head", "tree", "actual_checkout")},
        "private_log_identity_only": identity(raw),
        "source_observer_receipt": identity(safe_raw),
        "parser_identity": identity(Path(__file__).read_bytes()),
        "records": records,
        "duplicate_case_line_contexts": spans,
        "whole_run": {
            "status": run["status"],
            "conclusion": run["conclusion"],
            "complete_job_count": jobs["total_count"],
            "conclusion_counts": {
                value: sum(x["conclusion"] == value for x in jobs["jobs"])
                for value in ("success", "failure", "skipped", "cancelled", None)
            },
        },
        "original_assertion_expectations_unchanged": True,
        "full_numeric_probe_records": 0,
        "private_context_exported": False,
        "new_native_run": False,
        "production_P0_closed": False,
        "limits": [
            "Only the two known assertion grammars were decoded; arbitrary panic/context text was excluded.",
            "Duplicate printed context is not a second invocation or independent trial.",
            "No F0-F4 numeric fields or cleanup results are inferred from a passed captured test.",
            "The source-bound assertion values do not by themselves establish a unique production cause.",
        ],
    }
    with (HERE / "PRETTY_ASSERTION_VALUES.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
