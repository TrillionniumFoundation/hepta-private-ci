#!/usr/bin/env python3
"""Seal new recovered evidence groups after both independent readbacks."""
from pathlib import Path, PurePosixPath
import argparse,gzip,hashlib,json
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def pin(b):return dict(bytes=len(b),sha256=sha(b),git_blob=blob(b))
def enc(x):return (json.dumps(x,ensure_ascii=False,indent=2)+"\n").encode()
def js(p):return json.loads(p.read_bytes())
def put(p,b):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==b,f"Refusing unequal existing file: {p}"
 else:
  with p.open("xb") as f:f.write(b)
 assert p.read_bytes()==b
KNOWN={"2b1933b3437a8caff85bfe2aa56b43c06e4ab56b","8ddbd58b9be4c3efde5b971ad3e772909c3eba2e","dc38717525e664bb0da982f24a8c2f9b6b451a57","3dc9bbf67cb2271fcfb08bf3b38a3c127fa6a840"}
def seal(w,stage):
 group=w/"hepta-cell/qualification/cell-unification-20261106/native-evidence"/f"r{stage}-recovered-checkpoint"
 handroot=w/"recovery-independent-readback";hp=handroot/"HANDOFF-MANIFEST.json";hb=hp.read_bytes()
 assert len(hb)==4871 and sha(hb)=="d2834fdc8310ed0046aec29ee9966ea58d4bed75884cc60c9ee8d47b3802261d"
 hand=json.loads(hb);assert hand["frozen"] and hand["new_audit_after_scratch_loss"] and not hand["old_48_derived_artifact_bytes_reconstructed"]
 files=hand["files"];assert len(files)==hand["file_count"]==25 and sum(x["bytes"] for x in files)==hand["total_bytes"]
 mappings=[]
 for x in files+[dict(path="HANDOFF-MANIFEST.json",**pin(hb))]:
  rel=PurePosixPath(x["path"]);assert not rel.is_absolute() and ".." not in rel.parts
  source=handroot/x["path"];b=source.read_bytes();assert len(b)==x["bytes"] and sha(b)==x["sha256"]
  target=group/"independent-recovery"/x["path"];put(target,b)
  mappings.append(dict(source=str(source.relative_to(w)),destination=str(target.relative_to(group)),encoding="identity",original=pin(b),stored=pin(b),roundtrip_exact=True))
 own=js(group/"RECOVERY-READBACK.json");indpath=group/"independent-recovery"/f"r{stage}/INDEPENDENT-READBACK.json";ind=js(indpath)
 assert ind["audit_is_new_after_scratch_loss"] and not ind["old_lost_audit_bytes_reconstructed"]
 assert ind["source"]["computed_tree"]==own["source_tree"] and ind["source"]["source_count"]==own["source_files"]
 assert ind["archive"]["members"]==own["regular_members"] and ind["archive"]["indexed_members"]==own["indexed_members"]
 assert ind["archive"]["archive"]["sha256"]==own["archive"]["sha256"]
 for p in ind["original_phases_and_terminal"]["phase_results"]:
  q=own["phase_bindings"][p["phase"]]
  assert p["command"]==q["command"] and p["exit_code"]==q["exit_code"] and p["elapsed_seconds"]==q["elapsed_seconds"]
  for k in ("receipt","log","resources"):assert p["inputs"][k]["sha256"]==q[k]["sha256"]
  assert p["inputs"]["raw"]["sha256"]==q["raw_process_result"]["sha256"]
 assert ind["original_phases_and_terminal"]["outer"]["sha256"]==own["outer_terminal"]["sha256"]
 originals=js(group/"SOURCE-TO-DESTINATION.json")
 for x in originals:
  b=(group/x["destination"]).read_bytes();assert pin(b)==x["stored"]
  raw=gzip.decompress(b) if x["encoding"]=="gzip-mtime-zero" else b
  assert pin(raw)==x["original"]
  if x["encoding"]=="gzip-mtime-zero":assert b[4:8]==b"\0\0\0\0"
 put(group/"INDEPENDENT-SOURCE-TO-DESTINATION.json",enc(mappings))
 put(group/"seal_recovered.py",Path(__file__).read_bytes())
 closure=dict(schema="hepta.recovered-evidence-closure.v1",state="NEW_RECOVERY_AUDITS_CLOSED",stage=stage,
  source_commit=own["source_commit"],source_tree=own["source_tree"],
  original_gate_state=own["execution"]["state"],original_outer_exit=own["outer_terminal"]["exit_code"],
  counts={k:own["execution"][k] for k in ("unique_test_results","passed","failed","timed_out","reported_skipped")},
  original_material_mapping=dict(path="SOURCE-TO-DESTINATION.json",**pin((group/"SOURCE-TO-DESTINATION.json").read_bytes()),count=len(originals)),
  independent_material_mapping=dict(path="INDEPENDENT-SOURCE-TO-DESTINATION.json",**pin((group/"INDEPENDENT-SOURCE-TO-DESTINATION.json").read_bytes()),count=len(mappings)),
  log_semantics=dict(path="RECOVERY-READBACK.json",**pin((group/"RECOVERY-READBACK.json").read_bytes())),
  independent_source_tree=dict(path=str(indpath.relative_to(group)),**pin(indpath.read_bytes())),
  independent_pending_snapshot_superseded=True,pending_snapshot_field="RECOVERY-READBACK.json.independent_recovered_tree_review",
  all_archive_evidence_input_index_preserved=True,source_only_in_archive=True,
  source_counts_are_regular_files=True,source_directory_count_not_used_as_source_file_count=True,
  source47_original_fixture_comparison_not_redone=True,
  full_original_sources_in_archive=own["source_files"],archive_members=own["regular_members"],
  old_lost_formal_artifacts_recreated=False,old_pins_only_historical=True,
  rust_or_formatter_rerun=False,active_future_logs_read=False,original_evidence_modified=False,
  actual_old_gate_not_rerun_or_requalified=True,scope_and_scientific_dispositions_unchanged=True,
  note="Both readers are new post-recovery audits. Historical pending fields and stale native export-v1 fields remain unchanged in their original snapshots.",
  closure_gaps=[])
 put(group/"RECOVERY-CLOSURE.json",enc(closure))
 binary=[]
 for path in sorted(group.rglob("*")):
  if not path.is_file():continue
  b=path.read_bytes()
  try:b.decode("utf-8");is_binary=False
  except UnicodeDecodeError:is_binary=True
  if not is_binary:continue
  p=pin(b);row=dict(path=str(path.relative_to(group)),**p,prefer_existing_git_blob=True,
   git_action="REUSE_ROOT_REGISTERED_BLOB" if p["git_blob"] in KNOWN else "ROOT_RESOLVE_OR_REGISTER_EXACT_BLOB",
   uploaded_by_this_audit=False)
  if path.suffix==".gz":
   row["gzip_mtime_zero"]=b[4:8]==b"\0\0\0\0"
   row["decompressed"]=pin(gzip.decompress(b))
  binary.append(row)
 plan=dict(schema="hepta.recovered-evidence-binary-plan.v1",stage=stage,binary_path_count=len(binary),
  unique_blob_count=len({x["git_blob"] for x in binary}),entries=binary,
  original_archives_copied_unchanged=True,git_upload_performed=False,
  shared_framework_gzip_is_new_recovery_input="73327f14034f61fb143ea954998854121b486385")
 put(group/"BINARY-PLAN.json",enc(plan))
 manifest_entries=[]
 for path in sorted(group.rglob("*")):
  if path.is_file() and path.name!="ATTACHMENT-MANIFEST.json":
   manifest_entries.append(dict(path=str(path.relative_to(group)),**pin(path.read_bytes())))
 manifest=dict(schema="hepta.recovered-evidence-attachment-manifest.v1",stage=stage,state="CLOSED_NEW_RECOVERY_GROUP",
  entries=manifest_entries,file_count_excluding_this_manifest=len(manifest_entries),
  stored_bytes_excluding_this_manifest=sum(x["bytes"] for x in manifest_entries),
  original_artifact_mappings=len(originals),independent_artifact_mappings=len(mappings),
  closure_gaps=[],self_hash_excluded=True,old_manifest_reconstructed=False)
 put(group/"ATTACHMENT-MANIFEST.json",enc(manifest))
 allfiles=[p for p in group.rglob("*") if p.is_file()]
 assert len(allfiles)==len(manifest_entries)+1
 for x in manifest_entries:assert pin((group/x["path"]).read_bytes())=={k:x[k] for k in ("bytes","sha256","git_blob")}
 return dict(stage=stage,path=str(group.relative_to(w)),files=len(allfiles),stored_bytes=sum(p.stat().st_size for p in allfiles),
  manifest=pin((group/"ATTACHMENT-MANIFEST.json").read_bytes()),closure=pin((group/"RECOVERY-CLOSURE.json").read_bytes()),
  binary_plan=pin((group/"BINARY-PLAN.json").read_bytes()),binary_paths=len(binary),unique_binary_blobs=len({x["git_blob"] for x in binary}),closure_gaps=[])
if __name__=="__main__":
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--workspace",type=Path,required=True);ap.add_argument("--stage",type=int,choices=[20,21,22],required=True);a=ap.parse_args()
 print(json.dumps(seal(a.workspace,a.stage),ensure_ascii=False,indent=2))
