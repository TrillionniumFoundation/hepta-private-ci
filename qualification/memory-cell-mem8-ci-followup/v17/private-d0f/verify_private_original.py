"""Offline verification of the original d0f Windows-private evidence."""

import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

HEAD = "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
TREE = "658fa040046285116b1fd81b94ff8c96444072ad"
CASE = "circuit_cell::tests::credit_tests::signed_tests::signed_credit_rejects_cross_owner_ledger_episode_before_any_append"


def digest(data):
    return {
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_log(data, timestamps=False):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    if timestamps:
        text = re.sub(r"^\d{4}-\d\d-\d\dT[^ ]+Z ", "", text, flags=re.M)
    return text


def status_rows(text):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    return re.findall(r"^\s*(PASS|FAIL)\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$", text, re.M)


def replay(old, patch):
    lines = old.decode().splitlines(keepends=True)
    output, cursor = [], 0
    rows = patch.decode().replace("\r\n", "\n").splitlines(keepends=True)
    index = 0
    while index < len(rows):
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", rows[index])
        if not match:
            index += 1
            continue
        old_count = int(match[2]) if match[2] is not None else 1
        new_count = int(match[4]) if match[4] is not None else 1
        start = int(match[1]) if old_count == 0 else int(match[1]) - 1
        assert cursor <= start
        output.extend(lines[cursor:start])
        cursor = start
        used_old = used_new = 0
        index += 1
        while index < len(rows) and not rows[index].startswith("@@ "):
            row = rows[index]
            if row.startswith(("diff --git ", "--- ", "+++ ")):
                break
            if row.startswith(" "):
                assert lines[cursor] == row[1:]
                output.append(lines[cursor])
                cursor += 1
                used_old += 1
                used_new += 1
            elif row.startswith("-"):
                assert lines[cursor] == row[1:]
                cursor += 1
                used_old += 1
            elif row.startswith("+"):
                output.append(row[1:])
                used_new += 1
            else:
                raise AssertionError("unexpected patch row")
            index += 1
        assert (used_old, used_new) == (old_count, new_count)
    output.extend(lines[cursor:])
    return "".join(output).encode()


def verify(root):
    job = json_file(root / "original/job.json")
    run = json_file(root / "original/run.json")
    assert run["id"] == 43062473076 and run["run_attempt"] == 1
    assert run["head_sha"] == HEAD and run["status"] == "completed" and run["conclusion"] == "success"
    assert job["id"] == 130668436521 and job["run_id"] == 43062473076
    assert job["head_sha"] == HEAD and job["status"] == "completed" and job["conclusion"] == "success"
    assert any(s["name"] == "Confirm no generated or modified tracked source" and s["conclusion"] == "success" for s in job["steps"])
    raw = (root / "original/job.log").read_bytes()
    meta = json_file(root / "original/job-log-metadata.json")
    assert all(digest(raw)[key] == meta[key] for key in ("bytes", "sha256", "git_blob"))
    text = clean_log(raw, timestamps=True)
    statuses = status_rows(text)
    assert len(statuses) == 34 and len(set(statuses)) == 34
    assert all(row[0] == "PASS" for row in statuses)
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    counts = [tuple(map(int, m)) for m in re.findall(r"Summary \[[^\]]+\] (\d+) tests? run: (\d+) passed, (\d+) skipped", plain)]
    assert counts == [(15,15,5),(2,2,26),(3,3,147),(2,2,148),(11,11,260),(1,1,270)], counts
    assert not re.search(r"^\s*(RTRY|RETRY)\s", plain, re.M)

    artifacts = json_file(root / "original/artifacts.json")["artifacts"]
    assert {a["id"] for a in artifacts} == {13875243416, 13876965022}
    for artifact in artifacts:
        assert artifact["workflow_run"]["id"] == 43062473076
        assert artifact["workflow_run"]["head_sha"] == HEAD
        file = root / "original" / (str(artifact["id"]) + ".zip")
        data = file.read_bytes()
        assert len(data) == artifact["size_in_bytes"]
        assert "sha256:" + hashlib.sha256(data).hexdigest() == artifact["digest"]
        folder = root / ("credit" if artifact["id"] == 13875243416 else "acquisition")
        with zipfile.ZipFile(file) as archive:
            assert archive.testzip() is None
            for item in archive.infolist():
                assert not item.is_dir() and not item.filename.startswith("/")
                assert ".." not in Path(item.filename).parts and "\\" not in item.filename
                assert archive.read(item) == (folder / item.filename).read_bytes()

    receipt = json_file(root / "credit/credit-fixture.json")
    assert receipt["status"] == "passed" and receipt["run_id"] == "43062473076" and receipt["run_attempt"] == "1"
    assert receipt["tested_sha"] == receipt["source_sha"] == HEAD
    assert receipt["case"] == CASE
    assert receipt["before"] == receipt["after"]
    assert receipt["before"]["commit"] == HEAD and receipt["before"]["tree"] == TREE and receipt["before"]["dirty"] is False
    assert receipt["command_exit_code"] == receipt["exit_code"] == 0
    assert receipt["command"] == ["just","test","--locked","-p","codex-hepta-agentd","--lib","-E",f"test(={CASE})","--test-threads","1","--no-tests","fail","--retries","0"]
    credit = (root / "credit/credit-fixture.log").read_bytes()
    assert len(credit) == receipt["log_bytes"] and hashlib.sha256(credit).hexdigest() == receipt["log_sha256"]
    assert clean_log(credit) in text
    assert status_rows(clean_log(credit)) == [("PASS","codex-hepta-agentd",CASE)]

    manifest = json_file(root / "acquisition/manifest.json")
    assert manifest["source_head"] == HEAD and manifest["source_tree"] == TREE
    assert manifest["qualified"] is True and manifest["restored"] is True
    positive = (root / "acquisition/positive.rs").read_bytes()
    source = json_file(root / "original/production-source-readback.json")
    assert source["decoded_source"].encode() == positive
    assert HEAD in source["request_url"]
    assert all(digest(positive)[key] == source[key] for key in ("bytes","sha256","git_blob"))
    expected = {
        "positive": {"exit":0,"pass":2,"fail":0},
        "unchecked-create": {"exit":1,"pass":1,"fail":1},
        "path-check-open": {"exit":1,"pass":1,"fail":1},
    }
    controls = []
    for lane in manifest["lanes"]:
        name = lane["lane"]
        log = (root / "acquisition" / (name + ".log")).read_bytes()
        post = (root / "acquisition" / (name + ".rs")).read_bytes()
        assert hashlib.sha256(log).hexdigest() == lane["log_sha256"]
        assert hashlib.sha256(post).hexdigest() == lane["production_sha256"]
        rows = status_rows(clean_log(log))
        unique = {(package,case):status for status,package,case in rows}
        assert len(unique) == 2
        assert {case:status for (package,case),status in unique.items()} == lane["statuses"]
        actual = {"exit":lane["exit_code"],"pass":sum(x=="PASS" for x in unique.values()),"fail":sum(x=="FAIL" for x in unique.values())}
        assert actual == expected[name]
        if name != "positive":
            patch = (root / "acquisition" / (name + ".patch")).read_bytes()
            assert hashlib.sha256(patch).hexdigest() == lane["patch_sha256"]
            assert replay(positive,patch) == post
        controls.append({"lane":name,**actual,"observations":lane["observations"],"case_statuses":lane["statuses"]})

    result = {
        "source_head":HEAD,"source_tree":TREE,"run_id":43062473076,"run_attempt":1,"job_id":130668436521,
        "job_conclusion":"success","job_log":digest(raw),
        "original_unmutated_named_passes":34,"original_unmutated_unique_case_ids":34,
        "original_case_ids":[{"package":package,"case":case} for _,package,case in statuses],
        "phase_test_counts":[{"executed":n,"passed":p,"filtered_skips":s} for n,p,s in counts],
        "signed_credit":{"case":CASE,"passed":1,"failed":0,"filtered_skips":270,"retries":0,"source_before_after_clean":True,"raw_log_entirely_present_in_job":True,"raw_log":digest(credit)},
        "separate_repeated_and_counterfactual_controls":controls,
        "additional_unmutated_control_executions":2,"counterfactual_mutated_executions":4,"expected_mutation_failures":2,
        "controls_not_added_to_unique_34":True,"both_mutation_patches_replayed":True,"exact_head_positive_source_readback":digest(positive),
        "artifact_digests_crc_and_all_11_members_verified":True,
        "scope":"Original exact-head Windows private-state, prompt-runtime and signed-credit qualification only; no whole-Windows, ordinary/elevated sandbox, scientific-memory-benefit or production-owner claim.",
        "additional_execution_during_audit":False,
    }
    index = root / "MANIFEST.json"
    if index.exists():
        for item in json_file(index)["files"]:
            assert digest((root / item["path"]).read_bytes()) == {key:item[key] for key in ("bytes","sha256","git_blob")}
    return result


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent),indent=2,sort_keys=True))
