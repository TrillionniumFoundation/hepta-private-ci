import base64,hashlib,json,pathlib,shlex,stat,subprocess,time,zipfile
r=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
o=r/"research-export-operation-01";assert not o.exists();o.mkdir()
raw=(r/"operations/RESEARCH_POSTRUN_TERMINAL_01.json").read_bytes()
payload={"observation_base64":base64.b64encode(raw).decode(),"observation_sha256":hashlib.sha256(raw).hexdigest()}
remote="import base64,hashlib,json,os,pathlib,subprocess,sys,time\nw=pathlib.Path(\"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a\")\npayload=json.load(sys.stdin)\ndef sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()\ndef save(p,v):\n raw=(json.dumps(v,sort_keys=True,indent=2)+\"\\n\").encode()\n with p.open(\"xb\") as f:f.write(raw);f.flush();os.fsync(f.fileno())\n return hashlib.sha256(raw).hexdigest()\nraw=base64.b64decode(payload[\"observation_base64\"],validate=True);assert hashlib.sha256(raw).hexdigest()==payload[\"observation_sha256\"]\np=w/\"operations/RESEARCH_POSTRUN_TERMINAL_01.json\"\nwith p.open(\"xb\") as f:f.write(raw);f.flush();os.fsync(f.fileno())\nv=json.loads(raw);assert v[\"status\"][\"state\"]==\"exited\" and v[\"status\"][\"output_complete\"] is True\nwriters=[]\nfor role,output,owned,source,launch,observation in (\n (\"research\",\"research-sft-01\",\"owned-research-sft-01\",\"research-sft-v1-source/run_research_sft_v1.py\",\"RESEARCH_LAUNCH_FREEZE_01.json\",\"RESEARCH_ACTUAL_TERMINAL_01.json\"),\n (\"postrun\",\"research-diagnostic-01\",\"owned-research-diagnostic-01\",\"research-diagnostic-v1-source/qwen_research_diagnostic_v1.py\",\"RESEARCH_POSTRUN_LAUNCH_FREEZE_01.json\",\"RESEARCH_POSTRUN_TERMINAL_01.json\")):\n start=json.loads((w/owned/\"STARTED.json\").read_bytes());end=json.loads((w/owned/\"EXIT.json\").read_bytes())\n assert type(end[\"wait_returncode\"]) is int\n for ident in (start[\"child_identity\"],start[\"wrapper_identity\"]):assert not pathlib.Path(\"/proc\",str(ident[\"pid\"])).exists()\n writers.append({\"role\":role,\"output_directory\":output,\"owned_directory\":owned,\"source_path\":source,\"source_sha256\":sha(w/source),\"launch_freeze_path\":\"operations/\"+launch,\"launch_freeze_sha256\":sha(w/\"operations\"/launch),\"observation_path\":\"operations/\"+observation,\"observation_sha256\":sha(w/\"operations\"/observation)})\nfor p in (w/\"research-sft-01/processes\").glob(\"*/LAUNCH.json\"):\n q=p.parent/\"EXIT.json\";assert q.is_file()\n e=json.loads(q.read_bytes());assert type(e[\"exit_code\"]) is int and not pathlib.Path(\"/proc\",str(e[\"pid\"])).exists()\nindex={\"schema\":\"hepta.research-export-terminals.v1\",\"artifact_root\":str(w),\"writers_stopped_confirmed\":True,\"observed_at_ns\":time.time_ns(),\"research_freeze_sha256\":sha(w/\"research-sft-01/FREEZE.json\"),\"diagnostic_result_sha256\":sha(w/\"research-diagnostic-01/DIAGNOSTIC.json\"),\"writers\":writers,\"automatic_retry\":False}\nindex_sha=save(w/\"operations/RESEARCH_TERMINAL_INDEX_01.json\",index)\nentry=w/\"operations/archive_qwen_research_v1_02.py\"\nassert sha(entry)==\"658438b68dff7a039a9631beb9e07ded8e7f56de23912672f868a531e063c3b2\"\nargv=[sys.executable,\"-I\",\"-B\",str(entry),\"--artifact-root\",str(w),\"--helpers\",\"e1e2-operation-helpers-04\",\"--postrun-source\",\"research-diagnostic-v1-source/qwen_research_diagnostic_v1.py\",\"--terminal-index\",\"operations/RESEARCH_TERMINAL_INDEX_01.json\",\"--output\",\"research-export-01\"]\nresult=subprocess.run(argv,cwd=w,capture_output=True,timeout=120)\nassert result.returncode==0,{\"exit\":result.returncode,\"stdout\":result.stdout.decode(),\"stderr\":result.stderr.decode()}\nmanifest=w/\"research-export-01/TRANSFER_MANIFEST.json\"\ndiag=json.loads((w/\"research-diagnostic-01/DIAGNOSTIC.json\").read_bytes())\nprint(json.dumps({\"status\":\"EXPORTED\",\"archive_exit\":result.returncode,\"archive_stdout\":result.stdout.decode(),\"archive_stderr\":result.stderr.decode(),\"terminal_index_sha256\":index_sha,\"manifest_sha256\":sha(manifest),\"manifest\":json.loads(manifest.read_bytes()),\"diagnostic_sha256\":sha(w/\"research-diagnostic-01/DIAGNOSTIC.json\"),\"diagnostic_summary\":{k:diag.get(k) for k in (\"status\",\"operation_status\",\"first_attempt_opportunity\",\"binding_errors\",\"cost_ledger\")}}))\n"
argv=["/usr/bin/ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts","/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python -I -B -c "+shlex.quote(remote)]
(o/"STARTED.json").write_text(json.dumps({"started_at_ns":time.time_ns(),"argv":argv,"automatic_retry":False})+"\n")
p=subprocess.run(argv,input=json.dumps(payload).encode(),capture_output=True,timeout=150)
(o/"stdout.log").write_bytes(p.stdout);(o/"stderr.log").write_bytes(p.stderr)
(o/"EXIT.json").write_text(json.dumps({"exit_code":p.returncode,"stdout_sha256":hashlib.sha256(p.stdout).hexdigest(),"stderr_sha256":hashlib.sha256(p.stderr).hexdigest()})+"\n")
assert p.returncode==0,p.stderr.decode()
v=json.loads(p.stdout);print(json.dumps({k:x for k,x in v.items() if k not in ("manifest","diagnostic_summary")}))
dest=r/"research-final-export-01";assert not dest.exists()
copy=subprocess.run(["/usr/bin/scp","-q","-r","-p","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts:/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-export-01",str(dest)],capture_output=True,timeout=180)
(o/"scp.stdout.log").write_bytes(copy.stdout);(o/"scp.stderr.log").write_bytes(copy.stderr)
assert copy.returncode==0,copy.stderr.decode()
assert hashlib.sha256((dest/"TRANSFER_MANIFEST.json").read_bytes()).hexdigest()==v["manifest_sha256"]
manifest=v["manifest"]
expected={"STARTED.json","RESTORE.txt","TRANSFER_MANIFEST.json","MEMBERS.jsonl","qwen-research-sft.zip"}|{x["path"] for k in ("archive","members") for x in manifest[k]["parts"]}
assert {p.name for p in dest.iterdir()}==expected
for kind in ("archive","members"):
 item=manifest[kind];whole=hashlib.sha256();total=0
 for part in item["parts"]:
  p=dest/part["path"];assert not p.is_symlink()
  b=p.read_bytes();assert len(b)==part["bytes"] and hashlib.sha256(b).hexdigest()==part["sha256"]
  whole.update(b);total+=len(b)
 assert total==item["bytes"] and whole.hexdigest()==item["sha256"]
 data=(dest/item["transport_path"]).read_bytes();assert len(data)==total and hashlib.sha256(data).hexdigest()==whole.hexdigest()
members=[json.loads(line) for line in (dest/"MEMBERS.jsonl").read_bytes().splitlines()]
extract=r/"research-final-evidence-01";assert not extract.exists();extract.mkdir()
with zipfile.ZipFile(dest/"qwen-research-sft.zip") as z:
 assert z.testzip() is None and z.namelist()==[x["path"] for x in members]
 for item in members:
  name=pathlib.PurePosixPath(item["path"]);assert not name.is_absolute() and ".." not in name.parts
  info=z.getinfo(item["path"]);assert stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG)
  data=z.read(info);assert len(data)==item["bytes"] and hashlib.sha256(data).hexdigest()==item["sha256"]
  p=extract/name;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open("xb") as f:f.write(data)
receipt={"schema":"hepta.research-mac-archive-verified.v1","manifest_sha256":v["manifest_sha256"],"archive_sha256":manifest["archive"]["sha256"],"archive_bytes":manifest["archive"]["bytes"],"members":len(members),"all_member_hashes_equal":True,"all_parts_reconstructed":True,"source_bytes_not_rewritten":True,"extract_root":str(extract),"transfer_root":str(dest),"completed_at_ns":time.time_ns(),"model_calls":0,"verifier_calls":0}
(o/"MAC_VERIFIED.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
print(json.dumps(receipt));print(json.dumps(v["diagnostic_summary"]))
