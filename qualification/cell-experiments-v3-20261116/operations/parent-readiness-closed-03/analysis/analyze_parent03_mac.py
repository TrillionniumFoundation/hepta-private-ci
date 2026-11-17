"""Verify and summarize the complete original parent03 archive without rerunning it."""
from pathlib import Path
import collections,hashlib,io,json,time,zipfile
MAC=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
ROOT=MAC/"parent03-terminal-checkpoint01"
PROBE="probe-qwen-parent-03/"
SHA="036322be9179b66580717ace8f23faa5bdbaaa6a09145c329d2bbd7742863e4b"
MODEL="f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6"
def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def write(path,raw):
    with path.open("xb") as f:f.write(raw)
def unpack(value):
    if value.get("structuredContent"):return value["structuredContent"]
    return json.loads(next(row["text"] for row in value["content"] if row["type"]=="text"))
def main():
    raw=(ROOT/"stdout.zip").read_bytes();assert digest(raw)==SHA
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        capture=json.loads(archive.read("POSTHOC_CAPTURE.json"));assert len(capture["members"])==308
        original={row["path"]:archive.read(row["path"]) for row in capture["members"]}
        assert all((len(original[row["path"]]),digest(original[row["path"]]))==(row["bytes"],row["sha256"]) for row in capture["members"])
    valid={name:json.loads(raw) for name,raw in original.items() if name.endswith(".json")}
    result=valid[PROBE+"RESULT.json"];freeze=valid[PROBE+"FREEZE.json"];parent=valid[PROBE+"parent.json"]
    exit_receipt=valid["owned-qwen-parent-03/EXIT.json"]
    assert result["status"]=="COMPLETE" and result["repository_status"]=="NOT_READY"
    assert all(stage["status"]=="COMPLETE" for stage in result["stages"])
    assert result["model_digest"]==digest(canonical(parent))==MODEL
    assert result["freeze_digest"]==digest(canonical(freeze))
    assert result["receipt_sha256"]==digest(canonical({k:v for k,v in result.items() if k!="receipt_sha256"}))
    assert all(digest(original[PROBE+name])==sha for name,sha in result["retained_file_sha256"].items())
    assert exit_receipt["wait_returncode"]==0 and exit_receipt["exit_source"]=="subprocess.Popen.wait"
    for stream in ("stdout","stderr"):
        assert (len(original["owned-qwen-parent-03/"+stream+".log"]),digest(original["owned-qwen-parent-03/"+stream+".log"]))==(exit_receipt[stream]["bytes"],exit_receipt[stream]["sha256"])
    source=original["qwen-source-02.zip"];assert digest(source)=="38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7"
    source_manifest=valid["operations/QWEN_SOURCE_02.json"]
    with zipfile.ZipFile(io.BytesIO(source)) as package:
        assert package.testzip() is None and len(package.namelist())==119
        assert set(package.namelist())==set(source_manifest["files"])
        assert all(digest(package.read(name))==sha for name,sha in source_manifest["files"].items())
        assert sum(name.startswith("scripts/cell_experiments/") for name in package.namelist())==64
    outputs={n:v for n,v in valid.items() if n.startswith(PROBE) and "/output-" in n}
    repo_steps={n:v for n,v in valid.items() if n.startswith(PROBE+"repository/") and "/step-" in n}
    sqlite_steps={n:v for n,v in valid.items() if n.startswith(PROBE+"sqlite/") and "/step-" in n}
    repo_tasks=[valid[PROBE+"repository/"+str(i)+"/RESULT.json"] for i in range(9)]
    panel=valid[PROBE+"sqlite/PANEL.json"]
    assert (len(outputs),len(repo_steps),len(sqlite_steps))==(54,18,36)
    assert all(v["pid"]==1912611 and v["loaded_model_digest"]==MODEL for v in outputs.values())
    assert sum(v["output_tokens"] for v in outputs.values())<=20736
    def panel_cost(prefix):
        rows=[v for n,v in outputs.items() if n.startswith(PROBE+prefix+"/")]
        return {"completed_model_calls":len(rows),"input_tokens":sum(v["input_tokens"] for v in rows),"output_tokens":sum(v["output_tokens"] for v in rows),"generation_wall_seconds":sum(v["wall_seconds"] for v in rows),"output_limit_hits":sum(v["hit_output_limit"] for v in rows)}
    repo_cost,sqlite_cost=panel_cost("repository"),panel_cost("sqlite")
    sqlite_rows=[]
    for row in panel["rows"]:
        sqlite_rows.append({"task_id":row["task_id"],"success":row["success"],"decisions":row["decisions"],"terminal_reason":row["sqlite_result"]["terminal_reason"],"actions":dict(collections.Counter(s["parsed_action"] for s in row["steps"])),"parse_errors":sum(s["parse_error"] is not None for s in row["steps"]),"predictor_contract_errors":sum(s["predictor_contract_error"] is not None for s in row["steps"]),"business_result":row["sqlite_result"]["business_result"],"cost":row["cost"]})
    prior_path=MAC/"parent02-salvage-ram01/QWEN_PARENT02_POSTHOC_COUNTS.json"
    prior=json.loads(prior_path.read_bytes());assert prior["minimum_observed_model_calls"]==14
    terminal=unpack(json.loads((ROOT/"CONTROLLER_PTY_FINAL.json").read_bytes()))
    assert terminal["status"]["state"]=="exited" and terminal["status"]["exit_code"]==0 and terminal["output_complete"] is True
    originals=ROOT/"raw-summary";originals.mkdir()
    keep={"RESULT.json":PROBE+"RESULT.json","FREEZE.json":PROBE+"FREEZE.json","parent.json":PROBE+"parent.json","PREPARED_A_RECORDS.json":PROBE+"PREPARED_A_RECORDS.json","PREPARED_RECORDS.json":PROBE+"PREPARED_RECORDS.json","READINESS.json":PROBE+"repository/READINESS.json","SQLITE_PANEL.json":PROBE+"sqlite/PANEL.json","OWNED_EXIT.json":"owned-qwen-parent-03/EXIT.json"}
    for name,path in keep.items():write(originals/name,original[path])
    report={"schema":"hepta.qwen-parent03-posthoc-summary.v3","created_at_ns":time.time_ns(),"analysis_source_sha256":digest(Path(__file__).read_bytes()),"summary_kind":"derived analysis of complete preserved original bytes; no new model execution",
      "archive_sha256":SHA,"raw_members_verified":308,"source_members_verified":119,"core_members_verified":64,
      "original_result_sha256":digest(original[PROBE+"RESULT.json"]),"owned_exit_sha256":digest(original["owned-qwen-parent-03/EXIT.json"]),
      "controller_pty_final_sha256":digest((ROOT/"CONTROLLER_PTY_FINAL.json").read_bytes()),"owned_child_wait_returncode":0,"mac_pty_exit_code":0,"mac_pty_output_complete":True,
      "operation_status":result["status"],"repository_status":result["repository_status"],"model_digest":MODEL,"freeze_digest":result["freeze_digest"],
      "artifact_root":"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a","candidate_source_root":"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/candidate-qwen-03",
      "readiness_root":"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/probe-qwen-parent-03","runtime_root":"/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a",
      "python":"/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python","python_flags":["-I","-B"],
      "raw_summary_files":{name:{"bytes":len(original[path]),"sha256":digest(original[path])} for name,path in keep.items()},
      "repository":{"tasks":9,"successes":sum(r["success"] for r in repo_tasks),"A_tasks":6,"A_successes":sum(r["success"] for r in repo_tasks[:6]),"B_tasks":3,"B_successes":sum(r["success"] for r in repo_tasks[6:]),"attempts":18,"verification_reasons":dict(collections.Counter(v["verification"]["result"]["reason"] for v in repo_steps.values())),"format_errors":dict(collections.Counter(v["verification"]["result"].get("feedback","") for v in repo_steps.values())),"business_execution_attempts":sum(v["executed"] for v in repo_steps.values()),"successful_verifications":sum(v["verification"]["success"] for v in repo_steps.values()),"generation_cost":repo_cost},
      "sqlite":{"tasks":3,"successes":panel["successes"],"model_decisions":36,"parsed_actions":dict(collections.Counter(v["parsed_action"] for v in sqlite_steps.values())),"parse_errors":sum(v["parse_error"] is not None for v in sqlite_steps.values()),"business_execution_actions":sum(v["sqlite_receipt"]["execution_performed"] for v in sqlite_steps.values()),"primitive_calls":sum(v["sqlite_receipt"]["execution_summary"]["primitive_calls_delta"] for v in sqlite_steps.values()),"write_transactions":sum(v["sqlite_receipt"]["execution_summary"]["write_transactions_delta"] for v in sqlite_steps.values()),"applied_effects":sum(v["sqlite_receipt"]["execution_summary"]["applied_effects_delta"] for v in sqlite_steps.values()),"rows":sqlite_rows,"generation_cost":sqlite_cost,"payloads_supplied_by_destination":True,"distinct_independent_sources_added":0},
      "operation_cost":result["cost"],"operation_stage_costs":{r["stage"]:r["cost"] for r in result["stages"]},"wrapper_child_wall_seconds":exit_receipt["child_wall_seconds"],
      "all_completed_model_calls":54,"all_input_tokens":sum(v["input_tokens"] for v in outputs.values()),"all_output_tokens":sum(v["output_tokens"] for v in outputs.values()),"all_generation_wall_seconds":sum(v["wall_seconds"] for v in outputs.values()),
      "cost_scope_note":"operation, panels, generation and wrapper scopes overlap and must not be summed",
      "prior02_extra_cost":{"report_sha256":digest(prior_path.read_bytes()),"minimum_model_calls":14,"input_tokens":prior["retained_input_tokens"],"output_tokens":prior["retained_output_tokens"],"generation_wall_seconds":prior["retained_generation_wall_seconds"],"complete_operation_cost_available":False,"exit_code":None,"capture_complete":False},
      "combined_observed_minimum_calls":68,"combined_observed_output_tokens":3819+sum(v["output_tokens"] for v in outputs.values()),"combined_observed_generation_seconds":prior["retained_generation_wall_seconds"]+sum(v["wall_seconds"] for v in outputs.values()),
      "new_C":False,"new_users":0,"external_teacher_count_added":0,"independent_sample_increment":0,"native_cell_adoption":False,"training_started":False,"scientific_confirmation_qualified":False,"outputs_repaired":False,"model_calls_added_by_analysis":0}
    output=ROOT/"QWEN_PARENT03_POSTHOC_SUMMARY.json";write(output,canonical(report)+b"\n")
    print(json.dumps({"report":str(output),"sha256":digest(output.read_bytes()),"repo":report["repository"],"sqlite":{k:v for k,v in report["sqlite"].items() if k!="rows"},"sqlite_business_rows":[{"task_id":r["task_id"],"business_result":r["business_result"],"terminal_reason":r["terminal_reason"]} for r in sqlite_rows],"calls":54,"all_output_tokens":report["all_output_tokens"],"all_generation_wall_seconds":report["all_generation_wall_seconds"],"combined_calls":68,"combined_output_tokens":report["combined_observed_output_tokens"]}),flush=True)
if __name__=="__main__":main()
