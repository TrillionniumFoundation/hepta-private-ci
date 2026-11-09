import hashlib,json,subprocess,tarfile,stat
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
R=Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
W=Path("/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e")
C=Path("/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e")
OUT=R/"increment008-preparation-v1"
REL="qualification/cell_common_candidate/20261108/execution_history"
HEAD="e781fbebad63968adf18cce97dd04657b3854917"
INDEX="6a1a7c2ed7cf55f72b0e9beff24b01be09c326a7097fdd32af6ab09352b89aed"
def digest(x):return hashlib.sha256(x).hexdigest()
def same(a,b):
 if type(a)is not type(b):return False
 if isinstance(a,dict):return a.keys()==b.keys() and all(same(a[k],b[k])for k in a)
 if isinstance(a,list):return len(a)==len(b)and all(same(x,y)for x,y in zip(a,b))
 return a==b
def git(c,*a):return subprocess.check_output(["git",*a],cwd=c).decode().strip()
def state(p):
 s=p.lstat();assert stat.S_ISREG(s.st_mode)and s.st_nlink==1
 return(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,stat.S_IMODE(s.st_mode),digest(p.read_bytes()))
def save(name,obj):
 b=(json.dumps(obj,indent=2,ensure_ascii=False)+"\n").encode()
 p=OUT/name
 with p.open("xb")as f:f.write(b)
 return{"path":str(p),"bytes":len(b),"sha256":digest(b)}
if not __debug__:raise RuntimeError("Required assertions disabled")
before=(git(W,"rev-parse","HEAD"),git(W,"status","--porcelain=v1","--untracked-files=all"),git(C,"rev-parse","HEAD"),git(C,"status","--porcelain=v1","--untracked-files=all"))
assert before==(HEAD,"","bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d","")
ip=R/"increment008a-inputs.json";ib=ip.read_bytes();istate=state(ip)
assert len(ib)==335257 and digest(ib)=="66dabd527f8bf092fbaf4b8c3201f26cdc5fc94ecd5b5a0307ef601bdb9d2d05"
inputs=json.loads(ib)
original=subprocess.check_output(["git","show",HEAD+":"+REL+"/manifest.json"],cwd=W)
assert digest(original)==INDEX and (W/REL/"manifest.json").read_bytes()==original
prior=json.loads(original)
retained=deepcopy(inputs["current_common_validation"])
new={k:retained["separate_source_observations"].pop(k)for k in("core_output_45a_failed_history","remote_timer_6ec_dependency_failure_history")}
assert same(retained,prior["current_common_validation"])
assert len(prior["packets"])==83 and sum(x["file_member_count"]for x in prior["packets"])==9469
assert len(inputs["packets"])==4 and sum(x["file_member_count"]for x in inputs["packets"])==635
assert inputs["expected_prior_packet_count"]==83 and inputs["expected_final_packet_count"]==87
assert inputs["full_history_cost"]is None and all(v=="HOLD"for v in inputs["stages"].values())
seen=set();jcount=0;archive_states=[];pins=[]
for p in inputs["packets"]:
 assert p["packet_id"]not in seen;seen.add(p["packet_id"])
 archive=Path(p["archive_path"]);s=state(archive)
 assert s[2]==p["bytes"]and s[-1]==p["sha256"]
 with tarfile.open(archive,"r:xz")as tf:
  members=tf.getmembers();names=[m.name for m in members]
  assert len(names)==len(set(names))and all(m.isfile()or m.isdir()for m in members)
  assert sum(m.isfile()for m in members)==p["file_member_count"]
  for b in p["required_json_members"]:
   raw=tf.extractfile(b["path"]).read()
   assert len(raw)==b["bytes"]and digest(raw)==b["sha256"]
   value=json.loads(raw);assert len(b["equals"])==1 and b["equals"][0]["path"]==[]
   assert same(value,b["equals"][0]["value"])
   pins.append({"packet_id":p["packet_id"],"member":b["path"],"bytes":len(raw),"sha256":digest(raw)})
   jcount+=1
 assert state(archive)==s
 archive_states.append({"path":str(archive),"sha256":s[-1],"bytes":s[2],"file_member_count":p["file_member_count"]})
assert jcount==27
assert len(inputs["supplementary_observations"])==7
patch_whitespace=[];obs_states=[]
for o in inputs["supplementary_observations"]:
 p=Path(o["source_path"]);s=state(p);data=p.read_bytes()
 assert s[2]==o["bytes"]and s[-1]==o["sha256"]
 assert not(W/REL/o["relative_path"]).exists()
 if o["kind"]=="reviewed_source_patch":
  assert data.startswith(b"diff --git ")or data.startswith(b"--- a/")
  lines=[i for i,l in enumerate(data.splitlines(),1)if l.endswith((b" ",b"\t"))]
  patch_whitespace.append({"path":o["source_path"],"bytes":len(data),"sha256":digest(data),"whitespace_lines":lines,"original_bytes_must_be_preserved":True})
 else:
  assert o["kind"]=="original_json_observation";json.loads(data)
 assert state(p)==s;obs_states.append({"path":str(p),"bytes":s[2],"sha256":s[-1]})
assert len(patch_whitespace)==3
assert same(new["core_output_45a_failed_history"]["counts"],{"executed":3827,"passed":3274,"failed_exit101":6,"signal_aborted":545,"timed_out":2,"failed_including_timeouts":553,"original_ignored_not_executed":9,"retries":0,"leaks":0})
assert [a["original_preparation_returncode"]for a in new["remote_timer_6ec_dependency_failure_history"]["actual_original_AI_attempts"]]==[None,None]
assert [a["overall_preparation_returncode"]for a in new["remote_timer_6ec_dependency_failure_history"]["actual_original_AI_attempts"]]==[1,1]
after=(git(W,"rev-parse","HEAD"),git(W,"status","--porcelain=v1","--untracked-files=all"),git(C,"rev-parse","HEAD"),git(C,"status","--porcelain=v1","--untracked-files=all"))
assert after==before and state(ip)==istate
assert (W/REL/"manifest.json").read_bytes()==original
derived=[
 save("CURRENT_COMMON_VALIDATION.json",inputs["current_common_validation"]),
 save("PRIOR_CURRENT_COMMON_VALIDATION.json",prior["current_common_validation"]),
 save("NEW_SOURCE_OBSERVATIONS.json",new),
 save("PACKET_INDEX.json",[{k:v for k,v in p.items()if k!="required_json_members"}|{"required_json_members":[{k:v for k,v in b.items()if k!="equals"}for b in p["required_json_members"]]}for p in inputs["packets"]]),
 save("SUPPLEMENTARY_METADATA.json",inputs["supplementary_observations"]),
 save("ORIGINAL_PATCH_WHITESPACE.json",patch_whitespace)]
result={"status":"actual_inputs_reverse_review_passed_not_appended","input_sha256":digest(ib),"input_bytes":len(ib),"source_and_evidence_before":before,"source_and_evidence_after":after,"old_83_packets_and_current_validation_typed_unchanged":True,"four_archive_bytes_and_member_counts_match":True,"original_json_closed_bindings":27,"whole_objects_checked_recursively_with_types":True,"new_packet_count":4,"new_member_entries_with_overlap":635,"target_packets":87,"target_member_entries_with_overlap":10104,"seven_metadata_sources_byte_exact":True,"three_original_patch_whitespace_preserved":True,"new_desktop_recovery_or_native_records_included":False,"independent_stage_review_separate":True,"derived_readable_files":derived,"read_only_no_append_or_source_write":True,"tests_executed":False,"network_calls":0,"full_history_cost":None,"stages":{f"S{i}":"HOLD"for i in range(6)},"finished_at":datetime.now(timezone.utc).isoformat()}
pin=save("REVERSE_REVIEW.json",result);print(json.dumps({"result":result,"pin":pin}),flush=True)
