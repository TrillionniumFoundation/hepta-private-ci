import collections
import datetime
import gzip
import hashlib
import io
import json
import pathlib
import re
import xml.etree.ElementTree as ET
import zipfile

SOURCE = "30a697c50e10abd56e61b6b84f28ac9ae9f32f5d"
TREE = "b2a21d98380340b1c091006f4130aafdbeabca50"
ROOT = pathlib.Path("/workspace/scratch/f7c0ded86bcc")
DELIVERY = ROOT / "p0-ci-audit/shared-30a697c-readback"
DEST = ROOT / "hepta-p0-converged/qualification/cell-p0-converged-20261110-f7c0/shared-30a"


def digest(data):
    return hashlib.sha256(data).hexdigest()


raw = (DELIVERY / "shared-30a697c-raw-bundle.zip").read_bytes()
assert len(raw) == 247921
assert digest(raw) == "5d2eb4996755b5de6967d7c00c1658824deb46c1e2068788d7503fe0ff87f54e"
with zipfile.ZipFile(io.BytesIO(raw)) as outer:
    assert outer.testzip() is None
    manifest = json.loads(outer.read("MANIFEST.json"))
    assert set(outer.namelist()) == set(manifest["files"]) | {"MANIFEST.json"}
    for name, record in manifest["files"].items():
        data = outer.read(name)
        assert len(data) == record["bytes"] and digest(data) == record["sha256"]
    summary_bytes = outer.read("SUMMARY.json")
    summary = json.loads(summary_bytes)
    original = outer.read("original-artifact-13826946544.zip")
    assert original == (DELIVERY / "original-artifact-13826946544.zip").read_bytes()
    index = json.loads(outer.read("ORIGINAL_MEMBER_INDEX.json"))
    assert digest(original) == index["original_sha256"]
    job_log = gzip.decompress(outer.read("job-130295511508.log.gz"))
    assert job_log == (DELIVERY / "job-130295511508.decoded.log").read_bytes()
    assert len(job_log) == 345635
    assert digest(job_log) == "9dbea5e2f5aee5a4c1f73a2e04de296e9dabdb621cd455aeba587c420db1f6b7"
    api = json.loads(gzip.decompress(outer.read("API_CAPTURE.json.gz")))
    assert api["run"]["id"] == 42951157663
    assert api["run"]["head_sha"] == SOURCE and api["run"]["conclusion"] == "success"
    job = next(x for x in api["jobs"]["jobs"] if x["id"] == 130295511508)
    assert job["run_id"] == api["run"]["id"] and job["conclusion"] == "success"
    artifact = next(x for x in api["artifacts"]["artifacts"] if x["id"] == 13826946544)
    assert artifact["digest"] == "sha256:" + digest(original)
    with zipfile.ZipFile(io.BytesIO(original)) as inner:
        assert inner.testzip() is None
        assert len(inner.namelist()) == 14 and set(inner.namelist()) == set(index["members"])
        for name, record in index["members"].items():
            data = inner.read(name)
            assert len(data) == record["bytes"] and digest(data) == record["sha256"]
        assert inner.read("source.txt") == inner.read("source-after.txt") == f"{SOURCE}\n{TREE}\n".encode()
        execution = json.loads(inner.read("tests.json"))
        assert execution["source_sha"] == execution["tested_sha"] == SOURCE
        assert execution["exit_code"] == execution["command_exit_code"] == 0
        for side in ("before", "after"):
            assert execution[side]["commit"] == SOURCE and execution[side]["tree"] == TREE
            assert execution[side]["dirty"] is False
        native_raw = inner.read(execution["log_file"])
        assert digest(native_raw) == execution["log_sha256"]
        native = re.sub(r"\x1b\[[0-9;]*m", "", native_raw.decode())
        xml = inner.read("junit.xml")
        assert len(xml) == 281628 and digest(xml) == "6ecdb5db415f37e95819eb8738b8a9fbbf0449f656e896f541c6789ea5365e0e"
        cases = list(ET.fromstring(xml).iter("testcase"))
        keys = [(case.attrib["classname"], case.attrib["name"]) for case in cases]
        assert len(cases) == len(set(keys)) == 1190
        assert not any(any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases)
        counts = dict(collections.Counter(key[0] for key in keys))
        assert counts == {"codex-hepta-agentd": 890, "codex-hepta-automation": 85, "codex-hepta-neuron": 215}
        assert summary["native"]["summary_line"] in native
        verified_training = []
        for row in summary["training_stage_actual_cases"]:
            selected = [case for case in cases if case.attrib["name"] == row["full_name"]]
            assert len(selected) == 1
            assert selected[0].attrib["classname"] == row["classname"]
            assert float(selected[0].attrib["time"]) == row["junit_time_seconds"]
            assert native.splitlines().count(row["original_nextest_pass_line"]) == 1
            assert row["original_nextest_pass_line"].strip() in re.sub(r"\x1b\[[0-9;]*m", "", job_log.decode())
            verified_training.append(row["case"])
        assert len(verified_training) == len(set(verified_training)) == 6
        gate = json.loads(inner.read("execution-gate-tests.json"))
        gate_raw = inner.read(gate["log_file"])
        assert digest(gate_raw) == gate["log_sha256"]
        assert len(re.findall(r"^test_.* \.\.\. ok$", gate_raw.decode(), re.M)) == 15
        assert "Ran 15 tests in 3.073s" in gate_raw.decode()
        helper = json.loads(inner.read("helpers/manifest.json"))
        after = json.loads(inner.read("helpers-after.json"))
        assert helper["source_sha"] == helper["source_sha_after"] == SOURCE
        assert helper["source_status_before"] == helper["source_status_after"] == ""
        messages = [json.loads(line) for line in inner.read("helpers/codex-hepta-infer-worker-host.jsonl").splitlines() if line]
        assert len(messages) == 1303
        assert messages[-1]["reason"] == "build-finished" and messages[-1]["success"] is True
        helper_item = helper["artifacts"]["hepta-joint-propose"]
        assert any(m.get("reason") == "compiler-artifact" and m.get("executable") == helper_item["compiler_executable"] for m in messages)
        post = after["artifacts"]["hepta-joint-propose"]
        assert post["match"] is True and post["sha256"] == helper_item["sha256"] and post["bytes"] == helper_item["bytes"]
        for side in ("source_before", "source_after"):
            assert after[side] == {"head": SOURCE, "tree": TREE, "status": ""}

DEST.mkdir(parents=True, exist_ok=True)
(DEST / "RAW_BUNDLE.zip").write_bytes(raw)
(DEST / "SUMMARY.json").write_bytes(summary_bytes)
result = {
    "schema": "hepta.p0.root-shared-readback-verification.v1",
    "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_sha": SOURCE,
    "source_tree": TREE,
    "bundle_sha256": digest(raw),
    "outer_manifest_members_verified": 5,
    "complete_original_members_verified": 14,
    "full_job_log_roundtrip_verified": True,
    "original_api_run_job_and_artifact_digest_verified": True,
    "actual_unique_junit_cases": len(cases),
    "cases_by_binary": counts,
    "failure_error_or_xml_skips": 0,
    "nextest_excluded_or_ignored": 71,
    "training_cases_each_once_in_original_junit_and_nextest": verified_training,
    "python_gate_cases_separate": 15,
    "source_before_after_clean": True,
    "full_source_inventory_present": False,
    "helper_build_jsonl_and_verify_only_binding_verified": True,
    "helper_binary_independently_downloaded": False,
    "command_wall_seconds": execution["elapsed_seconds"],
    "test_wall_seconds": 227.579,
    "cpu_seconds": None,
    "peak_rss_bytes": None,
    "independent_scientific_tasks_added": 0,
    "full_p0_qualification": False,
    "other_source_or_dependency_suites_qualified": False,
}
(DEST / "ROOT_VERIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
