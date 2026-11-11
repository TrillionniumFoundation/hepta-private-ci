"""Read-only full-roster postcheck; does not rerun any closure case."""
from datetime import datetime,timezone
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve();out=pathlib.Path(sys.argv[2]).resolve()
source=root/"candidate-source"
def ident(path):
    raw=path.read_bytes();return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
receipt=json.loads((root/"EXECUTION.json").read_bytes())
before,original_after=receipt["source_before"],receipt["source_after"]
current={str(p.relative_to(source)):ident(p) for p in sorted(source.rglob("*")) if p.is_file()}
missing=sorted(set(before)-set(original_after))
expected=["supervisor-source/complete_os_envelope.py","supervisor-source/os_processes.py"]
assert receipt["source_unchanged"] is False and missing==expected
assert not (set(original_after)-set(before))
assert all(original_after[k]==before[k] for k in original_after)
assert current==before
producer=pathlib.Path("/workspace/scratch/c385a7439f8e/complete-os-supervisor-rebind-v3")
producer_ids={name:ident(producer/pathlib.Path(name).name) for name in expected}
assert all(producer_ids[name]==current[name] for name in expected)
result={"schema":"renderer155-posthoc-roster-coverage-rebind-v1",
    "status":"complete_current_bytes_match_original_before","observed_at_UTC":datetime.now(timezone.utc).isoformat(),
    "original_execution_receipt":ident(root/"EXECUTION.json"),"original_driver":ident(root/"launch_probe.py"),
    "original_source_unchanged_flag_retained":False,"original_before_member_count":len(before),
    "original_after_member_count":len(original_after),"posthoc_full_member_count":len(current),
    "omitted_original_after_members":missing,"changed_common_original_members":[],
    "posthoc_current_bytes":current,"source_only_producer_reference_bytes":producer_ids,
    "case_output":ident(root/"cases/CLOSURE.json"),
    "scope":"A later complete read-only source rebind. It does not manufacture the missing contemporaneous after entries or alter the original false flag. No case, analysis, plotting, model, native job or E access.",
    "original_after_code_and_config_were_unchanged":True,
    "fixture_source_pins_also_checked_in_original_native_positive_and_negative_calls":True}
out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
print(json.dumps({"original_before":len(before),"original_after":len(original_after),"posthoc":len(current),"missing_original_after":missing,"all_current_match_before":True}))

