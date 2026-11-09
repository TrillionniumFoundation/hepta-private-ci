#!/usr/bin/env python3
"""Independently verify the completed source-publication archive without executing archived code."""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
import hashlib,json,stat,tarfile
if not __debug__:raise RuntimeError("Evidence assertions must remain enabled")
R=Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
PACKET="core-output-6ec5993-quiet-source-publication-history-v1"
P=R/PACKET
OUT=R/"core-output-6ec5993-source-publication-history-independent-verification-v2"
def sha(b):return hashlib.sha256(b).hexdigest()
def capture(p):
    assert p.resolve()==p and p.is_relative_to(R)
    a=p.lstat();assert stat.S_ISREG(a.st_mode) and a.st_nlink==1
    b=p.read_bytes();z=p.lstat()
    for k in ("st_dev","st_ino","st_mode","st_size","st_mtime_ns","st_ctime_ns"):assert getattr(a,k)==getattr(z,k)
    return b,{"bytes":len(b),"sha256":sha(b),"mode":stat.S_IMODE(a.st_mode),"device":a.st_dev,"inode":a.st_ino,"mtime_ns":a.st_mtime_ns,"ctime_ns":a.st_ctime_ns}
def main():
    started=datetime.now(timezone.utc).isoformat();OUT.mkdir(exist_ok=False)
    rb,rp=capture(P/"RESULT.json");result=json.loads(rb)
    assert result["status"]=="SEALED_SOURCE_PUBLICATION_HISTORY_ALL_ORIGINALS_AND_MEMBERS_VERIFIED" and result["returncode"]==0
    assert result["packet_id"]==PACKET and result["native_tests"]==result["new_pushes_by_sealer"]==0
    inputs={str(P/"RESULT.json"):rp};values={}
    for key in ("archive","manifest","scope","observations"):
        pin=result[key];p=Path(pin["path"]);assert p.parent==P
        data,state=capture(p);assert state["bytes"]==pin["bytes"] and state["sha256"]==pin["sha256"]
        inputs[str(p)]=state;values[key]=data
    assert result["archive"]["bytes"]==1547100 and result["archive"]["sha256"]=="e11d190b31472cbc00582a4728a6073dfeda4d5a235b39527d6524df7c23699d"
    manifest=json.loads(values["manifest"]);scope=json.loads(values["scope"]);obs=json.loads(values["observations"])
    assert manifest["file_member_count"]==439 and manifest["manifest_is_external_to_archive"] is True
    expected={row["path"]:row for row in manifest["files"]};assert len(expected)==len(manifest["files"])==439
    contents={}
    with tarfile.open(result["archive"]["path"],"r:xz") as t:
        ms=t.getmembers();assert len(ms)==len({m.name for m in ms})==439 and {m.name for m in ms}==set(expected)
        for m in ms:
            q=PurePosixPath(m.name);assert not q.is_absolute() and ".." not in q.parts and m.isfile()
            row=expected[m.name];assert m.size==row["bytes"] and m.mode==row["mode"] and not m.mode&0o111
            b=t.extractfile(m).read();assert len(b)==row["bytes"] and sha(b)==row["sha256"]
            contents[m.name]=b
    assert contents["metadata/SCOPE.json"]==values["scope"] and contents["metadata/OBSERVATIONS.json"]==values["observations"]
    before=json.loads(contents["metadata/INPUTS_BEFORE.json"]);after=json.loads(contents["metadata/INPUTS_AFTER_BEFORE_ARCHIVE.json"])
    assert before==after and len(before)==433 and len({x["relative_path"] for x in before})==433
    expected_paths={"originals/"+x["relative_path"] for x in before}|{"metadata/"+x for x in ("sealer.py","DISCOVERY-original.json","SCOPE.json","OBSERVATIONS.json","INPUTS_BEFORE.json","INPUTS_AFTER_BEFORE_ARCHIVE.json")}
    assert expected_paths==set(contents)
    for row in before:
        path=R/row["relative_path"];assert "target-ci-test" not in str(path) and "/helpers/bin/" not in str(path)
        b,state=capture(path)
        for k in state:assert state[k]==row[k],(path,k)
        assert b==contents["originals/"+row["relative_path"]]
    assert scope["source_sha"]==result["source_sha"]==obs["source_sha"]=="6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"
    assert scope["source_tree"]==result["source_tree"]=="b0ddbe6b6f83dc42657260b266774f79c9d1ed90"
    assert scope["original_file_count"]==433 and scope["actual_normal_push_count"]==1
    assert scope["source_parent"]=="45a50bffd1631d502889069fc3f713b8a5e775d8"
    assert scope["source_publication_is_reviewability_only"] is True and scope["common_or_PR_head_advanced"] is False
    assert scope["original_appserver_FAIL_and_workspace_v1_pre_native_controller_FAIL_preserved"] is True
    assert scope["workspace_v2_result_not_read_or_inferred"] is True
    assert obs["normal_push_count"]==1 and obs["command_count"]==93
    assert len(obs["original17_same_source_validation_observations"])==17
    pub=json.loads(contents["originals/core-output-6ec-quiet-source-publication-v1/RESULT.json"])
    cmds=json.loads(contents["originals/core-output-6ec-quiet-source-publication-v1/commands.json"])
    assert len(cmds)==93 and all(type(c["returncode"]) is int and c["returncode"]==0 for c in cmds)
    assert pub["normal_push_attempt_count"]==1 and pub["native_tests_executed_by_publisher"] is False
    assert pub["source_sha"]==scope["source_sha"] and pub["source_tree"]==scope["source_tree"]
    assert pub["actions_observation"]["complete_pagination"] is True and pub["actions_observation"]["total_count"]==0
    assert scope["actions0_is_not_CI_success"] is True and obs["no_future_absence_or_CI_success_inferred"] is True
    nul={x["relative_path"]:x for x in before if x["nul_delimited_git_producer"] is not None}
    assert len(nul)==scope["raw_git_stdout_with_NUL_preserved"]==13
    for rel,row in nul.items():
        b=contents["originals/"+rel];p=row["nul_delimited_git_producer"]
        assert b"\0" in b and b.endswith(b"\0") and p["argv"][0]=="git" and "-z" in p["argv"]
        assert p["stdout"]=={"bytes":len(b),"sha256":sha(b)}
        commands_rel=str(Path(p["commands_path"]).relative_to(R))
        original_cmds=json.loads(contents["originals/"+commands_rel])
        matches=[c for c in original_cmds if c["label"]==p["command_label"]]
        assert len(matches)==1 and matches[0]["argv"]==p["argv"] and matches[0]["stdout"]==p["stdout"]
    assert {rel.removeprefix("originals/") for rel,b in contents.items() if b"\0" in b}==set(nul)
    assert all(v=="HOLD" for v in scope["stages"].values())
    assert scope["full_history_cost"] is scope["physical_cost"] is None and scope["scientific_acceptance"] is False
    for path,pin in inputs.items():assert capture(Path(path))[1]==pin
    answer={"status":"INDEPENDENT_SOURCE_PUBLICATION_ARCHIVE_AND_ORIGINAL_RECORDS_VERIFIED","returncode":0,"packet_id":PACKET,
      "started_at":started,"finished_at":datetime.now(timezone.utc).isoformat(),"source_sha":scope["source_sha"],"source_tree":scope["source_tree"],
      "archive":result["archive"],"manifest":result["manifest"],"scope":result["scope"],
      "file_members":439,"original_file_count":433,"all_archive_bytes_mode_sha_verified":True,
      "original_and_generated_records_unchanged":True,"source_publication_is_reviewability_only":True,"original_normal_push_count":1,"new_pushes":0,
      "appserver_original_FAIL_and_workspace_controller_FAIL_preserved":True,"admission_v1_failure_and_NUL_capture_failure_preserved":True,
      "exact13_original_git_NUL_stdout_producers_verified":True,"new_native_tests_executed":0,
      "source_target_executable_or_active_workspace_read":False,"archive_code_executed":False,"append_commit_push":False,
      "full_history_cost":None,"physical_cost":None,"scientific_acceptance":False}
    data=(json.dumps(answer,indent=2,sort_keys=True)+"\n").encode()
    with (OUT/"RESULT.json").open("xb") as f:f.write(data)
    print(json.dumps({"result":{"path":str(OUT/"RESULT.json"),"bytes":len(data),"sha256":sha(data)},**answer}),flush=True)
if __name__=="__main__":main()
