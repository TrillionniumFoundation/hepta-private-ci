from pathlib import Path
import base64,hashlib,json,os,re,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="a6717d7228045e6cb60532966f06e6e02c4a6abe"
tree="647b9e78151299c1e7de455eae9c530ca93b28c9"
frames=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/static-frames-a6717d722804-v1")
elf_path="/data/hepta-learn-ce434-runtime-20261112-v2/target/debug/deps/codex_hepta_agentd-0bb720b95785b5fd"
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/static-frame-export-a6717d722804-full-v1")
branch="codex/learn-a671-static-frame-evidence-ce434-20261112-v1"
prefix="qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/static-frames-a671/"
env=dict(os.environ)
def git(*args,input=None):
 command=["git",*args]
 process=subprocess.Popen(command,cwd=repo,env=env,stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:stdout,stderr=process.communicate(input)
 except BaseException:
  try:process.communicate()
  finally:process.wait()
  raise
 process.wait()
 if process.returncode:raise subprocess.CalledProcessError(process.returncode,command,output=stdout,stderr=stderr)
 return stdout.decode().strip()
def remote(*args):
 return git("-c","http.proxy=socks5h://127.0.0.1:11080","-c","http.lowSpeedLimit=1","-c","http.lowSpeedTime=30",*args)
def sha(b):return hashlib.sha256(b).hexdigest()
def identity(s):
 return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def read(p,maximum=67108864):
 before=p.lstat()
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or before.st_size>maximum:
  raise RuntimeError("original evidence type/owner/size differs")
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
 with os.fdopen(fd,"rb") as stream:
  first=os.fstat(stream.fileno())
  if identity(first)!=identity(before):raise RuntimeError("original evidence replaced before read")
  b=stream.read(maximum+1)
  after=os.fstat(stream.fileno())
 if identity(first)!=identity(after) or identity(first)!=identity(p.lstat()) or len(b)!=first.st_size:
  raise RuntimeError("original evidence changed during bounded read")
 return b
def clean():
 if git("rev-parse","HEAD")!=source or git("rev-parse","HEAD^{tree}")!=tree or git("status","--porcelain=v1","--untracked-files=all"):
  raise RuntimeError("fixed source changed")
def snapshot():
 directory=frames.lstat()
 if not stat.S_ISDIR(directory.st_mode) or directory.st_uid!=os.getuid():
  raise RuntimeError("fixed diagnostic directory differs")
 result_bytes=read(frames/"result.json")
 symbols_bytes=read(frames/"symbols.json")
 result=json.loads(result_bytes);symbols=json.loads(symbols_bytes)
 expected_source={"head":source,"tree":tree,"status":""}
 if result["state"]!="observed_static_only" or result["source_sha"]!=source or result["source_tree"]!=tree:
  raise RuntimeError("diagnostic result source/state differs")
 if result["source_before"]!=expected_source or result["source_after"]!=expected_source:
  raise RuntimeError("diagnostic source was not fixed clean before and after")
 for key in ("target_executed","process_attached","signals_sent","authority_created"):
  if result.get(key) is not False:raise RuntimeError("diagnostic effect flag differs")
 if result.get("tests_executed")!=0:raise RuntimeError("diagnostic test count differs")
 if result["elf_path"]!=elf_path:
  raise RuntimeError("observed ELF path differs")
 observed=result["elf_observation"]
 digest=observed["sha256"]
 if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest) or result["elf_sha256_after"]!=digest:
  raise RuntimeError("recorded ELF before/after hash differs")
 if observed.get("preexisting_hash_pin") is not None:
  raise RuntimeError("diagnostic invented an earlier ELF hash pin")
 if not stat.S_ISREG(observed["identity"]["st_mode"]):
  raise RuntimeError("diagnostic ELF identity is not a regular file")
 terminals=(
  ("native_terminal","/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-a6717d722804-v1/result.json","98348f69ead79e7a2428680b822b5d419784e20f99de12c2f0d0f8892f5b1f71",51057),
  ("outer_terminal","/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/unified-a6717d722804-validation-v1/result.json","3db7ed1f0760fadbf50a741600f9d877767ef26fb51bed7ee935d3b46c17ce60",2396),
 )
 for key,path,expected_hash,size in terminals:
  pin=result[key]
  if pin["path"]!=path or pin["sha256"]!=expected_hash or pin["identity"]["st_size"]!=size:
   raise RuntimeError("original terminal pin differs")
 functions=result["functions"]
 if not isinstance(functions,list) or not 1<=len(functions)<=64 or result["selected_symbol_count"]!=len(functions):
  raise RuntimeError("diagnostic symbol bound/count differs")
 projection=[{key:entry[key] for key in ("address","size","names","original_mangled_names")} for entry in functions]
 if symbols!=projection:
  raise RuntimeError("complete symbol data differs from completed function records")
 pending=[("result.json",result_bytes),("symbols.json",symbols_bytes)]
 for key,name in (("nm_demangled","nm-demangled.stderr"),("nm_raw","nm-raw.stderr")):
  if result[key]["exit_code"]!=0 or result[key]["stderr_file"]!=name:
   raise RuntimeError("original nm result differs")
  pending.append((name,read(frames/name)))
 for index,entry in enumerate(functions):
  if entry["size"]==0:
   if entry.get("state")!="unavailable_zero_symbol_size" or "prologue_file" in entry:
    raise RuntimeError("zero-size symbol record differs")
   continue
  name="prologue-"+str(index).zfill(3)+".txt"
  if entry.get("prologue_file")!=name or not re.fullmatch(r"prologue-[0-9]{3}\.txt",name):
   raise RuntimeError("prologue name/index differs")
  if entry["exit_code"]!=0 or entry["inspected_address_bytes"]!=min(entry["size"],512) or not 1<=entry["inspected_address_bytes"]<=512:
   raise RuntimeError("prologue command or bounded range differs")
  expected_hash=entry["prologue_sha256"]
  if not isinstance(expected_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",expected_hash):
   raise RuntimeError("prologue hash is invalid")
  raw=read(frames/name,524288)
  if len(raw)!=entry["prologue_bytes"] or sha(raw)!=expected_hash:
   raise RuntimeError("complete original prologue differs")
  pending.append((name,raw))
  stderr_name="prologue-"+str(index).zfill(3)+".stderr"
  pending.append((stderr_name,read(frames/stderr_name,524288)))
 if read(frames/"result.json")!=result_bytes or read(frames/"symbols.json")!=symbols_bytes or identity(frames.lstat())!=identity(directory):
  raise RuntimeError("diagnostic snapshot changed while reading")
 return result,pending
if out.exists() or out.is_symlink():raise RuntimeError("evidence exporter exists; reconcile original key")
clean()
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
if re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)!=["127.0.0.1:11080"]:
 raise RuntimeError("existing forward differs")
out.mkdir(mode=0o700)
if remote("ls-remote","--heads","origin","refs/heads/"+branch):
 raise RuntimeError("new evidence branch already exists")
result,pending=snapshot()
clean()
original_index=env.get("GIT_INDEX_FILE")
env["GIT_INDEX_FILE"]=str(out/"terminal.index")
try:
 git("read-tree",source)
 records=[]
 def insert(path,raw):
  blob=git("hash-object","-w","--stdin",input=raw)
  if blob!=hashlib.sha1(("blob "+str(len(raw))+"\0").encode()+raw).hexdigest():raise RuntimeError("evidence blob differs")
  git("update-index","--add","--cacheinfo","100644,"+blob+","+path)
  return {"path":path,"bytes":len(raw),"sha256":sha(raw),"git_blob":blob}
 for name,raw in pending:
  record={"name":name,"original_bytes":len(raw),"original_sha256":sha(raw),"complete_file":True,"parts":[]}
  path=prefix+name
  if len(raw)<=524288:
   raw.decode("utf-8")
   record["encoding"]="utf-8"
   record["parts"].append(insert(path,raw))
  else:
   record["encoding"]="base64-parts"
   for index,start in enumerate(range(0,len(raw),393216)):
    record["parts"].append(insert(path+".part-"+str(index).zfill(4)+".base64",base64.b64encode(raw[start:start+393216])+b"\n"))
  records.append(record)
 manifest={"schema":"original-a671-static-frame-observation-export-v1","source_sha":source,"source_tree":tree,"observed_unix_ms":int(time.time()*1000),"diagnostic_state":result["state"],"selected_symbol_count":result["selected_symbol_count"],"elf_path":elf_path,"elf_sha256":result["elf_observation"]["sha256"],"files":records,"scope":"Copies only already completed diagnostic evidence. No ELF read, target/tool/test rerun, source edit, process attachment or signal. Original finite prologues are static observations, not peak-stack measurements or native passes. No ordinary acceptance is claimed.","tests_executed":0,"ordinary_acceptance":{"positive":0,"no_update":0,"fresh_C":0,"daemon_root_cold_restart":0}}
 manifest_bytes=(json.dumps(manifest,indent=2)+"\n").encode()
 insert(prefix+"export-manifest.json",manifest_bytes)
 result_tree=git("write-tree")
 commit=git("commit-tree",result_tree,"-p",source,input=b"LEARN: retain original a671 bounded static frame evidence\n")
finally:
 if original_index is None:env.pop("GIT_INDEX_FILE",None)
 else:env["GIT_INDEX_FILE"]=original_index
clean()
(out/"terminal.json").write_text(json.dumps({"commit":commit,"tree":result_tree,"branch":branch,"manifest":manifest},indent=2)+"\n")
if remote("ls-remote","--heads","origin","refs/heads/"+branch):
 raise RuntimeError("new evidence branch was concurrently created")
remote("push","--porcelain","origin",commit+":refs/heads/"+branch)
if remote("ls-remote","--heads","origin","refs/heads/"+branch).split()[0]!=commit:raise RuntimeError("published evidence differs")
clean()
print(json.dumps({"state":"evidence-published","commit":commit,"tree":result_tree,"branch":branch,"diagnostic_state":result["state"],"tests_executed":0}),flush=True)
