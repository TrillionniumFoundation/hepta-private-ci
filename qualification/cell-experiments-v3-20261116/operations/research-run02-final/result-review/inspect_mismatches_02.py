"""Read-only diagnosis of review predicates; no model or verifier execution."""
import json
from pathlib import Path
R=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
C=R/"research-final-evidence-02"
def read(p): return json.loads((C/p).read_bytes())
reuse=read("research-sft-02/workers/corrections-collect/CONTROLLED_REUSE.json")["observations"]
for i,row in enumerate(reuse):
    raw=read("probe-qwen-parent-03/repository/%d/RESULT.json"%i)
    print(json.dumps({"kind":"old_parent","index":i,"raw_keys":list(raw),"aggregate_keys":list(row),
      "different_common_fields":[k for k in raw if k in row and raw[k]!=row[k]],
      "extra_fields":{k:v for k,v in row.items() if k not in raw}},sort_keys=True))
for arm in ("final_answer","trajectory"):
    prefix="research-sft-02/workers/"
    a=read(prefix+arm+"-primary/RESULT.json");b=read(prefix+arm+"-cold/RESULT.json")
    print(json.dumps({"kind":"identity","arm":arm,"same_manifest":a["manifest"]==b["manifest"],
        "pids":[a["pid"],b["pid"]]},sort_keys=True))
    for i,(ra,rb) in enumerate(zip(a["evaluation"]["rows"],b["evaluation"]["rows"])):
        for n,(sa,sb) in enumerate(zip(ra["steps"],rb["steps"])):
            for key in ("answer","output_token_ids","input_tokens","output_tokens","messages_sha256"):
                va,vb=sa["output"][key],sb["output"][key]
                if va!=vb:
                    print(json.dumps({"kind":"cold_difference","arm":arm,"row":i,"task_id":ra["task_id"],
                        "attempt":n,"field":key,"primary":va,"cold":vb,
                        "prior_feedback_primary":ra["steps"][n-1]["feedback"] if n else None,
                        "prior_feedback_cold":rb["steps"][n-1]["feedback"] if n else None},sort_keys=True))
