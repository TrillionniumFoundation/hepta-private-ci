"""Freeze and deploy the prospectively registered eleven-arm primary study."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from ..field_bridge_20261027.run import digest, write_json, object_hash
from ..field_bridge_20261027.task import prepare_episode, finish_episode
from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors
from .learning import make_model
from .native_fast import NativeFastBridge
from .primary_common import P, source_freeze, setup_primary, load_checkpoint, qualified_H7
from .primary_media import MediaStore
from .primary_runtime import fit_runtime, select


def runtime(args):
    root = Path(args.out).resolve()
    trained = json.loads((root / "TRAINING_COMPLETE.json").read_text())
    sources = source_freeze()
    if trained["source_files"] != sources:
        raise ValueError("Training source changed before runtime fitting")
    corpus, observers, originals, _ = setup_primary(args)
    info = trained["seeds"][str(args.seed)]
    readouts = {}
    with NativeFastBridge(args.native, P["native_library_sha256"]) as bridge:
        for profile in ("frozen", "ordinary", "field"):
            model = make_model(originals[args.seed], args.seed, info["recipe"])
            if profile != "frozen":
                if digest(root / info["profiles"][profile]["checkpoint"]) != info["profiles"][profile]["checkpoint_sha256"]:
                    raise ValueError("Training checkpoint changed before runtime fitting")
                model, _, _ = load_checkpoint(root / "training" / str(args.seed) / f"{profile}.pt",
                                               originals[args.seed], args.seed, info["recipe"])
            readouts[profile] = fit_runtime(model, corpus, observers["reward"], bridge,
                                            args.seed, profile, root, protocol=P)
            print(f"runtime seed={args.seed} profile={profile} frozen", flush=True)
    if source_freeze() != sources:
        raise RuntimeError("Scientific source changed during runtime fitting")
    write_json(root / "runtime" / f"COMPLETE-{args.seed}.json", {
        "seed": args.seed, "readouts": readouts, "source_files": sources,
        "training_complete_sha256": digest(root / "TRAINING_COMPLETE.json"),
        "registered_commit": args.registered_commit,
        "test_retention_scored": False, "audit_observer_loaded": False})


def freeze(args):
    root = Path(args.out).resolve()
    if (root / "PRETEST_FREEZE.json").exists() or (root / "eval").exists():
        raise ValueError("Primary objects already frozen or evaluation started")
    sources = source_freeze()
    trained = json.loads((root / "TRAINING_COMPLETE.json").read_text())
    _, qualification = qualified_H7(args.parent_bank)
    if trained["source_files"] != sources:
        raise ValueError("Final training source differs")
    seeds = {}
    for seed in P["seeds"]:
        rt = json.loads((root / "runtime" / f"COMPLETE-{seed}.json").read_text())
        if rt["source_files"] != sources or rt["training_complete_sha256"] != digest(root / "TRAINING_COMPLETE.json"):
            raise ValueError("Incomplete or changed runtime fitting")
        for profile, checkpoint in trained["seeds"][str(seed)]["profiles"].items():
            if digest(root / checkpoint["checkpoint"]) != checkpoint["checkpoint_sha256"]:
                raise ValueError("Training checkpoint changed before the pretest freeze")
        for profile in ("frozen", "ordinary", "field"):
            fitted = json.loads((root / "runtime" / f"{seed}-{profile}" / "READOUTS.json").read_text())
            if fitted["models"] != rt["readouts"][profile]:
                raise ValueError("Runtime selected policy differs from its complete fitting record")
        seeds[str(seed)] = {**trained["seeds"][str(seed)], "readouts": rt["readouts"]}
    files = [root / "TRAINING_COMPLETE.json"]
    files += [p for name in ("training", "runtime") for p in (root / name).rglob("*") if p.is_file()]
    identities = {str(p.relative_to(root)): digest(p) for p in sorted(files)}
    if digest(args.native) != P["native_library_sha256"]:
        raise ValueError("Native library differs from original-kernel parity receipt")
    write_json(root / "PRETEST_FREEZE.json", {"schema": "hepta.field-bridge.v2.primary-pretest.1",
        "seeds": seeds, "files_sha256": identities, "source_files": sources,
        "qualified_H7_inputs": qualification, "registered_source_commit": args.registered_commit,
        "native_library_sha256": digest(args.native), "protocol_sha256": object_hash(P),
        "test_retention_scored": False, "audit_observer_used_for_selection": False})
    print("ALL PRIMARY MODELS AND CONTROLLERS FROZEN; commit before evaluation.", flush=True)


def deploy_batch(model, readout, control, fixed_action, bridge, observers, batch,
                 noise_seed, context, temporary, media, row_stream, native_stream):
    """Execute the selected continuation, preserve its real bytes, then score it."""
    size, start = len(batch.source_ids), context["batch_start"]
    names = [f"pair-{start+i:04d}" for i in range(size)]
    prepared = prepare_episode(model, batch.observation, observers["reward"],
        noise_seed=noise_seed, output_root=temporary, case_ids=names)
    prefix = f"{context['seed']}-{context['arm']}-{context['split']}-{context['corruption']}-{start}"
    native_path = temporary / "native.jsonl"
    before, cpu = time.perf_counter_ns(), time.process_time_ns()
    native_summary = {}
    if control == "fixed":
        actions = np.full(size, fixed_action, dtype=int)
    else:
        actions, native_summary = select(readout, prepared.features0, prepared.features1,
            bridge=bridge, case_prefix=prefix, reset=control == "reset",
            receipt_path=native_path if control in {"native", "reset"} else None)
    decision_wall, decision_cpu = time.perf_counter_ns()-before, time.process_time_ns()-cpu
    final = finish_episode(model, prepared, actions)
    scores = {name: observe_tensors(observer, final.pixels_u8.float()/255, final.captions,
                                    batch.target.pixels, batch.target.labels)
              for name, observer in observers.items()}
    native_storage_started = time.perf_counter_ns()
    if native_path.exists():
        for line in native_path.open():
            native_stream.write(json.dumps({"batch_id": prefix, **json.loads(line)}, sort_keys=True) + "\n")
        native_summary_path = native_path.with_name(native_path.name + ".summary.json")
        if native_summary_path.exists():
            native_summary["native_batch_receipt"] = json.loads(native_summary_path.read_text())
        native_stream.flush()
    native_storage_ns = time.perf_counter_ns()-native_storage_started
    media_started = time.perf_counter_ns()
    receipts, decisions = [], []
    for index, name in enumerate(names):
        receipts.append([media.ingest(h.receipts[index]) for h in (prepared.preview0, prepared.preview1, final)])
        decision_bytes = (temporary / name / "decision.json").read_bytes()
        decisions.append((json.loads(decision_bytes), decision_bytes))
    storage_ns = time.perf_counter_ns()-media_started
    resource = {"decision_wall_ns": decision_wall/size, "decision_python_cpu_ns": decision_cpu/size,
        "native_tick_calls": 2 if control in {"native", "reset"} else 0,
        "native_kernel_ns": native_summary.get("native_ns", 0)/size,
        "preserve_media_wall_ns": storage_ns/size, "native_evidence_compress_wall_ns": native_storage_ns/size}
    for phase, values in (("prepare", prepared.resources), ("finish", final.resources)):
        resource.update({f"{phase}_{key}": value/size for key, value in values.items() if isinstance(value, (int,float))})
    controller_sha = object_hash({"action":fixed_action} if readout is None else readout)
    for index in range(size):
        decision, raw = decisions[index]
        row = {**context, "pair": start+index, "batch_size":size, "noise_seed":noise_seed,
            "source_ids":batch.source_ids[index], "action":int(actions[index]),
            "refinement_count":1+int(actions[index]!=0),
            "reward":scores["reward"][index], "audit":scores["audit"][index],
            "resources":resource, "artifacts":receipts[index], "model_sha":prepared.model_sha256,
            "controller_sha":controller_sha, "public_features0":prepared.features0[index].tolist(),
            "public_features1":prepared.features1[index].tolist(),
            "private_labels_after_decision":batch.target.labels[index].tolist(),
            "decision":decision, "decision_bytes_utf8":raw.decode("utf-8"),
            "decision_sha256":hashlib.sha256(raw).hexdigest(),
            "native_receipt_case":f"{prefix}:{index:08d}" if control in {"native","reset"} else None,
            "native_batch_summary":native_summary if index==0 else None}
        row_stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n")
    row_stream.flush()
    shutil.rmtree(temporary)
    return size


def evaluate(args):
    root = Path(args.out).resolve()
    frozen = json.loads((root / "PRETEST_FREEZE.json").read_text())
    if source_freeze()!=frozen["source_files"] or object_hash(P)!=frozen["protocol_sha256"]:
        raise ValueError("Primary decision source differs from the pretest freeze")
    for relative, identity in frozen["files_sha256"].items():
        if digest(root / relative)!=identity:
            raise ValueError(f"Frozen primary input changed: {relative}")
    corpus, observers, originals, identities = setup_primary(args,audit=True)
    seed, info = args.seed, frozen["seeds"][str(args.seed)]
    models={"frozen":make_model(originals[seed],seed,info["recipe"])}
    for profile in ("ordinary","field","generic","richer"):
        models[profile],_,_=load_checkpoint(root/"training"/str(seed)/f"{profile}.pt",originals[seed],seed,info["recipe"])
    out=root/"eval"/str(seed)
    out.mkdir(parents=True,exist_ok=False)
    media=MediaStore(out/"media.zip")
    arms={**P["canonical_arms"],**P["supplementary_arms"]}
    order=list(arms); np.random.default_rng(seed+271027).shuffle(order)
    count,started=0,time.perf_counter_ns()
    with NativeFastBridge(args.native,frozen["native_library_sha256"]) as bridge, \
            gzip.open(out/"rows.jsonl.gz","xt",encoding="utf-8",compresslevel=6) as stream, \
            gzip.open(out/"native.jsonl.gz","xt",encoding="utf-8",compresslevel=6) as native_stream:
        for arm in order:
            profile,control=arms[arm]
            readout=None if control=="fixed" else info["readouts"][profile]["native" if control=="reset" else control]
            for split in ("test","retention"):
                for ci,condition in enumerate(P[f"{split}_conditions"]):
                    for start in range(0,P[f"{split}_pairs"],P["evaluation_batch_size"]):
                        size=min(P["evaluation_batch_size"],P[f"{split}_pairs"]-start)
                        batch_seed,noise_seed=271027+start+ci*10000,seed*100003+start+ci*1009
                        batch=make_batch(corpus,split,size,batch_seed,offset=P[f"{split}_offset"]+start,corruption=condition)
                        context=dict(seed=seed,arm=arm,split=split,corruption=condition,batch_start=start,batch_seed=batch_seed)
                        count+=deploy_batch(models[profile],readout,control,info["fixed_action"],bridge,
                            observers,batch,noise_seed,context,out/"temporary",media,stream,native_stream)
            print(f"primary seed={seed} arm={arm} complete; rows={count}",flush=True)
    media_info=media.close()
    expected=len(arms)*sum(P[f"{split}_pairs"]*len(P[f"{split}_conditions"]) for split in ("test","retention"))
    if count!=expected or source_freeze()!=frozen["source_files"]:
        raise RuntimeError("Primary execution grid incomplete or source changed")
    if any(parameter_hash(originals[s])!=identities[s]["parameter_sha256"] for s in P["seeds"]):
        raise RuntimeError("Original model changed during primary deployment")
    write_json(out/"COMPLETE.json",{"rows":count,"seed":seed,"media":media_info,
        "files_sha256":{name:digest(out/name) for name in ("rows.jsonl.gz","native.jsonl.gz","media.zip")},
        "pretest_freeze_sha256":digest(root/"PRETEST_FREEZE.json"),"registered_pretest_commit":args.registered_commit,
        "source_files":frozen["source_files"],"source_models_unchanged":True,"wall_ns":time.perf_counter_ns()-started})


def analyze(args):
    from .primary_analyze import analyze as compute
    root=Path(args.out).resolve()
    rows,completions=[],{}
    for seed in P["seeds"]:
        path=root/"eval"/str(seed)
        done=json.loads((path/"COMPLETE.json").read_text())
        for name,identity in done["files_sha256"].items():
            if digest(path/name)!=identity: raise ValueError("Primary evidence changed")
        with gzip.open(path/"rows.jsonl.gz","rt") as stream:
            for line in stream:
                row=json.loads(line)
                rows.append({k:row[k] for k in ("seed","arm","split","corruption","pair","source_ids","action",
                                                "refinement_count","reward","audit","resources")})
        completions[str(seed)]=done
    write_json(root/"RESULT.json",compute(rows))
    write_json(root/"EVALUATION_COMPLETE.json",{"rows":len(rows),"seeds":completions,
        "result_sha256":digest(root/"RESULT.json"),"source_files":source_freeze(),
        "pretest_freeze_sha256":digest(root/"PRETEST_FREEZE.json")})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("runtime","freeze","evaluate","analyze"))
    parser.add_argument("--assets",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--native",required=True)
    parser.add_argument("--parent-bank",required=True)
    parser.add_argument("--registered-commit",required=True)
    parser.add_argument("--seed",type=int,choices=P["seeds"])
    args=parser.parse_args()
    if args.phase in {"runtime","evaluate"} and args.seed is None:
        parser.error("Per-seed execution requires --seed")
    {"runtime":runtime,"freeze":freeze,"evaluate":evaluate,"analyze":analyze}[args.phase](args)


if __name__=="__main__":
    main()
