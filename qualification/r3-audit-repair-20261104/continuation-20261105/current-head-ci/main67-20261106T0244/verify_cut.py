#!/usr/bin/env python3
"""Read-only verification of the frozen 02:44 increment. No API/native actions."""
from pathlib import Path
import argparse,collections,hashlib,json,re
SOURCE="67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
TREE="3982ba56dc5a3f1da0c1de7ea57992f88125c359"
BASE="63652be658ebed8d3052eb789b951793384fd5e4"
UI_MERGE="c0f9b518d0b14c32396294cfc88ffe92c98692c5"
PARENT="eed4d6bb61b789b19f60facc79f9e031765fa4c9"
TIMESTAMP=re.compile(r"^\ufeff?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z) (.*)$")
def identity(b):
 return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}
def load(p):return json.loads(p.read_bytes())
def api(p):
 r=load(p);assert r["isError"] is False
 d=r["structuredContent"];assert isinstance(d["content"],str)
 if isinstance(d.get("structuredContent"),dict):
  assert d["structuredContent"]["content"]==d["content"]
 return json.loads(d["content"]),d["url"]
def state(x):
 return x["conclusion"] if x["status"]=="completed" else x["status"]
def bodies(p):
 b=p.read_bytes();s=b.decode("utf-8",errors="strict");lines=[]
 for n,line in enumerate(s.splitlines(),1):
  m=TIMESTAMP.match(line)
  lines.append({"line":n,"timestamp":m[1] if m else None,"body":m[2] if m else line})
 return b,lines
def prove(root):
 original=root/"original";manifest=load(root/"input-manifest.json");assert len(manifest["files"])==9
 inputs=[]
 for item in manifest["files"]:
  body=(root/item["path"]).read_bytes();i=identity(body)
  assert all(item[k]==v for k,v in i.items())
  inputs.append({"path":item["path"],**i})
 meta=load(original/"collection-metadata.json")
 assert meta["source"]==SOURCE
 for item in meta["items"]:
  assert identity((original/item["name"]).read_bytes())=={k:item[k] for k in ("bytes","git_blob","sha256")}
  assert item["HTTP_wire_bytes_claimed"] is False
 runs,url=api(original/"run-list.original.json")
 assert url==f"https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/runs?head_sha={SOURCE}&per_page=100"
 assert runs["total_count"]==len(runs["workflow_runs"])==19
 assert len({x["id"] for x in runs["workflow_runs"]})==19
 assert all(x["head_sha"]==SOURCE and x["run_attempt"]==1 for x in runs["workflow_runs"])
 run_counts=dict(collections.Counter(state(x) for x in runs["workflow_runs"]))
 assert run_counts=={"success":10,"queued":2,"skipped":2,"failure":4,"in_progress":1}
 run_projection=[{k:x[k] for k in ("id","name","head_sha","run_attempt","status","conclusion","updated_at")} for x in runs["workflow_runs"]]
 alljobs=[];selected=[]
 for run in (42123581408,42123581260,42123581031,42123581363):
  d,url=api(original/f"run-{run}-jobs.original.json")
  assert url==f"https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/runs/{run}/jobs?filter=all&per_page=100"
  assert d["total_count"]==len(d["jobs"])<100
  assert all(x["run_id"]==run and x["head_sha"]==SOURCE and x["run_attempt"]==1 for x in d["jobs"])
  selected.append({"run":run,"jobs":len(d["jobs"]),"counts":dict(collections.Counter(state(x) for x in d["jobs"]))})
  alljobs+=d["jobs"]
 assert len(alljobs)==len({x["id"] for x in alljobs})==23
 jobcounts=dict(collections.Counter(state(x) for x in alljobs))
 assert jobcounts=={"success":19,"cancelled":3,"in_progress":1}
 job_projection=[{k:x[k] for k in ("id","run_id","name","head_sha","run_attempt","status","conclusion","runner_id","started_at","completed_at")} for x in alljobs]
 jobs={x["id"]:x for x in alljobs}
 ui=[]
 for jid,lane,head in ((127581904221,"base-merge",UI_MERGE),(127581904330,"source-head",SOURCE)):
  assert jobs[jid]["run_id"]==42123581031 and state(jobs[jid])=="success"
  raw,lines=bodies(original/f"job-{jid}.original.log")
  groups=[];pass_rows=[];tap=[];browser=[];lib=[];gateways=[];syntax=[];history=[]
  for i,row in enumerate(lines):
   text=row["body"];n=row["line"]
   pm=re.match(r"\s*PASS\s+\[[^]]+\]\s+\(\s*\d+/\d+\)\s+(\S+)\s+(.+)$",text)
   if pm:pass_rows.append({"line":n,"binary":pm[1],"name":pm[2]})
   sm=re.match(r"\s*Summary \[([^]]+)\] (\d+) tests run: (\d+) passed, (\d+) skipped$",text)
   if sm:
    tests,passed,skipped=map(int,sm.groups()[1:])
    assert tests==passed==len(pass_rows)
    groups.append({"summary_line":n,"elapsed":sm[1].strip(),"tests_run":tests,"passed":passed,"skipped":skipped,"actual_PASS_rows":pass_rows})
    pass_rows=[]
   tm=re.fullmatch(r"# tests (\d+)",text)
   if tm:
    values={"tests":int(tm[1])};refs={"tests":n}
    for nxt in lines[i+1:i+10]:
     mm=re.fullmatch(r"# (suites|pass|fail|cancelled|skipped|todo) (\d+)",nxt["body"])
     if mm:values[mm[1]]=int(mm[2]);refs[mm[1]]=nxt["line"]
    assert values["tests"]==values["pass"] and all(values[k]==0 for k in ("fail","cancelled","skipped","todo"))
    tap.append({"values":values,"lines":refs})
   bm=re.fullmatch(r"\s*(\d+) passed \(([^)]+)\)",text)
   if bm:browser.append({"line":n,"passed":int(bm[1]),"elapsed":bm[2]})
   lm=re.fullmatch(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (.+)",text)
   if lm:
    assert list(map(int,lm.groups()[:5]))==[5,0,0,0,0]
    lib.append({"line":n,"passed":5,"failed":0,"ignored":0,"measured":0,"filtered_out":0,"elapsed":lm[6]})
   if "SyntaxError:" in text:
    following=lines[i+1:i+15];negative=[x for x in following if x["body"]=="ok 25 - rejects malformed JavaScript without modifying the pristine bridge"]
    assert len(negative)==1
    syntax.append({"diagnostic":row,"actual_passing_negative_control":negative[0],"classified_as_new_failure":False})
   if text.startswith("{") and "\x1b" not in text:
    try:obj=json.loads(text)
    except json.JSONDecodeError:continue
    if obj.get("schema")=="hepta.ui-exact-history.v1":
     assert obj["source_sha"]==SOURCE and obj["source_tree"]==TREE and obj["base_sha"]==BASE and obj["checkout_unchanged"] is True
     history.append({"line":n,"object":obj})
    if obj.get("schema_version")==1 and "command_exit_code" in obj and "before" in obj and "after" in obj:
     assert obj["lane"]==lane and obj["source_sha"]==SOURCE and obj["base_sha"]==BASE
     assert obj["tested_sha"]==head and obj["before"]==obj["after"]
     snap=obj["before"];assert snap["commit"]==head and snap["tree"]==TREE and snap["dirty"] is False
     assert snap["parents"]==([BASE,SOURCE] if lane=="base-merge" else [PARENT])
     if lane=="base-merge":assert obj["recomputed_merge_tree"]==TREE
     assert obj["status"]=="passed" and obj["exit_code"]==obj["returncode"]==obj["command_exit_code"]==0
     assert obj["timed_out"] is False and obj["output_limit_exceeded"] is False
     assert obj["observed_failed_tests"]==0 and obj["observed_passed_tests"]>=obj["minimum_tests"]
     assert obj["run_id"]=="42123581031" and obj["run_attempt"]=="1"
     gateways.append({"line":n,"object":obj})
  assert not pass_rows
  assert [(g["passed"],g["skipped"]) for g in groups]==[(88,0),(9,31),(5,35),(12,28),(2,38)]
  assert [x["values"]["tests"] for x in tap]==[13,5,159,12,7,32,1,4,31,41]
  assert [x["passed"] for x in browser]==[6,7,9,1] and len(lib)==len(syntax)==len(history)==1
  assert len(gateways)==4
  expressions=["test(http_transport::tests::)","test(owner_status::tests::)","test(ui_bundle::tests::)","test(http_origin::tests::)"]
  assert [g["object"]["command"][-1] for g in gateways]==expressions
  assert [g["object"]["observed_passed_tests"] for g in gateways]==[9,5,12,2]
  for i,g in enumerate(gateways):
   assert g["line"]==groups[i+1]["summary_line"]+1
  ui.append({"job_id":jid,"run_id":42123581031,"lane":lane,"tested_sha":head,"tree":TREE,"raw_log":identity(raw),"lines":len(lines),"LF_bytes":raw.count(b"\n"),"CRLF_bytes":raw.count(b"\r\n"),"nextest_groups":groups,"node_TAP_groups":tap,"libtest_groups":lib,"browser_groups":browser,"source_history":history,"gateway_records":gateways,"negative_controls":syntax,"unique_total_claimed":False,"filtered_gateways":"Four explicit -E selections; 31/35/28/38 skipped preserved, not counted as passes. No summed distinct-case or independence claim across groups/lanes."})
 jid=127581904963
 assert state(jobs[jid])=="success" and jobs[jid]["run_id"]==42123581408
 raw,lines=bodies(original/f"job-{jid}.original.log")
 actual_commands=[{"line":x["line"],"name":x["body"].removeprefix("Running original gate: ")} for x in lines if x["body"].startswith("Running original gate: ")]
 assert [x["name"] for x in actual_commands]==["native-update","native-install","v8","metadata","format","memory","agentd","desktop-ui","fix-memory","fix-agentd","fix-desktop-ui","format-final"]
 uncolored=[x for x in lines if "\x1b" not in x["body"]]
 actual_summaries=[x for x in uncolored if re.match(r"\s*Summary \[",x["body"]) or x["body"].startswith("test result:")]
 assert not actual_summaries
 redirection=[{"line":x["line"],"body":re.sub(r"\x1b\[[0-9;]*m","",x["body"])} for x in lines if "completed = subprocess.run(COMMANDS[label], cwd=cwd, stdout=out, stderr=err, check=False)" in x["body"]]
 assert len(redirection)==1
 objective={"job_id":jid,"run_id":42123581408,"API_conclusion":"success","raw_log":identity(raw),"lines":len(lines),"actual_start_markers":actual_commands,"embedded_source_redirection":redirection,"actual_nextest_or_libtest_summaries_in_console":0,"case_counts_from_console":None,"scope":"Complete decoded console retained. Inner command stdout/stderr are redirected to artifact files; no per-case or JUnit result is inferred from echoed source, counters in source, or API green. Separate 52-member artifact qualification is outside this bundle."}
 return {"schema":"main67-20261106T0244-independent-verification","result":"PASS_FROZEN_INPUT_CUSTODY_AND_BOUNDED_INCREMENT_REVIEW","source":SOURCE,"source_tree_authority":TREE,"inputs":inputs,"observations":{"run_list_UTC":meta["run_list_observed_utc"],"four_jobs_API_UTC":meta["jobs_observed_utc"],"decoded_logs_UTC":[{"job_id":x["job_id"],"observed_utc":x["observed_utc"]} for x in meta["items"]],"non_atomic":True,"timestamps_source":"Fixed collector metadata; no new queries or recreated read timestamps."},"runs":{"denominator":19,"counts":run_counts,"complete_original_query":True,"records":run_projection},"jobs":{"denominator":23,"scope":"Only four selected changed runs, not a refreshed all-19-run census","counts":jobcounts,"runs":selected,"records":job_projection,"new_full_58_job_census_claimed":False},"run_failure_interpretation":"Four top-level failed runs are not four proven product test failures. This four-run child subset contains zero job failure and three V8 cancellations; cancellation cause is not established here.","ui_console_evidence":ui,"objective_console":objective,"custody_limits":{"included_API_MCP_responses":5,"included_complete_original_decoded_logs":3,"included_metadata":1,"log_MCP_wrapper_included":False,"log_wrapper_note":"Root retained wrappers separately in code-mode; no wrapper member or HTTP-wire-byte claim is made for this package.","log_newline_normalized":False,"source_gateway_embedded_log_digests_independently_rebuilt":False,"source_gateway_note":"Complete JSON receipts and preceding actual named PASS rows are parsed; underlying per-gateway artifact files were not fetched or independently rebuilt in this bundle.","new_artifact_native_or_product_qualification":False,"all_blockers_closed":False,"all_required_CI_passed":False,"ref_or_PR_mutation":False}}
if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parent);args=parser.parse_args()
 print(json.dumps(prove(args.root),ensure_ascii=False,sort_keys=True,indent=2))

