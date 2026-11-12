import os,sys,json,hashlib,pathlib,struct,mmap,subprocess,shutil,datetime,fcntl,traceback
sys.dont_write_bytecode=True
P=INPUT
R=pathlib.Path(P["records"])
REPO=pathlib.Path(P["repo"])
B=pathlib.Path(P["binary"])
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha_file(p):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for c in iter(lambda:f.read(1048576),b""):h.update(c)
 return h.hexdigest()
def put(name,b):
 if isinstance(b,str): b=b.encode()
 with open(R/name,"xb") as f:f.write(b)
 return {"path":str(R/name),"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()}
def js(name,o): return put(name,json.dumps(o,indent=2,sort_keys=True)+"\n")
def git(a):
 q=subprocess.run(["git","-C",str(REPO),*a],capture_output=True,env={**os.environ,"GIT_OPTIONAL_LOCKS":"0"},timeout=30)
 if q.returncode:raise RuntimeError("git failed "+repr(a)+": "+q.stderr.decode(errors="replace"))
 return q.stdout.decode()
def identity():
 st=B.stat()
 if not B.is_file() or B.is_symlink() or st.st_nlink!=1:raise RuntimeError("bad pinned ELF type")
 h=sha_file(B)
 if st.st_size!=281625080 or h!=P["binary_sha256"]:raise RuntimeError("pinned ELF identity differs")
 return {"path":str(B),"bytes":st.st_size,"sha256":h,"stat":[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]}
R.mkdir(mode=0o700)
result={"started_at":now(),"qualification":False,"tests_started":False,"cargo_started":False,"binary_executed":False,"source_mutated":False,"status":"started"}
js("DRIVER_INPUT.json",P);put("driver.py",P["driver"])
lock=open(P["source_lock"],"rb")
fcntl.flock(lock,fcntl.LOCK_SH)
try:
 result["binary_before"]=identity()
 result["source_before"]={"sha":git(["rev-parse","HEAD"]).strip(),"tree":git(["rev-parse","HEAD^{tree}"]).strip(),"status":git(["status","--porcelain=v1","--untracked-files=no"])}
 if result["source_before"]!={"sha":P["source_sha"],"tree":P["source_tree"],"status":""}:raise RuntimeError("source identity differs")
 objdump=shutil.which("objdump")
 if not objdump:raise RuntimeError("objdump unavailable")
 q=subprocess.run([objdump,"--version"],capture_output=True,timeout=10)
 put("objdump-version.stdout",q.stdout);put("objdump-version.stderr",q.stderr)
 if q.returncode:raise RuntimeError("objdump version failed")
 with open(B,"rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
  e=struct.unpack_from("<16sHHIQQQIHHHHHH",m,0)
  if e[0][:4]!=bytes.fromhex("7f454c46") or e[0][4:6]!=bytes([2,1]) or e[2]!=62:raise RuntimeError("unsupported ELF")
  ph=[]
  for i in range(e[10]):
   v=struct.unpack_from("<IIQQQQQQ",m,e[5]+i*e[9])
   ph.append(dict(zip(["type","flags","offset","vaddr","paddr","filesz","memsz","align"],v)))
  zero=[v for v in ph if v["type"]==1 and v["offset"]==0]
  if len(zero)!=1:raise RuntimeError("ambiguous offset-zero LOAD")
  bias=int(P["mapped_offset_zero_start"],16)-(zero[0]["vaddr"]&~4095)
  sections=[]
  for i in range(e[12]):sections.append(struct.unpack_from("<IIQQQQIIQQ",m,e[6]+i*e[11]))
  funcs=[]
  for s in sections:
   if s[1]!=2:continue
   strings=sections[s[6]]
   ss=m[strings[4]:strings[4]+strings[5]]
   if s[9]!=24:raise RuntimeError("unsupported symbol entry")
   for pos in range(s[4],s[4]+s[5],s[9]):
    no,info,other,index,val,size=struct.unpack_from("<IBBHQQ",m,pos)
    if info&15!=2 or not size:continue
    name=ss[no:ss.find(b"\x00",no)].decode("utf-8",errors="replace")
    funcs.append({"name":name,"value":val,"size":size})
  rows=[]
  for target in P["frames"]:
   pc=int(target["pc"],16); rva=pc-bias
   matches=[s for s in funcs if s["value"]<=rva<s["value"]+s["size"]]
   if not matches:raise RuntimeError("no exact covering symbol frame "+str(target["frame"])+" RVA "+hex(rva))
   vals={(s["value"],s["size"]) for s in matches}
   if len(vals)!=1:raise RuntimeError("overlapping distinct symbols for "+str(target["frame"]))
   s=matches[0]
   rows.append({**target,"rva":hex(rva),"function_rva":hex(s["value"]),"function_size":s["size"],"offset_in_function":rva-s["value"],"mangled_aliases":[v["name"] for v in matches]})
  result["elf"]={"elf_type":e[1],"machine":e[2],"mapped_offset_zero_start":P["mapped_offset_zero_start"],"load_bias":hex(bias),"program_headers":ph,"symtab_function_count":len(funcs),"observed_frame_count":len(rows)}
  js("FRAME_SYMBOLS.json",rows)
  outputs=[]
  seen={}
  for row in rows:
   v=int(row["function_rva"],16)
   if v in seen:
    row["disassembly"]=seen[v];continue
   end=v+min(row["function_size"],256)
   args=[objdump,"-d","--demangle=rust","--no-show-raw-insn","--start-address="+hex(v),"--stop-address="+hex(end),str(B)]
   q=subprocess.run(args,capture_output=True,timeout=20)
   if len(q.stdout)>32768 or len(q.stderr)>8192:raise RuntimeError("bounded disassembly exceeded output guard")
   name="frame-"+str(row["frame"]).zfill(2)+"-prologue.txt"
   info=put(name,q.stdout)
   out={"command":args,"returncode":q.returncode,"stdout":info,"stderr":put(name+".stderr",q.stderr)}
   outputs.append(out);row["disassembly"]=info;seen[v]=info
   if q.returncode:raise RuntimeError("objdump bounded disassembly failed")
  js("FRAME_ANALYSIS.json",{"elf":result["elf"],"frames":rows,"commands":outputs})
  combined="".join("\n===== frame "+str(r["frame"])+" "+r["symbol"]+" RVA "+r["rva"]+" =====\n"+(R/pathlib.Path(r["disassembly"]["path"]).name).read_text() for r in rows)
  result["combined_disassembly"]=put("BOUNDED_PROLOGUES.txt",combined)
 result["binary_after"]=identity()
 result["source_after"]={"sha":git(["rev-parse","HEAD"]).strip(),"tree":git(["rev-parse","HEAD^{tree}"]).strip(),"status":git(["status","--porcelain=v1","--untracked-files=no"])}
 if result["binary_after"]!=result["binary_before"] or result["source_after"]!=result["source_before"]:raise RuntimeError("postcheck differs")
 result["status"]="bounded_static_prologues_retained"
except BaseException as e:
 result["status"]="failed";result["error"]=str(e);put("exception.txt",traceback.format_exc())
finally:
 result["finished_at"]=now()
 js("RESULT.json",result)
 print(json.dumps(result,sort_keys=True),flush=True)
 fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="bounded_static_prologues_retained" else 1)
