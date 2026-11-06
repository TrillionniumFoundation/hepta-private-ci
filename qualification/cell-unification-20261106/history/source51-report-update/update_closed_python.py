from pathlib import Path
import copy,json,hashlib,re
B=Path("/workspace/scratch/08f5efd48967");D=B/"hepta-cell/qualification/cell-unification-20261106";H=D/"history";U=H/"source51-report-update";C=B/"native-validation-results/r26-start-and-python-closed"
def load(p):return json.loads(Path(p).read_bytes())
def jd(o):return (json.dumps(o,ensure_ascii=False,indent=2)+"\n").encode()
def pin(p,raw=None):
 p=Path(p);raw=p.read_bytes() if raw is None else raw
 try:n=p.relative_to(D).as_posix()
 except ValueError:n=str(p)
 return dict(path=n,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())
def create(p,raw):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==raw,str(p)
 else:
  with p.open("xb") as f:f.write(raw)
 return pin(p,raw)
rb=load(C/"LOCAL-READBACK.json")
for x in rb["files"]:
 q=pin(C/x["path"]);assert all(q[k]==x[k] for k in ("bytes","sha256","git_blob")),x["path"]
prefix="native-source51-project-r26-python-runner"
receipt=load(C/(prefix+"-receipt.json"));raw_result=load(C/(prefix+"-raw-process-result.json"));review=load(C/(prefix+"-result-review.json"));post=load(C/(prefix+"-source-post-verification.json"));running=load(C/"observed-running-process-status.json")
log=(C/(prefix+".log")).read_bytes();resources=(C/(prefix+"-resources.txt")).read_bytes()
assert receipt["exit_code"]==raw_result["exit_code"]==receipt["effective_exit_code"]==0 and receipt["phase_pass"] and receipt["issues"]==[]
assert receipt["log_sha256"]==hashlib.sha256(log).hexdigest() and receipt["resources_sha256"]==hashlib.sha256(resources).hexdigest()
assert re.findall(rb"(?m)^\s*Exit status: (\d+)\s*$",resources)==[b"0"]
assert review["pass"] and review["reported_test_count"]==32 and review["reported_skipped"]==0
assert re.findall(rb"(?m)^Ran (\d+) tests in ([\d.]+)s$",log)==[(b"32",b"59.132")]
assert len(re.findall(rb"(?m)^OK$",log))==1
names=re.findall(rb"(?m)^(test[A-Za-z0-9_]+) \(([^()\n]+)\) \.\.\.",log)
assert len(names)==len(set(names))==32
assert post["pass"] and post["changed_file_count"]==194 and post["actual_tree"]=="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
assert receipt["source_guards_pass"] and running["state"]=="running" and running["job_id"]=="1a1b1b739ee-fc05-7a70"
progress=[json.loads(x) for x in (C/"progress-original-stdout.txt").read_text().splitlines() if x.strip()]
assert any(x.get("phase")=="strict-start" and x.get("command")==["just","clippy","--locked","-p","codex-cli","-p","codex-exec-server","-p","codex-network-proxy","-p","codex-external-agent-migration","--","-D","warnings"] for x in progress)
dest=H/"source51-r26-python-checkpoint";files=sorted(p for p in C.rglob("*") if p.is_file());rows=[]
for p in files:rows.append(dict(source_workspace_path=p.relative_to(B).as_posix(),snapshot=create(dest/p.relative_to(C),p.read_bytes())))
mp=create(dest/"MANIFEST.json",jd(dict(schema="hepta.r26-closed-python-running-snapshot.v1",state="PYTHON_PASS_STRICT_STARTED_NO_RUST_TERMINAL",source_commit=receipt["source_commit"],source_tree=receipt["source_tree"],job_id=running["job_id"],files=rows,original_bytes_unchanged=True,python_tests=32,python_skipped=0,python_raw_exit_code=0,whole_command_seconds=receipt["elapsed_seconds"],unittest_seconds=59.132,strict_terminal=None,tests_terminal=None,outer_terminal=None,original_gate_not_repeated=True,local_readback_attempt1_error_is_not_native_gate_failure=True)))
r26base=load(U/"STATUS.candidate.json")["validation"]["gates"]["r26"];r26=copy.deepcopy(r26base)
r26.update(state="RUNNING_PYTHON_PASS_STRICT_STARTED",last_observed_job_state="running",python_exit_code=0,python_effective_exit_code=0,python_counts=dict(executed=32,passed=32,reported_skipped=0),python_elapsed_seconds_including_fixtures=receipt["elapsed_seconds"],python_unittest_seconds=59.132,python_source_and_dual_lock_guards_pass=True,strict_started=True,strict_exit_code=None,tests_raw_exit_code=None,original_outer_exit_code=None,test_execution_started=None,new_gate_pass_claimed=False,closed_python_snapshot=mp,python_receipt=pin(dest/(prefix+"-receipt.json")),python_log=pin(dest/(prefix+".log")),python_raw_result=pin(dest/(prefix+"-raw-process-result.json")),python_acceptance=pin(dest/(prefix+"-result-review.json")),python_postguard=pin(dest/(prefix+"-source-post-verification.json")),last_running_observation=pin(dest/"observed-running-process-status.json"),strict_start_original_stdout=pin(dest/"progress-original-stdout.txt"))
s=load(U/"STATUS.candidate.json");i=load(U/"SOURCE_IDENTITY.candidate.json")
s["record_state"]="DRAFT_SOURCE51_APPLIED_R26_PYTHON_PASS_STRICT_STARTED_SOURCE50_R24_FAILED"
s["snapshot_boundary"]="Source51 staged apply closed0. Same r26 job was observed running, with original Python32/0skip raw/effective0 and source/dual-lock postguard PASS; strict-start observed. Strict, complete Rust tests and outer terminal remain unclosed. Latest complete Rust project gate is source50 r24 failed100."
s["validation"]["gates"]["r26"]=r26;s["next_source_preparation"]["r26"]=r26;s["next_source_preparation"]["state"]="SOURCE51_APPLIED_R26_PYTHON_PASS_STRICT_STARTED_RUST_RESULTS_PENDING"
i["state"]="SOURCE51_APPLIED_R26_PYTHON_PASS_STRICT_STARTED_PRE_FINAL_FIX_FMT";i["current_source_validation_status"]="APPLY0_R26_PYTHON32_PASS_STRICT_STARTED_NO_RUST_TERMINAL_SOURCE50_R24_FAILED";i["pending_native_gates"]["r26"]=r26
readme=(U/"README.candidate.md").read_text()
old="source51 的 r26 已唯一发起，首次状态／输出查询遇到控制连接准入超时，尚无成功读回的阶段结果；这不是 Rust 失败或任务重启。r27 完整工作区门仍是惰性准备，被 r24 阻止的旧 r25 未启动。"
new="source51 的同一 r26 任务已观察为 running：原 Python 测试 **32/32、0 skip，raw／effective 退出 0**，194 路径与双锁守卫通过，strict 已开始。严格门、完整 Rust 测试和外层任务均尚无闭合终态。r27 完整工作区门仍是惰性准备，被 r24 阻止的旧 r25 未启动。"
assert readme.count(old)==1;readme=readme.replace(old,new)
readme=readme.replace("[r26 已闭合 launch 快照][r26-launch]","[r26 已闭合 Python 与进度快照][r26-python]")
old="| r26 | source51 / "+chr(96)+"763c8d2"+chr(96)+" | 已发起；首次状态／输出查询不可用，尚无阶段或终态结果。全部终态计数为 "+chr(96)+"null"+chr(96)+"。[launch 原件][r26-launch] |"
new="| r26 | source51 / "+chr(96)+"763c8d2"+chr(96)+" | Python **32/32、0 skip、退出 0**；strict-start 已观察。同一 job 最后观察为 running；strict／Rust tests／outer 均无终态，终态计数为 "+chr(96)+"null"+chr(96)+"。[闭合 Python 原件][r26-python] |"
assert readme.count(old)==1;readme=readme.replace(old,new)
readme=readme.replace("新的 source51 登记、有限 probe、apply-only 与 r26 launch 快照均明确注明范围","新的 source51 登记、有限 probe、apply-only、r26 launch 与闭合 Python 快照均明确注明范围")
readme += "[r26-python]: history/source51-r26-python-checkpoint/MANIFEST.json\n"
readme=readme.replace("## 5. 剩余采用与发布门槛","r26 原 Python 命令含实际 fixture 构建等工作共 **71.149435997 秒**；unittest 自报执行 **59.132 秒**，两者分别保留。最初两次控制查询不可用的原件仍在 launch 历史中，不记为 Rust 失败或重跑。[launch 历史][r26-launch]\n\n## 5. 剩余采用与发布门槛")
# The scientific section must remain exactly equal; the timing paragraph belongs to section 3.
oldread=(H/"source49-r23-checkpoint/README.md").read_text();science=oldread[oldread.index("## 4."):oldread.index("## 5.")]
assert science in readme
# Move the progress timing note before section 4 so the original scientific section stays byte-identical.
note="r26 原 Python 命令含实际 fixture 构建等工作共 **71.149435997 秒**；unittest 自报执行 **59.132 秒**，两者分别保留。最初两次控制查询不可用的原件仍在 launch 历史中，不记为 Rust 失败或重跑。[launch 历史][r26-launch]\n\n"
readme=readme.replace(note,"");readme=readme.replace("## 4.",note+"## 4.",1)
assert readme[readme.index("## 4."):readme.index("## 5.")]==science
for name,data in [("STATUS.candidate.json",jd(s)),("SOURCE_IDENTITY.candidate.json",jd(i)),("README.candidate.md",readme.encode())]:(U/name).write_bytes(data)
print(json.dumps(dict(snapshot=mp,candidates=[pin(U/n) for n in ["README.candidate.md","STATUS.candidate.json","SOURCE_IDENTITY.candidate.json"]]),ensure_ascii=False))

