"""Posthoc retained-byte analysis; no inferred completion and no model calls."""
from pathlib import Path
import collections,hashlib,json,time,zipfile
ROOT=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
DIRECTORY=ROOT/"parent02-salvage-ram01"
ARCHIVE=DIRECTORY/"salvage-parent02-01/QWEN_PARENT02_PARTIAL_RAW.zip"

def main():
    archive_sha=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    assert archive_sha=="6fb45706a7123b65cdc260ed33ce0a4afc9456eafd96b08a7dc9707cf38a70e7"
    valid,invalid={},[]
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None and len(archive.namelist())==114
        for name in archive.namelist():
            if not name.endswith(".json"):continue
            raw=archive.read(name)
            try:valid[name]=json.loads(raw)
            except (ValueError,UnicodeError) as error:invalid.append({"path":name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"parse_error":str(error)})
    outputs={k:v for k,v in valid.items() if k.startswith("probe/repository/") and "/output-" in k}
    steps={k:v for k,v in valid.items() if k.startswith("probe/repository/") and "/step-" in k}
    tasks={k:v for k,v in valid.items() if k.startswith("probe/repository/") and k.endswith("/RESULT.json")}
    references={k:v for k,v in valid.items() if k.startswith("probe/reference-")}
    assert (len(outputs),len(steps),len(tasks),len(references))==(14,13,6,9)
    assert all(v["pid"]==1555758 for v in outputs.values())
    assert all(v["loaded_model_digest"]=="f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6" for v in outputs.values())
    fields=("input_tokens","output_tokens","wall_seconds","hit_output_limit","started_at_ns","completed_at_ns")
    report={"schema":"hepta.partial-qwen-posthoc-analysis.v3","created_at_ns":time.time_ns(),"analysis_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      "raw_archive_sha256":archive_sha,"interpretation_kind":"posthoc retained-byte summary; not an operation result",
      "operation_status":"INCOMPLETE_ENOSPC_CAPTURE_LOSS","original_exit_code":None,"original_capture_complete":False,
      "complete_operation_cost_available":False,"minimum_observed_model_calls":14,"complete_generation_outputs":14,
      "output_rows":[{"path":k,**{f:v[f] for f in fields}} for k,v in sorted(outputs.items())],
      "retained_input_tokens":sum(v["input_tokens"] for v in outputs.values()),"retained_output_tokens":sum(v["output_tokens"] for v in outputs.values()),
      "retained_generation_wall_seconds":sum(v["wall_seconds"] for v in outputs.values()),
      "generation_time_scope":"render/tokenize/generate/decode; excludes load, verifiers and unretained work",
      "output_limit_hits":sum(v["hit_output_limit"] for v in outputs.values()),"complete_student_verification_receipts":13,
      "student_verification_reasons":dict(collections.Counter(v["verification"]["result"]["reason"] for v in steps.values())),
      "student_attempts_with_executed_business_checks":sum(v["executed"] for v in steps.values()),
      "student_successful_attempts":sum(v["verification"]["success"] for v in steps.values()),
      "failure_classification":"13 complete receipts reject JSON parsing before any business execution",
      "fourteenth_verification":"original 4096-byte step is truncated JSON; no completed outcome inferred",
      "completed_A_task_results":6,"completed_A_successes":sum(v["success"] for v in tasks.values()),
      "first_B_task":"two generation outputs; no completed task RESULT","repository_panel_completed":False,
      "sqlite_stage_retained":False,"sqlite_successes":None,"author_reference_verifications":9,
      "author_reference_successes":sum(v["success"] for v in references.values()),
      "author_reference_original_subject_calls":sum(len(v["result"]["result"]["observations"][0]["calls"]) for v in references.values()),
      "author_reference_controls_rejected":sum(v["result"]["controls_rejected"] for v in references.values()),
      "reference_results_are_student_results":False,"finished_stage_costs":{k:v["cost"] for k,v in valid.items() if k.startswith("probe/") and k.endswith("_FINISHED.json")},
      "invalid_original_json":invalid,"original_bytes_changed":False,"answers_repaired":False,
      "model_calls_added_by_analysis":0,"training_started":False,"new_C":False,"independent_sample_increment":0,
      "monetary_cost":None,"energy_joules":None,"gpu_active_seconds":None,"later_replay_costs":"additional; this partial operation cost is retained"}
    path=DIRECTORY/"QWEN_PARENT02_POSTHOC_COUNTS.json"
    with path.open("x") as f:json.dump(report,f,sort_keys=True,separators=(",",":"));f.write("\n")
    print(json.dumps({"report":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"calls":14,"input_tokens":report["retained_input_tokens"],"output_tokens":report["retained_output_tokens"],"generation_seconds":report["retained_generation_wall_seconds"],"student_business_executions":report["student_attempts_with_executed_business_checks"]}),flush=True)

if __name__=="__main__":main()
