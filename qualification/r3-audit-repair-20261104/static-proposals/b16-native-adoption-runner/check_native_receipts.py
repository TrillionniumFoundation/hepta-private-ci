"""Read-only B adoption receipt checks; never applies source or starts tests."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def record(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def metadata_check(path, repository, plan):
    data = json.loads(path.read_text())
    contract = plan["metadata_contract"]["driver"]
    drivers = [p for p in data["packages"] if p["name"] == contract["name"]]
    assert len(drivers) == 1, "driver package identity is not unique"
    driver = drivers[0]
    assert driver["version"] == contract["version"]
    assert driver.get("source") is None, "driver is still registry-backed"
    expected = (repository / contract["manifest_relative"]).resolve()
    assert Path(driver["manifest_path"]).resolve() == expected
    assert driver["id"] in data["workspace_members"], "dependency tests are not a workspace target"
    nodes = {n["id"]: n for n in data["resolve"]["nodes"]}
    assert set(nodes[driver["id"]]["features"]) == set(contract["exact_observed_features"])
    cores = [p for p in data["packages"] if p["name"] == "sqlx-core" and p["version"] == "0.9.0"]
    assert len(cores) == 1
    core = cores[0]
    assert "_rt-tokio" in nodes[core["id"]]["features"], "actual driver unit runtime is absent"
    assert any(d["pkg"] == core["id"] for d in nodes[driver["id"]]["deps"])
    sqlite = [p for p in data["packages"] if p.get("links") == "sqlite3"]
    assert len(sqlite) == 1 and sqlite[0]["name"] == "libsqlite3-sys" and sqlite[0]["version"] == "0.37.0"
    return {"status": "METADATA_IDENTITY_PASS_ONLY", "receipt": record(path),
            "driver_package_id": driver["id"], "driver_features": nodes[driver["id"]]["features"],
            "core_features": nodes[core["id"]]["features"], "sqlite_package_id": sqlite[0]["id"],
            "limits": ["No native COMMIT, close, cancellation or test has been proven by metadata.",
                       "Generated Cargo/MODULE locks and Bazel DEP_DATA/target still require their actual commands."]}


def junit_check(path, expected_path, negative):
    expected_data = json.loads(expected_path.read_text())
    expected = expected_data["exact_names"]
    assert expected and len(set(expected)) == len(expected)
    root = ET.fromstring(path.read_bytes())
    cases = list(root.iter("testcase"))
    selected = [c for c in cases if c.attrib.get("name") in expected]
    assert len(selected) == len(expected) and {c.attrib["name"] for c in selected} == set(expected)
    assert not any(c.find("skipped") is not None for c in selected), "selected test was skipped"
    unexpected_executed = [c.attrib for c in cases if c.attrib.get("name") not in expected and c.find("skipped") is None]
    assert not unexpected_executed, "unreviewed actual execution roster"
    assert not any(c.find(x) is not None for c in selected for x in ("rerunFailure", "rerunError", "flakyFailure", "flakyError")), "retry/flaky evidence is not zero-retry qualification"
    results = []
    for case in selected:
        failures = case.findall("failure") + case.findall("error")
        assert bool(failures) == negative, "unexpected selected test outcome"
        results.append({"name": case.attrib["name"], "classname": case.attrib.get("classname"),
                        "time": case.attrib.get("time"), "failure_types": [f.attrib.get("type") for f in failures],
                        "failure_messages": [f.attrib.get("message") for f in failures]})
    return {"status": "NEGATIVE_STRUCTURE_ONLY_REQUIRES_PHYSICAL_CAUSAL_REVIEW" if negative else "POSITIVE_JUNIT_STRUCTURE_PASS_ONLY",
            "receipt": record(path), "selected": results,
            "outside_selected_skipped": sum(c.find("skipped") is not None for c in cases if c not in selected),
            "limits": ["Inspect complete per-case raw/child output and actual stage/physical lock/SQLite endpoint before accepting a negative.",
                       "Source tree, freshness/run UUID, command, zero retry configuration and actual host/binary identities must be independently bound.",
                       "Passing structure does not close B16 or establish Current/Root authority."]}


parser = argparse.ArgumentParser()
parser.add_argument("--plan", type=Path, default=Path(__file__).with_name("execution-plan.json"))
parser.add_argument("--metadata", type=Path)
parser.add_argument("--repository", type=Path)
parser.add_argument("--junit", type=Path)
parser.add_argument("--expected-roster", type=Path)
parser.add_argument("--negative", action="store_true")
args = parser.parse_args()
plan = json.loads(args.plan.read_text())
if args.metadata:
    assert args.repository is not None and args.junit is None
    print(json.dumps(metadata_check(args.metadata, args.repository, plan), indent=2))
elif args.junit:
    assert args.expected_roster is not None
    print(json.dumps(junit_check(args.junit, args.expected_roster, args.negative), indent=2))
else:
    parser.error("choose one real metadata or JUnit receipt; this tool cannot run native tests")
