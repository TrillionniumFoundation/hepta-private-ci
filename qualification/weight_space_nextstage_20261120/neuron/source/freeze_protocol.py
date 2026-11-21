"""Freeze explicit technical revision; existing v1 artifacts remain unchanged."""
from pathlib import Path
import ast
import copy
import datetime
import json
from reuse_candidates import identity,read,V1_SHA

ROOT=Path(__file__).resolve().parent
V1=ROOT.parent
if (ROOT/"attempt001").exists():raise ValueError("v2 attempt already exists")
if not (ROOT/"verify_records.py").exists():raise ValueError("independent reader required before freeze")
old=read(V1/"PROTOCOL_FROZEN.json")
if identity(V1/"PROTOCOL_FROZEN.json")["sha256"]!=V1_SHA:raise ValueError("v1 protocol identity")
preflight=read(ROOT/"PREFLIGHT.json")
if preflight["status"]!="PASS_ZERO_FORWARD_REUSE_PREFLIGHT" or preflight["model_calls"]!=0:
    raise ValueError("zero-forward preflight missing")
receipt=read(V1/"attempt001_supervisor.json")
files={}
for name,meta in old["files"].items():
    path=(V1/name).resolve()
    if identity(path)!=meta:raise ValueError("v1 frozen source modified")
    files[str(path)]=meta
for path in V1.iterdir():
    if path.is_file():files[str(path.resolve())]=identity(path)
for path in (V1/"attempt001").rglob("*"):
    if path.is_file():files[str(path.resolve())]=identity(path)
for path in ROOT.glob("*.py"):
    ast.parse(path.read_text(),filename=str(path));files[path.name]=identity(path)
for name in ("DRAFT_PROTOCOL.md","PREFLIGHT.json"):
    files[name]=identity(ROOT/name)
if identity(ROOT/"causal_core.py")!=identity(V1/"causal_core.py"):
    raise ValueError("v2 causal mathematics must remain byte-identical")
protocol=copy.deepcopy(old)
protocol.update(schema="hepta-endpoint-causal-rescue-constructive-WSP-v2",
    status="FROZEN_BEFORE_REVISED_EVALUATION",created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    output_absolute=str(ROOT/"attempt001"),files=files)
protocol["confirmation"]["known_history"]=3256
protocol["resources"].update(CPU_soft_seconds=250,CPU_hard_seconds=261,wall_seconds=560,
    total_scientific_CPU_hard_seconds=300,total_scientific_wall_seconds=600,
    prior_child_CPU_seconds=receipt["child_CPU_seconds"],prior_wall_seconds=receipt["enclosed_wall_seconds"],
    metadata_preflight_CPU_seconds=preflight["CPU_seconds"],reader_budget_separate=True)
protocol["revision"]=dict(kind="technical_path_fix_reuse_frozen_candidates",
    v1_root_absolute=str(V1),v1_protocol_sha256=V1_SHA,
    v1_failure_sha256=identity(V1/"attempt001/FAILED.json")["sha256"],
    v1_supervisor_sha256=identity(V1/"attempt001_supervisor.json")["sha256"],
    v1_family_seal_sha256=identity(V1/"attempt001/ALL_FAMILIES_FROZEN.json")["sha256"],
    v1_child_CPU_seconds=receipt["child_CPU_seconds"],v1_wall_seconds=receipt["enclosed_wall_seconds"],
    excluded_v1_DEV_worlds=40,known_history=3256,TRAIN_recomputed=False,
    candidate_bytes="all v1 family records, teachers, C/D/R/P/RP and four alpha files reused exactly",
    scientific_hyperparameters_changed=False,primary_tests_changed=False,
    exposure_evidence="v1 first DEV file lookup exception; no graphs/selection/CONF/RESULTS; event chain ends DEV_worlds_frozen",
    preflight_sha256=identity(ROOT/"PREFLIGHT.json")["sha256"],
    external_custodian=False,automatic_retry=False,
    authorization="parent explicitly authorized separate v2 technical correction without recomputing candidates")
if receipt["child_CPU_seconds"]+261>300 or receipt["enclosed_wall_seconds"]+560>600:
    raise ValueError("combined original budget exceeded")
for key in old:
    if key not in ("schema","status","created_utc","output_absolute","files","confirmation","resources"):
        if protocol[key]!=old[key]:raise ValueError("scientific configuration changed: "+key)
confirm=copy.deepcopy(protocol["confirmation"]);confirm["known_history"]=3216
if confirm!=old["confirmation"]:raise ValueError("confirmation contract changed beyond history")
target=ROOT/"PROTOCOL_FROZEN.json"
with target.open("x") as stream:json.dump(protocol,stream,sort_keys=True,indent=2);stream.write("\n")
print(json.dumps(dict(protocol=str(target),files=len(files),**identity(target),real_model_calls=0)))
