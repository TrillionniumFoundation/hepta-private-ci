"""Reverse only the two original, source-fixed Windows44 assertion hunks."""

import hashlib
import json
from pathlib import Path
import re
import stat

WORK = Path("/dev/shm/ndu_root_continuation_20261107")
OWNER = Path("/dev/shm/ndu_windows44_20261107/source_auto_ci_42352197933")
ALLOWED = re.compile(
    r'\s*(?:\[|\]|\(|\),?|Some\(|PermissionDenied,|None,|true,|false,|"outside",|-?\d+,)\s*'
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def read(path, sha):
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode), "Regular original required")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == sha, "Exact input identity required")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": sha,
        "mode": format(stat.S_IMODE(st.st_mode), "04o"),
    }


def canonical_array(values):
    require(
        len(values) == 4 and all(x in ("PermissionDenied", None) for x in values),
        "Four fixed errors only",
    )
    return (
        "["
        + ",".join(
            "None" if value is None else "Some(PermissionDenied,)" for value in values
        )
        + ",]"
    )


def canonical_tuple(values):
    require(len(values) == 6 and type(values[0]) is int, "Six source fields")
    require(
        all(type(values[i]) is bool for i in (1, 2, 3, 5))
        and values[4] in (None, "outside"),
        "Fixed tuple types",
    )
    words = [
        str(values[0]),
        *(str(value).lower() for value in values[1:4]),
        "None" if values[4] is None else 'Some("outside",)',
        str(values[5]).lower(),
    ]
    return "(" + ",".join(words) + ",)"


def main():
    root_raw, root_pin = read(
        WORK / "windows44_terminal_root/ROOT_REVIEW.json",
        "3581467bcff919ad720dcf17f71f0cebb9620d3ba0d272180e173afd59b5c03b",
    )
    root = json.loads(root_raw)
    report_raw, report_pin = read(
        OWNER / "PRETTY_ASSERTION_VALUES.json",
        "e6a467783ceabf2dabf22ac01e24fd41af0e9732c42867b159815af7ba110da4",
    )
    report = json.loads(report_raw)
    parser_raw, parser_pin = read(
        OWNER / "assertion_values44_v3.py",
        "cac1e72bfebc4ed53470a8d76f8c8b3b4d636328f2d82efc366d1f96bfc22869",
    )
    require(len(parser_raw) == 8888, "Reviewed peer parser identity")
    raw, raw_pin = read(
        OWNER / "job_128343024490.log",
        "afc8e0e074eb2243ad53db45a0832f93d9c496c3cb38bfece3f094522c4297cb",
    )
    require(
        raw_pin["bytes"] == 532020 and raw_pin["mode"] == "0600", "Private original"
    )
    require(
        report["run"] == root["run"]
        and report["job"] == root["job"]
        and report["attempt"] == 1,
        "Native identity",
    )
    require(
        report["source"]
        == {key: root[key] for key in ("head", "tree", "actual_checkout")},
        "Source identity",
    )
    source_text = {}
    for item in root["source_leaves"]:
        if item["repository_path"].endswith(
            ("token_tests.rs", "unified_exec/tests.rs")
        ):
            body, _ = read(Path(item["path"]), item["sha256"])
            source_text[item["repository_path"]] = body.decode()
    require(len(source_text) == 2, "Original two assertion sources")
    broad = source_text["codex-rs/windows-sandbox-rs/src/token_tests.rs"]
    require(
        "assert_eq!(refused, [Some(std::io::ErrorKind::PermissionDenied); 4]);"
        in broad,
        "Original broad assertion",
    )
    require(
        'std::fs::remove_file(outside.join("keep.txt")),' in broad
        and 'std::fs::remove_dir(outside.join("keep-dir")),' in broad,
        "Actual broad operations",
    )
    require(
        ".map(|result| result.err().map(|error| error.kind()));" in broad,
        "Success-to-None mapping",
    )
    legacy = source_text["codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs"]
    require(
        '(0, false, false, false, Some("outside".to_string()), true),' in legacy,
        "Original legacy assertion",
    )
    require(
        "fs::read_to_string(&outside_file).ok()," in legacy
        and "protected_git_dir.is_dir()," in legacy,
        "Legacy observations are lossy",
    )
    lines = [
        re.sub(r"^\d{4}-\d{2}-\d{2}T\S+ ", "", line)
        for line in raw.decode().splitlines()
    ]
    require(len(report["records"]) == 2, "Two fixed assertion records")
    checked = []
    for index, record in enumerate(report["records"]):
        case = record["case"]
        header, label = record["header_line"], record["label_line"]
        start, end = record["diff_lines"]
        require(
            lines[header - 1] == "---- " + case + " stdout ----",
            "Fixed original header",
        )
        require(
            lines[label - 1].strip() == "Diff < left / right > :", "Exact diff label"
        )
        require(
            start == label + 1 and header < label and end >= start, "Finite hunk bounds"
        )
        require(
            (start, end) == ((3495, 3510) if index == 0 else (3523, 3534)),
            "Original fixed hunk locations",
        )
        left, right = [], []
        for line in lines[start - 1 : end]:
            require(
                line[:1] in (" ", "<", ">") and ALLOWED.fullmatch(line[1:]),
                "Closed assertion grammar",
            )
            if line[0] != ">":
                left.append(line[1:])
            if line[0] != "<":
                right.append(line[1:])
        compact = [re.sub(r"\s+", "", "".join(value)) for value in (left, right)]
        render = canonical_array if index == 0 else canonical_tuple
        require(
            compact == [render(record["actual"]), render(record["expected"])],
            "Entire hunk roundtrip",
        )
        require(
            record["additional_header_values"] == "NOT_PARSED",
            "No later hunk inference",
        )
        checked.append(
            {
                key: record[key]
                for key in (
                    "case",
                    "fields",
                    "actual",
                    "expected",
                    "header_line",
                    "label_line",
                    "diff_lines",
                    "additional_header_lines",
                    "additional_header_values",
                )
            }
        )
    require(
        checked[0]["actual"] == ["PermissionDenied", "PermissionDenied", None, None],
        "Broad native values",
    )
    require(
        checked[1]["actual"] == [0, False, False, False, None, False],
        "Legacy native values",
    )
    result = {
        "schema": "windows44-root-two-assertion-roundtrip-v1",
        "root_native_binding": root_pin,
        "peer_assertion_observation": report_pin,
        "reviewed_peer_parser_not_executed": parser_pin,
        "private_log_identity_only": raw_pin | {"included": False},
        "source_bound_assertion_records": checked,
        "entire_first_two_hunks_reverse_exact": True,
        "broad_outside_file_and_directory_removal_returned_Ok": True,
        "legacy_read_None_and_is_dir_false_unique_cause": "NOT_ESTABLISHED",
        "later_duplicate_headers": "NOT_PARSED",
        "F0_F4_numeric_observations": "UNOBSERVED",
        "unknown_private_context_exported": False,
        "new_native_or_candidate_execution": False,
        "P0_closed": False,
    }
    out = WORK / "windows44_assertion_root"
    out.mkdir(exist_ok=False)
    path = out / "ROOT_REVIEW.json"
    payload = (json.dumps(result, indent=2) + "\n").encode()
    path.write_bytes(payload)
    print(
        json.dumps(
            {
                "path": str(path),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
