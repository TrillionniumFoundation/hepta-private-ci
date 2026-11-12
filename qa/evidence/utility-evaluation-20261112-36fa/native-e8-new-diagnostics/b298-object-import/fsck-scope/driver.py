import os,sys,json,hashlib,pathlib,stat,fcntl,subprocess,gzip,datetime,re,traceback
sys.dont_write_bytecode=True
P=INPUT;R=pathlib.Path(P["records"]);repo=pathlib.Path(P["repo"]);old=pathlib.Path(P["old_records"])
env={**os.environ,"GIT_OPTIONAL_LOCKS":"0","GIT_NO_LAZY_FETCH":"1"}
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(t,b):return hashlib.sha1(t.encode()+b" "+str(len(b)).encode()+bytes([0])+b).hexdigest()
def put(name,b):
 if isinstance(b,str):b=b.encode()
 with open(R/name,"xb") as f:f.write(b)
 return {"path":str(R/name),"bytes":len(b),"sha256":sha(b),"git_blob":oid("blob",b)}
def js(name,o):return put(name,json.dumps(o,sort_keys=True,indent=2)+"\n")
def git(args,data=None,check=True):
 q=subprocess.run(["git","-C",str(repo),*args],input=data,env=env,capture_output=True,timeout=120)
 if check and q.returncode:raise RuntimeError("git "+repr(args)+" failed: "+q.stderr.decode(errors="replace"))
 return q
def source(label):
 names=sorted(set(git(["ls-files","-z"]).stdout.split(bytes([0]))+git(["ls-files","--others","--exclude-standard","-z"]).stdout.split(bytes([0])))-{b""});rows=[]
 for name in names:
  p=repo/os.fsdecode(name);st=p.lstat()
  if stat.S_ISLNK(st.st_mode):b=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(st.st_mode):b=p.read_bytes();mode="100755" if st.st_mode&0o111 else "100644"
  else:raise RuntimeError("unexpected source type")
  rows.append({"path":os.fsdecode(name),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":oid("blob",b)})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode();put(label+".files.json.gz",gzip.compress(raw,mtime=0))
 info={"sha":git(["rev-parse","HEAD"]).stdout.decode().strip(),"tree":git(["rev-parse","HEAD^{tree}"]).stdout.decode().strip(),"status":git(["status","--porcelain=v1","--untracked-files=all"]).stdout.decode(),"files":len(rows),"inventory_sha256":sha(raw)}
 js(label+".json",info)
 if info!={"sha":P["source_sha"],"tree":P["source_tree"],"status":"","files":14741,"inventory_sha256":P["source_inventory_sha256"]}:raise RuntimeError("source differs")
 return info
R.mkdir(mode=0o700)
put("driver.py",P["driver"]);js("INPUT.json",P)
result={"started_at":now(),"status":"started","qualification":False,"git_objects_written":False,"source_mutated":False,"scope":"Read-only current-tree object availability and original full-fsck failure analysis; does not replace or mark the failed fsck as passing"}
lock=open(P["source_lock"],"rb");fcntl.flock(lock,fcntl.LOCK_SH)
before=None
try:
 before=source("source-before");result["source_before"]=before
 index=pathlib.Path(git(["rev-parse","--path-format=absolute","--git-path","index"]).stdout.decode().strip());head=pathlib.Path(git(["rev-parse","--path-format=absolute","--git-path","HEAD"]).stdout.decode().strip())
 ib=index.read_bytes();hb=head.read_bytes()
 result["index_before_sha256"]=sha(ib);result["head_before_sha256"]=sha(hb)
 result["is_shallow_repository"]=git(["rev-parse","--is-shallow-repository"]).stdout.decode().strip()
 objs={};snapshots={}
 for label,commit in P["snapshots"].items():
  tree=git(["rev-parse",commit+"^{tree}"]).stdout.decode().strip()
  q=git(["ls-tree","-r","-t","--full-tree","-z",tree])
  put(label+".ls-tree.raw.gz",gzip.compress(q.stdout,mtime=0))
  entries=[];links=[]
  objs[commit]="commit";objs[tree]="tree"
  for line in q.stdout.split(bytes([0])):
   if not line:continue
   metadata,path=line.split(b"\t",1);mode,kind,s=metadata.decode().split()
   row={"path":os.fsdecode(path),"mode":mode,"type":kind,"sha":s}
   if mode=="160000":links.append(row);continue
   if s in objs and objs[s]!=kind:raise RuntimeError("object type conflict")
   objs[s]=kind;entries.append(row)
  snapshots[label]={"commit":commit,"tree":tree,"entries":entries,"gitlinks":links}
 readbacks=json.loads((old/"OBJECT_READBACKS.json").read_text())
 if len(readbacks)!=244:raise RuntimeError("imported object record count")
 for obj in readbacks:
  s=obj["sha"];kind=obj["type"]
  if s in objs and objs[s]!=kind:raise RuntimeError("import object type conflict")
  objs[s]=kind
 data=("".join(s+"\n" for s in sorted(objs))).encode()
 check=git(["cat-file","--batch-check=%(objectname) %(objecttype) %(objectsize)"],data)
 put("object-availability.raw.gz",gzip.compress(check.stdout,mtime=0));put("object-availability.stderr",check.stderr)
 observations={}
 for line in check.stdout.decode().splitlines():
  pieces=line.split()
  if len(pieces)==2 and pieces[1]=="missing":observations[pieces[0]]={"present":False}
  elif len(pieces)==3:
   s,kind,size=pieces
   if kind!=objs[s]:raise RuntimeError("available object wrong type")
   observations[s]={"present":True,"type":kind,"bytes":int(size)}
  else:raise RuntimeError("unrecognized batch-check output")
 if set(observations)!=set(objs):raise RuntimeError("object inventory response differs")
 result["object_inventory"]={"unique":len(observations),"missing":sum(not o["present"] for o in observations.values())}
 summaries={}
 for label,snapshot in snapshots.items():
  members={snapshot["commit"],snapshot["tree"],*[e["sha"] for e in snapshot["entries"]]}
  missing=[s for s in sorted(members) if not observations[s]["present"]]
  summaries[label]={"commit":snapshot["commit"],"tree":snapshot["tree"],"paths":len(snapshot["entries"]),"unique_objects":len(members),"gitlinks":snapshot["gitlinks"],"missing_objects":missing,"all_required_objects_present":not missing}
  js(label+".object-availability.json",{"summary":summaries[label],"entries":snapshot["entries"],"missing_objects":missing})
 result["snapshots"]=summaries
 result["imported_244_objects"]={"count":len(readbacks),"missing":[o["sha"] for o in readbacks if not observations[o["sha"]]["present"]]}
 raw=(old/"fsck.stdout.log").read_bytes();err=(old/"fsck.stderr.log").read_bytes()
 if len(raw)!=27453910 or sha(raw)!="b17a02343f862f1425fe2ecd07669212d6ca18e3524755a1d52ebb360e5cfae9" or len(err)!=896 or sha(err)!="4a562ea1cf30471f5a2fa1ce0f61f11e2c9b44db29645e9f039615cfba10ec2a":raise RuntimeError("original fsck raw differs")
 packed=gzip.compress(raw,mtime=0);put("fsck.stdout.log.gz",packed)
 parts=[]
 for offset in range(0,len(packed),262144):
  piece=packed[offset:offset+262144];info=put("fsck.stdout.log.gz.part-"+str(len(parts)).zfill(3),piece);info["offset"]=offset;parts.append(info)
 patterns={}
 for line in raw.decode().splitlines():
  pattern=re.sub("[0-9a-f]{40}","<object>",line)
  patterns[pattern]=patterns.get(pattern,0)+1
 ids=set(re.findall(r"\b[0-9a-f]{40}\b",raw.decode()))
 result["fsck_observation"]={"original_exit":3,"original_stdout_bytes":len(raw),"original_stdout_sha256":sha(raw),"original_stderr_bytes":len(err),"original_stderr_sha256":sha(err),"gzip_bytes":len(packed),"gzip_sha256":sha(packed),"parts":parts,"line_patterns":sorted(patterns.items(),key=lambda x:(-x[1],x[0])),"all_object_ids_mentioned":len(ids),"mentioned_imported_objects":sorted(ids&{o["sha"] for o in readbacks}),"mentioned_snapshot_members":{label:sorted(ids&{v["commit"],v["tree"],*[e["sha"] for e in v["entries"]]}) for label,v in snapshots.items()}}
 js("FSCK_RETENTION_MANIFEST.json",result["fsck_observation"])
 if index.read_bytes()!=ib or head.read_bytes()!=hb:raise RuntimeError("default index or HEAD changed")
 result["status"]="read_only_scope_observation_retained"
except BaseException as e:
 result["status"]="failed";result["error"]=type(e).__name__+": "+str(e);put("exception.txt",traceback.format_exc())
finally:
 try:
  result["source_after"]=source("source-after")
  if before and result["source_after"]!=before:raise RuntimeError("source differs after")
 except BaseException as e:result["status"]="failed";result["source_after_error"]=str(e)
 result["finished_at"]=now();js("RESULT.json",result);print(json.dumps(result,sort_keys=True),flush=True)
 fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="read_only_scope_observation_retained" else 1)
