import base64,hashlib,json,pathlib,shlex,subprocess,time
r=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
o=r/"research-deployment-01"
assert not o.exists()
groups=[]
for path,sha,target,members,name in [
 ("research-sft-v1-source-working/RESEARCH_SOURCE_V1.zip","a3e2228377c20dab52a8cdfa20ce3cef62f92b75c5eacb1a5cea426b43e922bc","research-sft-v1-source",14,"RESEARCH_SOURCE_V1.zip"),
 ("operations/research-diagnostic-v1-source/qwen-research-diagnostic-helper-01.zip","c395702327f6cf3356b611c4533a0a9c82759f8141b5165703051fa0107ec2a3","research-diagnostic-v1-source",13,"qwen-research-diagnostic-helper-01.zip")]:
 raw=(r/path).read_bytes()
 assert hashlib.sha256(raw).hexdigest()==sha
 groups.append({"target":target,"sha256":sha,"members":members,"archive_filename":name,"data_base64":base64.b64encode(raw).decode()})
p=r/"operations/archive_qwen_research_v1_02.py"
raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()=="658438b68dff7a039a9631beb9e07ded8e7f56de23912672f868a531e063c3b2"
payload={"groups":groups,"extra_files":{"operations/archive_qwen_research_v1_02.py":{"sha256":hashlib.sha256(raw).hexdigest(),"data_base64":base64.b64encode(raw).decode()}}}
remote="import base64,hashlib,io,json,os,pathlib,shutil,stat,sys,time,zipfile\nw=pathlib.Path(\"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a\")\nr=pathlib.Path(\"/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a\")\nassert pathlib.Path(sys.executable)==r/\"venv/bin/python\" and sys.flags.isolated and sys.dont_write_bytecode\nassert w.resolve()==w and w.stat().st_uid==os.getuid()\npayload=json.load(sys.stdin)\ndest=w/\"research-deployment-01\"\nassert not dest.exists()\ngroups=[]\nfor group in payload[\"groups\"]:\n raw=base64.b64decode(group[\"data_base64\"],validate=True)\n assert hashlib.sha256(raw).hexdigest()==group[\"sha256\"]\n target=w/group[\"target\"]\n assert target.parent==w and not target.exists()\n with zipfile.ZipFile(io.BytesIO(raw)) as z:\n  assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))\n  files={}\n  for info in z.infolist():\n   p=pathlib.PurePosixPath(info.filename)\n   assert str(p)==info.filename and not p.is_absolute() and \"..\" not in p.parts and \"\\\\\" not in info.filename\n   assert not info.is_dir() and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG)\n   data=z.read(info)\n   assert len(data)<512000\n   files[info.filename]=data\n assert len(files)==group[\"members\"]\n archive=w/\"operations\"/group[\"archive_filename\"]\n assert not archive.exists()\n groups.append((group,target,raw,files,archive))\nextras=[]\nfor name,item in payload[\"extra_files\"].items():\n p=w/name\n assert p.resolve()==p and p.is_relative_to(w) and not p.exists()\n raw=base64.b64decode(item[\"data_base64\"],validate=True)\n assert hashlib.sha256(raw).hexdigest()==item[\"sha256\"]\n extras.append((p,raw))\nassert shutil.disk_usage(w).free>8*1024**3\ndest.mkdir()\ndef write(path,data):\n path.parent.mkdir(parents=True,exist_ok=True)\n with path.open(\"xb\") as f:f.write(data);f.flush();os.fsync(f.fileno())\nwrite(dest/\"STARTED.json\",(json.dumps({\"started_at_ns\":time.time_ns(),\"model_calls\":0,\"automatic_retry\":False})+\"\\n\").encode())\ninventory={}\nfor group,target,raw,files,archive in groups:\n target.mkdir()\n write(archive,raw)\n for name,data in files.items():\n  p=target/name\n  write(p,data)\n  assert p.read_bytes()==data\n  inventory[p.relative_to(w).as_posix()]={\"bytes\":len(data),\"sha256\":hashlib.sha256(data).hexdigest()}\nfor p,raw in extras:\n write(p,raw)\n assert p.read_bytes()==raw\n inventory[p.relative_to(w).as_posix()]={\"bytes\":len(raw),\"sha256\":hashlib.sha256(raw).hexdigest()}\nreceipt={\"schema\":\"hepta.research-source-deployment.v1\",\"status\":\"DEPLOYED_VERIFIED\",\"workspace_root\":str(w),\"files\":inventory,\"groups\":[{\"target\":g[\"target\"],\"sha256\":g[\"sha256\"],\"members\":g[\"members\"]} for g,_,_,_,_ in groups],\"boot\":pathlib.Path(\"/proc/sys/kernel/random/boot_id\").read_text().strip(),\"completed_at_ns\":time.time_ns(),\"model_calls\":0,\"research_fits\":0,\"automatic_retry\":False}\nraw=(json.dumps(receipt,sort_keys=True,indent=2)+\"\\n\").encode()\nwrite(dest/\"DEPLOYED.json\",raw)\nprint(json.dumps({\"status\":receipt[\"status\"],\"files\":len(inventory),\"receipt_sha256\":hashlib.sha256(raw).hexdigest(),\"receipt\":receipt}))\n"
argv=["/usr/bin/ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts","/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python -I -B -c "+shlex.quote(remote)]
o.mkdir()
(o/"STARTED.json").write_text(json.dumps({"started_at_ns":time.time_ns(),"argv":argv,"automatic_retry":False})+"\n")
before=time.perf_counter()
result=subprocess.run(argv,input=json.dumps(payload).encode(),capture_output=True,timeout=180)
(o/"stdout.log").write_bytes(result.stdout);(o/"stderr.log").write_bytes(result.stderr)
value={"exit_code":result.returncode,"wall_seconds":time.perf_counter()-before,"stdout_sha256":hashlib.sha256(result.stdout).hexdigest(),"stderr_sha256":hashlib.sha256(result.stderr).hexdigest(),"automatic_retry":False}
(o/"EXIT.json").write_text(json.dumps(value,sort_keys=True,indent=2)+"\n")
print(json.dumps(value))
print(result.stdout.decode())
print(result.stderr.decode())
assert result.returncode==0
