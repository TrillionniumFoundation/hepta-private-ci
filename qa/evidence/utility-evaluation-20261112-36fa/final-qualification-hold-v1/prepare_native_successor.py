from pathlib import Path
import ast,difflib,hashlib,json
root=Path(__file__).resolve().parent
before=(root/'canonical-wrapper.previous.py').read_text();after=before
replacements=[]
def replace(old,new):
 global after
 assert after.count(old)==1,old[:120]
 after=after.replace(old,new,1);replacements.append({'before':old,'after':new})
replace('import fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,xml.etree.ElementTree as ET','import fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,types,xml.etree.ElementTree as ET')
replace('repo=Path(INPUT["repo"])','if INPUT.get("state")!="READY_FOR_FINAL_SOURCE_QUALIFICATION" or INPUT.get("root_execution_approved") is not True:raise RuntimeError("qualification input remains HOLD")\nrepo=Path(INPUT["repo"])')
replace('records=Path("/home/qian-qi/hepta-utility-36fa-evidence")','records=Path(INPUT["records_parent"])')
replace('driver=records/"native-exact-driver-3c318e8d.py"','driver=Path(INPUT["native_driver_path"])')
replace('lock=(records/"REVIEW_SOURCE.lock").open("a+")\nbefore=None','guard=None\nbefore=None')
replace(' fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)',' admission_path=Path(INPUT["admission_path"]);admission_raw=admission_path.read_bytes()\n admission_pin={"bytes":len(admission_raw),"sha256":sha(admission_raw),"git_blob":hashlib.sha1(b"blob "+str(len(admission_raw)).encode()+b"\\0"+admission_raw).hexdigest()}\n if admission_pin!=INPUT["admission_pin"]:raise RuntimeError("exact admission module differs")\n admission=types.ModuleType("final_qualification_admission");admission.__file__=str(admission_path)\n exec(compile(admission_raw,str(admission_path),"exec"),admission.__dict__)\n guard=admission.Admission(INPUT,out/"admission",True)\n guard.acquire_and_validate()')
replace(' env=dict(os.environ);env.update(json.loads((records/"MAINTENANCE_STARTED.json").read_text())["environment"])',' env=dict(os.environ) # The unchanged V5 environment_preflight has validated and installed only its restored explicit environment.')
old=''' command("toolchain",["python3","-c","import subprocess; commands=[['rustc','--version','--verbose'],['cargo','--version'],['just','--version'],['cargo','nextest','--version']]; [subprocess.run(c,check=True) for c in commands]"],120)
 command("fix",["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd"],7200)
 if git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("canonical maintenance changed source; preserve and review")
 command("fmt",["just","fmt","--base",INPUT["fmt_base"]],900)
 maintained=snapshot("source-after-maintenance");verify_clean(maintained)
 if maintained!=before:raise RuntimeError("canonical source changed during maintenance")
 save(out/"EXACT_CHECKOUT.json",{"status":"ready_for_readonly_source_gates","source_sha":source,"source_tree":tree,"repo":str(repo),"source_snapshot":maintained,"maintenance_stable":True,"at":datetime.now(timezone.utc).isoformat()})
 fcntl.flock(lock,fcntl.LOCK_SH)'''
new=''' # Final format and canonical alignment are actual pinned prerequisites;
 # qualification never repeats fix/fmt. Original b92 retains its own toolchain
 # and helper phases on each focused/all invocation.
 save(out/"EXACT_SOURCE_ADMISSION.json",{"status":"actual_clean_final_source_admitted","source_sha":source,"source_tree":tree,"repo":str(repo),"source_snapshot":before,"actual_prerequisites":INPUT["canonical_alignment"],"qualification":False,"at":datetime.now(timezone.utc).isoformat()})
 guard.before_native_stage("eval-lib")'''
replace(old,new)
replace(' state("eval-lib");record["behavioral_tests_started"]=True',' record["behavioral_tests_started"]=True;record["attempted"]= ["eval-lib"];state("eval-lib")\n save(out/"eval-lib-execution-start.json",{"source_sha":source,"at":datetime.now(timezone.utc).isoformat(),"entrypoint":"original hepta_ci_exec.run","timeout_seconds":3600})')
old=''' save(out/"eval-lib-coverage.json",{"source_sha":source,"expected_count":163,"actual_count":len(actual),"passed_count":len(passed),"required_four":sorted(required),"observed_four":sorted(required&set(passed)),"names":actual})
 if len(actual)!=163 or len(passed)!=163 or len(set(actual))!=163 or not required.issubset(set(passed)):raise RuntimeError("full eval lib inventory or four regression cases differ")'''
new=''' all_names=[c.attrib.get("name") for c in cases]
 save(out/"eval-lib-coverage.json",{"source_sha":source,"count_policy":"actual final-source complete unfiltered library; no historical-count gate","actual_count":len(actual),"passed_count":len(passed),"required_four":sorted(required),"observed_four":sorted(required&set(passed)),"names":actual,"all_fresh_junit_names":all_names,"skipped_names":[c.attrib.get("name") for c in cases if c.find("skipped") is not None]})
 if not actual or len(passed)!=len(actual) or len(set(actual))!=len(actual) or len(set(all_names))!=len(all_names) or not all(isinstance(name,str) and name for name in all_names) or not required.issubset(set(passed)):raise RuntimeError("full eval lib inventory or four regression cases differ")'''
replace(old,new)
replace('  state(suite);destination=out/suite','  guard.before_native_stage(suite)\n  record["attempted"].append(suite);state(suite);destination=out/suite')
replace('  if suite=="all":cmd+=["--root-parent","/run/hepta-utility-36fa-"+source[:12]+"-root"]','  if suite=="all":cmd+=["--root-parent",INPUT["root_parent"]]')
replace('except Exception as error:record.update(status="failed",error=type(error).__name__+": "+str(error))','except Exception as error:\n record.update(status="unknown" if isinstance(error,(OSError,ET.ParseError,json.JSONDecodeError)) else "failed",error=type(error).__name__+": "+str(error))')
replace(' except Exception as error:record.update(status="failed",final_snapshot_error=str(error),source_change=None,source_comparison="unknown_missing_after")',' except Exception as error:record.update(status="unknown" if record["status"]=="passed" else record["status"],final_snapshot_error=str(error),source_change=None,source_comparison="unknown_missing_after")\n if guard is not None:\n  try:record["actual_full_physical_observation"]=guard.finish()\n  except Exception as error:record.update(status="unknown" if record["status"]=="passed" else record["status"],full_physical_evidence_error=type(error).__name__+": "+str(error))\n  finally:guard.close()')
# Preserve an actual known command failure, and leave missing post-dispatch
# evidence unknown. This narrow predicate does not reinterpret old records.
old='''except Exception as error:
 record.update(status="unknown" if isinstance(error,(OSError,ET.ParseError,json.JSONDecodeError)) else "failed",error=type(error).__name__+": "+str(error))'''
new='''except Exception as error:
 known=any(row.get("result") not in (None,0) or row.get("returncode") not in (None,0) or row.get("timed_out") is True or row.get("output_limit_exceeded") is True for row in record["stages"])
 status="failed" if known else "unknown" if isinstance(error,(OSError,ET.ParseError,json.JSONDecodeError)) else "failed"
 record.update(status=status,error=type(error).__name__+": "+str(error))'''
replace(old,new)
replace('  except Exception as error:record.update(status="unknown" if record["status"]=="passed" else record["status"],full_physical_evidence_error=type(error).__name__+": "+str(error))','  except Exception as error:record.update(status="failed" if isinstance(error,admission.SourceChanged) else "unknown" if record["status"]=="passed" else record["status"],full_physical_evidence_error=type(error).__name__+": "+str(error))')
replace('import fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,types,xml.etree.ElementTree as ET','import fcntl,gzip,hashlib,json,os,re,signal,stat,subprocess,sys,types,xml.etree.ElementTree as ET')
replace(' guard.acquire_and_validate()',' signal.signal(signal.SIGALRM,guard.m.alarm_handler);guard.m.set_alarm(600)\n try:guard.acquire_and_validate()\n finally:signal.alarm(0)')
replace('  try:record["actual_full_physical_observation"]=guard.finish()','  try:\n   signal.signal(signal.SIGALRM,guard.m.alarm_handler);guard.m.set_alarm(300)\n   record["actual_full_physical_observation"]=guard.finish()')
replace('  finally:guard.close()','  finally:signal.alarm(0);guard.close()')
replace(' retained=collect(out/"eval-lib.json",report,out/"eval-lib.xml")\n execution=json.loads((out/"eval-lib.json").read_text());record["stages"].append({"name":"eval-lib","result":result,"collection":retained,"record":str(out/"eval-lib.json")})',' execution=json.loads((out/"eval-lib.json").read_text());record["stages"].append({"name":"eval-lib","result":result,"collection":None,"record":str(out/"eval-lib.json")})\n retained=collect(out/"eval-lib.json",report,out/"eval-lib.xml");record["stages"][-1]["collection"]=retained')
replace('out.mkdir(parents=True,exist_ok=False)','if not out.is_absolute() or out.is_relative_to(repo) or repo.is_relative_to(out) or out.is_relative_to(Path(INPUT["target"])) or Path(INPUT["target"]).is_relative_to(out):raise RuntimeError("fresh external records required")\nout.mkdir(parents=True,exist_ok=False)')
ast.parse(after);compile(after,'native-wrapper.HOLD.py','exec')
(root/'native-wrapper.HOLD.py').write_text(after)
patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='previous/5be7e21.py',tofile='prepared/native-wrapper.HOLD.py',n=3))
(root/'NATIVE_WRAPPER_FROM_5BE7.diff').write_text(patch)
(root/'NATIVE_WRAPPER_REPLACEMENTS.json').write_text(json.dumps(replacements,indent=2,sort_keys=True)+'\n')
print(json.dumps({'bytes':len(after.encode()),'sha256':hashlib.sha256(after.encode()).hexdigest(),'changes':len(replacements),'patch_bytes':len(patch.encode()),'main_executed':False}))
