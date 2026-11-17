import hashlib,json,pathlib,subprocess,time
root=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
entry=root/"operations/observe_research_run_02.py"
assert hashlib.sha256(entry.read_bytes()).hexdigest()=="4e0c3de2db8d0e3444c10c0f979cbce994810d3ad046cab2ae8fa1ee4b816235"
out=root/"research02-watch-01";out.mkdir(exist_ok=False)
for number in range(8,38):
 label=f"{number:02d}";before=time.perf_counter()
 child=subprocess.run(["/opt/homebrew/bin/python3","-I","-B",str(entry),"--label",label],capture_output=True,timeout=55)
 (out/(label+".stdout.log")).write_bytes(child.stdout);(out/(label+".stderr.log")).write_bytes(child.stderr)
 if child.returncode:
  print(json.dumps({"label":label,"observer_failed":True,"exit_code":child.returncode}),flush=True);raise SystemExit(child.returncode)
 values=[json.loads(line) for line in child.stdout.decode().splitlines() if line.strip()]
 value=next(v for v in values if v.get("schema")=="hepta.research-live-observation.v1")
 ident=value["pid_observation"]
 assert ident and ident["pid"]==2451059
 assert ident["state"]=="absent" or (ident["same_start"] and ident["start_time_ticks"]==23948518)
 summary={"label":label,"observed_at_ns":value["observed_at_ns"],"pid":ident,"readable_outputs":value["readable_completed_outputs"],"input_tokens_subtotal":value["input_tokens_measured_subtotal"],"output_tokens_subtotal":value["output_tokens_measured_subtotal"],"owned_wait_returncode":value["owned_exit"].get("wait_returncode") if value["owned_exit"] else None,"terminal_status":value["terminal_summary"].get("status") if value["terminal_summary"] else None,"workers":[{"worker":w["worker"],"status":w["status"],"steps":w["training_step_receipts"],"failure":w["failure"],"panels":w.get("by_panel")} for w in value["workers"]],"observer_wall_seconds":time.perf_counter()-before,"independent_sample_increment":0,"final_accounting":False}
 with (out/"OBSERVATIONS.jsonl").open("ab") as stream:stream.write((json.dumps(summary,sort_keys=True)+"\n").encode())
 print(json.dumps(summary,sort_keys=True),flush=True)
 if value["owned_exit"] is not None or ident["state"]=="absent":break
 time.sleep(55)
print(json.dumps({"status":"WATCH_WINDOW_FINISHED","model_calls":0,"training_calls":0,"verifier_calls":0}),flush=True)
