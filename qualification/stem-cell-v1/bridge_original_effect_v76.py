"""Independent real V6 source-cluster effects: immutable evidence, no model fitting.

Consumes *historical* real trained Bridge output and original TRAIN-source labels.
Not a future validation, NDU efficacy test, CellSplit, new model forward or
independent issuer authentication. Three seeds share the same sixteen paragraphs.
No imports from the training/scoring pipeline or Torch are permitted here.
"""
from __future__ import annotations

from collections import defaultdict
import argparse
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import stat
import zipfile

V6_SHA256 = "197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
SEEDS = (41, 47, 53)
ARMS = ("warmup", "natural_only", "replay", "contrastive")
SOURCE_COUNT, CASE_COUNT, QUESTION_COUNT = 16, 827, 194
SCHEMA = "hepta.bridge.original-v6.source-cluster-effects.shadow.v1"
MAX_ARCHIVE = 64_000_000


def demand(ok, reason):
    if not ok:
        raise ValueError(reason)


def _sha(data):
    return sha256(data).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for k, value in pairs:
            demand(k not in result, "duplicate JSON member")
            result[k] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def _bytes(path, *, expected_sha=V6_SHA256):
    path = Path(path)
    demand(not path.is_symlink(), "symlink input forbidden")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as file:
        before = os.fstat(file.fileno())
        demand(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_ARCHIVE,
               "bounded regular immutable V6 source required")
        raw = file.read(MAX_ARCHIVE + 1)
        after = os.fstat(file.fileno())
        demand(len(raw) == before.st_size and
               (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
               (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
               "source changed between byte read and acceptance")
    demand(_sha(raw) == expected_sha, "unexpected original archive SHA256")
    return raw


def original_archive(path):
    """One exact held-byte snapshot; verify all 211 manifest-listed original files."""
    blob = _bytes(path)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        infos = archive.infolist()
        names = [v.filename for v in infos]
        demand(len(names) == len(set(names)) == 212 and
               sum(v.file_size for v in infos) <= 800_000_000, "complete bounded V6 ZIP inventory")
        for info in infos:
            p = PurePosixPath(info.filename)
            demand(not p.is_absolute() and ".." not in p.parts and not info.is_dir() and
                   info.file_size <= MAX_ARCHIVE and
                   ((info.external_attr >> 16) & 0o170000) != 0o120000,
                   "unregistered unsafe archive member")
        manifest = _json(archive.read("MANIFEST.json"))
        entries = manifest["entries"]
        demand(len(entries) == 211 and {e["path"] for e in entries} ==
               set(names) - {"MANIFEST.json"}, "full original manifest mismatch")
        for entry in entries:
            data = archive.read(entry["path"])
            demand(len(data) == entry["size_bytes"] and _sha(data) == entry["sha256"],
                   "original member size or digest mismatch")
        return {name: archive.read(name) for name in names if name.endswith(".json") and
                (name.startswith("reader-v6-bridge/seed-") or
                 name in ("reader-v5-independent-audit/natural-cases.json",
                          "reader-v6-bridge/all-cases.json",
                          "reader-v6-bridge/continuation-completion.json",
                          "reader-v6-baselines/natural-internal-baselines.json"))},len(entries)


def cid(r):
    return json.dumps([r[k] for k in ("source_split","paragraph_id","question_id","answer_id")],
                      separators=(",", ":"),ensure_ascii=False)


def validate_natural(rows):
    demand(type(rows) is list and len(rows)==CASE_COUNT, "original 827 tune candidates required")
    ids=[cid(r) for r in rows]
    demand(len(set(ids))==CASE_COUNT, "duplicate original candidate identifiers")
    sources=defaultdict(set)
    questions=defaultdict(list)
    for i,r in enumerate(rows):
        demand(r["source_split"]=="train" and type(r["label"]) is int and r["label"] in (0,1)
               and type(r["source_hash"]) is str and len(r["source_hash"])==64,
               "only authentic original natural TRAIN-source labels")
        sources[r["source_hash"]].add(r["paragraph_id"])
        questions[(r["source_split"],r["paragraph_id"],r["question_id"])].append(i)
    demand(len(sources)==SOURCE_COUNT and all(len(v)==1 for v in sources.values()) and
           len(questions)==QUESTION_COUNT, "sixteen independent paragraph/source groups required")
    return dict(ids=ids, groups=tuple(sorted(sources)), group_to_indices={
        g:tuple(i for i,r in enumerate(rows) if r["source_hash"]==g) for g in sorted(sources)},
        questions=questions)


def _f1(rows, cls):
    tp=sum(y==p==cls for y,p in rows)
    d=sum(y==cls for y,_ in rows)+sum(p==cls for _,p in rows)
    return 2*tp/d if d else 0.


def score(rows, probabilities, *, expected_ids=None):
    demand(type(probabilities) is list and len(probabilities)==len(rows) and len(rows)>0,
           "complete unchanged source prediction length required")
    demand(all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1
               for p in probabilities), "finite genuine saved prediction probabilities required")
    if expected_ids is not None:
        demand([cid(r) for r in rows]==expected_ids,"prediction source/candidate ordering changed")
    grouped=defaultdict(list)
    pairs=[]
    correct=0
    for r,p in zip(rows,probabilities):
        pred=int(p>.5)
        y=r["label"]
        correct+=int(pred==y)
        grouped[(r["source_split"],r["paragraph_id"],r["question_id"])].append((y,pred))
        pairs.append((y,pred))
    macros=[]
    for q in grouped.values():
        unique={v for a,b in q for v in (a,b)}
        macros.append(sum(_f1(q,v) for v in unique)/len(unique))
    return dict(candidates=len(rows),questions=len(grouped),
                paragraphs=len({(r["source_split"],r["paragraph_id"]) for r in rows}),
                accuracy=correct/len(rows),f1_a=_f1(pairs,1),
                exact_match=sum(all(y==p for y,p in q) for q in grouped.values())/len(grouped),
                f1_m=sum(macros)/len(macros))


def validate_panel(panel, rows, ids, model):
    demand(type(panel) is dict and panel["case_ids"]==ids and
           panel["model_execution_parameter_sha256"]==model["execution_parameter_sha256"] and
           panel["scope"]=="old_training_source_internal_tune_not_fresh" and
           panel["threshold_selected"] is False and model["parameter_count"]==42562,
           "authentic source/weight/label-scope panel required")
    computed=score(rows,panel["probabilities"],expected_ids=ids)
    for field in ("accuracy","f1_a","f1_m","exact_match"):
        demand(abs(computed[field]-panel["metrics"][field])<1e-11,
               "source-independent original metric replay differs")
    demand(all(computed[k]==panel["metrics"][k] for k in ("candidates","questions","paragraphs")),
           "real full question/paragraph census differs")
    return computed


def original_old_binding(rows, panel, baseline, gate=None):
    """Recheck old 128-candidate 64-pair TRAIN retention from original probabilities."""
    demand(len(rows)==128 and panel["case_ids"]==[cid(r) for r in rows],
           "complete original old paired-world cases")
    ps=panel["probabilities"]
    demand(type(ps) is list and len(ps)==128 and
           all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1 for p in ps),
           "finite original binding probabilities")
    pairs=defaultdict(dict)
    correct=0
    for row,p in zip(rows,ps):
        root,sep,world=row["paragraph_id"].rpartition("/world-")
        demand(sep and world in ("0","1") and row["answer_id"] in ("0","1"),
               "four-row paired-world provenance required")
        key=(root,row["answer_id"])
        demand(world not in pairs[key], "duplicate old binding case")
        prediction=int(p>.5)
        correct+=int(prediction==row["label"])
        pairs[key][world]=(prediction,row["label"])
    demand(len(pairs)==64 and all(set(v)=={"0","1"} for v in pairs.values()),
           "64 complete old world-pairs required")
    both=sum(all(pred==actual for pred,actual in values.values()) for values in pairs.values())
    acc, paired = correct/128,both/64
    demand(abs(acc-panel["metrics"]["accuracy"])<1e-12 and
           abs(paired-panel["metrics"]["both_worlds_correct"])<1e-12,
           "independent old training correctness differs from original output")
    demand(baseline["accuracy"]==baseline["both_worlds_correct"]==1,
           "original frozen complete fit baseline required")
    accepted=acc>=.95-1e-12 and paired>=.95-1e-12 and 1-acc<=.05+1e-12 and 1-paired<=.05+1e-12
    if gate is not None:
        demand(gate["passed"] is accepted and gate["fresh_selection"] is False,
               "original retention gate report differs from saved probabilities")
    return dict(candidate_correct=correct,paired_world_correct=both,
                candidate_accuracy=acc,paired_world_accuracy=paired,
                retention_train_only=accepted)


def _parts_by_source(rows, ps, geometry):
    grouped={}
    for group, idxs in geometry["group_to_indices"].items():
        pairs=[(rows[i]["label"],int(ps[i]>.5)) for i in idxs]
        grouped[group]=(sum(y==p==1 for y,p in pairs),
                        sum(y for y,p in pairs),sum(p for y,p in pairs))
    return grouped


def _f1_counts(counts):
    tp,gold,pos=counts
    denom=gold+pos
    return 2*tp/denom if denom else 0.


def paired_source_bootstrap(rows, geometry, probability_by_arm, *, repeats=2048, seed=20261015):
    """Resample 16 original source clusters, reusing *the same* draw across seeds.

    Repeated seeds are correlated observations of the same original 16 texts.
    These descriptive cluster intervals are not a future performance guarantee.
    """
    demand(type(repeats) is int and 100<=repeats<=10000 and type(seed) is int,
           "registered deterministic bounded resampling requested")
    expected={(s,a) for s in SEEDS for a in ARMS}
    demand(set(probability_by_arm)==expected,"complete 12 seed/arm original panel required")
    groups=geometry["groups"]
    base={g:(sum(rows[i]["label"] for i in geometry["group_to_indices"][g]),
              len(geometry["group_to_indices"][g])) for g in groups}
    counts={key:_parts_by_source(rows, ps, geometry) for key,ps in probability_by_arm.items()}
    point_baseline=_f1_counts((sum(v[0] for v in base.values()),
                               sum(v[0] for v in base.values()),sum(v[1] for v in base.values())))
    arm_keys=("warmup","natural_only","replay","contrastive")
    arms={a:sum(_f1_counts(tuple(sum(counts[(s,a)][g][j] for g in groups) for j in range(3)))
                for s in SEEDS)/3 for a in arm_keys}
    def contrasts(f1,baseline):
        return {
            "warmup_vs_all_positive":f1["warmup"]-baseline,
            "natural_only_vs_all_positive":f1["natural_only"]-baseline,
            "replay_vs_all_positive":f1["replay"]-baseline,
            "contrastive_vs_all_positive":f1["contrastive"]-baseline,
            "contrastive_minus_replay":f1["contrastive"]-f1["replay"],
            "contrastive_minus_natural_only":f1["contrastive"]-f1["natural_only"],
            "contrastive_minus_warmup":f1["contrastive"]-f1["warmup"],
        }
    observed=contrasts(arms,point_baseline)
    rng=random.Random(seed)
    estimates={k:[] for k in observed}
    for _ in range(repeats):
        draw=[groups[rng.randrange(len(groups))] for _ in groups]
        gold=sum(base[g][0] for g in draw)
        size=sum(base[g][1] for g in draw)
        b=_f1_counts((gold,gold,size))
        values={}
        for arm in arm_keys:
            values[arm]=sum(_f1_counts(tuple(sum(counts[(s,arm)][g][j] for g in draw)
                                                  for j in range(3))) for s in SEEDS)/3
        for k,value in contrasts(values,b).items():
            estimates[k].append(value)
    # Predeclared nearest-rank, not i.i.d. row-based intervals.
    intervals={}
    for name,values in estimates.items():
        ordered=sorted(values)
        lo=ordered[int(.025*(repeats-1))]
        hi=ordered[int(.975*(repeats-1))]
        intervals[name]={"point":observed[name],"source_cluster_bootstrap_95_interval":[lo,hi]}
    return dict(seed_repeat_is_not_independent=True,original_source_groups=len(groups),
                resampled_source_groups_once_across_all_three_seeds=True,
                resamples=repeats,random_seed=seed,
                baseline_all_positive_f1a=point_baseline,
                mean_seed_f1a_by_arm=arms,paired_effects=intervals,
                intervals_exploratory_not_prospective=True)


def evaluate(archive_path, *, repeats=2048):
    content,verified=original_archive(archive_path)
    def get(name):
        demand(name in content, "missing original source-bound JSON: "+name)
        return _json(content[name])
    natural=get("reader-v5-independent-audit/natural-cases.json")["tune"]
    geometry=validate_natural(natural)
    binding=get("reader-v6-bridge/all-cases.json")["reader_train"]
    baseline=get("reader-v6-baselines/natural-internal-baselines.json")
    ids=geometry["ids"]
    all_pos=score(natural,[1.]*CASE_COUNT,expected_ids=ids)
    all_neg=score(natural,[0.]*CASE_COUNT,expected_ids=ids)
    for name,metric in (("all_positive",all_pos),("all_negative",all_neg)):
        demand(all(abs(metric[key]-baseline[name][key])<1e-11 for key in
                   ("f1_a","f1_m","accuracy","exact_match")), "original cheap control changed")
    probabilities={}
    measured={}
    retention_summary={}
    original_completion=get("reader-v6-bridge/continuation-completion.json")
    for seed in SEEDS:
        prefix=f"reader-v6-bridge/seed-{seed}/bridge/"
        old_baseline=get(prefix+"warmup-binding-train.json")["metrics"]
        gates=get(prefix+"retention-gates.json")
        for arm in ARMS:
            model=get(prefix+arm+"-model.json")
            panel=get(prefix+arm+"-natural-internal.json")
            stats=validate_panel(panel,natural,ids,model)
            probabilities[(seed,arm)]=panel["probabilities"]
            old_panel=get(prefix+arm+"-binding-train.json")
            own=original_old_binding(binding,old_panel,old_baseline,
                                     gates[arm] if arm!="warmup" else None)
            if arm!="warmup":
                demand(original_completion["gates"][str(seed)][arm]["passed"] == own["retention_train_only"],
                       "complete original V6 retention disposition inconsistent")
            receipt=get(prefix+arm+"-training.json")
            demand(model["parameter_count"]==receipt["parameter_count"]==42562,
                   "original trained Reader parameter count changed")
            demand(receipt["status"] in ("train_gate_passed","completed") and
                   receipt["completed_steps"]>=1 and receipt["final_evaluation_authorized"] is False,
                   "original training receipt not historical/closed")
            measured[f"{seed}/{arm}"]=dict(
                original_natural_internal=stats,
                old_binding_train=own,
                actual_historical_fit_cpu_ns=receipt["cpu_ns"],
                historical_updates=receipt["completed_steps"],
                natural_old_internal_tune_not_future=True,
                new_training_performed=False,model_tensor_execution_digest=model["execution_parameter_sha256"])
            retention_summary[f"{seed}/{arm}"]=own["retention_train_only"]
    bootstrap=paired_source_bootstrap(natural,geometry,probabilities,repeats=repeats)
    arm_pass={arm:all(retention_summary[f"{s}/{arm}"] for s in SEEDS) for arm in ARMS}
    return dict(schema=SCHEMA,archive_sha256=V6_SHA256,
        original_member_sha256_count=verified,real_historical_trained_reader_checkpoints=12,
        original_natural_train_tune_candidates=CASE_COUNT,
        original_tune_questions=QUESTION_COUNT,original_source_groups=SOURCE_COUNT,
        same_sources_repeated_over_three_seeds=True,never_future_independent_data=True,
        cheaply_recomputed_controls=dict(all_positive=all_pos,all_negative=all_neg),
        model_observations=measured,all_seed_old_train_retention_by_arm=arm_pass,
        source_cluster_effects=bootstrap,
        selection_authorized=False,model_promoted=False,
        independent_heldout_efficacy_proven=False,ndu_admitted=False,
        cell_split_authorized=False,production_authorized=False,
        original_data_retrained=False,pretrained_encoder_executed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original-v6",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--bootstrap-replicates",type=int,default=2048)
    args=p.parse_args()
    demand(not args.output.exists() and not args.output.is_symlink(),"write-once analysis output required")
    report=evaluate(args.original_v6,repeats=args.bootstrap_replicates)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as out:
        json.dump(report,out,sort_keys=True,indent=2,allow_nan=False)
        out.write("\n");out.flush();os.fsync(out.fileno())
    print(json.dumps({"status":"HISTORICAL_INTERNAL_SOURCE_EFFECTS_ONLY",
                      "original_source_groups":SOURCE_COUNT,
                      "old_train_retention":report["all_seed_old_train_retention_by_arm"],
                      "production_authorized":False},sort_keys=True))


if __name__=="__main__":
    main()
