#!/usr/bin/env python3
import argparse,base64,hashlib,io,json,zipfile,collections
from pathlib import Path,PurePosixPath
def ident(b):
 return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}
def api(x):
 for _ in range(12):
  if isinstance(x,dict) and isinstance(x.get("content"),str):return json.loads(x["content"])
  for k in ("result","value","raw","structuredContent"):
   if isinstance(x,dict) and k in x:x=x[k];break
  else:return x
 raise AssertionError("API wrapper")
p=argparse.ArgumentParser();p.add_argument("--packet",type=Path,default=Path(__file__).resolve().parent);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
m=json.loads((a.packet/"manifest.json").read_bytes());data=[]
for row in m["parts"]:
 b=(a.packet/row["path"]).read_bytes();assert ident(b)==row["identity"];q=base64.b64decode(b.strip(),validate=True);assert ident(q)==row["decoded_identity"];data.append(q)
raw=b"".join(data);assert ident(raw)==m["archive_identity"];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);expected={r["path"]:r for r in m["members"]}
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 assert z.testzip() is None and len(z.namelist())==len(expected) and set(z.namelist())==set(expected)
 for name in z.namelist():
  q=PurePosixPath(name);assert not q.is_absolute() and ".." not in q.parts and str(q)==name
  b=z.read(name);assert ident(b)==expected[name]["identity"];f=out/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
root=out/"review"
initial=json.loads((root/"FINDINGS.initial.json").read_bytes());final=json.loads((root/"REVIEW.final.json").read_bytes())
assert final["decision"]=="ACCEPT_REPORT_FACTS_AND_QUALIFICATION_SCOPE" and final["remaining_report_findings"]==0
assert ident((root/"reviewed-report-1b5b9b985d72495b681e423b3e0f99cf2427260a.md").read_bytes())=={k:initial["reviewed_report"][k] for k in ("bytes","git_blob","sha256")}
assert ident((root/"reviewed-report-final.md").read_bytes())=={k:final["accepted_report"][k] for k in ("bytes","git_blob","sha256")}
for kind in ("FINDINGS.initial","REVIEW.final"):
 receipt=json.loads((root/(kind+".actual.json")).read_bytes());b=(root/(kind+".json")).read_bytes()
 assert ident(b)==receipt["identity"] and receipt["actual_full_GET"]["structuredContent"]["content"].encode()==b
src=root/"source-dependencies"
ledger=json.loads((src/"documents/continuation-blocker-progress-v8.json").read_bytes());old=json.loads((src/"old/continuation-blocker-progress-v7.json").read_bytes())
assert ident((src/"documents/continuation-blocker-progress-v8.json").read_bytes())["git_blob"]=="ea5ad333eacf2f49326a8f80a39e94ad771d818d"
assert [(x["id"],x["original_exit_condition_zh"]) for x in ledger["items"]]==[(x["id"],x["original_exit_condition_zh"]) for x in old["items"]]
assert dict(collections.Counter(x["closure_class"] for x in ledger["items"]))=={"CLOSED_SCOPED":16,"OPEN":6,"SCIENTIFIC_HOLD":1}
reg=json.loads((src/"b21-collector-v3-native-delivery/registry.actual.json").read_bytes());plan=json.loads((src/"b21-collector-v3-native-delivery/C3-complete-290-tree-elements.json").read_bytes())
e={x["repo_path"]:x["git_blob"] for x in reg["objects"]}
for f in ("registry.actual.json","registry.self.actual.json"):e[reg["prefix"]+f]=ident((src/"b21-collector-v3-native-delivery"/f).read_bytes())["git_blob"]
assert len(e)==290 and e=={x["path"]:x["sha"] for x in plan}
receipts=json.loads((src/"b21-collector-v3-native-delivery/registration-receipts.manifest.json").read_bytes())
assert [receipts[x] for x in ("actual_tool_return_count","actual_new_materialization_returns","actual_successful_full_GET_returns","actual_failed_GET_returns")]==[340,62,277,1]
headraw=json.loads((src/"integration-ci-review/head-2d1137-runs-second.original.json").read_bytes());runs=api(headraw)
assert headraw["observed_at_utc"]=="2026-11-06T07:43:03Z" and runs["total_count"]==len(runs["workflow_runs"])==18
assert len({x["id"] for x in runs["workflow_runs"]})==18 and {x["head_sha"] for x in runs["workflow_runs"]}=={"2d1137b1ba39fab0e6a28bac8decc114dfa0138c"}
assert dict(collections.Counter(x["conclusion"] or x["status"] for x in runs["workflow_runs"]))=={"queued":13,"in_progress":2,"success":1,"skipped":2}
jraw=json.loads((root/"final-delta-source/blocking-42180997764-jobs-fifth.original.json").read_bytes());jobs=api(jraw)
assert jraw["observed_at_utc"]=="2026-11-06T07:47:10Z" and jobs["total_count"]==len(jobs["jobs"])==3
assert {x["id"]:(x["status"],x["conclusion"]) for x in jobs["jobs"]}=={127770340918:("queued",None),127770341230:("queued",None),127770341439:("completed","success")}
proof={"schema":"post-audit-v2-independent-report-packet-restoration-v1","members":len(expected),"member_bytes":sum(x["identity"]["bytes"] for x in expected.values()),"all_member_identities_and_two_actual_review_GETs_equal":True,"original23_literal_exits_and_16_6_1_preserved":True,"B21_290_and340_denominators_recomputed":True,"new18run_and3job_cuts_recomputed":True,"accepted_report_git_blob":final["accepted_report"]["git_blob"],"native_CI_or_network_execution":False,"refs_or_PR_changed":False}
(out/"RESTORE_VERIFICATION.json").write_text(json.dumps(proof,indent=2)+"\n");print(json.dumps(proof,indent=2))
