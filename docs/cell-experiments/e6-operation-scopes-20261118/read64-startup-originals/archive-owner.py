import pathlib,stat,os,json,hashlib,tarfile,time,resource,traceback
B=pathlib.Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
O=B/"read64-startup-originals-1"
assert not O.exists();O.mkdir()
start=time.monotonic();u=resource.getrusage(resource.RUSAGE_SELF)
def sha(p):
 with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
r={"successful":False,"scope":"Completed original startup edit1-7, contract1-5, source-probe1-4, freeze1-2 and failed native7; active source-probe5 is excluded. Original source/native failures and real costs are retained without turning them into adoption.","started_at_ns":str(time.time_ns()),"new_native_cases":0,"new_model_calls":0,"automatic_retry":False,"native_adoption":False,"complete_NoUpdate":False,"full_system_cost_known":False}
try:
 roots=[B/("read64-startup-edit-"+str(i)) for i in range(1,8)]
 roots += [B/("read64-startup-contract-edit-"+str(i)) for i in range(1,6)]
 roots += [B/("read64-startup-source-probe-"+str(i)) for i in range(1,5)]
 roots += [B/("read64-startup-frozen-source-"+str(i)) for i in range(1,3)]
 roots += [B/"native-validation-7",B/"retired-build-output-native7-1/RESULT.json"]
 roots += [p for p in B.iterdir() if p.is_file() and ("startup" in p.name or "native7" in p.name) and "probe5" not in p.name]
 roots=list(dict.fromkeys(roots))
 rows=[];missing=[];special=[]
 for root in roots:
  if not root.exists():missing.append(str(root));continue
  paths=[root] if root.is_file() else sorted(root.rglob("*"))
  for p in paths:
   st=p.lstat()
   if stat.S_ISDIR(st.st_mode):continue
   if not stat.S_ISREG(st.st_mode):special.append({"path":str(p),"mode":oct(st.st_mode)});continue
   assert not p.is_relative_to(B/"read64-startup-source-probe-5")
   rows.append({"path":str(p),"member":str(p.relative_to(B)),"bytes":st.st_size,"sha256":sha(p),"uid":st.st_uid,"gid":st.st_gid,"mode":oct(st.st_mode&0o7777)})
 rows=sorted({x["path"]:x for x in rows}.values(),key=lambda x:x["member"])
 idx=(json.dumps(rows,indent=2)+"\n").encode();(O/"INDEX.json").write_bytes(idx)
 assert not missing,missing
 assert any(x["member"]=="read64-startup-contract-deployment-failure-1.json" for x in rows)
 archive=O/"complete-read64-startup-through-native7-originals.tar.xz"
 print(json.dumps({"status":"archiving","original_files":len(rows),"original_bytes":sum(x["bytes"] for x in rows)}),flush=True)
 with tarfile.open(archive,"w:xz") as t:
  for row in rows:t.add(row["path"],arcname=row["member"],recursive=False)
 with tarfile.open(archive,"r:xz") as t:
  assert t.getnames()==[x["member"] for x in rows]
  for row in rows:
   raw=t.extractfile(row["member"]).read()
   assert len(raw)==row["bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
   assert sha(pathlib.Path(row["path"]))==row["sha256"]
 r.update(successful=True,roots=[str(p) for p in roots],missing_original_paths=missing,non_regular_entries_not_archived=special,original_regular_files=len(rows),original_bytes=sum(x["bytes"] for x in rows),archive=str(archive),archive_bytes=archive.stat().st_size,archive_sha256=sha(archive),index_sha256=hashlib.sha256(idx).hexdigest(),all_members_verified=True,all_originals_unchanged=True)
except BaseException as e:
 r["error"]=repr(e);(O/"ERROR.txt").write_text(traceback.format_exc())
finally:
 a=resource.getrusage(resource.RUSAGE_SELF)
 r.update(finished_at_ns=str(time.time_ns()),wall_seconds=time.monotonic()-start,self_user_cpu_seconds=a.ru_utime-u.ru_utime,self_system_cpu_seconds=a.ru_stime-u.ru_stime)
 (O/"RESULT.json").write_text(json.dumps(r,indent=2)+"\n")
 print(json.dumps({**r,"result_sha256":sha(O/"RESULT.json")}),flush=True)
raise SystemExit(0 if r["successful"] else 1)
