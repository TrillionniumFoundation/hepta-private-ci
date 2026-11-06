import collections,datetime,hashlib,json,os,pathlib,stat,struct,subprocess,sys
q=json.load(sys.stdin)
root=pathlib.Path(q["root"]);source=root/"source"
out=root/"evidence"/q["evidence_name"];out.mkdir(exist_ok=False)
env=dict(os.environ);env["GIT_OPTIONAL_LOCKS"]="0"
records=[];commands=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def rec(p):
 b=pathlib.Path(p).read_bytes();return {"path":str(p),"bytes":len(b),"sha256":sha(b)}
def write(n,b):
 p=out/n
 with p.open("xb") as f:f.write(b)
 assert p.read_bytes()==b
 r=rec(p);records.append(r);return r
def js(n,v):return write(n,(json.dumps(v,indent=2)+"\n").encode())
def command(n,args,index=None):
 e=dict(env)
 if index:e["GIT_INDEX_FILE"]=str(index)
 p=subprocess.run(["git"]+args,cwd=source,env=e,capture_output=True)
 row={"argv":["git"]+args,"env_override":{"GIT_OPTIONAL_LOCKS":"0",**({"GIT_INDEX_FILE":str(index)} if index else {})},"exit_code":p.returncode,"stdout":write(n+".stdout",p.stdout),"stderr":write(n+".stderr",p.stderr)}
 commands.append(row);return p
def parse_index(b):
 assert b[:4]==b"DIRC" and hashlib.sha1(b[:-20]).digest()==b[-20:]
 version,count=struct.unpack(">II",b[4:12]);assert version in (2,3),(version,count)
 entries=[];offset=12
 for _ in range(count):
  start=offset;fields=struct.unpack(">10I",b[offset:offset+40]);oid=b[offset+40:offset+60].hex();flags=struct.unpack(">H",b[offset+60:offset+62])[0];offset+=62
  extended=0
  if flags&0x4000:extended=struct.unpack(">H",b[offset:offset+2])[0];offset+=2
  end=b.index(b"\0",offset);path=os.fsdecode(b[offset:end]);offset=start+((end-start+1+7)//8)*8
  assert not any(b[end:offset]),"nonzero entry padding"
  entries.append({"path":path,"oid":oid,"mode":format(fields[6],"06o"),"stage":(flags>>12)&3,"assume_valid":bool(flags&0x8000),"extended":extended,"skip_worktree":bool(extended&0x4000),"intent_to_add":bool(extended&0x2000),"flags":flags,"stat":{"ctime_s":fields[0],"ctime_ns":fields[1],"mtime_s":fields[2],"mtime_ns":fields[3],"dev":fields[4],"ino":fields[5],"uid":fields[7],"gid":fields[8],"size":fields[9]}})
 extensions=[]
 while offset<len(b)-20:
  name=b[offset:offset+4].decode("ascii");size=struct.unpack(">I",b[offset+4:offset+8])[0];payload=b[offset+8:offset+8+size];assert len(payload)==size
  extensions.append({"signature":name,"bytes":size,"sha256":sha(payload),"offset":offset})
  offset+=8+size
 assert offset==len(b)-20
 return {"version":version,"entry_count":count,"entries":entries,"extensions":extensions,"checksum_sha1":b[-20:].hex()}
def stages(data):
 rows=[]
 for item in data.split(b"\0"):
  if item:
   header,path=item.split(b"\t",1);mode,oid,stage=header.decode().split()
   rows.append((os.fsdecode(path),mode,oid,int(stage)))
 return rows
def tree_rows(data):
 rows=[]
 for item in data.split(b"\0"):
  if item:
   header,path=item.split(b"\t",1);mode,kind,oid=header.decode().split()
   assert kind=="blob" or mode=="160000"
   rows.append((os.fsdecode(path),mode,oid,0))
 return rows
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
js("request.json",q)
index=source/".git/index";index_stat=index.lstat();assert stat.S_ISREG(index_stat.st_mode) and not index.is_symlink()
before=index.read_bytes();assert len(before)==q["expected_index"]["bytes"] and sha(before)==q["expected_index"]["sha256"]
write("ordinary-index.snapshot",before);parsed=parse_index(before);js("ordinary-index-parsed.json",parsed)
head=command("head",["rev-parse","HEAD"]);assert head.returncode==0 and head.stdout.decode().strip()==q["ordinary_head"]
listed=command("ordinary-ls-files-stage",["ls-files","--stage","-z"]);assert listed.returncode==0
base=command("ordinary-head-ls-tree",["ls-tree","-r","-z",q["ordinary_head"]]);assert base.returncode==0
actual_rows=stages(listed.stdout);expected_rows=tree_rows(base.stdout)
parsed_rows=[(r["path"],r["mode"],r["oid"],r["stage"]) for r in parsed["entries"]]
assert collections.Counter(actual_rows)==collections.Counter(parsed_rows)
semantic_diff={"missing":list((collections.Counter(expected_rows)-collections.Counter(actual_rows)).elements()),"extra":list((collections.Counter(actual_rows)-collections.Counter(expected_rows)).elements())}
js("ordinary-index-semantic-diff.json",semantic_diff)
tags=command("ordinary-ls-files-flags",["ls-files","-v","-z"]);assert tags.returncode==0
after_guard=pathlib.Path(q["after_guard"]);frozen=json.loads(after_guard.read_text());assert frozen["actual_source"]==q["candidate_tree"]
private=after_guard.with_name(after_guard.name.replace("-source-guard.json",".index"))
private_before=rec(private)
private_listing=command("private-candidate-ls-files-stage",["ls-files","--stage","-z"],private);assert private_listing.returncode==0
candidate_listing=command("candidate-ls-tree",["ls-tree","-r","-z",q["candidate_tree"]]);assert candidate_listing.returncode==0
candidate_index_exact=collections.Counter(stages(private_listing.stdout))==collections.Counter(tree_rows(candidate_listing.stdout))
worktree_diff=command("candidate-diff-files",["diff-files","--raw","-z","--no-ext-diff","--no-textconv"],private);assert worktree_diff.returncode==0
untracked=command("candidate-untracked",["ls-files","--others","--exclude-standard","-z"],private);assert untracked.returncode==0
locks={p:rec(source/p) for p in q["expected_locks"]}
for p,expected in q["expected_locks"].items():assert all(locks[p][k]==expected[k] for k in ("bytes","sha256"))
after=index.read_bytes();private_after=rec(private);assert after==before and private_before==private_after
summary={"schema":"hepta-ordinary-index-read-only-reconciliation-v1","started_at":started,"completed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":q["candidate_tree"],"ordinary_head":q["ordinary_head"],"old_guard_index":q["old_guard_index"],"actual_ordinary_index":rec(index),"ordinary_index_lstat":{"mode":oct(index_stat.st_mode),"size":index_stat.st_size,"mtime_ns":index_stat.st_mtime_ns,"ctime_ns":index_stat.st_ctime_ns,"dev":index_stat.st_dev,"ino":index_stat.st_ino},"ordinary_index_version":parsed["version"],"ordinary_index_entry_count":parsed["entry_count"],"index_semantics_exact_head":not semantic_diff["missing"] and not semantic_diff["extra"],"semantic_difference_counts":{k:len(v) for k,v in semantic_diff.items()},"parsed_index_matches_git_ls_files":True,"flags":{"stage_nonzero":sum(r["stage"]!=0 for r in parsed["entries"]),"assume_valid":sum(r["assume_valid"] for r in parsed["entries"]),"extended_nonzero":sum(r["extended"]!=0 for r in parsed["entries"]),"skip_worktree":sum(r["skip_worktree"] for r in parsed["entries"]),"intent_to_add":sum(r["intent_to_add"] for r in parsed["entries"]),"git_ls_files_v_tag_counts":dict(collections.Counter(os.fsdecode(item[:1]) for item in tags.stdout.split(b"\0") if item))},"extensions":parsed["extensions"],"private_source_index_before":private_before,"private_source_index_after":private_after,"private_source_index_exact_candidate":candidate_index_exact,"working_tree_raw_diff_empty":not worktree_diff.stdout,"untracked_source_paths":[os.fsdecode(x) for x in untracked.stdout.split(b"\0") if x],"locks":locks,"ordinary_index_bytes_stable_during_read":True,"limitations":["The prior original ordinary-index bytes were not available to this inspector; this does not assert which individual stat fields or extension bytes changed.","No test, Cargo, source write, ordinary-index refresh/reset or staging operation was performed. Only new evidence files were written."]}
js("commands.json",commands);summary["records"]=records.copy();js("summary.json",summary)
print(json.dumps({k:v for k,v in summary.items() if k not in ("records",)},indent=2))
assert summary["index_semantics_exact_head"] and candidate_index_exact and summary["working_tree_raw_diff_empty"] and not summary["untracked_source_paths"]
assert all(summary["flags"][k]==0 for k in ("stage_nonzero","assume_valid","extended_nonzero","skip_worktree","intent_to_add"))
