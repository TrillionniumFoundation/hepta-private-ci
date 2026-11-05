import json,subprocess,hashlib,re,time
p=subprocess.run(['journalctl','--user','-u','heptatrader-execution.service','-n','120','--no-pager','-o','json','--output-fields=MESSAGE,__REALTIME_TIMESTAMP'],capture_output=True,text=True,timeout=12)
counts={}; times=[];message_hashes=set()
for line in p.stdout.splitlines():
 try:r=json.loads(line)
 except ValueError:continue
 m=r.get('MESSAGE','');t=r.get('__REALTIME_TIMESTAMP');times.append(t);message_hashes.add(hashlib.sha256(m.encode()).hexdigest())
 for tag in ['invalid catch-up','catch-up','failed','failure','ledger','panic','permission','No space','out of memory']:
  if tag.lower() in m.lower():counts[tag]=counts.get(tag,0)+1
statuses={}
for unit in ['heptatrader-execution.service','heptatrader-laya-trainer.service']:
 q=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,SubState,NRestarts,ExecMainStatus,Result'],capture_output=True,text=True,timeout=6)
 statuses[unit]=dict(x.split('=',1) for x in q.stdout.splitlines() if '=' in x)
print(json.dumps({'schema':'hepta.wsp.execution_log_classification.v1','observed_unix':time.time(),'requested_tail_records':120,'command_exit':p.returncode,'observed_records':len(times),'first_timestamp_us':times[0] if times else None,'last_timestamp_us':times[-1] if times else None,'message_substring_counts':counts,'unique_message_sha256':sorted(message_hashes),'raw_log_sha256':hashlib.sha256(p.stdout.encode()).hexdigest(),'raw_logs_exported':False,'service_status':statuses,'binary_to_source_bound':False,'root_cause_proven':False,'state_mutated':False},indent=2))

