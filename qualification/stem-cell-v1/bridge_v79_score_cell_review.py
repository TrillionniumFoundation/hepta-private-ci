"""Separate NumPy-only numerical replay of V7.9 real-human-label Cell Heads.

Does not load torch or train any model; replays original byte-bound data,
independently decodes the six 1700-parameter weight tensors and full 827
candidate 2-class logits for every fixed seed/arm. This is not issuer
attestation, prospective test evidence or complete-lifecycle compute parity.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import re
import stat
from io import BytesIO

import numpy as np
from bridge_v79_archived_scores import (SEEDS,SCHEMA,V6_SHA,V7_SHA,load_sources,original_logits,
    make_features,score,sha,canonical,require)

ARMS=("score_only_row","score_only_source","score_text_row","score_text_source")
KEYS={"input.weight":(16,97),"input.bias":(16,),"gate.weight":(1,97),"gate.bias":(1,),
      "output.weight":(2,16),"output.bias":(2,)}
DIMS=1700


def _checked_path(path, expected_sha, limit=3_000_000):
    path=Path(path)
    require(not path.is_symlink(), "candidate file symlinks forbidden")
    fd=os.open(path,os.O_RDONLY | getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        before=os.fstat(f.fileno())
        require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=limit,
                "bounded regular candidate file required")
        data=f.read(limit+1)
        after=os.fstat(f.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),
                "candidate replaced during read")
    require(len(data)==before.st_size and sha(data)==expected_sha,
            "candidate file byte digest mismatched")
    return data


def read_json(path, maximum=4_000_000):
    path=Path(path)
    require(not path.is_symlink() and path.stat().st_size <= maximum,"bounded receipt JSON")
    def uniq(pairs):
        out={}
        for k,v in pairs:
            require(k not in out,"duplicate JSON field forbidden")
            out[k]=v
        return out
    return json.loads(path.read_bytes(),object_pairs_hook=uniq,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def read_head(path, expected_sha):
    """Independent bounded state geometry/numeric/parameter-digest recomputation."""
    raw=_checked_path(path,expected_sha,limit=120_000)
    import zipfile
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        expected={name.replace(".","__")+".npy" for name in KEYS}
        names=archive.namelist()
        require(len(names)==6 and len(set(names))==6 and set(names)==expected and
                sum(info.file_size for info in archive.infolist()) <= 40_000,
                "registered six non-pickle Head tensors required")
        for key, expected_shape in KEYS.items():
            name=key.replace(".","__")+".npy"
            tensor_blob=archive.read(name)
            header_io=BytesIO(tensor_blob)
            version=np.lib.format.read_magic(header_io)
            require(version in ((1,0),(2,0)),"registered safe NPY version required")
            reader=(np.lib.format.read_array_header_1_0 if version==(1,0)
                    else np.lib.format.read_array_header_2_0)
            shape,fortran,dtype=reader(header_io,max_header_size=4096)
            require(tuple(shape)==expected_shape and not fortran and dtype==np.float32 and
                    len(tensor_blob)==header_io.tell()+4*math.prod(expected_shape),
                    "NPY declared Head tensor shape must be verified BEFORE allocation")
    with np.load(BytesIO(raw),allow_pickle=False,max_header_size=4096) as record:
        require(set(record.files)=={name.replace(".","__") for name in KEYS},
                "unexpected Head tensor mapping")
        weights={name:record[name.replace(".","__")].copy() for name in KEYS}
    dig=sha256(); total=0
    for name in sorted(weights):
        w=weights[name]
        require(type(w) is np.ndarray and tuple(w.shape)==KEYS[name] and
                w.dtype==np.float32 and w.flags.c_contiguous and bool(np.isfinite(w).all()),
                "complete frozen FP32 Head numerical tensor required")
        dig.update(name.encode()+str(tuple(w.shape)).encode()+w.tobytes())
        total+=w.size
    require(total==DIMS,"exact V7.7 lightweight 1700-scalar Head required")
    return weights,dig.hexdigest()


def gelu(x):
    cdf=np.vectorize(math.erf,otypes=[np.float32])((x/np.float32(math.sqrt(2))).astype(np.float32))
    return np.float32(.5)*x*(np.float32(1)+cdf)


def numpy_forward(w,x,old):
    require(x.ndim==2 and x.shape[1]==97 and old.shape==(len(x),2),
            "97D lexical feature contract and 2-class pretrained logits required")
    hidden=gelu(x@w["input.weight"].T+w["input.bias"])
    raw=x@w["gate.weight"].T+w["gate.bias"]
    gate=np.float32(1)/(np.float32(1)+np.exp(-np.clip(raw,-30,30)))
    update=hidden@w["output.weight"].T+w["output.bias"]
    out=old+gate*update
    require(bool(np.isfinite(out).all()),"finite bounded independent candidate model output")
    return out.astype(np.float32)


def _same_score(left,right):
    require(type(left) is dict and set(left)==set(right),"candidate summary geometry mismatch")
    for k in right:
        a,b=left[k],right[k]
        if type(a) in (float,int) and type(b) in (float,int):
            require(abs(a-b)<=1e-10,"model outcome differs from independent original-label rescore: "+k)
        else:require(a==b,"model scope differs: "+k)


def bootstrap(rows,predictions,originals,*,draws=2048):
    """One common bootstrap draw across three repeated seeds; 16 SOURCE units."""
    original_groups=sorted({r["source_hash"] for r in rows})
    require(len(original_groups)==16 and set(predictions)==set(SEEDS)==set(originals),
            "exact repeated source-cluster cohort required")
    groups=defaultdict(list)
    for ix,r in enumerate(rows):groups[r["source_hash"]].append(ix)
    rng=random.Random("hepta-v79-source-bootstrap-20261015-2048")
    effects={k:[] for k in ("text_source_vs_frozen","text_source_vs_row","text_source_vs_always_positive")}
    for _ in range(draws):
        sample=[rng.choice(original_groups) for j in range(16)]
        indices=[ix for g in sample for ix in groups[g]]
        ys=[rows[ix]["label"] for ix in indices]
        def f1(p):
            tp=sum(a==b==1 for a,b in zip(ys,p))
            pos=sum(ys)+sum(p)
            return 2*tp/pos if pos else 0.
        diffs={k:[] for k in effects}
        for seed in SEEDS:
            d=predictions[seed]
            full=f1([d["score_text_source"][ix] for ix in indices])
            diffs["text_source_vs_frozen"].append(full-f1([originals[seed][ix] for ix in indices]))
            diffs["text_source_vs_row"].append(full-f1([d["score_text_row"][ix] for ix in indices]))
            diffs["text_source_vs_always_positive"].append(full-f1([1]*len(indices)))
        for key in effects:effects[key].append(sum(diffs[key])/len(SEEDS))
    results={}
    for name,deltas in effects.items():
        vals=sorted(deltas)
        results[name]=dict(bootstrap_mean_delta=sum(deltas)/draws,
            exploratory_95_percent_source_cluster_interval=[vals[int(.025*draws)],vals[int(.975*draws)]],
            draws=draws,source_groups=16,repeated_seeds_are_not_new_samples=True,
            first_seen_on_historical_development_tune=True)
    return results


def review(v6,v7,output):
    data=load_sources(v6,v7)
    root=Path(output)
    beginning=read_json(root/"start.json")
    full=read_json(root/"completed.json",maximum=500_000)
    require(beginning["schema"]==full["schema"]==SCHEMA and
            beginning["source_identity_sha256"]==full["source_identity_sha256"]==data["source_sha256"] and
            beginning["v6_sha256"]==V6_SHA and beginning["v7_sha256"]==V7_SHA and
            full["archive_sha256"]=={"v6":V6_SHA,"v7":V7_SHA},
            "full authentic original source/document integrity required")
    require(full["status"]=="COMPLETE_EXPOSED_INTERNAL_RESEARCH_ONLY" and
            full["seeds"]==list(SEEDS) and full["arms"]==list(ARMS) and
            full["total_new_head_updates"]==5040 and
            full["physical_new_encoder_forward_calls"]==0 and
            full["original_reader_weight_byte_changes"]==0 and
            full["production_authorized"] is False and full["cell_split_authorized"] is False and
            full["native_ndu_admitted"] is False and full["future_independent_task_accuracy_established"] is False,
            "completed research-only nine-plus-three candidate policy required")
    census=0; all_source_ids=set(); all_models={}; prediction={}; original={}; max_diff=0.; max_flips=0
    for seed in SEEDS:
        row=full["results"][str(seed)]
        ref=data["reports"][seed]
        require(row["parent_execution_parameter_sha256"]==ref["model_sha256"] and
                row["original_train_panel_sha256"]==ref["train_panel_sha256"] and
                row["original_tune_panel_sha256"]==ref["tune_panel_sha256"] and
                set(row["arms"])==set(ARMS),
                "historical frozen original model identity missing")
        source_pred=[int(p>.5) for p in ref["tune_p"]]
        original[seed]=source_pred
        _same_score(row["frozen_baseline"],score(data["tune"],source_pred))
        _same_score(row["always_positive"],score(data["tune"],[1]*827))
        ctrl=row["two_scalar_control"]
        require(ctrl["trainable_parameters"]==2 and ctrl["update_count"]==420 and
                ctrl["batch_size"]==16,"registered cheap scalar learning comparison required")
        z=original_logits(ref["tune_p"])[:,1].astype(np.float64)
        scalar=[int(math.exp(ctrl["log_scale"])*float(v)+ctrl["bias"]>0) for v in z]
        _same_score(ctrl["tune_metrics"],score(data["tune"],scalar))
        require(ctrl["tune_prediction_sha256"]==sha(canonical(scalar)),
                "trained scalar control predictions cannot be counterfeited")
        pred={}; per={}
        for arm in ARMS:
            candidate=row["arms"][arm]
            folder=root/f"seed-{seed}"/arm
            receipt=read_json(folder/"candidate.json")
            require(candidate==receipt and receipt["schema"]==SCHEMA and
                    receipt["seed"]==seed and receipt["arm"]==arm and
                    receipt["updates"]==420 and receipt["batch_size"]==16 and
                    receipt["total_optimizer_exposures"]==6720 and
                    receipt["trainable_parameters"]==1700 and
                    receipt["trainable_weight_bytes"]==6800 and
                    receipt["production_authorized"] is False and
                    receipt["cell_split_authorized"] is False and
                    receipt["native_ndu_admitted"] is False and
                    receipt["original_granite_hidden_states_used"] is False and
                    receipt["original_granite_encoder_calls_this_run"]==0 and
                    receipt["tune_source_labels_used_in_training"] is False and
                    receipt["frozen_old_model_weight_updated"] is False,
                    "missing original data/schedule/no-authority evidence")
            expected_mode="score_text" if arm.startswith("score_text") else "score_only"
            expected_sampler="source" if arm.endswith("source") else "row"
            require(receipt["mode"]==expected_mode and receipt["sampler"]==expected_sampler,
                    "unregistered source/score Head ablation")
            weights,weight_digest=read_head(folder/"head-weights.npz",receipt["weights_file_sha256"])
            require(weight_digest==receipt["final_head_sha256"],
                    "actual numeric weights disagree with FP32 named digest")
            model_bytes=_checked_path(folder/"tune-logits.npy",receipt["tune_logits_file_sha256"],limit=100_000)
            original_stream=BytesIO(model_bytes)
            version=np.lib.format.read_magic(original_stream)
            require(version in ((1,0),(2,0)),"safe logits NPY version required")
            reader=(np.lib.format.read_array_header_1_0 if version==(1,0)
                    else np.lib.format.read_array_header_2_0)
            shape,fortran,dtype=reader(original_stream,max_header_size=4096)
            require(tuple(shape)==(827,2) and not fortran and dtype==np.float32 and
                    len(model_bytes)==original_stream.tell()+827*2*4,
                    "complete exact 827x2 FP32 logits header before allocation")
            external=np.load(BytesIO(model_bytes),allow_pickle=False,max_header_size=4096)
            require(type(external) is np.ndarray and external.dtype==np.float32 and
                    external.shape==(827,2) and bool(np.isfinite(external).all()),
                    "complete actual Torch candidate logits required")
            x=make_features(data["tune"],ref["tune_p"],mode=expected_mode)
            old=original_logits(ref["tune_p"])
            independently=numpy_forward(weights,x,old)
            maximum=float(np.max(np.abs(independently.astype(np.float64)-external.astype(np.float64))))
            require(maximum<=0.0002,"independent PyTorch/NumPy candidate logits disagree")
            decision=independently.argmax(axis=1).tolist()
            external_dec=external.argmax(axis=1).tolist()
            require(decision==external_dec and
                    sha(canonical(decision))==receipt["candidate_tune_prediction_sha256"],
                    "source-bound archived candidate class predictions changed")
            original_score=score(data["tune"],decision)
            _same_score(receipt["tune_metrics"],original_score)
            require(receipt["tune_class_flip_count"]==sum(a!=b for a,b in zip(decision,source_pred)),
                    "candidate old pretrained score delta changed")
            pred[arm]=decision
            per[arm]=dict(genuine_human_label_internal_tune=original_score,
                    final_head_digest=weight_digest,
                    actual_original_probabilities_used=True,
                    max_abs_numpy_torch_logit_error=maximum,
                    exact_top_class_agreement=True)
            max_diff=max(max_diff,maximum)
            census+=receipt["updates"]
        prediction[seed]=pred;all_models[str(seed)]=per
    require(census==5040,"registered 12-Cell 420-step independent receipt census required")
    effects=bootstrap(data["tune"],prediction,original)
    summary={}
    for arm in ("frozen","always_positive","two_scalar",*ARMS):
        vals=[]
        for seed in SEEDS:
            part=full["results"][str(seed)]
            a=(part["frozen_baseline"] if arm=="frozen" else
               part["always_positive"] if arm=="always_positive" else
               part["two_scalar_control"]["tune_metrics"] if arm=="two_scalar" else
               part["arms"][arm]["tune_metrics"])
            vals.append(a)
        summary[arm]=dict(mean_f1_a=sum(x["f1_a"] for x in vals)/3,
                          mean_exact_match=sum(x["exact_match"] for x in vals)/3,
                          mean_accuracy=sum(x["accuracy"] for x in vals)/3,
                          individual_seeds={str(seed):vals[j] for j,seed in enumerate(SEEDS)})
    return dict(schema="hepta.bridge.v79.independent-score-cell-review.v1",
                status="NUMERICAL_REPLAY_PASS_EXPOSED_SOURCE_ONLY_NOT_PRODUCTION",
                archive_sha256={"v6":V6_SHA,"v7":V7_SHA},
                source_identity_sha256=data["source_sha256"],
                real_human_label_train_candidates=3909,
                previously_exposed_natural_internal_tune_candidates=827,
                train_source_groups=64,tune_source_groups=16,
                genuine_original_pretrained_frozen_logits=True,
                original_pretrained_encoder_or_Reader_forward_reexecuted=False,
                new_embedded_features_are_public_handcrafted_lexical_not_97d_hidden=True,
                candidate_models_independently_replayed=12,
                candidate_optimizer_steps_receipted=5040,
                model_summaries=summary,model_replay=all_models,
                maximum_original_torch_vs_numpy_abs_logits_error=max_diff,
                source_cluster_exploratory_bootstrap=effects,
                complete_lifecycle_equal_compute_established=False,
                future_source_disjoint_prospective_efficacy_established=False,
                native_ndu_admitted=False,model_selected=False,cell_split_authorized=False,
                production_authorized=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for flag in ("v6","v7","run","report"):
        ap.add_argument("--"+flag,type=Path,required=True)
    args=ap.parse_args()
    require(not args.report.exists() and not args.report.is_symlink(),"write-once independent report")
    result=review(args.v6,args.v7,args.run)
    with args.report.open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write("\n")
    print(json.dumps(dict(status=result["status"],numerically_replayed=result["candidate_models_independently_replayed"]),sort_keys=True))


if __name__=="__main__":main()
