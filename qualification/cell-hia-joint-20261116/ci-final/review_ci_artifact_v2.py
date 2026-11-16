"""Inspect retained CI JSON and byte identities without executing task code."""
import argparse, hashlib, json
from pathlib import Path

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(path):
    return json.loads(path.read_bytes())

def calls(session):
    return [row["request"]["params"]["name"] for row in session["protocol"]
            if row["request"].get("method") == "tools/call"]

def lane(report, candidate_sha, label):
    assert report["status"] == "PASS", label
    assert report["candidate_sha256"] == candidate_sha, label
    assert report["actual_runtime_transport"] is True, label
    assert report["controller_cold_restart_observed"] is True, label
    assert report["no_second_process_submission"] is True, label
    first, cold = report["first_observation"], report["recovered_observation"]
    assert first == cold, label + " terminal mismatch"
    assert first["state"] == "TERMINAL" and first["runtime_state"] == "succeeded"
    assert first["exit_code"] == 0
    sessions = report["sessions"]
    assert len(sessions) == 2, label + " session count"
    first_calls, cold_calls = map(calls, sessions)
    assert first_calls.count("process_start") == 1
    assert cold_calls.count("process_start") == 0
    assert "process_status" in cold_calls and "process_read" in cold_calls
    assert sessions[0]["runtime"] == sessions[1]["runtime"]
    out = bytes.fromhex(first["streams"]["stdout"]["bytes_hex"])
    err = bytes.fromhex(first["streams"]["stderr"]["bytes_hex"])
    domain = json.loads(out)
    assert domain == report["worker_result"], label + " domain is not original stdout"
    assert domain["candidate_sha256"] == candidate_sha
    return dict(job_id=first["job_id"], exit_code=first["exit_code"],
                first_process_starts=first_calls.count("process_start"),
                cold_process_starts=cold_calls.count("process_start"),
                first_calls=first_calls, cold_calls=cold_calls,
                terminal_objects_exact=True, stdout_sha256=sha(out),
                stdout_bytes=len(out), stderr_sha256=sha(err), stderr_bytes=len(err),
                runtime_identity=sessions[0]["runtime"])

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args()
    root=args.directory.resolve(strict=True)
    report=load(root/"runtime-joint/result.json")
    candidate_raw=(root/"runtime-joint/candidate.json").read_bytes()
    candidate=json.loads(candidate_raw)
    candidate_sha=sha(candidate_raw)
    runtime=candidate["runtime_identity"]
    assert runtime["source_commit"] == "73b5c33d5762eefc0554a86750094350f18ae6a0"
    assert candidate["source_bases"]["runtime"] == runtime["source_commit"]
    assert (root/"runtime-source.txt").read_text().strip() == runtime["source_commit"]
    assert (root/"runtime-source-before.txt").read_bytes() == b""
    assert (root/"runtime-source-after.txt").read_bytes() == b""
    assert (root/"runtime-binary.sha256").read_text().split()[0] == runtime["binary_sha256"]
    origin_raw=(root/"local-joint/candidate.json").read_bytes()
    origin_sha=sha(origin_raw)
    assert candidate["origin_candidate_sha256"] == origin_sha
    assert report["origin_candidate_sha256"] == origin_sha
    assert report["runtime_identity"] == runtime
    assert report["cleanup_errors"] == []
    one=lane(report,candidate_sha,"Cell")
    campaign=load(root/"runtime-joint/campaign-runtime.json")
    assert campaign == report["maintenance"]
    two=lane(campaign,candidate_sha,"campaign")
    assert one["job_id"] != two["job_id"]
    worker=root/"runtime-joint/campaign-worker"
    assert (worker/"OUTER_CANDIDATE.json").read_bytes() == candidate_raw
    observed=load(worker/"OBSERVATION.json")
    assert observed == campaign["worker_result"]
    assert observed["runtime_identity"] == runtime
    assert observed["native_image_sha256"] == candidate["native"]["image_sha256"]
    result_raw=(worker/"campaign/RESULT.json").read_bytes()
    result=json.loads(result_raw)
    assert observed["campaign_result"] == result
    assert observed["campaign_result_sha256"] == sha(result_raw)
    assert result["status"] == "CONTROLLED_FIXTURE_COMPLETE"
    assert result["fixture_only"] is True and result["ordinary_daemon_qualification"] is False
    assert result["native_hia_enabled"] is True
    native_counts=observed["native_counts"]
    assert set(native_counts) == {"memory","predictor"}
    assert all(set(v)=={"completed"} and type(v["completed"]) is int and v["completed"]>0 for v in native_counts.values())
    original_build=(worker/"ORIGINAL_BUILD.json").read_bytes()
    assert original_build == (root/"local-joint/native/build.json").read_bytes()
    relocated=load(worker/"RELOCATED_BUILD.json")
    original=json.loads(original_build)
    assert relocated["original_build_record_sha256"] == sha(original_build)
    differences={k for k in set(original)|set(relocated) if original.get(k)!=relocated.get(k)}
    assert differences <= {"hepta_root","image_path","original_build_record_sha256","relocation_scope"}
    assert (worker/"campaign/native/build.json").read_bytes() == (worker/"RELOCATED_BUILD.json").read_bytes()
    readonly=load(root/"runtime-joint/campaign-readonly-review.json")
    assert readonly["status"] == "READ_ONLY_SNAPSHOT_CONSISTENCY_PASS"
    assert readonly["source_unchanged_verified"] is True and readonly["snapshot_unchanged_during_review"] is True
    review=readonly["review"]
    assert review["status"] == "READ_ONLY_CONSISTENCY_PASS"
    assert review["result_sha256"] == sha(result_raw)
    omitted={r["path"]:r for r in readonly["omitted_files"]}
    assert set(omitted) <= {"memory/owner.sqlite-wal","predictor/owner.sqlite-wal"}
    assert all(r["bytes"] == 0 and r["sha256"] == sha(b"") for r in omitted.values())
    retained_files=readonly["source_before"]["files"]
    for name, row in retained_files.items():
        data=(worker/"campaign"/name).read_bytes()
        assert len(data)==row["bytes"] and sha(data)==row["sha256"], name
    snapshot=readonly["snapshot_before_review"]["files"]
    assert set(snapshot)==set(retained_files)-set(omitted)
    for name, row in snapshot.items():
        data=(root/"runtime-joint/review-snapshot"/name).read_bytes()
        assert len(data)==row["bytes"] and sha(data)==row["sha256"], name
    cells={}
    for cell in ("memory","predictor"):
        source=result["cells"][cell]
        decision=source["decision"]["decision"]
        assert decision in ("Adopt","NoUpdate")
        assert review["cells"][cell]["decision"]==decision
        assert source["local_no_update_complete"] is (decision=="NoUpdate")
        assert source["cold"]["matches_pre_restart"] is True
        cells[cell]={"decision":source["decision"],"training":source["training"],
                     "C_successes":source["C_successes"],"C_denominator":source["C_denominator"],
                     "cold":source["cold"],"local_no_update_complete":source["local_no_update_complete"],
                     "readonly_review":review["cells"][cell]}
    handoff={"schema":"hepta.cell.linux-ci-retained-evidence-review.v1","status":"PASS",
             "head_sha":"f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb","run_id":43802821002,
             "candidate_sha256":candidate_sha,"origin_candidate_sha256":origin_sha,
             "runtime_identity":runtime,"native_image_sha256":candidate["native"]["image_sha256"],
             "cell_lane":one,"campaign_lane":two,"native_counts":native_counts,
             "campaign_result_sha256":sha(result_raw),"cells":cells,
             "whole_campaign_cost":{k:result[k] for k in ("wall_seconds","parent_cpu_seconds","energy_joules","peak_rss_bytes","compile_calls","cost_scope")},
             "read_only_snapshot":{"source_files_verified":len(retained_files),"snapshot_files_verified":len(snapshot),"omitted_empty_wals":sorted(omitted),"source_unchanged":True},
             "original_build_sha256":sha(original_build),"relocated_build_sha256":sha((worker/"RELOCATED_BUILD.json").read_bytes()),
             "ordinary_daemon_qualification":False,"model_native_runtime_reexecution":False,
             "separate_from_original_mac_candidate":candidate_sha!="2a8e8759c7e1941f184fde2463a13a9d39dfa9edcf00c8a5ae475ad81dd3b469"}
    args.output.open("x").write(json.dumps(handoff,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":"PASS","candidate_sha256":candidate_sha,"origin_candidate_sha256":origin_sha,"jobs":[one["job_id"],two["job_id"]],"native_counts":native_counts,"decisions":{k:v["decision"]["decision"] for k,v in cells.items()}},sort_keys=True))
if __name__=="__main__":
    main()
