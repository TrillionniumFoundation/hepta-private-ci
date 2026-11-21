#!/usr/bin/env python3
"""Independent standard-library raw-record reader; no models, NumPy or training."""
import argparse
from fractions import Fraction
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import signal
import stat
import statistics
import struct
import sys
import time

FITS = (11, 23, 37, 53, 71)
ARMS = ("C", "S", "B", "Q", "SB", "SQ", "BQ", "SBQ", "J_own", "D", "R", "P", "RP", "K")
TOTAL_READ = 0


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def raw_file(path, expected=None):
    global TOTAL_READ
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_size <= 32*1024*1024, "regular bounded file required")
        raw = f.read(32*1024*1024+1)
    TOTAL_READ += len(raw)
    check(len(raw) <= 32*1024*1024 and TOTAL_READ <= 512*1024*1024, "reader byte budget")
    if expected is not None:
        check(sha(raw) == expected, "file hash mismatch: "+str(path))
    return raw


def pairs(rows):
    result = {}
    for key, value in rows:
        check(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(raw, compressed=False):
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(32*1024*1024+1)
    check(len(raw) <= 32*1024*1024, "expanded JSON byte budget")
    def bad(value):
        raise ValueError("nonfinite JSON: "+value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def read(path, expected=None):
    return decode(raw_file(path, expected), path.suffix == ".gz")


def close(a, b, message, tolerance=2e-11):
    check(math.isfinite(a) and math.isfinite(b) and abs(a-b) <= tolerance*(1+abs(b)), message)


def tensor_hash(values, code):
    return sha(struct.pack("<"+str(len(values))+code, *values))


def pack(model):
    n = model["network"]
    check(set(n) == {"w1", "b1", "w2", "b2"}, "network key set")
    check(len(n["w1"]) == 48 and all(len(row) == 85 for row in n["w1"]) and
          len(n["b1"]) == 48 and len(n["w2"]) == 4 and all(len(row) == 48 for row in n["w2"]) and
          len(n["b2"]) == 4, "model shapes")
    values = [x for row in n["w1"] for x in row]+n["b1"]+[x for row in n["w2"] for x in row]+n["b2"]
    check(all(type(x) in (int, float) and math.isfinite(x) for x in values), "model finite F64")
    return values


def model_check(path, meta, base, original, allowed, radius):
    raw = raw_file(path, meta["sha256"])
    check(len(raw) == meta["bytes"], "model byte extent")
    model = decode(raw, True)
    check({k:v for k,v in model.items() if k != "network"} ==
          {k:v for k,v in base.items() if k != "network"}, "protected non-network field changed")
    values = pack(model)
    changed = [i for i,(a,b) in enumerate(zip(values, original))
               if struct.pack("<d",a) != struct.pack("<d",b)]
    check(set(changed) <= allowed and len(changed) <= 368, "undeclared parameter coordinates")
    actual = sum((Fraction.from_float(float(values[i]))-Fraction.from_float(float(original[i])))**2
                 for i in changed)
    Q = [x for row in base["network"]["w2"][:3] for x in row]+base["network"]["b2"][:3]
    declared = sum(Fraction.from_float(float(x))**2 for x in Q)/4
    check(actual <= Fraction.from_float(float(radius))**2 <= declared, "independent exact full norm bound")
    return values


def graph_check(g, records, checks, state_cap, family=None):
    n = len(g["states"])
    check(0 < n <= state_cap and len(g["keys"]) == n and len(set(g["keys"])) == n, "state inventory")
    check(g["keys"] == [canonical(s).decode() for s in g["states"]], "state content identity")
    check(g["order"] == sorted(range(n), key=lambda i:g["states"][i]["tick"]), "DAG order")
    check(0 <= g["initial"] < n, "initial index")
    for key in ("masks", "terminal", "edges", "qstar", "optimal_values", "posterior", "omega", "C_occupancy", "C_belief", "K_belief"):
        check(len(g[key]) == n, "graph field extent: "+key)
    check(set(g["arm_actions"]) == set(ARMS) and set(records) == set(ARMS), "complete 14-arm inventory")
    check(sha(canonical(g["keys"])) == checks["common_support_sha256"], "common support hash")
    check(tensor_hash(g["omega"], "d") == checks["common_weights_sha256"], "common weights hash")
    order, masks, edges, terminal = g["order"], g["masks"], g["edges"], g["terminal"]
    for i in range(n):
        p = g["posterior"][i]
        check(math.isfinite(p) and 0 <= p <= 1 and len(masks[i]) == 6 and any(masks[i]) and
              len(terminal[i]) == 6 and len(edges[i]) == 3, "finite probability/mask/edge shape")
        close(terminal[i][4], 1-2*p, "negative terminal")
        close(terminal[i][5], 2*p-1, "positive terminal")
        check(terminal[i][:4] == [0,0,0,0], "terminal zero columns")
        for action, outgoing in enumerate(edges[i], 1):
            if not masks[i][action]:
                check(not outgoing, "illegal edge exists")
                continue
            close(math.fsum(r[0] for r in outgoing), 1., "outgoing probability mass")
            for probability, after, fee in outgoing:
                check(math.isfinite(probability) and probability >= 0 and math.isfinite(fee) and fee >= 0 and
                      type(after) is int and 0 <= after < n and
                      g["states"][after]["tick"] == g["states"][i]["tick"]+1, "finite causal edge")
                close(fee, g["states"][after]["charges"]-g["states"][i]["charges"], "edge charge")
    optimum = [0.]*n
    optimal_actions = [0]*n
    for i in reversed(order):
        q = terminal[i].copy()
        for action in (1,2,3):
            if masks[i][action]:
                q[action] = sum(probability*(optimum[after]-fee) for probability,after,fee in edges[i][action-1] if probability)
        for a,b in zip(q,g["qstar"][i]):
            close(a,b,"independent Bellman Q")
        best = max((a for a in range(6) if masks[i][a]),key=lambda a:(q[a],-a))
        optimal_actions[i], optimum[i] = best, q[best]
        close(optimum[i],g["optimal_values"][i],"independent Bellman V")

    def policy(actions, record):
        check(len(actions) == n and all(type(a) is int and 0 <= a < 6 and masks[i][a]
                                      for i,a in enumerate(actions)), "illegal recorded action")
        check(tensor_hash(actions,"q") == record["action_sha256"], "action payload hash")
        values=[0.]*n
        for i in reversed(order):
            a=actions[i]
            values[i] = terminal[i][a] if a in (0,4,5) else sum(
                probability*(values[after]-fee) for probability,after,fee in edges[i][a-1] if probability)
        close(values[g["initial"]],record["utility"],"raw-DAG utility differs")
        return values[g["initial"]]

    values={arm:policy(g["arm_actions"][arm],records[arm]) for arm in ARMS}
    check(g["arm_actions"]["BQ"] == g["arm_actions"]["SBQ"] == optimal_actions, "oracle optimal action identity")
    close(values["BQ"],optimum[g["initial"]],"BQ utility upper bound")
    check(all(v <= optimum[g["initial"]]+checks["oracle_tolerance"] for v in values.values()), "policy exceeds optimum")
    occupancy=[0.]*n;occupancy[g["initial"]]=1.
    for i in order:
        a=g["arm_actions"]["C"][i]
        if a not in (0,4,5):
            for probability,after,_ in edges[i][a-1]:
                if probability:occupancy[after]+=occupancy[i]*probability
    close(sum(occupancy[i] for i,a in enumerate(g["arm_actions"]["C"]) if a in (0,4,5)),1.,"terminal occupancy")
    total=sum(occupancy)
    for i,o in enumerate(occupancy):
        close(o,g["C_occupancy"][i],"C occupancy")
        close(.9*o/total+.1/n,g["omega"][i],"fixed candidate-independent calibration weight")
    close(sum(g["omega"]),1.,"calibration sum")
    def brier(belief, record):
        check(len(belief) == n and all(math.isfinite(p) and 0 <= p <= 1 for p in belief), "finite belief")
        check(tensor_hash(belief,"d") == record["belief_sha256"], "belief payload hash")
        error=math.fsum(w*(p-truth)**2 for w,p,truth in zip(g["omega"],belief,g["posterior"]))
        close(error,record["excess_Brier"],"single-Bernoulli excess Brier")
        return error
    calibrations={arm:brier(g[arm+"_belief"],records[arm]) for arm in ("C","K")}
    families=[]
    if family is not None:
        check(len(family) == len(g["family_actions"]) == len(g["family_beliefs"]) == 4, "DEV family count")
        for actions,belief,record in zip(g["family_actions"],g["family_beliefs"],family):
            families.append((policy(actions,record),brier(belief,record)))
        check(g["family_actions"][0] == g["arm_actions"]["C"] and g["family_beliefs"][0] == g["C_belief"], "alpha0 original state outputs")
    return values,calibrations,families,n


def interval5(values):
    check(len(values) == 5, "five independent fit units")
    # Independent closed-form df4 CDF, not SciPy's inverse-t implementation.
    target=1-.05/16;lo=0.;hi=32.
    for _ in range(80):
        middle=(lo+hi)/2;u=middle/math.sqrt(middle*middle+4)
        cdf=.5+.75*u-.25*u*u*u
        if cdf < target:lo=middle
        else:hi=middle
    mean=statistics.fmean(values);half=hi*statistics.stdev(values)/math.sqrt(5)
    return mean,[mean-half,mean+half]


def revision_check(protocol_path, protocol, out):
    """A new prospective revision, not a successful relabeling of failed v1."""
    r=protocol["revision"]
    check(r["kind"] == "technical_path_fix_reuse_frozen_candidates" and
          r["TRAIN_recomputed"] is False and r["excluded_v1_DEV_worlds"] == 40 and
          r["known_history"] == 3256,"explicit technical revision scope")
    old=Path(r["v1_root_absolute"])
    prior=read(old/"PROTOCOL_FROZEN.json",r["v1_protocol_sha256"])
    failed=read(old/"attempt001/FAILED.json",r["v1_failure_sha256"])
    costs=read(old/"attempt001_supervisor.json",r["v1_supervisor_sha256"])
    check(failed["type"] == "TypeError" and failed["stage"] == "DEV_selection_11" and
          "PosixPath" in failed["error"] and costs["exit_code"] == 1,"preserved v1 technical failure")
    check(costs["protocol_sha256"] == r["v1_protocol_sha256"],"v1 failure protocol binding")
    close(costs["child_CPU_seconds"],r["v1_child_CPU_seconds"],"v1 actual CPU accounting")
    limits=protocol["resources"]
    check(limits["CPU_soft_seconds"] == 250 and limits["CPU_hard_seconds"] == 261 and
          limits["wall_seconds"] == 560 and limits["total_scientific_CPU_hard_seconds"] == 300 and
          limits["total_scientific_wall_seconds"] == 600,"unchanged cumulative science budget")
    check(costs["child_CPU_seconds"]+261 <= 300 and costs["enclosed_wall_seconds"]+560 <= 600,
          "prior failed run must fit cumulative planned budget")
    current_costs=read(protocol_path.parent/"attempt001_supervisor.json")
    check(current_costs["exit_code"] == 0 and current_costs["protocol_sha256"] == sha(raw_file(protocol_path)) and
          current_costs["automatic_retry"] is False,"successful single v2 science child receipt")
    check(costs["child_CPU_seconds"]+current_costs["child_CPU_seconds"] <= 300 and
          costs["enclosed_wall_seconds"]+current_costs["enclosed_wall_seconds"] <= 600,
          "actual cumulative scientific CPU/wall budget exceeded")
    check(not list((old/"attempt001/graphs").glob("*")) and
          not list((old/"attempt001").glob("fit_*_SELECTION.json.gz")) and
          not list((old/"attempt001").glob("CONF*")) and not (old/"attempt001/RESULTS.json").exists(),
          "v1 had exposed evaluation outputs; unreviewed revision")
    pinned={str((protocol_path.parent/name).resolve()):meta for name,meta in protocol["files"].items()}
    for name,meta in prior["files"].items():
        check(pinned.get(str((old/name).resolve())) == meta,"v2 must bind every original v1 source/input")
    check(raw_file(protocol_path.parent/"causal_core.py") == raw_file(old/"causal_core.py"),"scientific core changed in technical revision")
    for key in ("fits","alphas","state_cap","posterior_clip","std_floor","svd_gap","input_ridge",
                "head_ridge","DEV_minimum_gain","calibration_margin","oracle_tolerance"):
        check(protocol[key] == prior[key],"scientific hyperparameter changed: "+key)
    prior_seal=read(old/"attempt001/ALL_FAMILIES_FROZEN.json",r["v1_family_seal_sha256"])
    for fit in FITS:
        rel=f"fit_{fit}_FAMILY.json.gz"
        raw=raw_file(old/"attempt001"/rel,prior_seal[str(fit)]["sha256"])
        check(raw_file(out/rel) == raw,"frozen v1 family record changed")
        doc=decode(raw,True)
        for meta in [*doc["models"].values(),*(x["model"] for x in doc["family"]),doc["teacher"]]:
            old_bytes=raw_file(old/"attempt001"/meta["path"],meta["sha256"])
            check(raw_file(out/meta["path"],meta["sha256"]) == old_bytes,"reused model/teacher bytes changed")
    return old, costs


def review(protocol_path, expected_protocol_sha, out):
    protocol=read(protocol_path,expected_protocol_sha)
    check(protocol["fits"] == list(FITS) and protocol["alphas"] == [0.,.25,.5,1.], "fixed fit/alpha registry")
    check(len(protocol["files"]) <= 1000, "source count budget")
    for relative,meta in protocol["files"].items():
        raw=raw_file(protocol_path.parent/relative,meta["sha256"])
        check(len(raw) == meta["bytes"], "source byte extent")
    v1_root,v1_costs=revision_check(protocol_path,protocol,out)
    original_root=Path(protocol["input_root_absolute"])/"neuron_margin_experiment"
    full_root=Path(protocol["input_root_absolute"])/"neuron_full_mlp_experiment"
    result=read(out/"RESULTS.json")
    check(result["status"] == "COMPLETED" and result["protocol_sha256"] == expected_protocol_sha,
          "scientific run did not complete under this protocol")
    check(result["independent_units"] == 5 and result["new_fit_count"] == result["gradient_updates"] == 0,
          "statistical/execution scope changed")
    family_seal=read(out/"ALL_FAMILIES_FROZEN.json",result["family_seal"])
    selection_seal=read(out/"ALL_SELECTIONS_FROZEN.json",result["selection_seal"])
    events=[];previous=None
    paths=sorted((out/"events").glob("*.json"))
    check(0 < len(paths) <= 128,"event chain count")
    for index,path in enumerate(paths):
        raw=raw_file(path);event=decode(raw)
        check(event["sequence"] == index and event["previous_sha256"] == previous,"event chain break")
        previous=sha(raw);events.append(event)
    kinds=[e["kind"] for e in events]
    for key in ("all_families_frozen","DEV_entropy","DEV_worlds_frozen","all_selections_frozen","CONF_entropy","CONF_worlds_frozen","completed"):
        check(kinds.count(key) == 1,"unique ordering event: "+key)
    for kind,filename in (("all_families_frozen","ALL_FAMILIES_FROZEN.json"),
                          ("all_selections_frozen","ALL_SELECTIONS_FROZEN.json"),
                          ("DEV_entropy","DEV_ENTROPY.json"),("CONF_entropy","CONF_ENTROPY.json"),
                          ("DEV_worlds_frozen","DEV_WORLDS_FROZEN.json"),
                          ("CONF_worlds_frozen","CONF_WORLDS_FROZEN.json")):
        check(events[kinds.index(kind)]["payload"]["sha256"] == sha(raw_file(out/filename)),
              "event identity must match actual seal/entropy: "+kind)
    check([kinds.index(k) for k in ("all_families_frozen","DEV_entropy","DEV_worlds_frozen","all_selections_frozen","CONF_entropy","CONF_worlds_frozen","completed")] ==
          sorted(kinds.index(k) for k in ("all_families_frozen","DEV_entropy","DEV_worlds_frozen","all_selections_frozen","CONF_entropy","CONF_worlds_frozen","completed")),
          "family/DEV/selection/CONF chronology")
    check(sum(e["kind"] == "fit_family_frozen" for e in events[:kinds.index("all_families_frozen")]) == 5 and
          sum(e["kind"] == "fit_selection_frozen" for e in events[kinds.index("DEV_worlds_frozen"):kinds.index("all_selections_frozen")]) == 5,
          "all fits must be sealed before next entropy")
    entropy={}
    for split,seal in (("DEV",result["family_seal"]),("CONF",result["selection_seal"])):
        doc=read(out/(split+"_ENTROPY.json"))
        check(doc["protocol_sha256"] == expected_protocol_sha and doc["preceding_seal_sha256"] == seal,
              "entropy preceding seal binding")
        entropy[split]=bytes.fromhex(doc["entropy_hex"])
        check(len(entropy[split]) == 32 and doc["external_custodian"] is False,"entropy scope")
    check(entropy["DEV"] != entropy["CONF"],"DEV/CONF entropy reused")
    registry=read(original_root/"inputs/history/HISTORY_REGISTRY.json.gz")
    schedule_fields=registry["canonical_schedule_fields"]
    schedule=lambda public:sha(canonical({k:public[k] for k in schedule_fields}))
    known=set()
    for entry in registry["entries"]:
        check(schedule(entry["world"]) == entry["schedule_sha256"],"legacy history content hash")
        known.add(entry["schedule_sha256"])
    for path in sorted((original_root/"inputs/history").glob("fit_*_*_WORLDS.json.gz")):
        known.update(schedule(world) for world in read(path))
    check(len(known) == 1936,"initial historical schedule count")
    for directory in (original_root/"inputs/history/followup", original_root/"inputs/history/anchored",
                      original_root/"attempt001/worlds",full_root/"attempt001/worlds"):
        for path in sorted(directory.glob("*.json.gz")):
            for public in read(path)["worlds"]:
                key=schedule(public);check(key not in known,"duplicate historical content");known.add(key)
    history=read(out/"HISTORY.json")
    check(len(known) == 3216,"pre-v1 historical schedule count")
    old_dev=set()
    for fit in FITS:
        doc=read(v1_root/f"attempt001/worlds/DEV_{fit}_iid.json.gz")
        check(len(doc["worlds"]) == 8,"v1 excluded DEV count")
        for public in doc["worlds"]:
            key=schedule(public);check(key not in known,"v1 DEV history collision")
            known.add(key);old_dev.add(key)
    old_dev_seal=read(v1_root/"attempt001/DEV_WORLDS_FROZEN.json")
    check(len(old_dev) == 40 and set(old_dev_seal["keys"]) == old_dev,"v1 excluded DEV content seal")
    check(len(known) == 3256 and set(history["keys"]) == known,"complete recorded exposure identity")
    world_docs={};split_keys={};all_seen=set(known)
    for split,domains,count in (("DEV",("iid",),8),("CONF",("iid","ood"),16)):
        new=set()
        for fit in FITS:
            for domain in domains:
                doc=read(out/f"worlds/{split}_{fit}_{domain}.json.gz")
                seed=int.from_bytes(hashlib.sha256(entropy[split]+canonical([split,fit,domain])).digest(),"big")
                check(doc["seed"] == str(seed) and len(doc["worlds"]) == count,"world generation seed/count")
                for public in doc["worlds"]:
                    key=schedule(public);check(key not in all_seen,"historical/DEV/CONF content overlap")
                    all_seen.add(key);new.add(key)
                world_docs[(split,fit,domain)]=doc["worlds"]
        frozen=read(out/(split+"_WORLDS_FROZEN.json"))
        check(set(frozen["keys"]) == new and frozen["count"] == len(new),"world seal content")
        split_keys[split]=new
    all_stats={};selections={};graphs=0;states=0;models=0
    for fit in FITS:
        family=read(out/f"fit_{fit}_FAMILY.json.gz",family_seal[str(fit)]["sha256"])
        selection=read(out/f"fit_{fit}_SELECTION.json.gz",selection_seal[str(fit)]["sha256"])
        base_path=original_root/f"inputs/fit_{fit}_C.json.gz"
        base_raw=raw_file(base_path);base=decode(base_raw,True);original=pack(base)
        check(family["source_C"] == {"bytes":len(base_raw),"sha256":sha(base_raw)},"source checkpoint identity")
        units=family["program"]["selected_units"]
        check(len(units) == len(set(units)) == 2 and all(type(x) is int and 0 <= x < 48 for x in units),"two hidden units")
        repr_allowed={85*u+j for u in units for j in range(85)} | {4080+u for u in units}
        head_allowed=set(range(4128,4324));radius=family["program"]["radius"]
        endpoint={}
        for arm in ("C","D","R","P","RP"):
            allowed=repr_allowed if arm == "R" else head_allowed if arm in ("D","P") else repr_allowed|head_allowed
            meta=family["models"][arm]
            endpoint[arm]=model_check(out/meta["path"],meta,base,original,allowed,radius);models+=1
        check(endpoint["C"] == original and sha(raw_file(out/family["models"]["C"]["path"])) == sha(base_raw),"C original bytes")
        check(all(struct.pack("<d",endpoint["R"][i]) == struct.pack("<d",endpoint["RP"][i]) for i in repr_allowed) and
              all(struct.pack("<d",endpoint["P"][i]) == struct.pack("<d",endpoint["RP"][i]) for i in head_allowed),
              "R/P must be exact component-removal ablations of RP")
        family_models=[]
        check(len(family["family"]) == 4,"four fixed family candidates")
        endpoint_touched=[i for i,(a,b) in enumerate(zip(original,endpoint["RP"])) if struct.pack("<d",a) != struct.pack("<d",b)]
        for index,item in enumerate(family["family"]):
            check(item["index"] == index and item["alpha"] == protocol["alphas"][index],"family alpha order")
            meta=item["model"]
            values=model_check(out/meta["path"],meta,base,original,repr_allowed|head_allowed,radius);models+=1
            wanted=original.copy()
            if item["alpha"] == 1:
                wanted=endpoint["RP"].copy()
            elif item["alpha"] != 0:
                for i in endpoint_touched:wanted[i]=original[i]+item["alpha"]*(endpoint["RP"][i]-original[i])
            check(tensor_hash(values,"d") == tensor_hash(wanted,"d"),"serialized family path including signed zero")
            family_models.append(meta)
        dev_family=[[] for _ in range(4)];dev_brier=[[] for _ in range(4)];C_values=[];C_brier=[]
        check(len(selection["records"]) == 8,"DEV record count")
        for index,(row,public) in enumerate(zip(selection["records"],world_docs[("DEV",fit,"iid")])):
            check(row["schedule_sha256"] == schedule(public) and row["public_id"] == public["id"],"DEV public identity")
            graph=read(out/row["graph"],row["graph_sha256"])
            vals,cal,fams,n=graph_check(graph,row["diagnostic_arms"],row["oracle_checks"],protocol["state_cap"],row["family"])
            C_values.append(vals["C"]);C_brier.append(cal["C"])
            for j,(value,br) in enumerate(fams):dev_family[j].append(value);dev_brier[j].append(br)
            graphs+=1;states+=n
        cv=statistics.fmean(C_values);cb=statistics.fmean(C_brier);eligible=[]
        for j,choice in enumerate(selection["choices"]):
            value=statistics.fmean(dev_family[j]);br=statistics.fmean(dev_brier[j])
            close(value,choice["utility"],"DEV choice utility");close(br,choice["excess_Brier"],"DEV choice calibration")
            allowed=j != 0 and family["program"]["valid"] and value-cv >= protocol["DEV_minimum_gain"] and br-cb <= protocol["calibration_margin"]
            check(bool(allowed) == choice["eligible"],"DEV eligibility")
            if allowed:eligible.append((value,-j,j))
        selected=max(eligible)[2] if eligible else 0
        check(selected == selection["selected_index"] and selection["selected_alpha"] == protocol["alphas"][selected],"DEV-only selected alpha")
        K=selection["K"]
        check(K == selection_seal[str(fit)]["K"] and K["sha256"] == family_models[selected]["sha256"],"K identity bound to selection")
        raw_file(out/K["path"],K["sha256"])
        if selected == 0:check(K["sha256"] == sha(base_raw),"rejected program must preserve original bytes")
        restored=raw_file(out/f"restored/fit_{fit}_C.json.gz")
        check(restored == base_raw and result["restoration"][str(fit)]["exact_original"] is True,"byte rollback")
        selections[str(fit)]={"alpha":protocol["alphas"][selected],"decision":selection["decision"]}
        for domain in ("iid","ood"):
            block=read(out/f"confirmation_{fit}_{domain}.json.gz")
            check(len(block["records"]) == block["worlds"] == 16,"CONF complete block")
            values={arm:[] for arm in ARMS};calibrations={arm:[] for arm in ("C","K")}
            for row,public in zip(block["records"],world_docs[("CONF",fit,domain)]):
                check(row["schedule_sha256"] == schedule(public) and row["public_id"] == public["id"],"CONF public identity")
                graph=read(out/row["graph"],row["graph_sha256"])
                vals,cal,_,n=graph_check(graph,row["arms"],row["oracle_checks"],protocol["state_cap"])
                for arm in ARMS:values[arm].append(vals[arm])
                for arm in ("C","K"):calibrations[arm].append(cal[arm])
                graphs+=1;states+=n
            means={arm:statistics.fmean(values[arm]) for arm in ARMS}
            brier={arm:statistics.fmean(calibrations[arm]) for arm in ("C","K")}
            for arm in ARMS:close(means[arm],block["means"][arm],"CONF arm mean")
            for arm in ("C","K"):close(brier[arm],block["Brier_means"][arm],"CONF calibration mean")
            all_stats[(fit,domain)]=(means,brier)
    primary={}
    for domain in ("iid","ood"):
        for label in ("K_minus_C","BQ_minus_C","joint_interaction","calibration_K_minus_C"):
            differences=[]
            for fit in FITS:
                m,b=all_stats[(fit,domain)]
                differences.append(m["K"]-m["C"] if label == "K_minus_C" else m["BQ"]-m["C"] if label == "BQ_minus_C" else
                                   m["RP"]-m["R"]-m["P"]+m["C"] if label == "joint_interaction" else b["K"]-b["C"])
            mean,ci=interval5(differences);key=label+"_"+domain;old=result["primary"][key]
            close(mean,old["delta"],"primary mean")
            for a,b in zip(ci,old["familywise95"]):close(a,b,"independent Bonferroni8 interval")
            passed=ci[1] < protocol["calibration_margin"] if label.startswith("calibration") else ci[0] > .005
            check(passed == old["passes"],"primary gate")
            primary[key]={"delta":mean,"per_fit":differences,"familywise95":ci,"passes":passed}
    qualified=all(primary[key+"_"+domain]["passes"] for key in ("K_minus_C","calibration_K_minus_C") for domain in ("iid","ood"))
    check(qualified == result["qualified"],"K four-gate qualification")
    check(graphs == 200 and len(split_keys["DEV"]) == 40 and len(split_keys["CONF"]) == 160,"complete experiment inventory")
    return {"schema":"hepta.causal-rescue-independent-record-review.v1","status":"PASS_RAW_DAG_AND_BYTE_REVIEW",
            "protocol_sha256":expected_protocol_sha,"source_files":len(protocol["files"]),"models_checked":models,
            "graphs_checked":graphs,"states_checked":states,"fit_units":5,"DEV_worlds":40,"CONF_worlds":160,
            "historical_exclusion":3256,"excluded_unscored_v1_DEV":40,
            "v1_failure_protocol_sha256":protocol["revision"]["v1_protocol_sha256"],
            "v1_failed_child_CPU_seconds":v1_costs["child_CPU_seconds"],
            "frozen_v1_candidate_and_teacher_bytes_reused":True,
            "selections":selections,"primary":primary,"quality_qualified":qualified,
            "production_eligible":False,"future_resource_bounds":None,"resource_utility_conversion":None,
            "decision":"KEEP_ORIGINAL_AND_STOP","model_calls":0,"optimizer_calls":0,"numpy_imports":0,
            "scope":"Recomputed stored DAG probabilities/actions, Bellman values, utility, common-support calibration, selection, intervals, model bytes and norm bounds. Did not regenerate CTMC/emission probabilities, model actions, TRAIN targets or external-label custody.",
            "source_reader_sha256":sha(Path(__file__).read_bytes())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--protocol-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();start=time.process_time();wall=time.monotonic()
    def timeout(*_):raise TimeoutError("independent reader fixed CPU/wall budget")
    signal.signal(signal.SIGXCPU,timeout);signal.signal(signal.SIGALRM,timeout)
    resource.setrlimit(resource.RLIMIT_CPU,(7,8));signal.alarm(30)
    try:
        check(sys.byteorder == "little","recorded F64/int64 byte-order profile")
        report=review(args.protocol.resolve(),args.protocol_sha256,args.output.resolve())
    except BaseException as exc:
        report={"schema":"hepta.causal-rescue-independent-record-review.v1","status":"FAILED",
                "type":type(exc).__name__,"reason":str(exc),"decision":"KEEP_ORIGINAL_AND_STOP",
                "production_eligible":False,"model_calls":0,"optimizer_calls":0}
    finally:signal.alarm(0)
    report.update(CPU_seconds=time.process_time()-start,wall_seconds=time.monotonic()-wall,
                  bytes_read=TOTAL_READ,peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report["status"] == "PASS_RAW_DAG_AND_BYTE_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
