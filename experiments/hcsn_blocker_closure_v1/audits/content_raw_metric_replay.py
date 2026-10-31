"""Independent, bounded replay of saved content logits and registered labels.

No model, original evaluator, metric function or analysis module is imported.
Only a completed, externally bound publication can enter the formal audit.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
import traceback
import zipfile

import numpy as np
import scipy
from scipy.special import logsumexp, softmax


ROOT = Path(__file__).resolve().parents[3]
RUN_ID = 41156755829
SEAL = "c9063043d088b6b469e740b9b6f341f3faea3928"
PROTOCOL_SHA = "911067f668c94a68ca41af710e1977005806dad202fbf18f32bda580b077a27b"
METRICS_SOURCE = "experiments/hcsn_blocker_closure_v1/content/study.py"
METRICS_SHA = "1e7039a7d2cbf3e4be1f009c0aeab92b31c5098b606ee55f89d6f74105d7b3d0"
PREFIX = "content/results/hosted001/"
EDGES = np.arange(11, dtype=np.float64)/10.
TOLERANCE = 2e-12


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def emit(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def bounded(root, relative):
    part = Path(relative)
    path = root/part
    if part.is_absolute() or ".." in part.parts or path.is_symlink():
        raise ValueError("Invalid relative evidence path")
    path.resolve().relative_to(root.resolve())
    return path


def calibration(correct, confidence):
    bins = np.clip(np.searchsorted(EDGES, confidence, side="right")-1, 0, 9)
    observed = np.bincount(bins, weights=np.asarray(correct, np.float64), minlength=10)
    expected = np.bincount(bins, weights=confidence, minlength=10)
    return float(np.abs(observed-expected).sum()/len(confidence))


def independent_metrics(logits, labels):
    scores = np.asarray(logits, np.float64)
    labels = np.asarray(labels)
    if (scores.ndim != 2 or scores.shape[1] != 8 or labels.shape != (len(scores),)
            or len(scores) == 0 or labels.dtype.kind not in "iu"
            or not np.isfinite(scores).all() or np.any(labels < 0) or np.any(labels >= 8)):
        raise ValueError("Eight finite class logits and valid integer labels required")
    probability = softmax(scores, axis=1)
    centered = scores-np.max(scores, axis=1, keepdims=True)
    loss = logsumexp(centered, axis=1)-centered[np.arange(len(labels)), labels]
    correct = probability.argmax(axis=1) == labels
    brier = np.einsum("ij,ij->i", probability, probability)+1.-2.*probability[np.arange(len(labels)),labels]
    return dict(cross_entropy=float(loss.mean()), accuracy=float(correct.mean()),
        brier=float(brier.mean()), ece=calibration(correct, probability.max(axis=1)),
        correct=int(correct.sum()), positions=len(labels))


def arrays(path, specs, members):
    """Check NPY headers before NumPy allocates any decompressed array."""
    if path.stat().st_size > 8*1024**2:
        raise ValueError("NPZ exceeds the declared small evaluation-file bound")
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(members) or len(archive.namelist()) != len(members):
            raise ValueError("Unexpected or duplicate NPZ member")
        for name, (shape, dtype) in specs.items():
            info = archive.getinfo(name+".npy")
            if info.file_size > int(np.prod(shape))*np.dtype(dtype).itemsize+512:
                raise ValueError("NPY member exceeds its shape allocation bound")
            with archive.open(info) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1,0):
                    observed_shape, order, observed_dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2,0):
                    observed_shape, order, observed_dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError("Unsupported NPY version for frozen numerical outputs")
            if observed_shape != shape or order or observed_dtype != np.dtype(dtype):
                raise ValueError("NPY shape, order or dtype differs from the frozen contract")
    with np.load(path, allow_pickle=False) as archive:
        return {name: np.array(archive[name], copy=True) for name in specs}


def completed_run(path):
    value = read(path)
    if (value.get("id") != RUN_ID or value.get("head_sha") != SEAL
            or value.get("status") != "completed"
            or value.get("repository",{}).get("full_name") != "TrillionniumFoundation/hepta-private-ci"):
        raise PermissionError("Exact completed GitHub run receipt required before study-output access")
    return value


def member_map(index, expected_sha):
    if digest(index) != expected_sha:
        raise ValueError("Externally pinned archive index differs")
    value, rows = read(index), {}
    if value["schema"] != "hcsn-bounded-member-index.v1":
        raise ValueError("Unexpected publication index schema")
    for shard in value["member_shards"]:
        path = bounded(index.parent, shard["path"])
        if digest(path) != shard["sha256"] or path.stat().st_size != shard["bytes"]:
            raise ValueError("Published member shard changed")
        entries = read(path)
        if len(entries) != shard["members"]:
            raise ValueError("Member shard count differs")
        for row in entries:
            bounded(index.parent, row["path"])
            if row["path"] in rows:
                raise ValueError("Duplicate publication member")
            rows[row["path"]] = row
    if len(rows) != value["original_member_count"]:
        raise ValueError("Publication member count differs")
    return rows


def plan():
    return dict(run_id=RUN_ID, execution_seal=SEAL, study_protocol_sha256=PROTOCOL_SHA,
        metric_source=dict(path=METRICS_SOURCE, sha256=METRICS_SHA),
        ece=dict(bins=10, edges=EDGES.tolist(), intervals="Left closed, right open; final bin includes1.0"),
        floating_absolute_tolerance=TOLERANCE, integer_counts="Exact equality",
        accuracy_ties="Argmax of FP64 softmax probabilities, choosing the smallest class index on a numerical tie",
        prediction_shapes=dict(logits=[1024,8],labels=[1024]), prediction_dtypes=dict(logits="float32",labels="int64"),
        expected_workers=dict(development=76,fixed=304,equal_cpu=64),
        prediction_npz_maximum=1624, raw_array_bytes_per_prediction=40960,
        maximum_raw_prediction_array_bytes=1624*40960,
        prediction_patterns=[PREFIX+stage+"/*/validation_*.npz" for stage in ("development","fixed","equal_cpu")]
            +[PREFIX+stage+"/*/"+split+".npz" for stage in ("fixed","equal_cpu") for split in ("test","ood")],
        ground_truth_patterns=[PREFIX+"data/"+task+"_"+split+".npz" for task in ("selective_copy","mqar")
            for split in ("dev_val","val","test","ood")],
        allocation="One prediction NPZ at a time; only y from registered dataset NPZs; NPY headers checked before allocation",
        scope="Recompute raw prediction metrics and exact registered label order; no model forward, training, new significance test or changed scientific gate")


def selfcheck(output):
    checks=[]
    def check(name, condition):
        checks.append(dict(name=name,passed=bool(condition)))
    labels=np.arange(1024,dtype=np.int64)%8
    uniform=independent_metrics(np.zeros((1024,8)),labels)
    check("uniform eight-class closed form",np.isclose(uniform["cross_entropy"],np.log(8.),rtol=0,atol=1e-13)
        and uniform["accuracy"]==.125 and uniform["brier"]==.875 and uniform["ece"]==0.)
    perfect=np.full((1024,8),-1000.);perfect[np.arange(1024),labels]=0.
    check("perfect prediction closed form",independent_metrics(perfect,labels)==dict(
        cross_entropy=0.,accuracy=1.,brier=0.,ece=0.,correct=1024,positions=1024))
    wrong=independent_metrics(perfect,(labels+1)%8)
    check("confident error closed form",wrong==dict(cross_entropy=1000.,accuracy=0.,brier=2.,ece=1.,correct=0,positions=1024))
    check("large common logit offset remains stable",independent_metrics(np.full((1024,8),1e30),labels)==uniform)
    tiny=independent_metrics(np.tile(np.arange(8)*1e-30,(2,1)),np.zeros(2,dtype=np.int64))
    check("probability-space numerical ties preserve registered class order",tiny["correct"]==2 and tiny["accuracy"]==1. and tiny["ece"]==.875)
    probabilities=np.array([.6,.2,.1,.05,.025,.015,.005,.005])
    mixed=independent_metrics(np.tile(np.log(probabilities),(3,1)),np.array([0,1,0]))
    check("nonuniform analytic CE Brier and calibration",np.isclose(mixed["cross_entropy"],-(2*np.log(.6)+np.log(.2))/3,rtol=0,atol=1e-13)
        and np.isclose(mixed["brier"],sum(float(p*p) for p in probabilities)+1-2*(.6+.2+.6)/3,rtol=0,atol=1e-13)
        and np.isclose(mixed["ece"],2/3-.6,rtol=0,atol=1e-13))
    confidence=np.array([.2,np.nextafter(.2,0),.3,np.nextafter(.3,1),1.])
    check("left-edge inclusion and final confidence one",np.isclose(calibration([1,0,0,1,1],confidence),.28,rtol=0,atol=1e-13))
    with tempfile.TemporaryDirectory(prefix="hcsn-raw-metric-") as name:
        temp=Path(name);path=temp/"synthetic.npz"
        np.savez_compressed(path,logits=perfect.astype(np.float32),labels=labels)
        loaded=arrays(path,dict(logits=((1024,8),"float32"),labels=((1024,),"int64")),("logits.npy","labels.npy"))
        check("bounded NPZ roundtrip exact tensor identity",np.array_equal(loaded["labels"],labels)
            and np.array_equal(loaded["logits"],perfect.astype(np.float32)))
        np.savez_compressed(path,logits=perfect.astype(np.float32),labels=labels.astype(np.float32))
        try:
            arrays(path,dict(logits=((1024,8),"float32"),labels=((1024,),"int64")),("logits.npy","labels.npy"));rejected=False
        except ValueError:rejected=True
        check("invalid label dtype rejected before array load",rejected)
        emit(temp/"run.json",dict(id=RUN_ID,head_sha=SEAL,status="in_progress",repository=dict(full_name="TrillionniumFoundation/hepta-private-ci")))
        try:completed_run(temp/"run.json");rejected=False
        except PermissionError:rejected=True
        check("incomplete run blocks formal access",rejected)
    receipt=dict(schema="hcsn-independent-raw-metric-preflight.v1",created_utc=utc(),
        source_sha256=digest(Path(__file__)),passed=all(row["passed"] for row in checks),checks=checks,
        plan=plan(),formal_raw_arrays_loaded=False,original_metric_modules_imported=False,
        software=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__))
    emit(output,receipt)
    return receipt


def audit(args):
    start,cpu=time.perf_counter(),time.process_time()
    records,inputs,errors,labels_cache=[],{},[],{}
    jobs_seen,targets=0,0
    result=dict(schema="hcsn-independent-raw-metric-replay.v1",started_utc=utc(),plan=plan(),
        source_sha256=digest(Path(__file__)),formal_raw_arrays_loaded=False,
        software=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__))
    try:
        proof=read(args.preflight)
        if not proof["passed"] or proof["source_sha256"]!=result["source_sha256"] or proof["plan"]!=plan():
            raise ValueError("Source-identical synthetic preflight required")
        if datetime.datetime.fromisoformat(proof["created_utc"])>datetime.datetime.fromisoformat(result["started_utc"]):
            raise ValueError("Synthetic preflight must precede formal access")
        result["prepared_before_access"]=dict(file=str(args.preflight),sha256=digest(args.preflight),utc=proof["created_utc"])
        run=completed_run(args.run_receipt)
        result["completed_run"]=dict(file=str(args.run_receipt),sha256=digest(args.run_receipt),status=run["status"],head_sha=run["head_sha"])
        members=member_map(args.archive_index,args.archive_index_sha256)
        result["archive_index"]=dict(file=str(args.archive_index),sha256=args.archive_index_sha256)
        def verified(relative, expected=None):
            path=bounded(args.root,relative);row=members[PREFIX+str(relative)]
            identity=digest(path)
            if path.stat().st_size!=row["bytes"] or identity!=row["sha256"] or (expected is not None and identity!=expected):
                raise ValueError("Published input identity differs: "+str(relative))
            inputs[str(relative)]=dict(bytes=path.stat().st_size,sha256=identity)
            return path
        protocol=read(verified("PROTOCOL.json",PROTOCOL_SHA))
        if (protocol["public_execution_commit"]!=SEAL or protocol["source_sha256"][METRICS_SOURCE]!=METRICS_SHA
                or digest(ROOT/METRICS_SOURCE)!=METRICS_SHA):
            raise ValueError("Frozen ten-bin metric source or execution identity differs")
        lock=read(verified("SELECTION_LOCK.json"))
        if lock["protocol_sha256"]!=PROTOCOL_SHA:raise ValueError("Selection lock belongs to another protocol")
        design=protocol["design"]
        for task in design["tasks"]:
            for split in ("dev_val","val","test","ood"):
                data=protocol["data"][task][split]
                path=verified("data/"+data["file"],data["sha256"])
                result["formal_raw_arrays_loaded"]=True
                y=arrays(path,{"y":((data["episodes"],data["length"]),"int64")},("x.npy","dt.npy","y.npy"))["y"]
                valid=y[y>=0]
                if len(valid)!=1024 or np.any(valid>=8):raise ValueError("Registered supervised label population differs")
                labels_cache[task,split]=valid
        for stage in ("development","fixed","equal_cpu"):
            jobs=read(verified("jobs_"+stage+".json"))
            expected=[]
            for task in design["tasks"]:
                arms=lock["equal_cpu_arms"][task] if stage=="equal_cpu" else design["arms"]
                for arm in arms:
                    seeds=[design["development_seed"]] if stage=="development" else design["formal_seeds"]
                    lrs=design["learning_rates"] if stage=="development" else [lock["choices"][task][arm]["learning_rate"]]
                    expected.extend(dict(stage=stage,task=task,arm=arm,seed=seed,learning_rate=lr,
                        updates=design["development_updates"] if stage=="development" else design["formal_updates"],
                        id=f"{task}__{arm}__lr{lr:g}" if stage=="development" else f"{task}__{arm}__seed{seed}")
                        for seed in seeds for lr in lrs)
            if sorted(jobs,key=lambda row:row["id"])!=sorted(expected,key=lambda row:row["id"]) or len({j["id"] for j in jobs})!=len(jobs):
                raise ValueError("Job matrix differs from the exact registered design")
            for job in jobs:
                directory=stage+"/"+job["id"]
                try:
                    worker=read(verified(directory+"/RESULT.json"))
                    if (worker["status"]!="complete" or worker["job"]!=job or worker["protocol_sha256"]!=PROTOCOL_SHA
                            or worker["public_execution_commit"]!=SEAL):
                        raise ValueError("Worker result identity differs")
                    validation=worker["validations"]
                    if not 1<=len(validation)<=2 or (stage!="equal_cpu" and len(validation)!=2):
                        raise ValueError("Unexpected validation checkpoint count")
                    if set(worker["evaluation"])!=(set() if stage=="development" else {"test","ood"}):
                        raise ValueError("Unexpected heldout evaluation inventory")
                    planned=[("dev_val" if stage=="development" else "val",row) for row in validation]+list(worker["evaluation"].items())
                    if len({row["file"] for _,row in planned})!=len(planned):raise ValueError("Duplicate prediction file")
                    jobs_seen+=1
                    for split,item in planned:
                        targets+=1
                        entry=dict(job=directory,split=split,file=item["file"],passed=False)
                        try:
                            expected_file=(f"validation_{item['step']:06d}.npz" if split in ("val","dev_val") else split+".npz")
                            if item["file"]!=expected_file:raise ValueError("Unexpected prediction filename")
                            path=verified(directory+"/"+item["file"],item["sha256"])
                            values=arrays(path,dict(logits=((1024,8),"float32"),labels=((1024,),"int64")),("logits.npy","labels.npy"))
                            if not np.array_equal(values["labels"],labels_cache[job["task"],split]):
                                raise ValueError("Saved prediction labels differ from registered ground truth and order")
                            computed=independent_metrics(values["logits"],values["labels"])
                            if not all(np.isfinite(item[key]) for key in computed):
                                raise ValueError("Worker metric summary contains a nonfinite value")
                            differences={key:abs(computed[key]-item[key]) for key in ("cross_entropy","accuracy","brier","ece")}
                            entry.update(recomputed=computed,reported={key:item[key] for key in computed},absolute_errors=differences,
                                labels_equal_registered=True,passed=all(np.isfinite(v) and v<=TOLERANCE for v in differences.values())
                                and all(computed[key]==item[key] for key in ("positions","correct")))
                        except Exception as error:entry["error"]=repr(error)
                        records.append(entry)
                        if not entry["passed"]:errors.append(directory+"/"+item["file"])
                except Exception as error:
                    records.append(dict(job=directory,passed=False,error=repr(error)))
                    errors.append(directory)
        if jobs_seen!=444:errors.append("Expected444 complete unique worker results")
    except Exception:
        errors.append(traceback.format_exc())
    result.update(passed=not errors and jobs_seen==444 and targets>0,worker_count=jobs_seen,prediction_npz_count=targets,
        failed_record_count=len(errors),error_examples=errors[:20],
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-start,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        scope="Independent raw metrics and registered label identity only; no model output generation or scientific threshold change")
    for name,rows in (("records",records),("inputs",[dict(path=key,**row) for key,row in sorted(inputs.items())])):
        parts=[]
        for number,offset in enumerate(range(0,len(rows),100)):
            path=args.output.with_name(args.output.stem+f"_{name}_{number:03d}.json")
            emit(path,rows[offset:offset+100])
            if path.stat().st_size>480000:raise ValueError("Audit shard exceeds publication bound")
            parts.append(dict(file=path.name,rows=min(100,len(rows)-offset),bytes=path.stat().st_size,sha256=digest(path)))
        result[name+"_shards"]=parts
    emit(args.output,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("selfcheck","audit"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--root",type=Path)
    parser.add_argument("--run-receipt",type=Path)
    parser.add_argument("--archive-index",type=Path)
    parser.add_argument("--archive-index-sha256")
    parser.add_argument("--preflight",type=Path)
    args=parser.parse_args()
    value=selfcheck(args.output) if args.command=="selfcheck" else audit(args)
    print(json.dumps({key:value[key] for key in ("passed","worker_count","prediction_npz_count") if key in value}))
    if not value["passed"]:raise SystemExit(1)


if __name__=="__main__":
    main()
