#!/usr/bin/env python3
"""Archive only the fixed stage410 cloud originals; never contact H or run code."""
import base64
import hashlib
import json
from pathlib import Path

SOURCE=Path("/tmp/hepta-36fa-coordinator-a489-maintenance-staging-v1")
OUT=Path(__file__).resolve().parent
EXPECTED_INDEX="2ccda94d043ee63b0a1ff6a201553a4cd158eb08"
JOB="1a1d47a555d-392-410"
LIMIT=512000
def pin(raw):
 return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
         "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
def exact(raw,expected):
 actual=pin(raw)
 assert all(actual[k]==expected[k] for k in actual),(actual,expected)
 return actual
def load(name):return json.loads((OUT/"originals"/name).read_bytes())
def native_payload(name):
 sdk=load(name)
 assert sdk["isError"] is False and sdk["structuredContent"] is None
 assert len(sdk["content"])==1 and sdk["content"][0]["type"]=="text"
 return json.loads(sdk["content"][0]["text"])
index_raw=(SOURCE/"CLOSED_STAGE_ARCHIVE_INPUTS.json").read_bytes()
assert pin(index_raw)["git_blob"]==EXPECTED_INDEX
index=json.loads(index_raw)
assert index["job_id"]==JOB and index["entry_count"]==len(index["entries"])==45
assert index["main_outcomes_included"] is False
names=[row["name"] for row in index["entries"]]
assert len(set(names))==45
originals=OUT/"originals";originals.mkdir()
rows=[]
for row in index["entries"]:
 relative=Path(row["name"])
 assert not relative.is_absolute() and ".." not in relative.parts
 src=Path(row["local_path"])
 assert src==SOURCE/relative
 before=src.stat();raw=src.read_bytes();after=src.stat()
 assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
 identity=exact(raw,row)
 assert len(raw)<=LIMIT
 dst=originals/relative;dst.parent.mkdir(parents=True,exist_ok=True)
 with dst.open("xb") as f:f.write(raw)
 assert dst.read_bytes()==raw
 rows.append({"name":row["name"],"local_path":str(dst),"original_source_path":str(src),**identity})
with (originals/"CLOSED_STAGE_ARCHIVE_INPUTS.json").open("xb") as f:f.write(index_raw)
rows.append({"name":"CLOSED_STAGE_ARCHIVE_INPUTS.json","local_path":str(originals/"CLOSED_STAGE_ARCHIVE_INPUTS.json"),
 "original_source_path":str(SOURCE/"CLOSED_STAGE_ARCHIVE_INPUTS.json"),**pin(index_raw)})
plan=load("NINE_RECORD_READ_PLAN.json")
manifest=load("STAGING_READBACK.json")
assert len(plan)==len(manifest["files"])==9
assert manifest["source_writes_during_staging"] is False and manifest["qualification"] is False
manifest_by_name={Path(row["path"]).name:row for row in manifest["files"]}
proof=[];chunk_count=0
for planned in plan:
 name=planned["name"]
 ranges=load("RANGES."+name+".json")
 assert ranges["name"]==name and ranges["path"]==planned["path"]
 assert ranges["complete_original_sdk_ranges"] is True
 data=[];offset=0;chunk_rows=[]
 for chunk in ranges["chunks"]:
  sdkname=chunk["original_sdk"]["name"]
  sdkraw=(originals/sdkname).read_bytes()
  exact(sdkraw,chunk["original_sdk"])
  item=native_payload(sdkname)
  assert item["offset"]==chunk["offset"]==offset
  assert item["next_offset"]==chunk["next_offset"]
  assert item["version"]==chunk["version"]==ranges["version"]
  assert item["size"]==planned["bytes"] and item["path"]==planned["path"]
  assert chunk["requested_expected_version"]==(None if offset==0 else ranges["version"])
  raw=base64.b64decode(item["data_base64"],validate=True)
  assert hashlib.sha256(raw).hexdigest()==item["chunk_sha256"]
  assert len(raw)==item["next_offset"]-offset
  assert item["eof"] is (item["next_offset"]==item["size"])
  offset=item["next_offset"];data.append(raw);chunk_count+=1
  chunk_rows.append({"sdk":sdkname,"offset":item["offset"],"next_offset":offset,"version":item["version"],
                     "eof":item["eof"],"chunk_sha256":item["chunk_sha256"]})
 raw=b"".join(data)
 assert offset==planned["bytes"]
 exact(raw,planned);exact(raw,ranges);exact(raw,manifest_by_name[name])
 assert raw==(originals/"native-readback"/name).read_bytes()
 proof.append({"name":name,**pin(raw),"version":ranges["version"],"chunks":chunk_rows,
               "exact_actual_native_body_equals_frozen_approved_record":True})
assert chunk_count==12
staging_read=native_payload("STAGING_READBACK.READ_01.original.json")
staging_bytes=base64.b64decode(staging_read["data_base64"],validate=True)
assert staging_read["offset"]==0 and staging_read["next_offset"]==staging_read["size"]==len(staging_bytes)
assert staging_read["eof"] is True
assert hashlib.sha256(staging_bytes).hexdigest()==staging_read["chunk_sha256"]
assert staging_bytes==(originals/"STAGING_READBACK.json").read_bytes()
normal=native_payload("STAGE_STATUS_01.original.json")
assert normal["job_id"]==JOB and normal["state"]=="succeeded" and normal["exit_code"]==0
for key in ("timed_out","cancelled","automatic_retry"):assert normal[key] is False
for key in ("terminal_publication_confirmed","output_complete","output_durable"):assert normal[key] is True
streams=native_payload("STAGE_STREAM_READ_01.original.json")
assert streams["job_id"]==JOB
stream_pins={}
for key,name in (("stdout","STDOUT.complete.original.txt"),("stderr","STDERR.complete.original.txt")):
 record=streams[key];raw=bytes.fromhex(record["bytes_hex"])
 assert record["offset"]==0 and record["next_offset"]==record["size"]==len(raw)
 assert record["eof"] is True and raw==(originals/name).read_bytes()
 assert normal["log_bytes"][key]=={"seen":len(raw),"stored":len(raw)}
 assert normal["log_truncated"][key] is False
 stream_pins[key]=pin(raw)
request=load("STAGE_REQUEST.original.json")
admission=native_payload("STAGE_ADMISSION.original.json")
job=admission["job"]
assert job["id"]==JOB and admission["reused"] is False and job["launch_error"] is None
assert job["args"]==request["args"] and job["cwd"]==request["cwd"] and job["executable"]==request["executable"]
assert job["idempotency_key"]==request["idempotency_key"] and job["env_keys"]==[]
assert request["timeout_seconds"]==900 and "env" not in request
assert request["args"][:2]==["-B","-c"]
assert request["args"][2].encode()==(originals/"native-readback/ACTUAL_BOOTSTRAP.py").read_bytes()
assert request["stdin"].encode()==(originals/"native-readback/ACTUAL_BOOTSTRAP_PAYLOAD.json").read_bytes()
packet=json.loads(request["stdin"])
assert packet["format"]=="hepta-original-maintenance-control-staging-v1" and len(packet["files"])==6
for name,encoded in packet["files"].items():
 raw=base64.b64decode(encoded,validate=True)
 assert raw==(originals/"native-readback"/name).read_bytes()
approval=(originals/"ROOT_ORDERED_APPROVAL.original.json").read_bytes()
assert pin(approval)["git_blob"]=="4049efd8e04db8a40d14a9182368a5632005e1da"
approval_sdk=load("ROOT_ORDERED_APPROVAL_GET.original.json")
assert approval_sdk["structuredContent"]["content"].encode()==approval
native_review=load("STAGE_COMPLETE_READBACK_REVIEW.json")
assert native_review["job_id"]==JOB and native_review["all_nine_full_bytes_match"] is True
assert native_review["actual_full_read_record_count"]==9 and native_review["actual_native_binary_read_chunks"]==12
assert native_review["main_dispatched"] is False and native_review["qualification"] is False
summary={
 "format":"hepta-completed-stage410-independent-archive-verification-v1",
 "status":"FIXED_45_ORIGINALS_AND_INDEX_BYTE_VERIFIED; ARCHIVE_GIT_READBACK_PENDING",
 "scope":"Closed stage410 window only; cloud offline reassembly of retained native reads is not a second H read. No main41e record or later result was read.",
 "input_index":pin(index_raw),"source_declared_cutoff":index["at"],"job_id":JOB,
 "source_entries":45,"index_entries":1,"total_payloads_before_archive_metadata":46,
 "max_payload_bytes":max(row["bytes"] for row in rows),"total_payload_bytes":sum(row["bytes"] for row in rows),
 "all_payloads_under_512000_bytes":True,"unique_blob_count":len({row["git_blob"] for row in rows}),
 "nine_native_readback_bodies":proof,"actual_native_file_read_chunks":chunk_count,
 "normal_stage":{"job_id":normal["job_id"],"state":normal["state"],"exit_code":normal["exit_code"],
 "timed_out":normal["timed_out"],"at_unix_ms":normal["at_unix_ms"]},
 "complete_streams":stream_pins,"staging_manifest_readback_full_equal":True,
 "stage_request":pin((originals/"STAGE_REQUEST.original.json").read_bytes()),
 "stage_timeout_seconds":900,"six_payload_exact_decode":True,"root_ordered_approval":pin(approval),
 "pending_wording_preserved":"Original RANGES files retain their then-pending decode wording; this independent report adds exact reassembly evidence without overwriting originals.",
 "execution_not_in_scope":{"H_actions_by_reviewer":0,"source_writes":0,"test_or_formatter_execution":0,
 "main41e_outcome_included":False,"qualification":False},
 "entries":rows}
raw=(json.dumps(summary,indent=2,sort_keys=True)+"\n").encode()
with (OUT/"ARCHIVE_BYTE_REVIEW.json").open("xb") as f:f.write(raw)
print(json.dumps({"report":str(OUT/"ARCHIVE_BYTE_REVIEW.json"),**pin(raw),"payload_count":len(rows),
 "max_payload_bytes":summary["max_payload_bytes"],"chunks":chunk_count}))
