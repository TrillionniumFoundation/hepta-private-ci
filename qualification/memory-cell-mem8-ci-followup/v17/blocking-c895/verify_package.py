"""Verify the complete retained c895 blocking packet offline; no native work."""
import collections
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
SOURCE="c89540598693697577cda8cba31cb07f6ce65317"
TREE="5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"
MERGE="f0a379f3ae78e6cb01abcc6ac6458bacef23997b"
RUN=43048568477


def pin(data):
    return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()}


def complete_tree_sha(data):
    root={}
    names=set()
    assert data.endswith(b"\0")
    for entry in data[:-1].split(b"\0"):
        header,name=entry.split(b"\t",1)
        mode,kind,digest=header.split()
        assert kind==b"blob" and mode in (b"100644",b"100755",b"120000")
        assert name not in names
        names.add(name)
        node=root
        components=name.split(b"/")
        for part in components[:-1]:node=node.setdefault(part,{})
        assert components[-1] not in node
        node[components[-1]]=(mode,bytes.fromhex(digest.decode()))
    def visit(node):
        content=b""
        for name,value in sorted(node.items(),key=lambda pair:pair[0]+(b"/" if isinstance(pair[1],dict) else b"")):
            mode,sha=(b"40000",visit(value)) if isinstance(value,dict) else value
            content+=mode+b" "+name+b"\0"+sha
        return hashlib.sha1(b"tree "+str(len(content)).encode()+b"\0"+content).digest()
    return len(names),visit(root).hex()


def main():
    manifest=json.loads((ROOT/"FILE_MANIFEST.json").read_bytes())
    rows=manifest["members"]
    assert len(rows)==len({r["path"] for r in rows})
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    assert actual=={r["path"] for r in rows}|{"FILE_MANIFEST.json"}
    for row in rows:
        relative=PurePosixPath(row["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        path=ROOT/row["path"]
        assert path.is_file() and not path.is_symlink()
        assert pin(path.read_bytes())=={k:row[k] for k in ("bytes","sha256","git_blob")}
    run=json.loads((ROOT/"RUN_TERMINAL.json").read_bytes())
    jobs=json.loads((ROOT/"JOBS_TERMINAL.json").read_bytes())
    assert run["id"]==RUN and run["run_attempt"]==1 and run["event"]=="pull_request"
    assert run["head_sha"]==SOURCE and run["status"]=="completed" and run["conclusion"]=="failure"
    assert jobs["total_count"]==len(jobs["jobs"])==37
    by_id={j["id"]:j for j in jobs["jobs"]}
    assert len(by_id)==37
    assert all(j["run_id"]==RUN and j["run_attempt"]==1 and j["head_sha"]==SOURCE and j["status"]=="completed" for j in by_id.values())
    counts=dict(collections.Counter(j["conclusion"] for j in by_id.values()))
    assert counts=={"success":20,"failure":9,"cancelled":4,"skipped":4}
    summary=json.loads((ROOT/"QUALIFICATION_SUMMARY.json").read_bytes())
    assert (summary["source_head"],summary["tested_merge"],summary["tested_tree"])==(SOURCE,MERGE,TREE)
    assert summary["job_counts"]==counts and summary["run_updated_at"]==run["updated_at"]
    source=json.loads((ROOT/"SOURCE_COMMIT.json").read_bytes())
    merge=json.loads((ROOT/"WORKFLOW_MERGE_COMMIT.json").read_bytes())
    assert source["sha"]==SOURCE and source["tree"]["sha"]==TREE
    assert merge["sha"]==MERGE and merge["tree"]["sha"]==TREE
    assert [p["sha"] for p in merge["parents"]]==["96038ccf0660154fac143ba6cbe4be81e00813e8",SOURCE]
    assert complete_tree_sha((ROOT/"SOURCE_TREE.ls-tree").read_bytes())==(14053,TREE)
    inventory=json.loads((ROOT/"RAW_LOG_INVENTORY.json").read_bytes())
    assert len(inventory)==len({r["job_id"] for r in inventory})==17
    for row in inventory:
        assert pin((ROOT/row["path"]).read_bytes())=={k:row[k] for k in ("bytes","sha256","git_blob")}
        job=json.loads((ROOT/f'job-metadata/{row["job_id"]}.json').read_bytes())
        assert job==by_id[row["job_id"]] and row["conclusion"]==job["conclusion"]
    assert by_id[130619379892]["conclusion"]=="success"
    for suffix in ("", "_2"):
        failure=json.loads((ROOT/f"job-130619379892-READ_FAILURE{suffix}.json").read_bytes())
        assert failure["isError"] is True and "Transport closed" in json.dumps(failure)
    assert all(j["runner_id"]==0 and j["steps"]==[] for j in by_id.values() if j["conclusion"]=="cancelled")
    artifacts=json.loads((ROOT/"ARTIFACT_METADATA_TERMINAL.json").read_bytes())["artifacts"]
    assert len(artifacts)==len({a["id"] for a in artifacts})==11
    assert all(a["workflow_run"]["id"]==RUN and a["workflow_run"]["head_sha"]==SOURCE for a in artifacts)
    assert any(a["id"]==13872750986 and a["size_in_bytes"]==10571840 and a["digest"]=="sha256:d55ff9a4a35784ce1055951140b95e6b3a5e9fe01d7bb092aa1feac191804324" for a in artifacts)
    result=subprocess.run([sys.executable,str(ROOT/"audit_bazel_terminal.py")],cwd=ROOT,capture_output=True,timeout=30,
                          env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
    assert result.returncode==0,result.stderr.decode()
    audit=json.loads(result.stdout)
    assert audit==json.loads((ROOT/"BAZEL_TERMINAL_AUDIT.json").read_bytes())
    assert len(audit["results"])==7
    mac=next(r for r in audit["results"] if r["job_id"]==130619380498)
    assert mac["target_outcomes"]=={"PASSED":402,"FLAKY":3,"FAILED":4,"TIMEOUT":3,"SKIPPED":172}
    assert sum(r["outcome"]=="PASSED" and r["cache_state"]=="fully_cached" for r in mac["target_rows"])==381
    assert len(mac["original_blocks"])==17
    core=next(r for r in mac["target_rows"] if r["label"]=="//codex-rs/core:core-all-test")
    assert core["reported_attempts"]=={"failed":16,"total":28} and len(core["printed_failure_log_paths"])==16
    assert sum("//codex-rs/core:core-all-test " in b["header"] for b in mac["original_blocks"])==7
    required=(ROOT/"job-130654241277.log").read_text(encoding="utf-8-sig")
    needs=json.JSONDecoder().raw_decode(required.split("  NEEDS: ",1)[1])[0]
    assert needs==summary["final_required"]["original_needs"]
    assert "CI gate rejected: invalid or absent CI result: bazel" in required
    print(json.dumps({"status":"PASS","outer_regular_members":len(actual),"original_run_id":RUN,"original_attempt":1,
                      "original_jobs":37,"job_counts":counts,"complete_original_job_raw_logs":17,
                      "test_job_records_replayed":7,"mac_complete_raw_present":True,"mac_target_outcomes":mac["target_outcomes"],
                      "mac_core_all_reported_failed_attempts":16,"mac_core_all_displayed_attempt_bodies":7,
                      "complete_source_tree_entries":14053,"cargo_deny_full_raw_gap_retained":True,
                      "eleven_bazel_artifacts_metadata_only":True,"no_native_or_model_execution":True},sort_keys=True))


if __name__=="__main__":main()
