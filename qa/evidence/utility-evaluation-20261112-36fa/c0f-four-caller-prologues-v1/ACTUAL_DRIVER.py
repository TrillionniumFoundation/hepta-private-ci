import os,sys,json,hashlib,pathlib,struct,mmap,subprocess,shutil,datetime,fcntl,traceback,re,time,selectors
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
 if st.st_size!=P["binary_bytes"] or h!=P["binary_sha256"]:raise RuntimeError("pinned ELF identity differs")
 return {"path":str(B),"bytes":st.st_size,"sha256":h,"stat":[st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]}
def bounded_cfi(rows):
 tool=shutil.which("readelf")
 if not tool:return {"available":False,"reason":"readelf unavailable; no dependency installed"}
 targets={r["frame"]:int(r["rva"],16) for r in rows};selected={};cies={};current=[];scanned=0;partial=b"";p=None
 outcome={"available":False,"tool":tool,"requested_frames":sorted(targets),"budget_seconds":20,"stream_byte_limit":67108864,"scope":"Only exact-PC covering FDE blocks and their referenced CIE blocks are retained; other readelf text is discarded"}
 def finish():
  if not current:return
  header=current[0]
  m=re.match(r"^\s*([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+(CIE|FDE)\b",header)
  if not m:return
  block="".join(current)
  if len(block.encode())>32768:raise RuntimeError("individual CFI block exceeds guard")
  if m.group(2)=="CIE":cies[int(m.group(1),16)]=block;return
  pc=re.search(r"cie=([0-9a-fA-F]+)\s+pc=([0-9a-fA-F]+)\.\.([0-9a-fA-F]+)",header)
  if not pc:return
  lo,hi=int(pc.group(2),16),int(pc.group(3),16)
  for frame,value in targets.items():
   if lo<=value<hi:selected[frame]={"frame":frame,"rva":hex(value),"range_start":hex(lo),"range_end":hex(hi),"cie_offset":int(pc.group(1),16),"fde":block}
 try:
  command=[tool,"--debug-dump=frames",str(B)];outcome["command"]=command
  p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ,"stdout");sel.register(p.stderr,selectors.EVENT_READ,"stderr");deadline=time.monotonic()+20;stderr=bytearray();stop_reason=None
  while sel.get_map():
   if time.monotonic()>=deadline:stop_reason="time_budget";break
   ready=sel.select(min(0.25,max(0,deadline-time.monotonic())))
   for key,_ in ready:
    data=os.read(key.fileobj.fileno(),65536)
    if not data:sel.unregister(key.fileobj);continue
    if key.data=="stderr":
     stderr.extend(data)
     if len(stderr)>8192:stop_reason="stderr_budget";break
     continue
    scanned+=len(data)
    if scanned>67108864:stop_reason="stream_byte_budget";break
    partial+=data
    while b"\n" in partial:
     line,partial=partial.split(b"\n",1);text=line.decode(errors="replace")+"\n"
     if re.match(r"^\s*[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+(?:CIE|FDE)\b",text):
      finish();current=[]
      if set(selected)==set(targets):stop_reason="all_requested_fdes_found";break
     current.append(text)
    if stop_reason:break
   if stop_reason:break
  if not stop_reason:
   if partial:current.append(partial.decode(errors="replace"))
   finish();stop_reason="readelf_eof"
  if p.poll() is None:p.terminate()
  try:p.wait(timeout=2)
  except subprocess.TimeoutExpired:p.kill();p.wait(timeout=2)
  sel.close()
  refs=sorted({v["cie_offset"] for v in selected.values()});retained={"frames":[selected[k] for k in sorted(selected)],"referenced_cies":[{"offset":hex(k),"text":cies.get(k),"available":k in cies} for k in refs]}
  outcome.update(available=set(selected)==set(targets) and all(k in cies for k in refs),selected_frames=sorted(selected),stop_reason=stop_reason,bytes_scanned=scanned,returncode=p.returncode,stderr=put("CFI.stderr",bytes(stderr)),retained=js("FOUR_CALLER_CFI.json",retained))
 except Exception as e:outcome.update(error=type(e).__name__+": "+str(e),bytes_scanned=scanned)
 finally:
  if p is not None and p.poll() is None:
   p.kill();p.wait(timeout=2)
 return outcome
R.mkdir(mode=0o700)
result={"started_at":now(),"qualification":False,"tests_started":False,"cargo_started":False,"binary_executed":False,"source_mutated":False,"status":"started"}
js("DRIVER_INPUT.json",P);put("driver.py",P["driver"])
lock=open(P["source_lock"],"rb")
fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
try:
 result["binary_before"]=identity()
 result["source_before"]={"sha":git(["rev-parse","HEAD"]).strip(),"tree":git(["rev-parse","HEAD^{tree}"]).strip(),"status":git(["status","--porcelain=v1","--untracked-files=all"])}
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
 result["cfi"]=bounded_cfi(rows)
 js("CFI_COLLECTION.json",result["cfi"])
 result["binary_after"]=identity()
 result["source_after"]={"sha":git(["rev-parse","HEAD"]).strip(),"tree":git(["rev-parse","HEAD^{tree}"]).strip(),"status":git(["status","--porcelain=v1","--untracked-files=all"])}
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
