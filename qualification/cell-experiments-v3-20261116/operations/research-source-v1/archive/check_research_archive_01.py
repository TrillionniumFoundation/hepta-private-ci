import ast,base64,hashlib,json,pathlib,shlex,subprocess,time
root=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
output=root/"research-archive-engineering-01"
output.mkdir(exist_ok=False)
expected={"archive_qwen_research_v1.py":"1b88e687a6c92148f6efff6bfd77bf0e20ae42eb613181e6d1ef523dd2d0e903",
          "archive_qwen_final_v3.py":"7bcd81d5bc8cae58c03a80c62e5c39f858a5996c1df1768ac4252a2d58fb80d1"}
packet={"sources":{}}
for name,want in expected.items():
    raw=(root/"operations"/name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==want
    ast.parse(raw)
    packet["sources"][name]={"data":base64.b64encode(raw).decode(),"sha256":want}
remote="import ast,base64,hashlib,importlib.util,json,os,pathlib,sys,time\nroot=pathlib.Path(\"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a\")\npacket=json.load(sys.stdin)\nverified=[]\nfor name,item in packet[\"sources\"].items():\n    raw=base64.b64decode(item[\"data\"],validate=True)\n    assert hashlib.sha256(raw).hexdigest()==item[\"sha256\"]\n    ast.parse(raw)\n    path=root/\"operations\"/name\n    reused=path.exists()\n    if reused:assert path.resolve()==path and path.read_bytes()==raw\n    else:\n        with path.open(\"xb\") as stream:stream.write(raw)\n    verified.append({\"name\":name,\"sha256\":item[\"sha256\"],\"reused_existing\":reused})\ntest=root/\"research-archive-engineering-01\"\ntest.mkdir(exist_ok=False)\npath=root/\"operations/archive_qwen_research_v1.py\"\nspec=importlib.util.spec_from_file_location(\"research_archive_fixture\",path)\nmodule=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nfixture=root/\"owned-launcher-engineering-01/child\"\nargv=json.loads((fixture/\"INTENT.json\").read_bytes())[\"argv\"]\nintent,started,exited,observed=module.owned_receipts(fixture,\"engineering_fixture\",argv)\nassert exited[\"wait_returncode\"]==7 and all(row[\"stopped\"] for row in observed)\nrejected=False\ntry:module.owned_receipts(fixture,\"engineering_fixture\",argv+[\"foreign-argument\"])\nexcept ValueError as error:\n    assert str(error)==\"owned argv differs\"\n    rejected=True\nassert rejected\nraw=pathlib.Path(\"/proc\",str(os.getpid()),\"stat\").read_text()\ntick=int(raw.rsplit(\")\",1)[1].split()[19])\nlive=module.process_observation({\"pid\":os.getpid(),\"boot\":pathlib.Path(\"/proc/sys/kernel/random/boot_id\").read_text().strip(),\"start_time_ticks\":tick})\nassert live[\"stopped\"] is False\nassert \"torch\" not in sys.modules and \"transformers\" not in sys.modules\nresult={\"status\":\"PASS\",\"behavior_checks\":3,\"checks\":[\"actual_nonzero_wait_and_raw_log_binding\",\"foreign_argv_rejected\",\"live_writer_not_terminal\"],\n        \"original_fixture_exit_code\":7,\"new_model_calls\":0,\"new_training_steps\":0,\n        \"source_files\":verified,\"owned_process_observations\":observed,\"live_process_observation\":live,\n        \"archive_source_sha256\":hashlib.sha256(path.read_bytes()).hexdigest()}\nwith (test/\"RESULT.json\").open(\"x\") as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write(\"\\n\")\nprint(json.dumps(result))\n"
argv=["/usr/bin/ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts","/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python -I -B -c "+shlex.quote(remote)]
with (output/"STARTED.json").open("x") as stream:json.dump({"argv":argv,"created_at_ns":time.time_ns(),"source_files":expected},stream,sort_keys=True,indent=2)
start=time.perf_counter()
r=subprocess.run(argv,input=json.dumps(packet).encode(),capture_output=True,timeout=120)
for name,data in (("stdout.log",r.stdout),("stderr.log",r.stderr)):
    with (output/name).open("xb") as stream:stream.write(data)
receipt={"exit_code":r.returncode,"wall_seconds":time.perf_counter()-start,"stdout_sha256":hashlib.sha256(r.stdout).hexdigest(),"stderr_sha256":hashlib.sha256(r.stderr).hexdigest()}
with (output/"EXIT.json").open("x") as stream:json.dump(receipt,stream,sort_keys=True,indent=2)
assert r.returncode==0,r.stderr.decode(errors="replace")
result=json.loads(r.stdout)
with (output/"RESULT.json").open("x") as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write("\n")
print(json.dumps({"status":result["status"],"checks":result["behavior_checks"],"source_sha256":result["archive_source_sha256"],"new_model_calls":0,"exit_code":r.returncode}))
