import pathlib,stat,os,re,json,hashlib,tarfile,time,resource,traceback,fcntl
b=pathlib.Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
out=b/"noupdate6-retained-originals-1"
assert not out.exists()
out.mkdir()
start=time.monotonic();usage=resource.getrusage(resource.RUSAGE_SELF)
def digest(p):
 with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
r={"scope":"Original completed native6 and failed NoUpdate6 files, original physical protected sources and retained process/runtime fixtures; no new native or model execution.","successful":False,"automatic_retry":False,"native_adoption":False,"complete_NoUpdate":False,"new_native_cases":0,"new_model_calls":0,"source_mutation":False,"started_at_ns":str(time.time_ns()),"unknown_costs":["whole-system concurrent CPU/RSS","physical energy","physical network bytes","physical storage byte-seconds","provider charges"]}
lock=(b/"noupdate6-archive-owner.lock").open("a+b")
try:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 terminal=b/"complete-noupdate-6/result.json"
 assert digest(terminal)=="10b86cd366bb6077841fafc585a01ab8d4bfc45e101623e3ac3ce5cabd4fbe82"
 native=b/"native-validation-6/RESULT.json"
 assert digest(native)=="37a4a84f25c751c12e51fd95e399233fafd97af71046ce7a65ca8749b547ada5"
 previous=json.loads(terminal.read_text())
 assert previous.get("finished_at_ns") or previous.get("finished_unix_ns") or previous.get("owner_wall_seconds")
 xml=b/"complete-noupdate-6/ordinary-post-a-no-update-fresh-native-observed-0.xml"
 assert digest(xml)=="813e96fd3dd4c953255b6e0627ec1d3bec5eda7bfcc8afa03dabf7945fefe1c5"
 raw=xml.read_text()
 rundir=pathlib.Path("/run/hepta-daemon-learning-root-e6-scopes-bc16-noupdate-6")
 roots=[b/"complete-noupdate-6",b/"native-validation-6",rundir]
 for s in re.findall(r"ORDINARY_Q24_ORIGINAL_CHILD_LOGS=([^\s<]+)",raw):roots.append(pathlib.Path(s))
 for s in re.findall(r"ORDINARY_Q24_RETAINED_DIRECTORY[^\n<]* path=([^\s<]+)",raw):roots.append(pathlib.Path(s))
 roots=list(dict.fromkeys(roots));missing=[];special=[];files={}
 def retain(p):
  st=p.lstat()
  if not stat.S_ISREG(st.st_mode):special.append({"path":str(p),"mode":oct(st.st_mode)});return
  files[str(p)]={"path":str(p),"member":str(p).lstrip("/"),"bytes":st.st_size,"sha256":digest(p),"uid":st.st_uid,"gid":st.st_gid,"mode":oct(st.st_mode&0o7777)}
 for root in roots:
  if not root.exists():missing.append(str(root));continue
  assert str(root).startswith((str(b),str(rundir),"/tmp/ordinary-","/run/oq-"))
  if root.is_file():retain(root);continue
  for here,dirs,names in os.walk(root,followlinks=False):
   for name in names:retain(pathlib.Path(here)/name)
 rows=sorted(files.values(),key=lambda r:r["path"])
 for required in ["/run/oq-m4BX4c","/tmp/ordinary-original-independent-b-1FXADC","/tmp/ordinary-q24-original-process-BCKnmi","/tmp/ordinary-q24-original-process-VbXARi","/tmp/ordinary-q24-original-process-23prrq","/tmp/ordinary-q24-original-process-VbFtMS","/tmp/ordinary-q24-original-process-eTLHrb","/tmp/ordinary-q24-original-process-WLLM3C"]:
  assert any(row["path"].startswith(required+"/") for row in rows),required
 idx=(json.dumps(rows,indent=2)+"\n").encode();(out/"INDEX.json").write_bytes(idx)
 archive=out/"complete-native6-noupdate6-originals.tar.xz"
 r.update(roots=[str(p) for p in roots],missing_original_paths=missing,missing_unmounted_bind_aliases_expected=True,non_regular_entries_not_archived=special,original_regular_files=len(rows),original_bytes=sum(x["bytes"] for x in rows),archive=str(archive),index_sha256=hashlib.sha256(idx).hexdigest())
 print(json.dumps({"status":"archiving-originals","files":len(rows),"original_bytes":r["original_bytes"],"missing":missing}),flush=True)
 with tarfile.open(archive,"w:xz") as t:
  for row in rows:t.add(row["path"],arcname=row["member"],recursive=False)
 with tarfile.open(archive,"r:xz") as t:
  assert t.getnames()==[x["member"] for x in rows]
  for row in rows:
   raw=t.extractfile(row["member"]).read()
   assert len(raw)==row["bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
   assert digest(pathlib.Path(row["path"]))==row["sha256"]
 fixture=[row for row in rows if row["path"].startswith(str(rundir)) or row["path"].startswith(("/tmp/ordinary-","/run/oq-"))]
 (out/"FIXTURE_FILES.json").write_text(json.dumps(fixture,indent=2)+"\n")
 r.update(successful=True,archive_bytes=archive.stat().st_size,archive_sha256=digest(archive),all_members_verified=True,all_originals_unchanged=True)
except BaseException as error:
 r.update(error=repr(error));(out/"ERROR.txt").write_text(traceback.format_exc())
finally:
 end=resource.getrusage(resource.RUSAGE_SELF)
 r.update(finished_at_ns=str(time.time_ns()),wall_seconds=time.monotonic()-start,self_user_cpu_seconds=end.ru_utime-usage.ru_utime,self_system_cpu_seconds=end.ru_stime-usage.ru_stime)
 (out/"RESULT.json").write_text(json.dumps(r,indent=2)+"\n")
 for p in [out,*out.rglob("*")]:os.chown(p,1000,1000,follow_symlinks=False)
 lock.close()
 print(json.dumps({**r,"result_sha256":digest(out/"RESULT.json")}),flush=True)
raise SystemExit(0 if r["successful"] else 1)
