#!/usr/bin/env python3
"""Pure local source/original-record comparison; never runs a gate or Rust.

Inputs are fixed Git blob bodies in originals/ and source/{c0f,cc57}/,
SOURCE_PINS.json, and EXPECTED_ORIGINAL_BLOBS.json. The deliberately narrow
function extractor is used only on these inspected top-level test definitions;
it is not a Rust semantic parser or a replacement for the repository verifier.
"""
from __future__ import annotations

import collections
import difflib
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
RUST_PREFIX = "codex-rs/hepta-agentd/src/"
OLD_COMMIT = "c0f78493f815780f68b9bf5e390a21314d79311f"
NEW_COMMIT = "cc57c7198db6293ccca562253c42fffbe2a04633"


def identity(raw: bytes) -> dict:
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def read_json(path: Path):
    return json.loads(path.read_text())


def test_definition(text: str, name: str):
    match = re.search(r"(?m)^async fn " + re.escape(name) + r"\s*\(", text)
    if match is None:
        return None
    end = text.find("\n}\n", match.start())
    if end < 0:
        raise ValueError("No inspected column-zero function end: " + name)
    return text[match.start() : end + 3]


def line_of(text: str, marker: str) -> int:
    assert text.count(marker) == 1, marker
    return text[: text.index(marker)].count("\n") + 1


def main() -> None:
    original_records = []
    for filename, expected in read_json(ROOT / "EXPECTED_ORIGINAL_BLOBS.json"):
        raw = (ROOT / "originals" / filename).read_bytes()
        got = identity(raw)
        assert got["git_blob"] == expected, filename
        original_records.append({"filename": filename, **got})

    source_pins = read_json(ROOT / "SOURCE_PINS.json")
    source_text = {"c0f": {}, "cc57": {}}
    source_rows = []
    exact_diffs = []
    for row in source_pins["rows"]:
        for version in ("c0f", "cc57"):
            expected = row[version]
            if expected is None:
                continue
            raw = (ROOT / "source" / version / row["path"]).read_bytes()
            got = identity(raw)
            assert got == {"bytes": expected["bytes"], "sha256": expected["sha256"], "git_blob": expected["working_blob"]}, (version, row["path"])
            source_text[version][row["path"]] = raw.decode("utf-8")
        source_rows.append(row)
        if row["c0f"] is not None and not row["byte_identical"]:
            exact_diffs.append("".join(difflib.unified_diff(
                source_text["c0f"][row["path"]].splitlines(True),
                source_text["cc57"][row["path"]].splitlines(True),
                fromfile="c0f/" + row["path"], tofile="cc57/" + row["path"],
            )))

    xml_root = ET.fromstring((ROOT / "originals/focused.junit.xml").read_bytes())
    tests = list(xml_root.iter("testcase"))
    failed = []
    for test in tests:
        failures = list(test.findall("failure")) + list(test.findall("error"))
        if not failures:
            continue
        name = test.attrib["name"]
        output = "\n".join((test.findtext(tag) or "") for tag in ("system-out", "system-err"))
        text = "\n".join(f.text or "" for f in failures)
        combined = text + "\n" + output
        category = (
            "stack_overflow" if "overflowed its stack" in combined else
            "timeout" if any("timeout" in f.attrib.get("type", "") for f in failures) else
            "functional"
        )
        function_name = name.rsplit("::", 1)[-1]
        matches = [(path, test_definition(content, function_name)) for path, content in source_text["cc57"].items()]
        matches = [(path, definition) for path, definition in matches if definition is not None]
        assert len(matches) == 1, (name, len(matches))
        path, current_definition = matches[0]
        old_definition = test_definition(source_text["c0f"][path], function_name)
        assert old_definition is not None, name
        body_same = old_definition == current_definition
        if category == "stack_overflow":
            assert body_same, name
        failed.append({
            "fqn": name,
            "crate": test.attrib.get("classname"),
            "historical_seconds": test.attrib.get("time"),
            "category": category,
            "failure_attributes": [f.attrib for f in failures],
            "failure_text": text,
            "original_output": output,
            "source_path": path,
            "c0f_function_line": line_of(source_text["c0f"][path], "async fn " + function_name + "("),
            "cc57_function_line": line_of(source_text["cc57"][path], "async fn " + function_name + "("),
            "same_test_definition_bytes": body_same,
            "c0f_definition": identity(old_definition.encode()),
            "cc57_definition": identity(current_definition.encode()),
        })
    counts = dict(collections.Counter(x["category"] for x in failed))
    assert len(tests) == 109 and len(failed) == 28
    assert counts == {"timeout": 2, "stack_overflow": 24, "functional": 2}, counts
    execution = read_json(ROOT / "originals/focused.execution.original.json")
    assert execution["source_sha"] == OLD_COMMIT
    assert execution["before"] == execution["after"]
    assert execution["returncode"] == 100 and execution["timed_out"] is False
    assert execution["output_limit_exceeded"] is False
    raw_log = (ROOT / "originals/focused.raw.original.log").read_bytes()
    assert len(raw_log) == execution["log_bytes"]
    assert hashlib.sha256(raw_log).hexdigest() == execution["log_sha256"]
    assert execution["observed_failed_tests"] == 28 and execution["observed_passed_tests"] == 81

    provider_path = RUST_PREFIX + "circuit_original_evaluation_provider_tests.rs"
    old_provider = test_definition(source_text["c0f"][provider_path], "original_evaluation_provider_current_withdrawal_and_corruption_never_release_cached_rows")
    new_provider = test_definition(source_text["cc57"][provider_path], "current_refusal_cases")
    old_body = old_provider[old_provider.index("{") + 1 :]
    new_body = new_provider[new_provider.index("{") + 1 :]
    projected_body = new_body.replace("for &mutation in mutations {", 'for mutation in ["withdraw", "source-bytes", "ledger-bytes", "rollback"] {').replace("for &mode in modes {", 'for mode in ["unreleased", "cold-readonly"] {')
    assert projected_body == old_body
    partition = [
        ("original_evaluation_provider_current_withdrawal_and_corruption_never_release_cached_rows", ["withdraw", "source-bytes"], []),
        ("original_evaluation_provider_ledger_corruption_and_clock_rollback_never_release_cached_rows", ["ledger-bytes", "rollback"], []),
        ("original_evaluation_provider_unreleased_and_cold_readonly_never_release_cached_rows", [], ["unreleased", "cold-readonly"]),
    ]
    for name, mutations, modes in partition:
        definition = test_definition(source_text["cc57"][provider_path], name)
        assert definition is not None
        call = re.search(r"current_refusal_cases\(&\[(.*?)\], &\[(.*?)\]\)\.await", definition)
        assert call
        assert re.findall(r'"([^"\\]+)"', call[1]) == mutations
        assert re.findall(r'"([^"\\]+)"', call[2]) == modes

    deep_path = RUST_PREFIX + "circuit_deep_training_readback_tests.rs"
    deep_name = "q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources"
    old_deep = test_definition(source_text["c0f"][deep_path], deep_name)
    new_deep = test_definition(source_text["cc57"][deep_path], deep_name)
    without_logger, logger_count = re.subn(r"    let stage = \|name: &str\| \{.*?\n    \};\n", "", new_deep, flags=re.S)
    without_calls, stage_call_count = re.subn(r'^    stage\("[^"]+"\);\n', "", without_logger, flags=re.M)
    assert logger_count == 1 and without_calls == old_deep

    adjacent = read_json(ROOT / "STACK_ADJACENT_PRODUCTION_INVENTORY_COMPARISON.json")
    assert len(adjacent["rows"]) == 24
    assert all(x["same_bytes"] for x in adjacent["rows"])
    report = {
        "format": "hepta-c0f-focused-versus-cc57-offline-analysis-v1",
        "execution_scope": "Pure local JSON/XML/hash/source-text comparison only; no H, Rust, Cargo, tests, verifier gates, source edits, refs or PR operations.",
        "old_commit": OLD_COMMIT,
        "current_commit": NEW_COMMIT,
        "original_records": original_records,
        "historical_execution": execution,
        "historical_counts": {"total": 109, "passed": 81, "failed": 28, **counts},
        "source_version_bodies_verified": sum(row[v] is not None for row in source_rows for v in ("c0f", "cc57")),
        "selected_source_paths": len(source_rows),
        "unique_source_blobs": len({row[v]["working_blob"] for row in source_rows for v in ("c0f", "cc57") if row[v] is not None}),
        "source_rows": source_rows,
        "failures": failed,
        "static_equalities": {
            "all_24_stack_test_definitions_byte_identical": True,
            "provider_helper_body_restores_old_body_by_only_two_loop_header_substitutions": True,
            "provider_partition": [{"test": n, "mutations": m, "modes": o} for n, m, o in partition],
            "provider_union": {"mutations": [x for _, m, _ in partition for x in m], "modes": [x for _, _, o in partition for x in o]},
            "deep_without_only_logger_and_stage_calls_restores_old_definition": True,
            "deep_logger_definitions": logger_count,
            "deep_stage_calls": stage_call_count,
            "adjacent_24_production_path_inventory_identities_equal": True,
        },
        "limits": [
            "Textual function comparisons are bounded to inspected definitions; not a Rust proof or a gate verdict.",
            "The old one-case GDB first signal is not a root-cause proof for all 24 failures.",
            "Future sizes and runtime results cannot be projected from these source comparisons.",
            "Original fixed source inventory files were recovered earlier and aligned; this script performs no second native observation.",
            "Current cc57 test count need not equal 109 because new default tests and explicit partitioned cases exist.",
        ],
    }
    (ROOT / "OFFLINE_ANALYSIS.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "SELECTED_SOURCE_EXACT_DIFFS.patch").write_text("".join(exact_diffs))
    print(json.dumps({"status": "offline_comparison_completed", "historical_counts": report["historical_counts"], "selected_source_paths": len(source_rows), "source_version_bodies_verified": report["source_version_bodies_verified"], "deep_stage_calls": stage_call_count}))


if __name__ == "__main__":
    main()
