#!/usr/bin/env python3
"""Verify the frozen main67 API cut and original Windows shard-4 artifact.

Read-only with respect to all original evidence. Re-run decode_compact.py first
to reproduce the deterministic compact projections. This report distinguishes
job, target, launch, XML-generation, and literal libtest-row denominators.
"""
import collections, hashlib, json, pathlib, re, sys, xml.etree.ElementTree as ET, zipfile
ROOT=pathlib.Path(__file__).resolve().parent
HEAD="67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
TREE="3982ba56dc5a3f1da0c1de7ea57992f88125c359"
MERGE="b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae"
def read(rel):return json.loads((ROOT/rel).read_text(encoding="utf-8"))
def unwrap(v):
    if isinstance(v,dict) and "total_count" in v:return v
    if "structuredContent" in v:v=v["structuredContent"]
    elif isinstance(v.get("content"),list):v=json.loads(next(x["text"] for x in v["content"] if x["type"]=="text"))
    if isinstance(v.get("content"),str):v=json.loads(v["content"])
    return v
def ident(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def counts(jobs):return dict(sorted(collections.Counter(j["conclusion"] or j["status"] for j in jobs).items()))
def little(j):return {k:j.get(k) for k in ("id","run_id","name","status","conclusion","runner_name","head_sha")}
def delta(old,new):
    a={j["id"]:j for j in old};b={j["id"]:j for j in new}
    return {"previous_total":len(a),"current_total":len(b),"old_counts":counts(old),"new_counts":counts(new),
      "added":[little(b[x]) for x in sorted(b.keys()-a.keys())],
      "removed":[little(a[x]) for x in sorted(a.keys()-b.keys())],
      "changed":[{"id":x,"name":b[x]["name"],"before":little(a[x]),"after":little(b[x])}
        for x in sorted(a.keys()&b.keys()) if (a[x]["status"],a[x]["conclusion"])!=(b[x]["status"],b[x]["conclusion"])]}
def merkle(tree):
    nodes={"":{}}
    for e in tree:
        if e["type"]=="tree":continue
        parts=e["path"].split("/");directory=""
        for part in parts[:-1]:
            parent=directory;directory=(directory+"/" if directory else "")+part
            nodes.setdefault(directory,{})
            nodes[parent][part]=("40000",directory)
        nodes[directory][parts[-1]]=(e["mode"],e["sha"])
    hs={}
    for path in sorted(nodes,key=lambda s:(s.count("/")+bool(s),s),reverse=True):
        payload=b""
        for name,(mode,value) in sorted(nodes[path].items(),key=lambda kv:(kv[0]+("/" if kv[1][0]=="40000" else "")).encode()):
            h=hs[value] if mode=="40000" else value
            payload+=mode.encode()+b" "+name.encode()+b"\0"+bytes.fromhex(h)
        hs[path]=hashlib.sha1(b"tree "+str(len(payload)).encode()+b"\0"+payload).hexdigest()
    return hs[""],len(hs)

def verify():
    runs=unwrap(read("original/run-list.original.json"));assert runs["total_count"]==len(runs["workflow_runs"])==19
    jobs=[];run_rows=[]
    for r in runs["workflow_runs"]:
        assert r["head_sha"]==HEAD
        data=unwrap(read(f'original/run-{r["id"]}-jobs.original.json'))
        assert data["total_count"]==len(data["jobs"])<=100
        assert all(j["run_id"]==r["id"] and j["head_sha"]==HEAD for j in data["jobs"])
        jobs+=data["jobs"];run_rows.append({"run_id":r["id"],"name":r["name"],"run_status":r["status"],
          "run_conclusion":r["conclusion"],"job_total":len(data["jobs"]),"job_counts":counts(data["jobs"])})
    assert len(jobs)==len({j["id"] for j in jobs})==85
    assert counts(jobs)=={"cancelled":9,"failure":2,"in_progress":4,"queued":10,"skipped":5,"success":55}
    old=[]
    for p in sorted((ROOT/"baseline-0201").glob("jobs-*.original-tool-return.json")):
        d=unwrap(json.loads(p.read_text()));assert d["total_count"]==len(d["jobs"]);old+=d["jobs"]
    assert len(old)==len({j["id"] for j in old})==58
    baseline_registry=read("baseline-0201/registry.original.json");checked_baseline_parts=0
    for part in baseline_registry["objects"]:
        member=part.get("source_member","")
        if not member.startswith("jobs-"):continue
        full=(ROOT/"baseline-0201"/member).read_text(encoding="utf-8").encode("utf-16-le")
        start=part["character_offset"]*2;end=start+part["characters"]*2
        text=full[start:end].decode("utf-16-le").encode("utf-8")
        assert all(ident(text)[k]==part[k] for k in ("bytes","sha256","git_blob"))
        assert part["actual_registered_blob_sha"]==part["git_blob"] and part["actual_full_GET_equal"]
        checked_baseline_parts+=1
    assert checked_baseline_parts==20
    d0201=delta(old,jobs);assert len(d0201["added"])==27 and not d0201["removed"] and len(d0201["changed"])==12
    prior24=[];ids24=set()
    for p in sorted((ROOT/"baseline-0244").glob("run-*-jobs.original.json")):
        d=unwrap(json.loads(p.read_text()));assert d["total_count"]==len(d["jobs"]);prior24+=d["jobs"];ids24|={j["run_id"] for j in d["jobs"]}
    d0244=delta(prior24,[j for j in jobs if j["run_id"] in ids24])
    authority=read("authority/main67-full-tree.json")
    assert not authority["truncated"] and authority["sha"]==TREE
    root,nodes=merkle(authority["tree"]);assert root==TREE
    leaves={x["path"]:x for x in authority["tree"] if x["type"]!="tree"}
    assert len(leaves)==10582
    for row in read("source-map.json"):
        got=ident((ROOT/"source"/row["path"]).read_bytes())
        assert all(got[k]==row[k] for k in got)
        assert got["git_blob"]==leaves[row["path"]]["sha"]
    merge=read("original/actual-executed-merge-commit.original.json")
    assert merge["sha"]==MERGE and merge["tree"]["sha"]==TREE
    assert [x["sha"] for x in merge["parents"]]==["63652be658ebed8d3052eb789b951793384fd5e4",HEAD]
    log=(ROOT/"original/job-127679861687.original.log").read_text()
    assert MERGE in log and "Process completed with exit code 3." in log
    assert "Selected 149 of 606 Bazel test targets for Windows shard 4/4." in log
    artifacts=unwrap(read("original/blocking-run-artifacts.original.json"))
    assert artifacts["total_count"]==len(artifacts["artifacts"])==6
    artifact=next(a for a in artifacts["artifacts"] if a["id"]==13473662833)
    zpath=ROOT/"artifacts/windows-shard4-13473662833.original.zip"
    zb=zpath.read_bytes();assert len(zb)==artifact["size_in_bytes"]
    assert "sha256:"+hashlib.sha256(zb).hexdigest()==artifact["digest"]
    inventory=read("windows-artifact-manifest.json")
    assert inventory["zip_sha256"]==hashlib.sha256(zb).hexdigest()
    zroot=ROOT/"artifacts/windows-shard4-original"
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None
        assert len(z.infolist())==len(inventory["entries"])==47
        assert {x.filename for x in z.infolist()}=={x["path"] for x in inventory["entries"]}
        for member in inventory["entries"]:
            raw=z.read(member["path"]);assert raw==(zroot/member["path"]).read_bytes()
            assert len(raw)==member["bytes"] and hashlib.sha256(raw).hexdigest()==member["sha256"]
    failed_manifest=read("artifacts/windows-shard4-original/failed-test-logs/invocation-jmk8w12b/manifest.json")
    selected_manifest=read("artifacts/windows-shard4-original/selected-target-test-logs/invocation-hz3qwdsx/manifest.json")
    for manifest,sub in [(failed_manifest,"failed-test-logs/invocation-jmk8w12b"),
                         (selected_manifest,"selected-target-test-logs/invocation-hz3qwdsx")]:
        assert manifest["complete_for_selected_targets"] and not manifest["errors"]
        assert manifest["source"]=={"commit":MERGE,"tracked_worktree_dirty":False,"tree":TREE}
        for member in manifest["files"]:
            raw=(zroot/sub/member["archive_relative_path"]).read_bytes()
            assert len(raw)==member["bytes"] and hashlib.sha256(raw).hexdigest()==member["sha256"]
    assert len(failed_manifest["files"])==42 and len(selected_manifest["files"])==2
    compact=read("derived/compact-core-test-runners.json")
    launch=[s for s in compact if s["args"][0].replace("\\","/").endswith("/tw.exe")]
    xmlgen=[s for s in compact if s["args"][0].replace("\\","/").endswith("/xml.exe")]
    assert len(launch)==len(xmlgen)==21 and len(compact)==42
    assert all(s["runner"]=="local" and not s["cache_hit"] and s["timeout_millis"]==900000 for s in launch)
    by_shard=collections.defaultdict(list);xml_by_shard=collections.defaultdict(list)
    for s in launch:by_shard[int(dict((x["name"],x["value"]) for x in s["env_vars"])["TEST_SHARD_INDEX"])+1].append(s)
    for s in xmlgen:xml_by_shard[int(dict((x["name"],x["value"]) for x in s["env_vars"])["TEST_SHARD_INDEX"])+1].append(s)
    assert set(by_shard)==set(range(1,17))
    assert {k:len(v) for k,v in by_shard.items() if len(v)>1}=={4:2,6:2,7:3,13:2}
    case_rx=re.compile(r"^test (.+) \.\.\. (ok|FAILED|ignored)(?:,.*)?$",re.M)
    summary_rx=re.compile(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([\d.]+)s$",re.M)
    attempt_rows=[];final_cases=collections.defaultdict(list);mismatches=[]
    base=zroot/"failed-test-logs/invocation-jmk8w12b/targets/0000"
    for shard in range(1,17):
        ss=by_shard[shard];xx=xml_by_shard[shard];assert len(ss)==len(xx)
        for i,(s,x) in enumerate(zip(ss,xx),1):
            rel=f"shard_{shard}_of_16/"+(f"test_attempts/attempt_{i}.log" if i<len(ss) else "test.log")
            p=base/rel;raw=p.read_bytes();txt=raw.decode("utf-8");norm=txt.replace("\r\n","\n")
            summaries=[{"status":m[0],"passed":int(m[1]),"failed":int(m[2]),"ignored":int(m[3]),
              "measured":int(m[4]),"filtered_out":int(m[5]),"seconds":m[6]} for m in summary_rx.findall(norm)]
            cases=[{"name":n,"status":st} for n,st in case_rx.findall(norm)]
            statuses=collections.Counter(c["status"] for c in cases)
            assert summaries and sum(z["passed"] for z in summaries)==statuses["ok"]
            assert sum(z["failed"] for z in summaries)==statuses["FAILED"]
            assert sum(z["ignored"] for z in summaries)==statuses["ignored"]
            assert bool(statuses["FAILED"])==bool(s["exit_code"])
            xml_path=p.with_suffix(".xml");xml_raw=xml_path.read_bytes();xt=ET.fromstring(xml_raw)
            xml_cases=xt.findall(".//testcase");assert len(xml_cases)==1
            assert bool(xt.findall(".//error"))==bool(s["exit_code"])
            assert int(x["args"][-1])==s["exit_code"] and x["exit_code"]==0
            assert xml_cases[0].attrib["time"]==x["args"][-2]
            outs=xt.findall(".//system-out");assert len(outs)==1
            assert case_rx.findall(outs[0].text or "")==case_rx.findall(norm)
            assert summary_rx.findall(outs[0].text or "")==summary_rx.findall(norm)
            digest=next(o["digest"]["hash"] for o in x["outputs"] if o.get("path","").endswith("/test.xml"))
            actual_digest=hashlib.sha256(xml_raw).hexdigest();matches=digest==actual_digest
            if not matches:mismatches.append({"shard":shard,"attempt":i,"compact_output_digest":digest,"archive_xml_sha256":actual_digest})
            row={"shard":shard,"attempt":i,"final_attempt":i==len(ss),"log":str(p.relative_to(ROOT)),
              "log_identity":ident(raw),"xml":str(xml_path.relative_to(ROOT)),"xml_identity":ident(xml_raw),
              "launch_sequence":s["sequence"],"xml_generation_sequence":x["sequence"],
              "runner":s["runner"],"cache_hit":s["cache_hit"],"timeout_millis":s["timeout_millis"],
              "original_exit_code":s["exit_code"],"libtest_summaries":summaries,"literal_case_rows":cases,
              "xml_compact_digest_matches_this_attempt":matches}
            attempt_rows.append(row)
            if i==len(ss):
                for c in cases:final_cases[c["name"]].append({"shard":shard,"status":c["status"]})
    assert len(attempt_rows)==21 and sum(bool(x["original_exit_code"]) for x in attempt_rows)==6
    assert len(mismatches)==5
    raw_final=collections.Counter(x["status"] for vs in final_cases.values() for x in vs)
    unique_status=collections.Counter()
    for n,vs in final_cases.items():
        assert len({x["status"] for x in vs})==1;unique_status[vs[0]["status"]]+=1
    cargo=next(j for j in jobs if j["id"]==127679861307)
    assert [s["name"] for s in cargo["steps"] if s["conclusion"]=="failure"]==["Run cargo-deny"]
    for rel in ["original/cargo-deny-log-tool-error-01.json","original/cargo-deny-log-tool-error-02.json"]:
        err=read(rel);assert err["isError"] and "Transport closed" in json.dumps(err)
    report={"schema":"hepta-main67-0319-evidence-verification-v1","collection":read("collection-metadata.json"),
      "api":{"baseline_0201_original_parts_reconstructed_and_hash_checked":checked_baseline_parts,"run_count":19,"unique_job_count":85,"job_counts":counts(jobs),"runs":run_rows,
        "failures":[little(j) for j in jobs if j["conclusion"]=="failure"],
        "pending":[little(j) for j in jobs if j["status"]!="completed"],"delta_0201":d0201,"delta_0244_four_runs":d0244},
      "source":{"requested_head":HEAD,"windows_actual_checkout":MERGE,"actual_checkout_tree":TREE,
        "complete_original_leaves":len(leaves),"recomputed_merkle_nodes":nodes,"verified_local_source_files":len(read("source-map.json"))},
      "windows":{"official_zip_identity":ident(zb),"official_artifact_digest":artifact["digest"],"zip_members":47,
        "failed_target_log_xml_files":42,"selected_pty_log_xml_files":2,"failed_target":"//codex-rs/core:core-all-test",
        "original_bazel_exit_code":3,"original_selected_test_targets":149,"original_query_test_targets":606,
        "core_actual_test_launches":21,"core_separate_xml_generators":21,"core_failed_attempts":6,
        "shards":16,"extra_attempts":5,"all_launches_local_noncache":True,"original_timeout_millis":900000,
        "final_failed_case_names":sorted(n for n,vs in final_cases.items() if vs[0]["status"]=="FAILED"),
        "literal_final_case_row_counts":dict(raw_final),"literal_final_unique_name_counts":dict(unique_status),
        "duplicate_literal_names":{n:vs for n,vs in final_cases.items() if len(vs)>1},
        "compact_xml_digest_mismatches":mismatches,"attempts":attempt_rows,
        "limits":["The selected PTY result was explicitly cached; it is not fresh native PTY execution.",
          "Compact TestRunner includes XML generators; only tw.exe entries count as actual test launches.",
          "Five repeated-path XML output references reuse prior digests; they do not cryptographically bind the later XML bytes. The original ZIP and in-artifact manifest independently retain all 42 exact log/XML files.",
          "Literal libtest rows include duplicate names. Do not conflate row totals, distinct names, declared full binary inventory, Bazel targets, and attempts.",
          "Collector scope is selected failed targets and the selected PTY result; this is not a complete test-log archive for all 149 targets."]},
      "cargo_deny":{"job_id":cargo["id"],"api_failed_step":"Run cargo-deny","source_declared_command":"cargo +1.95.0 deny --locked --all-features check --config deny.toml",
        "pinned_tool":"cargo-deny@0.19.0","toolchain":"1.95.0","whole_log":"UNAVAILABLE_TRANSPORT_CLOSED",
        "actual_checkout_commit":"UNKNOWN","native_exit_code":"UNKNOWN","failure_cause":"UNKNOWN",
        "matching_deny_artifacts_in_complete_list":0,"no_dependency_or_policy_change_inferred":True},
      "qualification":"EVIDENCE_ONLY; existing blockers and original exit criteria are not changed"}
    return report
if __name__=="__main__":
    print(json.dumps(verify(),ensure_ascii=False,indent=2)+"\n",end="")
