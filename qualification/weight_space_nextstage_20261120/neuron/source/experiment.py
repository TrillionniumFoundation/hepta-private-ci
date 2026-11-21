"""Explicit technical revision: evaluate v1 frozen families; never reconstruct or train."""
from pathlib import Path
from fractions import Fraction
import argparse,copy,datetime,gc,hashlib,json,os,resource,signal,sys,time,traceback
import numpy as np
from scipy.stats import t
import causal_core as c
from causal_core import BASE,OLD,FT,read,save,sha,canonical,identity,mlp,planning
from artifact_io import EventChain,verify_manifest
from original_experiment import load_history
from reuse_candidates import verify_v1

ROOT=Path(__file__).resolve().parent


def emit(**values):print(json.dumps(values),flush=True)


def copy_original(out,path,source):
    target=out/path;target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("xb") as f:f.write(source.read_bytes());f.flush();os.fsync(f.fileno())
    if identity(target)!=identity(source):raise ArithmeticError("byte copy changed original")
    return dict(path=path,**identity(target))


def restore(out,fits):
    result={}
    for fit in fits:
        path=f"restored/fit_{fit}_C.json.gz"
        source=OLD/f"inputs/fit_{fit}_C.json.gz"
        if not (out/path).exists():copy_original(out,path,source)
        result[str(fit)]=dict(**identity(out/path),exact_original=identity(out/path)==identity(source))
    return result


def prior_history(v1):
    known,schedule_hash,history=load_history(OLD)
    for folder in (OLD/"inputs/history/anchored",OLD/"attempt001/worlds",FT/"attempt001/worlds"):
        for path in sorted(folder.glob("*.json.gz")):
            for public in read(path)["worlds"]:
                key=schedule_hash(public)
                if key in known:raise ValueError("duplicate in frozen historical exclusion")
                known.add(key)
    if len(known)!=3216:raise ValueError("historical source set is not complete 3216")
    for path in sorted((v1/"attempt001/worlds").glob("DEV_*.json.gz")):
        for public in read(path)["worlds"]:
            key=schedule_hash(public)
            if key in known:raise ValueError("v1 unused DEV schedule duplicates history")
            known.add(key)
    if len(known)!=3256:raise ValueError("v2 history must include 40 unused v1 DEV schedules")
    return known,schedule_hash,history


def generate(full,out,split,fits,domains,count,known,schedule_hash,seal,events,protocol_sha):
    entropy=os.urandom(32)
    digest=save(out/f"{split}_ENTROPY.json",dict(entropy_hex=entropy.hex(),
        preceding_seal_sha256=seal,protocol_sha256=protocol_sha,external_custodian=False))
    events.add(f"{split}_entropy",dict(sha256=digest))
    collection={};used=set(known)
    for fit in fits:
        collection[fit]={}
        for domain in domains:
            seed=int.from_bytes(hashlib.sha256(entropy+canonical([split,fit,domain]).encode()).digest(),"big")
            rng=np.random.Generator(np.random.PCG64(seed))
            law=full.protocol["ood_domain" if domain=="ood" else "train_domain"]
            worlds=[]
            for index in range(count):
                public=dict(schema=full.ns["SCHEMA"],id=f"causal_v2_{split}_{domain}_{fit}_{index}",
                    deadline=6,initial_budget=3,target_tick=6,
                    duration=rng.choice(law["durations"],6).tolist(),drive=rng.choice(law["drives"],6).tolist(),
                    reliability=rng.choice(law["reliabilities"],6).tolist(),
                    read_price=rng.choice(law["prices"],6).tolist(),read_delay=rng.choice(law["delays"],6).tolist(),
                    prior_distance=float(rng.choice(full.protocol["prior_distances"])),
                    latency_price=law["latency_price"],repair_price=law["repair_price"],
                    failure_probability=law["failure_probability"],
                    packets=[f"not_opened_{j}.json" for j in range(6)],packet_sha256=["0"*64]*6)
                full.ns["validate_public"](public)
                key=schedule_hash(public)
                if key in used:raise ValueError("schedule collision; resampling forbidden")
                used.add(key);worlds.append(public)
            collection[fit][domain]=worlds
            save(out/f"worlds/{split}_{fit}_{domain}.json.gz",dict(seed=str(seed),worlds=worlds))
    seal=save(out/f"{split}_WORLDS_FROZEN.json",
              dict(count=len(used)-len(known),keys=sorted(used-known)))
    events.add(f"{split}_worlds_frozen",dict(sha256=seal,count=len(used)-len(known)))
    return collection,used


def graph_evidence(world,K_belief,arm_actions):
    g=world["graph"]
    return dict(states=g["states"],keys=g["keys"],order=g["order"],initial=g["initial"],
        masks=g["masks"],terminal=g["terminal"],edges=g["edges"],qstar=g["qstar"],
        optimal_values=g["optimal_values"],posterior=g["posterior"],
        C_occupancy=world["C_occupancy"],omega=world["omega"],
        C_belief=world["C_belief"],K_belief=K_belief,
        arm_actions=arm_actions,
        original_recursive_exact=world["original_recursive_exact"])


def main(args):
    start,wall=time.process_time(),time.perf_counter()
    protocol=read(args.protocol);protocol_sha=sha(args.protocol.read_bytes())
    if str(BASE)!=protocol["input_root_absolute"]:
        raise ValueError("HEPTA_WSP_INPUT_ROOT differs from frozen input identity")
    out=args.output.resolve()
    if str(out)!=protocol["output_absolute"]:raise ValueError("output differs from frozen identity")
    out.mkdir(exist_ok=False)
    def timeout(*unused):raise TimeoutError("fixed science CPU/wall budget reached")
    signal.signal(signal.SIGXCPU,timeout);signal.signal(signal.SIGALRM,timeout)
    resource.setrlimit(resource.RLIMIT_CPU,(250,261));signal.alarm(560)
    def budget():
        if time.process_time()>=250:timeout()
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024>protocol["RSS_bytes"]:
            raise MemoryError("fixed measured RSS cap exceeded")
    events=EventChain(out);stage="source_verification"
    save(out/"STARTED.json",dict(protocol_sha256=protocol_sha,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        python=sys.version,numpy=np.__version__,numeric_threads=1,external_preregistration=False))
    try:
        verify_manifest(ROOT,protocol["files"])
        prior=Path(protocol["revision"]["v1_root_absolute"])
        reuse=verify_v1(prior)
        if reuse["prior_protocol_sha256"]!=protocol["revision"]["v1_protocol_sha256"]:
            raise ValueError("prior protocol identity mismatch")
        save(out/"REUSE_VERIFIED.json",reuse)
        full=planning.load_context(OLD/"vendor/frozen_joint")
        known,schedule_hash,history=prior_history(prior)
        save(out/"HISTORY.json",dict(**history,complete_known=3256,keys=sorted(known)))
        events.add("sources_history_verified",dict(files=len(protocol["files"]),known=3256))
        fits={}
        for fit in protocol["fits"]:
            stage=f"reuse_frozen_family_{fit}"
            source=prior/"attempt001"
            record=read(source/f"fit_{fit}_FAMILY.json.gz")
            for meta in [record["teacher"],*record["models"].values(),
                         *(item["model"] for item in record["family"])]:
                actual=copy_original(out,meta["path"],source/meta["path"])
                if any(actual[key]!=meta[key] for key in ("bytes","sha256")):
                    raise ValueError("reused artifact differs from frozen family")
            family_meta=copy_original(out,f"fit_{fit}_FAMILY.json.gz",source/f"fit_{fit}_FAMILY.json.gz")
            digest=family_meta["sha256"]
            base=read(out/record["models"]["C"]["path"])
            if (base["schema"]!="joint-policy-v1" or base["family"]!="renewal" or
                base["head_dimensions"]!=[85,48,4] or base["parameter_count"]!=4332 or
                not np.array_equal(base["coordinates"],full.law.u)):
                raise ValueError("reused model/task/coordinate semantic identity failed")
            fits[fit]=dict(base=base,record=record,digest=digest)
            events.add("fit_family_frozen",dict(fit=fit,sha256=digest,reused_v1=True))
            emit(stage="fit_family_reused",fit=fit,valid=record["program"]["valid"],
                 units=record["program"]["selected_units"],CPU_seconds=time.process_time()-start)
        family_seal=save(out/"ALL_FAMILIES_FROZEN.json",
                         {str(f):dict(sha256=fits[f]["digest"]) for f in protocol["fits"]})
        events.add("all_families_frozen",dict(sha256=family_seal))
        stage="DEV_generation"
        dev,with_dev=generate(full,out,"DEV",protocol["fits"],["iid"],8,known,schedule_hash,
                             family_seal,events,protocol_sha)
        selections={}
        for fit in protocol["fits"]:
            stage=f"DEV_selection_{fit}";rows=[]
            state=fits[fit];base=state["base"];record=state["record"]
            artifacts={name:read(out/meta["path"]) for name,meta in record["models"].items()}
            artifacts["K"]=base
            family=[read(out/item["model"]["path"]) for item in record["family"]]
            for index,public in enumerate(dev[fit]["iid"]):
                budget();world=c.world_context(full,public,base,protocol,budget)
                diagnostics,checks,_=c.evaluate_all(full,world,artifacts,protocol,budget)
                arm_actions={name:row.pop("actions") for name,row in diagnostics.items()}
                candidates=[];probabilities=[];family_actions=[]
                for item,artifact in zip(record["family"],family):
                    measured,belief,_=c.evaluate_weight(world,artifact)
                    family_actions.append(measured.pop("actions"))
                    if item["index"]==0 and (measured["utility"]!=world["C_value"] or
                                              not np.array_equal(belief,world["C_belief"])):
                        raise ArithmeticError("alpha zero changes C execution")
                    candidates.append(dict(index=item["index"],alpha=item["alpha"],**measured))
                    probabilities.append(belief)
                evidence=graph_evidence(world,world["C_belief"],arm_actions)
                evidence["family_beliefs"]=np.array(probabilities)
                evidence["family_actions"]=np.array(family_actions)
                graph_path=f"graphs/DEV_{fit}_{index}.json.gz"
                graph_sha=save(out/graph_path,evidence)
                rows.append(dict(public_id=public["id"],schedule_sha256=schedule_hash(public),
                    graph=graph_path,graph_sha256=graph_sha,diagnostic_arms=diagnostics,
                    oracle_checks=checks,family=candidates))
                del world;gc.collect()
            C_mean=float(np.mean([row["diagnostic_arms"]["C"]["utility"] for row in rows]))
            C_brier=float(np.mean([row["diagnostic_arms"]["C"]["excess_Brier"] for row in rows]))
            choices=[]
            for index,alpha in enumerate(protocol["alphas"]):
                utility=float(np.mean([row["family"][index]["utility"] for row in rows]))
                brier=float(np.mean([row["family"][index]["excess_Brier"] for row in rows]))
                eligible=bool(index!=0 and record["program"]["valid"] and
                    utility-C_mean>=protocol["DEV_minimum_gain"] and
                    brier-C_brier<=protocol["calibration_margin"])
                choices.append(dict(index=index,alpha=alpha,utility=utility,excess_Brier=brier,
                                    delta_utility=utility-C_mean,delta_Brier=brier-C_brier,eligible=eligible))
            candidates=[item for item in choices if item["eligible"]]
            selected=max(candidates,key=lambda r:(r["utility"],-r["index"]))["index"] if candidates else 0
            source=out/record["family"][selected]["model"]["path"]
            K_meta=copy_original(out,f"models/fit_{fit}_K.json.gz",source)
            if selected==0 and identity(out/K_meta["path"])!=identity(OLD/f"inputs/fit_{fit}_C.json.gz"):
                raise ArithmeticError("no-update selection changed original bytes")
            selection=dict(fit=fit,selected_index=selected,selected_alpha=protocol["alphas"][selected],
                decision="WEIGHT_CANDIDATE" if selected else "KEEP_ORIGINAL_AND_STOP_EDIT",
                choices=choices,worlds=8,records=rows,K=K_meta)
            selected_sha=save(out/f"fit_{fit}_SELECTION.json.gz",selection)
            selections[fit]=selection
            events.add("fit_selection_frozen",dict(fit=fit,sha256=selected_sha))
            emit(stage="fit_selection_frozen",fit=fit,alpha=protocol["alphas"][selected],
                 decision=selection["decision"],CPU_seconds=time.process_time()-start)
        selection_seal=save(out/"ALL_SELECTIONS_FROZEN.json",
            {str(f):dict(sha256=identity(out/f"fit_{f}_SELECTION.json.gz")["sha256"],
                         K=selections[f]["K"]) for f in protocol["fits"]})
        events.add("all_selections_frozen",dict(sha256=selection_seal))
        stage="CONF_generation"
        confirmation,all_used=generate(full,out,"CONF",protocol["fits"],["iid","ood"],16,
            with_dev,schedule_hash,selection_seal,events,protocol_sha)
        results={}
        for fit in protocol["fits"]:
            results[fit]={};base=fits[fit]["base"]
            artifacts={name:read(out/meta["path"]) for name,meta in fits[fit]["record"]["models"].items()}
            artifacts["K"]=read(out/selections[fit]["K"]["path"])
            for domain,worlds in confirmation[fit].items():
                stage=f"CONF_{fit}_{domain}";rows=[]
                for index,public in enumerate(worlds):
                    budget();world=c.world_context(full,public,base,protocol,budget)
                    arms,checks,K_belief=c.evaluate_all(full,world,artifacts,protocol,budget)
                    arm_actions={name:row.pop("actions") for name,row in arms.items()}
                    graph_path=f"graphs/CONF_{fit}_{domain}_{index}.json.gz"
                    graph_sha=save(out/graph_path,graph_evidence(world,K_belief,arm_actions))
                    rows.append(dict(public_id=public["id"],schedule_sha256=schedule_hash(public),
                        arms=arms,oracle_checks=checks,graph=graph_path,graph_sha256=graph_sha))
                    del world;gc.collect()
                block=dict(worlds=len(rows),records=rows,
                    means={arm:float(np.mean([row["arms"][arm]["utility"] for row in rows])) for arm in c.ARMS},
                    Brier_means={arm:float(np.mean([row["arms"][arm]["excess_Brier"] for row in rows])) for arm in c.ARMS})
                results[fit][domain]=block;save(out/f"confirmation_{fit}_{domain}.json.gz",block)
                events.add("CONF_domain_scored",dict(fit=fit,domain=domain))
                emit(stage="CONF_domain_scored",fit=fit,domain=domain,CPU_seconds=time.process_time()-start)
        summary,primary={},{}
        for domain in ("iid","ood"):
            summary[domain]={}
            values={arm:np.array([results[f][domain]["means"][arm] for f in protocol["fits"]]) for arm in c.ARMS}
            for arm,array in values.items():summary[domain][arm]=dict(mean=float(array.mean()),per_fit=array.tolist())
            differences={
                "K_minus_C":values["K"]-values["C"],
                "BQ_minus_C":values["BQ"]-values["C"],
                "joint_interaction":values["RP"]-values["R"]-values["P"]+values["C"],
                "calibration_K_minus_C":np.array([results[f][domain]["Brier_means"]["K"]-
                    results[f][domain]["Brier_means"]["C"] for f in protocol["fits"]])}
            for name,difference in differences.items():
                half=t.ppf(1-.05/(2*8),4)*difference.std(ddof=1)/np.sqrt(5)
                interval=[float(difference.mean()-half),float(difference.mean()+half)]
                calibration=name.startswith("calibration")
                passed=interval[1]<protocol["calibration_margin"] if calibration else interval[0]>.005
                primary[name+"_"+domain]=dict(delta=float(difference.mean()),per_fit=difference.tolist(),
                                              familywise95=interval,passes=bool(passed))
        qualified=all(primary[key+"_"+domain]["passes"]
                      for key in ("K_minus_C","calibration_K_minus_C") for domain in ("iid","ood"))
        restored=restore(out,protocol["fits"]);verify_manifest(ROOT,protocol["files"])
        result=dict(status="COMPLETED",protocol_sha256=protocol_sha,
            family_seal=family_seal,selection_seal=selection_seal,summary=summary,primary=primary,
            qualified=qualified,independent_units=5,fits=protocol["fits"],new_fit_count=0,
            DEV_worlds=40,CONF_worlds=160,historical_exclusion=3256,
            decisions={str(f):dict(decision=selections[f]["decision"],alpha=selections[f]["selected_alpha"]) for f in protocol["fits"]},
            restoration=restored,CPU_seconds=time.process_time()-start,wall_seconds=time.perf_counter()-wall,
            peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            gradient_updates=0,actual_deployment=False,external_preregistration=False,
            weights_reconstructed=0,prior_science_CPU_seconds=protocol["revision"]["v1_child_CPU_seconds"],
            revision="explicit v2 technical correction; v1 failure retained, original families reused",
            scope="declared finite law causal rescues plus TRAIN-own-law teacher-fit weight program; no realized future outcomes",
            resource_exchange_rate="undefined; CPU never converted to task utility")
        save(out/"RESULTS.json",result);events.add("completed",dict(qualified=qualified))
        emit(stage="COMPLETED",qualified=qualified,CPU_seconds=time.process_time()-start)
    except BaseException as error:
        restored=restore(out,protocol["fits"])
        save(out/"FAILED.json",dict(stage=stage,type=type(error).__name__,error=str(error),
            traceback=traceback.format_exc(),CPU_seconds=time.process_time()-start,
            wall_seconds=time.perf_counter()-wall,partial_preserved=True,no_retry=True,restoration=restored))
        raise
    finally:signal.alarm(0)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);main(parser.parse_args())
