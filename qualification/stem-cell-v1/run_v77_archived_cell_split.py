"""Actual archived V6 Bridge training of 1,700-parameter split heads on synthetic labels.

NEVER use these token probes as pretrained Granite features or natural-language
quality. Pre-registered toy teacher depends only on frozen 97D latent, not text.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import time
import zipfile

import torch

from bridge_reader import build_reader
from bridge_split_cell_v77 import (SplitBridgeCell,RouteEvidence,collect_new_task_cache,
    digest_parameters,feature_digest,fit_new_task_head,physical_weight_budget,
    NEW_TASK,OLD_TASK)

V6_SHA = "197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
SEEDS = (41,47,53)
SCHEMA = "hepta.bridge.split-cell-v77.archived-weight-synthetic-task.shadow.v1"
SHADOW = dict(production_authorized=False,cell_split_production_authorized=False,
    pretrained_granite_model_executed=False,
    original_tokenbank_tensors_available=False,
    real_multirc_labels_used=False,
    real_multirc_generalization_verified=False,
    natural_task_transfer_verified=False,
    original_old_task_semantic_retention_verified=False,
    new_task_synthetic_latent_teacher_only=True,
    NDU_system2_policy_verified=False,
    new_cell_model_selected=False)


def require(predicate,reason):
    if not predicate:raise ValueError(reason)


def _read_original(path):
    path=Path(path)
    require(not path.is_symlink(),"symlinked source denied")
    with path.open("rb") as stream:
        s=os.fstat(stream.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_size==20928479,
                "complete original V6 source archive size required")
        blob=stream.read()
    require(hashlib.sha256(blob).hexdigest()==V6_SHA,"real original V6 SHA256 required")
    return zipfile.ZipFile(io.BytesIO(blob))


def synthetic_features(seed, *, n=16):
    """No tokenizer, raw text, publisher ground truth or Granite forward here."""
    rng=torch.Generator().manual_seed(seed)
    facts=torch.randn(n,3,4,384,generator=rng)
    q=torch.randn(n,2,384,generator=rng)
    c=torch.randn(n,2,384,generator=rng)
    fm=torch.ones(n,3,4,dtype=torch.bool)
    fm[:,-1,-1]=False
    return (facts,q,c,fm,torch.ones(n,2,dtype=torch.bool),
            torch.ones(n,2,dtype=torch.bool))


def synthetic_ticket(public,original_sha,seed,start,scope="train"):
    n=public[0].shape[0]
    return RouteEvidence(NEW_TASK,
        tuple(f"SYNTHETIC_V77/{scope}/seed-{seed}/row-{start+i}" for i in range(n)),
        tuple(hashlib.sha256(f"SYNTHETIC_V77/{scope}/seed-{seed}/source-{(start+i)//4}".encode()).hexdigest()
              for i in range(n)),feature_digest(public),original_sha,"7"*64,"8"*64,"9"*64,
        source_scope=scope)


def _synthetic_teacher(latent,train_threshold):
    # Only coordinate 0−1 of the *frozen V6 internal 97D representation*.
    return (latent[:,0]-latent[:,1]>train_threshold).long()


def run(original,output,*,physical_cohort=256):
    require(type(physical_cohort) is int and 1<=physical_cohort<=256,
            "bounded actual physically allocated head cohort required")
    out=Path(output)
    require(not out.exists() and not out.is_symlink(),"write-once result file required")
    torch.set_num_threads(1)
    started_cpu,started_wall=time.process_time_ns(),time.perf_counter_ns()
    with _read_original(original) as z:
        old_original=json.loads(z.read("reader-v6-bridge/all-cases.json"))["reader_train"]
        require(len(old_original)==128,"complete original Binding cohort required")
        old_source_ids={row["source_hash"] for row in old_original}
        require(len(old_source_ids)==64,"complete original paired-world source cohort required")
        records=[]
        for seed in SEEDS:
            prefix=f"reader-v6-bridge/seed-{seed}/bridge/"
            manifest=json.loads(z.read(prefix+"warmup-model.json"))
            src=z.read(prefix+"warmup.pt")
            require(hashlib.sha256(src).hexdigest()==manifest["file_sha256"]
                    and manifest["architecture"]["arm"]=="bridge"
                    and manifest["seed"]==seed,"original model weight identity failed")
            old=build_reader("bridge",seed).eval().requires_grad_(False)
            old.load_state_dict(torch.load(io.BytesIO(src),map_location="cpu",weights_only=True),strict=True)
            expected=manifest["training_parameter_sha256"]
            require(digest_parameters(old)==expected,"original decoded weights differ from manifest")
            cell=SplitBridgeCell(old,expected_parent_sha256=expected,new_head_seed=seed)
            probe=synthetic_features(75000+seed)
            old_before=old(*probe,steps=3)
            routed_before=cell.route(probe,replace(synthetic_ticket(probe,expected,seed,0),task_family=OLD_TASK))
            require(torch.equal(old_before,routed_before),"old Bridge route differs at start")
            exact_initial_new=torch.equal(old_before,cell.route(probe,synthetic_ticket(probe,expected,seed,0)))
            require(exact_initial_new,"new zero-residual Head changed original before fitting")

            # 10 batches x 16 rows = 160 synthetic sources, no natural labels.
            pairs=[]
            for start in range(0,160,16):
                feats=synthetic_features(50000+start)
                pairs.append((feats,synthetic_ticket(feats,expected,seed,start)))
            old_calls_before=cell.parent_forward_calls
            cache=collect_new_task_cache(cell,pairs,forbidden_old_sources=old_source_ids)
            require(cache.encoded_reader_calls==10,"all real Reader cache forwards required")
            signal=cache.hidden[:,0]-cache.hidden[:,1]
            cut=float(signal.median().item())  # training-only synthetic threshold
            synthetic_gold=_synthetic_teacher(cache.hidden,cut)
            require(int(synthetic_gold.sum())==80,"balanced synthetic teacher registration changed")
            receipt=fit_new_task_head(cell,cache,synthetic_gold,
                updates=420,batch_size=16,learning_rate=0.04,seed=seed,
                max_train_cpu_ns=45_000_000_000)
            require(cell.parent_forward_calls==old_calls_before+10,
                    "new Cell Head training called old parent after cache freeze")
            old_after=cell.route(probe,replace(synthetic_ticket(probe,expected,seed,0),task_family=OLD_TASK))
            require(torch.equal(old_before,old_after),"old route changed after new Cell learning")
            require(digest_parameters(old)==expected,"old immutable weight bytes changed")
            cell.check_frozen()
            # Synthetic held-input families never used by optimizer.
            hold_correct=hold_baseline=hold_pos=0
            unseen_groups=set()
            unseen_forward_count=0
            for offset in range(0,48,16):
                f=synthetic_features(60000+offset)
                ticket=synthetic_ticket(f,expected,seed,offset,"synthetic_unseen_source")
                require(not set(ticket.source_hashes)&set(cache.source_hashes),
                        "synthetic held-input source groups overlap training")
                unseen_groups.update(ticket.source_hashes)
                frozen_latent,base=cell.extract(f)
                truth=_synthetic_teacher(frozen_latent,cut)
                logits=cell.route(f,ticket)
                hold_correct+=int((logits.argmax(-1)==truth).sum().item())
                hold_baseline+=int((base.argmax(-1)==truth).sum().item())
                hold_pos+=int(truth.sum().item())
                unseen_forward_count+=2
            record=dict(seed=seed,parent_sha256=expected,archived_checkpoint_file_sha256=manifest["file_sha256"],
                original_base_parameter_count=42562,new_head_parameter_count=1700,
                synthetic_train_rows=160,synthetic_held_source_rows=48,
                synthetic_train_positive=80,synthetic_held_positive=hold_pos,
                synthetic_train_baseline_correct=receipt["train_only_before_correct"],
                synthetic_train_new_correct=receipt["train_only_after_correct"],
                synthetic_unseen_baseline_correct=hold_baseline,
                synthetic_unseen_new_correct=hold_correct,
                original_old_route_initial_exact=True,original_old_route_posttrain_exact=True,
                original_parent_state_unchanged=True,
                original_parent_state_train_gradient_count=0,
                physical_frozen_parent_forwards_for_training_cache=10,
                physical_frozen_parent_forwards_for_unseen_evaluation=unseen_forward_count,
                full_train_optimizer_steps=receipt["logical_optimizer_updates"],
                actual_optimizer_bytes=receipt["optimizer_tensor_bytes"],
                train_cpu_ns=receipt["training_cpu_ns"],
                train_wall_ns=receipt["training_wall_ns"],
                head_sha256=receipt["new_head_sha256"],
                independent_synthetic_held_source_groups=len(unseen_groups),
                original_real_pretrained_V6_weights_used=True,
                original_granite_features_used=False,
                labels_constructed_from_frozen_latent_train_median_only=True)
            records.append(record)

        # 256 real per-Cell Head modules, one actual original physical parent.
        cohort_parent=old  # most recent seed-53 original model
        cohort_sha=digest_parameters(cohort_parent)
        cohort_start_cpu=time.process_time_ns()
        cohort=[SplitBridgeCell(cohort_parent,expected_parent_sha256=cohort_sha,
                                 new_head_seed=120000+i) for i in range(physical_cohort)]
        physical_unique_parent_storage=len({c.parent.project.weight.data_ptr() for c in cohort})
        distinct_head_storages=len({c.new_head.input.weight.data_ptr() for c in cohort})
        require(physical_unique_parent_storage==1 and distinct_head_storages==physical_cohort,
                "cohort unexpectedly cloned frozen backbone or aliased Cell Heads")
        cohort_cpu_ns=time.process_time_ns()-cohort_start_cpu
        del cohort
    receipt=dict(schema=SCHEMA,status="MECHANISM_PASS_NO_NATURAL_GENERALIZATION",
                 original_V6_zip_sha256=V6_SHA,
                 original_V6_models=[r["parent_sha256"] for r in records],
                 experiment="new_cell_frozen_v6_reader_gated_1700_head",
                 synthetic_teacher="frozen_latent_column_0_minus_column_1_greater_than_train_median",
                 synthetic_feature_geometry="fp32_384d_non_granite_3_facts_4_tokens",
                 training_update_count_per_cell=420,
                 samples_per_seed=dict(train=160,synthetic_unseen=48),
                 results=records,
                 physical_allocated_cell_heads=physical_cohort,
                 physically_distinct_parent_tensor_storages=physical_unique_parent_storage,
                 physically_distinct_head_tensor_storages=distinct_head_storages,
                 shared_original_parent_same_python_module=True,
                 physical_cohort_init_cpu_ns=cohort_cpu_ns,
                 weight_budget=physical_weight_budget(physical_cohort),
                 process_cpu_ns=time.process_time_ns()-started_cpu,
                 process_wall_ns=time.perf_counter_ns()-started_wall,
                 source_disjoint_synthetic_only=True,
                 **SHADOW)
    with out.open("x",encoding="utf-8") as stream:
        json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n")
        stream.flush();os.fsync(stream.fileno())
    return receipt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original-v6-zip",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--physical-cohort",type=int,default=256)
    args=ap.parse_args()
    result=run(args.original_v6_zip,args.output,physical_cohort=args.physical_cohort)
    print(json.dumps({"status":result["status"],"seeds":len(result["results"]),
                      "heads_physically_allocated":result["physical_allocated_cell_heads"],
                      "main_or_production_affected":False},sort_keys=True))

if __name__=='__main__':main()
