#!/usr/bin/env python3
"""Replay original controls and retained real BEP; no Bazel/product/native execution."""
import collections
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest.mock
from urllib.parse import unquote, urlsplit, urlunsplit
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def ident(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

new = module("revised_collector", ROOT / "collect_attempts.py")
old = module("original_collector", ROOT / "preimage/collect_attempts.py")
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    fixtures = module("original_36", ROOT / "verify_original_36_fixtures.py")
original_stdout = captured.getvalue().encode()
assert original_stdout == (ROOT / "original-36.expected.stdout.json").read_bytes()
assert len(fixtures.RESULTS) == 36 and all(x["passed"] for x in fixtures.RESULTS)
# Original fixture module loaded the exact same revised source.
assert Path(fixtures.collector.__file__).read_bytes() == (ROOT / "collect_attempts.py").read_bytes()

results = {
    "schema": "fetch-xml-regression-v1",
    "scope": "Offline evidence parser/privacy and synthetic controls only; no new native execution.",
    "candidate_collector": ident((ROOT / "collect_attempts.py").read_bytes()),
    "original_36": {"all_passed": True, "stdout_byte_equal_to_frozen_baseline": True,
                    "stdout": ident(original_stdout)},
    "real_bep": [], "new_controls": [], "original_privacy_regressions": [],
}

source_map = json.loads((ROOT / "real-inputs/source-map.json").read_bytes())
real_pairs = []
regex = json.loads((ROOT / "candidate-identities.json").read_bytes())["remote_download_regex"]
pattern = re.compile(regex)
for label, want_missing, want_duplicates, want_attempts in [
    ("b21", 131, 1, 499), ("b23", 8, 2, 8),
]:
    root = ROOT / "real-inputs" / label
    for record in source_map[label]["members"]:
        path = ROOT / record["path"]
        assert path.resolve().is_relative_to(root.resolve())
        assert ident(path.read_bytes()) == {k: record[k] for k in ["bytes", "sha256", "git_blob"]}
    original_manifest = json.loads((root / "attempt-retention-manifest.json").read_bytes())
    original_bep_bytes = (root / new.DERIVED_NAME).read_bytes()
    original_events = [json.loads(line) for line in original_bep_bytes.splitlines()]
    events = copy.deepcopy(original_events)
    original_root = Path(original_manifest["resolved_testlogs_root"])
    local_root = (root / "all-testlogs").resolve()
    inventory = {row["relative_path"]: row for row in original_manifest["files"]}
    for relative, row in inventory.items():
        data = (local_root / relative).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    rebased = []
    def rebase(value, parts=()):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "uri" and isinstance(item, str):
                    uri = urlsplit(item)
                    if uri.scheme == "file" and uri.netloc in ("", "localhost"):
                        path = Path(unquote(uri.path))
                        if path.is_relative_to(original_root):
                            relative = path.relative_to(original_root)
                            candidate = urlsplit((local_root / relative).as_uri())
                            value[key] = urlunsplit((candidate.scheme, uri.netloc,
                                                     candidate.path, uri.query, uri.fragment))
                            rebased.append(list(parts + (key,)))
                else:
                    rebase(item, parts + (key,))
        elif isinstance(value, list):
            for i,item in enumerate(value):
                rebase(item, parts + (i,))
    rebase(events)
    # Rebase only local URI strings; byte-authoritative originals remain unchanged.
    def restore(value, original):
        if isinstance(value, dict):
            for key in value:
                if key == "uri" and isinstance(value[key], str):
                    value[key] = original[key]
                else:
                    restore(value[key], original[key])
        elif isinstance(value, list):
            for left,right in zip(value, original):
                restore(left,right)
    reverted = copy.deepcopy(events);restore(reverted, original_events)
    assert reverted == original_events

    before_errors, after_errors = [], []
    before = old.reconcile(events, local_root, inventory, original_manifest["expected_target"],
                           original_manifest["original_bazel_exit"], before_errors)
    after = new.reconcile(events, local_root, inventory, original_manifest["expected_target"],
                          original_manifest["original_bazel_exit"], after_errors)
    assert before == after[:2]
    assert before_errors == original_manifest["errors"]
    assert after_errors == [x for x in before_errors if x["kind"] != "duplicate_event_id"]
    assert collections.Counter(x["kind"] for x in after_errors) == {
        "attempt_reference_unavailable": want_missing}
    assert len(after[0]) == want_attempts
    assert len(after[2]) == want_duplicates
    for row in after[2]:
        first, current = original_events[row["first_event"]], original_events[row["event"]]
        assert row["id"] == first["id"] == current["id"]
        assert row["first_payload"] == first["fetch"] and row["payload"] == current["fetch"]
        assert row["payload_equal_to_first"] == (first["fetch"] == current["fetch"])
        real_pairs.append((label, row["first_event"], row["event"], first, current))
    for error in after_errors:
        event = events[error["event"]]
        output = event["testResult"]["testActionOutput"][error["output"]]
        assert output["name"] == "test.xml"
        p = Path(unquote(urlsplit(output["uri"]).path))
        assert not p.exists(), "A missing original XML must not be synthesized"
    matched = []
    for event in original_events:
        for output in event.get("testResult", {}).get("testActionOutput", []):
            if output.get("name") not in ("test.log", "test.xml"):
                continue
            path = unquote(urlsplit(output["uri"]).path)
            assert "/execroot/_main/" in path
            execpath = path.split("/execroot/_main/", 1)[1]
            assert pattern.fullmatch(execpath), execpath
            matched.append(execpath)
    assert (root / new.DERIVED_NAME).read_bytes() == original_bep_bytes
    results["real_bep"].append({
        "source": label, "original_events": len(events), "original_derived_bep": ident(original_bep_bytes),
        "original_zip_sha256": source_map[label]["official_zip"]["sha256"],
        "retained_original_files": len(inventory), "validated_file_bytes": sum(x["bytes"] for x in inventory.values()),
        "actual_attempts": len(after[0]), "actual_attempt_status_counts": dict(collections.Counter(a["status"] for a in after[0])),
        "original_bazel_exit": original_manifest["original_bazel_exit"],
        "before_errors": dict(collections.Counter(x["kind"] for x in before_errors)),
        "after_errors": dict(collections.Counter(x["kind"] for x in after_errors)),
        "complete_after": not after_errors, "repeated_fetch_events": after[2],
        "test_attempts_and_summaries_identical": True,
        "local_uri_rebase_count": len(rebased),
        "only_local_URI_location_rebased_in_memory": True,
        "every_missing_XML_still_physically_absent": True,
        "all_actual_log_xml_execpaths_match_download_regex": True,
        "matched_reference_count": len(matched),
    })

def control(name, change, expected_complete, inspect):
    with tempfile.TemporaryDirectory(prefix="fetch-xml-synthetic-") as temporary:
        f = fixtures.Fixture(Path(temporary));change(f)
        before = copy.deepcopy(f.events)
        m,g = f.run()
        assert m["complete"] is expected_complete, (name,m["errors"])
        assert g["safe_for_upload"] is True, (name,g)
        inspect(f,m)
        assert f.events == before
        results["new_controls"].append({
            "case": name, "complete": m["complete"], "safe_for_upload": g["safe_for_upload"],
            "error_kinds": sorted(set(e["kind"] for e in m["errors"])),
            "repeated_fetches": len(m["repeated_fetch_events"]), "passed": True,
        })

def pair_mutator(first, current):
    def mutate(f):
        f.events[2:2] = [copy.deepcopy(first),copy.deepcopy(current)]
    return mutate

def inspect_pair(f, m):
    assert len(m["repeated_fetch_events"]) == 1
    row = m["repeated_fetch_events"][0]
    assert row["first_event"] == 2 and row["event"] == 3
    assert row["first_payload"] == f.events[2]["fetch"] and row["payload"] == f.events[3]["fetch"]
    derived = [json.loads(line) for line in f.derived().splitlines()]
    assert derived[2] == f.events[2] and derived[3] == f.events[3]
    assert [x["status"] for x in m["actual_attempts"]] == ["FAILED","PASSED"]

for label, first_index, current_index, first,current in real_pairs:
    control("real_fetch_pair_" + label + "_" + str(first_index) + "_" + str(current_index),
            pair_mutator(first,current), True, inspect_pair)

first,current = copy.deepcopy(real_pairs[0][3]), copy.deepcopy(real_pairs[0][4])
current["fetch"]["success"] = False
def inspect_distinct(f,m):
    inspect_pair(f,m)
    row=m["repeated_fetch_events"][0]
    assert row["payload_equal_to_first"] is False and row["payload"]["success"] is False
control("same_fetch_id_distinct_payload_both_retained",pair_mutator(first,current),True,inspect_distinct)

def missing_xml(f):
    pair_mutator(first,current)(f)
    f.paths[1].unlink()
control("fetch_fix_never_waives_missing_xml", missing_xml, False,
        lambda f,m: (_ for _ in ()).throw(AssertionError()) if
        not any(e["kind"]=="attempt_reference_unavailable" for e in m["errors"]) else None)

def require_error(kind):
    def inspect(f,m):
        assert any(e["kind"]==kind for e in m["errors"])
    return inspect
def duplicate_summary(f):f.events.insert(-1,copy.deepcopy(f.events[-2]))
control("duplicate_test_summary_still_fails",duplicate_summary,False,require_error("duplicate_test_summary"))
def duplicate_attempt(f):f.events.insert(3,copy.deepcopy(f.events[2]))
control("duplicate_test_result_still_fails",duplicate_attempt,False,require_error("duplicate_event_id"))
def duplicate_other(f):f.events.insert(2,copy.deepcopy(f.events[1]))
control("duplicate_nonfetch_id_still_fails",duplicate_other,False,require_error("duplicate_event_id"))
def malformed_fetch(f):
    a,b=copy.deepcopy(first),copy.deepcopy(current);b["testResult"]={}
    f.events[2:2]=[a,b]
control("fetch_with_second_payload_not_exempted",malformed_fetch,False,require_error("duplicate_event_id"))

# Replay the exact independently frozen privacy counterexample files.
privacy = ROOT / "privacy-originals"
fake = "SYNTHETIC_BUILDBUDDY_TOKEN_ALPHA_0123456789_ONLY_FAKE_MATERIAL"
policy = new.SecretPolicy(fake)
for case in ("counterexample-boundary", "counterexample-zstd"):
    folder = privacy / "b21-collector-draft-v1" / case
    paths = [p for p in folder.rglob("*") if p.is_file()]
    before = {str(p.relative_to(folder)):ident(p.read_bytes()) for p in paths}
    gate = new.privacy_gate((folder/"public", folder/"execution-logs"), policy)
    after = {str(p.relative_to(folder)):ident(p.read_bytes()) for p in paths}
    assert before == after and gate["safe_for_upload"] is False
    assert any(e.get("error_code")=="known_credential_in_bytes" for e in gate["errors"])
    results["original_privacy_regressions"].append({"case":case,"safe":False,"inputs":before,"passed":True})
frames = [
    ("single_frame",True),("two_concatenated_frames",True),
    ("truncated_single_frame",False),("truncated_second_frame",False),
    ("trailing_unknown_bytes",False),("empty_input",False),
    ("unknown_format",False),("checksum_mismatch",False),
]
with tempfile.TemporaryDirectory(prefix="fetch-xml-original-privacy-") as temporary:
    base=Path(temporary);public=base/"public";logs=base/"execution-logs"
    public.mkdir();logs.mkdir()
    path=logs/"execution-log-test.zst"
    for name,expected in frames:
        data=(privacy/"zstd-1.5.7-cli"/(name+".zst")).read_bytes()
        path.write_bytes(data)
        gate=new.privacy_gate((public,logs),policy)
        assert gate["safe_for_upload"] is expected and path.read_bytes()==data
        results["original_privacy_regressions"].append({
            "case":name,"safe":expected,"input":ident(data),"passed":True})
    with unittest.mock.patch.object(new.shutil,"which",return_value=None):
        gate=new.privacy_gate((public,logs),policy)
    assert gate["safe_for_upload"] is False
    assert any(e.get("error_code")=="zstd_decoder_missing" for e in gate["errors"])
    results["original_privacy_regressions"].append({"case":"decoder_missing","safe":False,"passed":True})
for i,flag in enumerate(sorted(new.HEADERS)):
    unknown="SYNTHETIC_OTHER_BEARER_"+str(i)
    payload={"progress":{"stderr":"before --"+flag+"=Authorization=Bearer "+unknown+" after"},
             "rawStrings":["--"+flag,"Authorization=Bearer "+unknown]}
    clean=new.Sanitizer(policy).clean(payload)
    assert unknown not in json.dumps(clean) and clean["rawStrings"][1]==new.MARK
results["five_unknown_space_bearer_header_controls_passed"]=True

# The regex is bounded to test-log/XML names, not all remote build products.
for path in [
    "bazel-out/rbe-fastbuild/bin/codex-rs/core/core-all-test",
    "bazel-out/rbe-fastbuild/testlogs/x/test.cache_status",
    "bazel-out/rbe-fastbuild/testlogs/x/test_attempts/attempt_1.xml.extra",
    "bazel-out/rbe-fastbuild/testlogs/x/test_outputs.zip",
    "external/repository/test.xml", "/bazel-out/rbe-fastbuild/testlogs/x/test.xml",
]:
    assert pattern.fullmatch(path) is None,path
results["download_regex_scope_controls_passed"]=True
results["all_checks_passed"]=True
print(json.dumps(results,indent=2,sort_keys=True))
