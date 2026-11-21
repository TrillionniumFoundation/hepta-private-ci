"""Standard-library, zero-forward provenance preflight for v1 candidate reuse."""
from pathlib import Path
import ast
import datetime
import gzip
import hashlib
import io
import json
import math
import sys
import time

V1_SHA = "e783f20eb2ce7d76abcbddbbc26d34e777ff8a6a5c0aea66fd1625fcff8f1f50"
FITS = (11,23,37,53,71)


def identity(path):
    if path.stat().st_size>32*1024*1024:raise ValueError("bounded source extent")
    raw=path.read_bytes()
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    if path.stat().st_size>32*1024*1024:raise ValueError("bounded JSON input extent")
    raw=path.read_bytes()
    if path.suffix==".gz":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:raw=stream.read(32*1024*1024+1)
    if len(raw)>32*1024*1024:raise ValueError("bounded expanded JSON extent")
    return json.loads(raw)


def checked_relative(base,name):
    path=Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("candidate metadata contains an unsafe relative path")
    target=base/path
    if target.is_symlink() or base.resolve() not in target.resolve().parents:
        raise ValueError("candidate path escaped frozen output")
    if not target.is_file():raise ValueError("candidate file missing")
    return target


def finite_model(model):
    if (model["schema"]!="joint-policy-v1" or model["family"]!="renewal" or
        model["head_dimensions"]!=[85,48,4] or model["parameter_count"]!=4332):
        raise ValueError("candidate semantic identity")
    n=model["network"]
    if (set(n)!={"w1","b1","w2","b2"} or len(n["w1"])!=48 or
        any(len(row)!=85 for row in n["w1"]) or len(n["b1"])!=48 or
        len(n["w2"])!=4 or any(len(row)!=48 for row in n["w2"]) or len(n["b2"])!=4):
        raise ValueError("candidate model shape")
    values=[x for row in n["w1"] for x in row]+n["b1"]+[x for row in n["w2"] for x in row]+n["b2"]
    if not all(type(x) in (int,float) and math.isfinite(x) for x in values):
        raise ValueError("candidate finite parameter check")


def verify_v1(root):
    started=time.process_time();wall=time.perf_counter()
    root=root.resolve();out=root/"attempt001"
    if identity(root/"PROTOCOL_FROZEN.json")["sha256"]!=V1_SHA:
        raise ValueError("v1 frozen protocol identity")
    protocol=read(root/"PROTOCOL_FROZEN.json")
    for name,meta in protocol["files"].items():
        if identity(root/name)!=meta:raise ValueError("v1 frozen source changed: "+name)
    failure=read(out/"FAILED.json");receipt=read(root/"attempt001_supervisor.json")
    if (failure["stage"]!="DEV_selection_11" or failure["type"]!="TypeError" or
        failure["error"]!="'PosixPath' object is not subscriptable" or
        receipt["exit_code"]!=1 or receipt["protocol_sha256"]!=V1_SHA or
        receipt["child_CPU_seconds"]!=38.354773 or receipt["automatic_retry"]):
        raise ValueError("v1 failure/cost receipt differs")
    for name in ("RESULTS.json","ALL_SELECTIONS_FROZEN.json","CONF_ENTROPY.json","CONF_WORLDS_FROZEN.json"):
        if (out/name).exists():raise ValueError("v1 unexpected evaluation artifact: "+name)
    if list(out.glob("fit_*_SELECTION.json.gz")) or list(out.glob("confirmation_*.json.gz")) or list((out/"graphs").glob("*")):
        raise ValueError("v1 contains unexpected scored-world evidence")
    events=[];previous=None
    for index,path in enumerate(sorted((out/"events").glob("*.json"))):
        event=read(path)
        if event["sequence"]!=index or event["previous_sha256"]!=previous:
            raise ValueError("v1 event hash chain")
        previous=identity(path)["sha256"];events.append(event)
    kinds=[event["kind"] for event in events]
    if kinds!=["sources_history_verified"]+["fit_family_frozen"]*5+["all_families_frozen","DEV_entropy","DEV_worlds_frozen"]:
        raise ValueError("v1 must end before first DEV scoring")
    family_seal=read(out/"ALL_FAMILIES_FROZEN.json")
    if identity(out/"ALL_FAMILIES_FROZEN.json")["sha256"]!=events[6]["payload"]["sha256"]:
        raise ValueError("v1 family seal hash")
    inventory=[];models=0
    for fit in FITS:
        path=out/f"fit_{fit}_FAMILY.json.gz"
        if identity(path)["sha256"]!=family_seal[str(fit)]["sha256"]:
            raise ValueError("v1 per-fit family hash")
        record=read(path)
        if record["fit"]!=fit or set(record["models"])!={"C","D","R","P","RP"}:
            raise ValueError("v1 family identity")
        if [(r["index"],r["alpha"]) for r in record["family"]]!=list(enumerate((0.,.25,.5,1.))):
            raise ValueError("v1 family interpolation specification")
        base=read(checked_relative(out,record["models"]["C"]["path"]))
        for meta in [record["teacher"],*record["models"].values(),*(r["model"] for r in record["family"])]:
            source=checked_relative(out,meta["path"])
            actual=identity(source)
            if any(actual[key]!=meta[key] for key in ("bytes","sha256")):
                raise ValueError("v1 frozen candidate bytes changed")
            inventory.append(dict(path=meta["path"],**actual))
            if meta["path"].endswith(".json.gz"):
                model=read(source);finite_model(model);models+=1
                if {k:v for k,v in model.items() if k!="network"}!={k:v for k,v in base.items() if k!="network"}:
                    raise ValueError("non-network fields changed")
        original=Path(protocol["input_root_absolute"])/"neuron_margin_experiment"/f"inputs/fit_{fit}_C.json.gz"
        if record["source_C"]!=identity(original) or identity(out/f"restored/fit_{fit}_C.json.gz")!=identity(original):
            raise ValueError("original checkpoint or v1 restore identity")
        if record["family"][0]["model"]["sha256"]!=identity(original)["sha256"]:
            raise ValueError("alpha0 must be original compressed bytes")
    dev=read(out/"DEV_WORLDS_FROZEN.json")
    if dev["count"]!=40 or len(dev["keys"])!=40 or len(set(dev["keys"]))!=40:
        raise ValueError("v1 unused DEV inventory")
    if identity(out/"DEV_WORLDS_FROZEN.json")["sha256"]!=events[8]["payload"]["sha256"]:
        raise ValueError("v1 unused DEV seal")
    return dict(status="PASS_ZERO_FORWARD_REUSE_PREFLIGHT",v1_root_absolute=str(root),
        prior_protocol_sha256=V1_SHA,v1_failure=identity(out/"FAILED.json"),
        v1_supervisor=identity(root/"attempt001_supervisor.json"),
        v1_child_CPU_seconds=receipt["child_CPU_seconds"],
        v1_wall_seconds=receipt["enclosed_wall_seconds"],
        v1_family_seal=identity(out/"ALL_FAMILIES_FROZEN.json"),
        v1_unscored_DEV=identity(out/"DEV_WORLDS_FROZEN.json"),
        source_files=len(protocol["files"]),models_checked=models,candidate_files=inventory,
        observed_score_artifacts=0,last_v1_event=kinds[-1],
        exposure_scope="failure trace and local artifacts establish no v1 evaluation call; no external-custodian assertion",
        model_calls=0,optimizer_calls=0,TRAIN_recomputed=False,
        CPU_seconds=time.process_time()-started,wall_seconds=time.perf_counter()-wall)


if __name__=="__main__":
    root=Path(__file__).resolve().parent
    report=verify_v1(root.parent)
    path_findings=[]
    for source in root.glob("*.py"):
        tree=ast.parse(source.read_text(),filename=str(source))
        for node in ast.walk(tree):
            if (isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and
                node.value.id in ("out","ROOT","BASE","OLD","FT","path","root","source")):
                path_findings.append(dict(file=source.name,line=node.lineno,
                    expression=ast.get_source_segment(source.read_text(),node)))
    if path_findings:raise ValueError("remaining likely Path index: "+repr(path_findings))
    report.update(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  remaining_Path_subscripts=path_findings)
    with (root/"PREFLIGHT.json").open("x") as stream:json.dump(report,stream,indent=2);stream.write("\n")
    print(json.dumps({k:v for k,v in report.items() if k!="candidate_files"},indent=2))
