"""Build a bounded-blob, public-only evidence package for hepta-private-ci.

No credentials or private model files are read. This is packaging, not a rerun.
An optional Colab evidence archive can be supplied after its hashes are checked.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, io, json, shutil, tarfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE/"WeightCode"
DEST=HERE/"publish"/"weightcode"
CHUNK=450_000
def sha(data):return hashlib.sha256(data).hexdigest()
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
def put(relative,data):
    path=DEST/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if len(data)<=CHUNK:
        path.write_bytes(data)
        return {"path":relative,"bytes":len(data),"sha256":sha(data)}
    pieces=[]
    for i,start in enumerate(range(0,len(data),CHUNK)):
        name=relative+f".part{i:03d}"
        chunk=data[start:start+CHUNK]
        (DEST/name).write_bytes(chunk)
        pieces.append({"path":name,"bytes":len(chunk),"sha256":sha(chunk)})
    record={"reconstructed_path":relative,"bytes":len(data),"sha256":sha(data),"parts":pieces,
            "reconstruction":"Concatenate parts in listed order; verify complete SHA before decompression or reading"}
    save(DEST/(relative+".manifest.json"),record)
    return record
def make_tar(paths,root):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode="w") as archive:
        for p in sorted(paths):
            data=p.read_bytes()
            info=tarfile.TarInfo(str(p.relative_to(root)))
            info.size=len(data);info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=""
            archive.addfile(info,io.BytesIO(data))
    return gzip.compress(stream.getvalue(),mtime=0)

parser=argparse.ArgumentParser()
parser.add_argument("--cloud-archive",type=Path)
args=parser.parse_args()
summary_path=HERE/"scan_extension"/"summary.json"
if not summary_path.exists():raise RuntimeError("Fixed CPU matrix is not complete; do not package partial results as final")
summary=json.loads(summary_path.read_text())
DEST.mkdir(parents=True,exist_ok=True)
sources=["scan_extension_protocol.json","run_scan_extension.py","scan_rule_to_data_protocol.json",
         "run_scan_rule_to_data.py","colab_rule_to_data_amendment.json","colab_rule_to_data_worker.py",
         "colab_scan_rule_to_data_job.py","wsp_research_handoff_20261128.md","prepare_weightcode_publish.py"]
sources.append("audit_rulegen_gradient_accumulation.py")
for name in sources:put("source/"+name,(HERE/name).read_bytes())
put("source/WEIGHTCODE_LICENSE",(REPO/"LICENSE").read_bytes())
session=REPO/"reproduction_scan"/"downloads"/"hf"/"records"/"sessions"/"s9be29c2c302e4daa"
run=json.loads((session/"run.json").read_text())
session_result=json.loads((session/"session_result.json").read_text())
cost={"created_at":run["created_at"],"finalized_at":run["finalized_at"],"queries_used":run["queries_used"],
      "editor":run["editor"],"tokens":session_result["tokens"],"session_wall_seconds":session_result["wall_s"],
      "dollar_bill":"Not present in the inspected per-session records; do not infer from current list pricing",
      "token_interpretation":"Upstream fields retained. Thinking may be included in output; do not double-count.",
      "our_program_update_seconds":json.loads((HERE/"scan_extension"/"program_audit.json").read_text())["published_program_update_wall_seconds"],
      "our_official_reexecute_plus_readout_seconds":144.679}
save(DEST/"results"/"author_discovery_cost.json",cost)
put("results/official_scan_reexecution.json",(REPO/"reproduction_scan"/"runs"/"20261128T103750.741015Z"/"result.json").read_bytes())
put("results/matrix_summary.json",summary_path.read_bytes())
for name in ("manifest.json","program_audit.json"):
    put("results/"+name,(HERE/"scan_extension"/name).read_bytes())
for path in sorted((HERE/"scan_extension"/"arms").glob("*.json")):
    put("results/arms/"+path.name,path.read_bytes())
put("results/cpu_matrix_stdout.log",(HERE/"scan_extension_run.log").read_bytes())
put("results/cancelled_cpu_queue.json",(HERE/"scan_rule_to_data"/"queue_cancelled_before_fit.json").read_bytes())
put("results/postsubmission_nonzero_gradient_audit.json",(HERE/"rulegen_gradient_accumulation_audit.json").read_bytes())
prediction_archive=put("artifacts/scan_predictions.tar.gz",make_tar(list((HERE/"scan_extension"/"predictions").glob("*.npz")),HERE/"scan_extension"))
patch_root=REPO/"reproduction_scan"/"runs"/"20261128T103750.741015Z"/"replay"/"patch"
patch_archive=put("artifacts/exact_public_program_patch.tar.gz",make_tar(list(patch_root.glob("*")),patch_root))
put("source/centroid_meanrow_floor.py",(session/"final"/"centroid_meanrow_floor.py").read_bytes())
pins={"upstream_url":"https://github.com/Gen-Verse/WeightCode","source_commit":summary["source_commit"],
      "dataset_url":"https://huggingface.co/datasets/Boom5426/WeightCode","dataset_revision":"4c27541829737b8a4c438634d12792043409706d",
      "dataset_sha256sums_sha256":"31edb7a83866bb9950e527a8f2d7d55826089a75552f1a34efa6a8247faba0e4",
      "base_params_sha256":summary["base_params_sha256"],"edited_params_sha256":summary["published_child_sha256"],
      "source_files":{str(p.relative_to(session)):sha(p.read_bytes()) for p in (session/"run.json",session/"session_result.json",session/"final"/"centroid_meanrow_floor.py")},
      "selected_models":{r["name"]:r["params_sha256"] for r in summary["records"]},
      "storage":"Public base checkpoint is fetched by pinned downloader; unchanged selected models reference that hash. Edited model is reconstructed by exact patch. All candidate-selection records and predictions are retained.",
      "prediction_archive":prediction_archive,"published_patch_archive":patch_archive}
save(DEST/"source_pins.json",pins)
csv_buffer=io.StringIO()
writer=csv.writer(csv_buffer)
writer.writerow(["arm","kind","new_n","new_correct","new_em","old_n","old_correct","old_em","selected_changed_parameters","fit_wall_s","check_wall_s","final_wall_s"])
for r in summary["records"]:
    n,o=r["final"]["new"],r["final"]["old"]
    writer.writerow([r["name"],r["kind"],n["n"],round(n["n"]*n["em_child"]),n["em_child"],o["n"],round(o["n"]*o["em_child"]),o["em_child"],r["n_changed"],r.get("fit_wall_seconds",0),r.get("check_wall_seconds",0),r["final_wall_seconds"]])
put("results/matrix_quality_cost.csv",csv_buffer.getvalue().encode())
cloud={"status":"pending_actual_colab_result","warning":"Do not mark rule-to-data reproduction complete from this CPU package"}
if args.cloud_archive:
    cloud={"status":"artifact_provided_review_summary_inside_archive","archive":put("artifacts/colab_rule_to_data_evidence.tar.gz",args.cloud_archive.read_bytes())}
save(DEST/"colab_status.json",cloud)
rows=[]
for r in summary["records"]:
    rows.append(f"| {r['name']} | {100*r['final']['new']['em_child']:.4f}% | {100*r['final']['old']['em_child']:.4f}% | {r['n_changed']} |")
readme="""# WeightCode/SCAN public reproduction evidence

This package contains a completed fixed CPU matrix and its public source pins.
It contains no pocket4 model, private Hepta checkpoint, credentials or trading data.
The accompanying `colab_status.json` states whether the separate same-grammar
rule-to-data run has actually completed or is still awaiting evidence.

## Outcome and interpretation

The published 257-parameter WSP program reproduced its full canonical child hash
exactly. On the public sealed split it changes new-command exact match from 0 to
99.8053%, preserving old-command exact match at 99.6%. This reruns a program
originally authored by Claude Opus 5.5; it is not a new independent GPT discovery.

The fixed 65-label Adam/LoRA comparisons begin with token CE only 5.23e-9 on their
training rows. Their lack of new-command gain does not establish that gradient
learning cannot perform the task. The explicit grammar supplies knowledge beyond
those 65 labels; published grammar-generated training reaches 99.6%, and its
independent fixed-configuration reproduction is recorded separately.

The WSP program probes 299 of 2,568 final-new inputs and every final-old input
without labels, so this is a label-heldout public reproduction, not a fresh
completely unseen-input experiment. Inferences about HeptaTrader are not made.

| Fixed arm | Final new EM | Final old EM | Selected parameters changed |
|---|---:|---:|---:|
"""+"\n".join(rows)+"\n\n"+f"CPU matrix wall time: {summary['total_wall_seconds']:.3f}s. All restore operations verified the complete original canonical hash.\n"+"""

## Files and reproduction

`source/scan_extension_protocol.json` was fixed before extension results were
observed. `results/manifest.json` records protocol, runner, source and environment
identities. `results/arms/*_selection.json` records every BP candidate and the
check-only decision before its selected final reading. The source scripts call
the pinned upstream model/optimizer implementations.

Clone the pinned upstream commit, use its public downloader to fetch and verify
the declared model/data, run the official `weightcode reproduce scan` example,
and run `source/run_scan_extension.py` with paths adjusted as a recorded harness
change. The recorded local execution path is deliberately preserved in evidence;
do not present an unrun path adaptation as another verified reproduction.

Large archives use ≤450,000-byte chunks. Concatenate the listed parts in order,
verify the complete SHA in the adjacent `.manifest.json`, then decompress. Each
archive retains exact filenames and public scientific arrays.

Read `source/wsp_research_handoff_20261128.md` for primary-source literature,
the distinction between metadata inspection and circuit analysis, and Hepta
information-path/span/true-recursion diagnostics. Literature suggestions are
not converted into measured Hepta performance claims.
"""
put("README.md",readme.encode())
files=[{"path":str(p.relative_to(DEST)),"bytes":p.stat().st_size,"sha256":sha(p.read_bytes())} for p in sorted(DEST.rglob("*")) if p.is_file() and p.name!="PACKAGE_MANIFEST.json"]
assert all(f["bytes"]<=CHUNK for f in files)
save(DEST/"PACKAGE_MANIFEST.json",{"files":files,"all_blobs_max_bytes":CHUNK,"cpu_matrix_complete":True,"cloud":cloud})
print(json.dumps({"directory":str(DEST),"files":len(files)+1,"total_bytes":sum(f["bytes"] for f in files),"cloud":cloud["status"]}))
