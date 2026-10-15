"""Torch-free original V6 source-bound review of genuine V7.7 synthetic mechanisms.

The parent .pt bytes are read only to authenticate historical identities;
this reviewer does not decode new Cell weights or attest training execution.
Two separately executed deterministic physical runs are compared by HEAD digest.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import os
import zipfile

V6_SHA="197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
SCHEMA="hepta.bridge.split-cell-v77.archived-weight-synthetic-task.shadow.v1"
SEEDS=(41,47,53)
ALLOWED_REPORT = frozenset(('schema','status','original_V6_zip_sha256','original_V6_models',
    'experiment','synthetic_teacher','synthetic_feature_geometry',
    'training_update_count_per_cell','samples_per_seed','results',
    'physical_allocated_cell_heads','physically_distinct_parent_tensor_storages',
    'physically_distinct_head_tensor_storages','shared_original_parent_same_python_module',
    'physical_cohort_init_cpu_ns','weight_budget','process_cpu_ns','process_wall_ns',
    'source_disjoint_synthetic_only','production_authorized',
    'cell_split_production_authorized','pretrained_granite_model_executed',
    'original_tokenbank_tensors_available','real_multirc_labels_used',
    'real_multirc_generalization_verified','natural_task_transfer_verified',
    'original_old_task_semantic_retention_verified',
    'new_task_synthetic_latent_teacher_only','NDU_system2_policy_verified',
    'new_cell_model_selected'))
ALLOWED_ROW = frozenset(('seed','parent_sha256','archived_checkpoint_file_sha256',
    'original_base_parameter_count','new_head_parameter_count','synthetic_train_rows',
    'synthetic_held_source_rows','synthetic_train_positive','synthetic_held_positive',
    'synthetic_train_baseline_correct','synthetic_train_new_correct',
    'synthetic_unseen_baseline_correct','synthetic_unseen_new_correct',
    'original_old_route_initial_exact','original_old_route_posttrain_exact',
    'original_parent_state_unchanged','original_parent_state_train_gradient_count',
    'physical_frozen_parent_forwards_for_training_cache',
    'physical_frozen_parent_forwards_for_unseen_evaluation',
    'full_train_optimizer_steps','actual_optimizer_bytes','train_cpu_ns',
    'train_wall_ns','head_sha256','independent_synthetic_held_source_groups',
    'original_real_pretrained_V6_weights_used','original_granite_features_used',
    'labels_constructed_from_frozen_latent_train_median_only'))
HEX=re.compile(r"[0-9a-f]{64}\Z")


def check(condition,why):
    if not condition:raise ValueError(why)


def _unique_pairs(pairs):
    result={}
    for key,value in pairs:
        check(key not in result,"duplicate JSON property")
        result[key]=value
    return result


def _json(blob,*,cap=1_000_000):
    check(isinstance(blob,bytes) and 0<len(blob)<=cap,"bounded original receipt JSON required")
    return json.loads(blob,object_pairs_hook=_unique_pairs,
        parse_constant=lambda bad:(_ for _ in ()).throw(ValueError("nonfinite JSON: "+bad)))


def _regular(path,max_size):
    path=Path(path)
    check(not path.is_symlink(),"symlinked evidence forbidden")
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        st=os.fstat(stream.fileno())
        check(stat.S_ISREG(st.st_mode) and 0<st.st_size<=max_size,
              "bounded regular evidence required")
        blob=stream.read()
        after=os.fstat(stream.fileno())
        check((st.st_ino,st.st_dev,st.st_size,st.st_mtime_ns)==
              (after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns),
              "evidence changed during read")
    return blob


def _sha(blob):return hashlib.sha256(blob).hexdigest()

def _digest(x):
    check(type(x) is str and HEX.fullmatch(x) is not None,"registered original SHA256 required")
    return x


def _number(v,*,minimum=0):
    check(type(v) in (float,int) and math.isfinite(v) and v>=minimum,
          "nonnegative finite physical observation required")
    return v


def validate_reports(archive,observation,replica):
    source=_regular(archive,30_000_000)
    check(len(source)==20928479 and _sha(source)==V6_SHA,"complete authentic V6 ZIP required")
    receipts=[_json(_regular(p,2_000_000)) for p in (observation,replica)]
    with zipfile.ZipFile(io.BytesIO(source)) as z:
        archived={}
        for seed in SEEDS:
            prefix=f"reader-v6-bridge/seed-{seed}/bridge/"
            record=_json(z.read(prefix+"warmup-model.json"))
            raw=z.read(prefix+"warmup.pt")
            check(_sha(raw)==record["file_sha256"] and
                  record["architecture"]["arm"]=="bridge" and
                  record["seed"]==seed and record["parameter_count"]==42562,
                  "authentic original V6 source/warmup geometry differs")
            archived[seed]=record
    for item in receipts:
        check(type(item) is dict and set(item)==ALLOWED_REPORT,
              "complete exact original V7.7 shadow result schema required")
        check(item.get("schema")==SCHEMA and
              item.get("status")=="MECHANISM_PASS_NO_NATURAL_GENERALIZATION" and
              item.get("original_V6_zip_sha256")==V6_SHA and
              item.get("physical_allocated_cell_heads")==256 and
              item.get("physically_distinct_parent_tensor_storages")==1 and
              item.get("physically_distinct_head_tensor_storages")==256 and
              item.get("shared_original_parent_same_python_module") is True and
              item.get("training_update_count_per_cell")==420 and
              item.get("samples_per_seed")=={"train":160,"synthetic_unseen":48} and
              item.get("experiment")=="new_cell_frozen_v6_reader_gated_1700_head" and
              item.get("synthetic_teacher")=="frozen_latent_column_0_minus_column_1_greater_than_train_median" and
              item.get("synthetic_feature_geometry")=="fp32_384d_non_granite_3_facts_4_tokens",
              "registered exact 3-seed physical research cohort required")
        check(item.get("pretrained_granite_model_executed") is False and
              item.get("original_tokenbank_tensors_available") is False and
              item.get("real_multirc_labels_used") is False and
              item.get("real_multirc_generalization_verified") is False and
              item.get("natural_task_transfer_verified") is False and
              item.get("original_old_task_semantic_retention_verified") is False and
              item.get("new_task_synthetic_latent_teacher_only") is True and
              item.get("source_disjoint_synthetic_only") is True and
              item.get("NDU_system2_policy_verified") is False and
              item.get("cell_split_production_authorized") is False and
              item.get("production_authorized") is False and
              item.get("new_cell_model_selected") is False,
              "failed scientific scope separation / forged qualification")
        w=item["weight_budget"]
        check(w["cells"]==256 and w["shared_reader_bytes"]==42562*4
              and w["each_head_bytes"]==1700*4
              and w["physical_parameter_bytes"]==(42562+256*1700)*4
              and w["dense_replica_baseline_bytes"]==256*42562*4
              and w["pretrained_encoder_not_included"] is True and
              w["train_optimizer_cache_activations_not_included"] is True,
              "incorrect narrow weight-only physical memory claim")
        check(item["original_V6_models"]==[archived[s]["training_parameter_sha256"] for s in SEEDS],
              "original 3-seed model roster mismatch")
        _number(item["physical_cohort_init_cpu_ns"])
        _number(item["process_cpu_ns"])
        _number(item["process_wall_ns"])
        rows=item["results"]
        check(type(rows) is list and len(rows)==3 and
              [x["seed"] for x in rows]==list(SEEDS),
              "exact 3 original archived warmup seed identities required")
        for row in rows:
            check(type(row) is dict and set(row)==ALLOWED_ROW,
                  "complete registered 3-seed Cell experiment row required")
            seed=row["seed"]
            check(row["parent_sha256"]==archived[seed]["training_parameter_sha256"] and
                  row["archived_checkpoint_file_sha256"]==archived[seed]["file_sha256"] and
                  row["original_base_parameter_count"]==42562 and
                  row["new_head_parameter_count"]==1700 and
                  row["synthetic_train_rows"]==160 and
                  row["synthetic_held_source_rows"]==48 and
                  row["synthetic_train_positive"]==80 and
                  0<=row["synthetic_held_positive"]<=48 and
                  row["original_old_route_initial_exact"] is True and
                  row["original_old_route_posttrain_exact"] is True and
                  row["original_parent_state_unchanged"] is True and
                  row["original_parent_state_train_gradient_count"]==0 and
                  row["physical_frozen_parent_forwards_for_training_cache"]==10 and
                  row["physical_frozen_parent_forwards_for_unseen_evaluation"]==6 and
                  row["full_train_optimizer_steps"]==420 and
                  row["original_real_pretrained_V6_weights_used"] is True and
                  row["original_granite_features_used"] is False and
                  row["labels_constructed_from_frozen_latent_train_median_only"] is True,
                  "original frozen V6 source/start, training work or synthetic-only scope changed")
            _digest(row["head_sha256"])
            for key,limit in (("synthetic_train_baseline_correct",160),
                ("synthetic_train_new_correct",160),
                ("synthetic_unseen_baseline_correct",48),
                ("synthetic_unseen_new_correct",48)):
                score=row[key]
                check(type(score) is int and 0<=score<=limit,
                      "invalid complete synthetic-only score census")
            check(type(row["independent_synthetic_held_source_groups"]) is int and
                  1<=row["independent_synthetic_held_source_groups"]<=48,
                  "bounded separately constructed synthetic unseen source groups required")
            _number(row["train_cpu_ns"])
            _number(row["train_wall_ns"])
            _number(row["actual_optimizer_bytes"])
    # Reproducibility, not a hypothesis significance test. Identical physical
    # original tensors + synthetic samples + CPU backward/Adam → same new state.
    paired=[]
    for a,b in zip(receipts[0]["results"],receipts[1]["results"]):
        for field in ("seed","parent_sha256","head_sha256",
                      "synthetic_train_baseline_correct","synthetic_train_new_correct",
                      "synthetic_unseen_baseline_correct","synthetic_unseen_new_correct",
                      "original_old_route_posttrain_exact","full_train_optimizer_steps"):
            check(a[field]==b[field],"independent repeated actual run result drift: "+field)
        paired.append(dict(seed=a["seed"],frozen_parent_sha256=a["parent_sha256"],
           trained_head_sha256=a["head_sha256"],
           synthetic_train_before_correct=a["synthetic_train_baseline_correct"],
           synthetic_train_after_correct=a["synthetic_train_new_correct"],
           synthetic_unseen_before_correct=a["synthetic_unseen_baseline_correct"],
           synthetic_unseen_after_correct=a["synthetic_unseen_new_correct"],
           frozen_original_old_route_exact=True))
    return dict(schema="hepta.bridge.split-cell-v77.independent-receipt-review.v1",
      status="SOURCE_DIGEST_AND_DETERMINISTIC_REPEAT_CONSISTENT_NOT_MODEL_QUALIFICATION",
      original_v6_sha256=V6_SHA,
      original_v6_warmup_sha256_by_seed={str(k):v["file_sha256"] for k,v in archived.items()},
      repeated_execution_receipt_sha256s=[_sha(_regular(p,2_000_000)) for p in (observation,replica)],
      original_3_seed_frozen_weights_authenticated_by_archive=True,
      actual_model_training_independently_reexecuted_by_stdlib_reviewer=False,
      independent_task_evaluation_labels_present=False,
      all_candidate_head_sha256_deterministically_identical_across_two_real_runs=True,
      original_old_route_output_invariance_reported_not_separately_recomputed_here=True,
      actual_pretrained_encoder_executed=False,
      original_natural_task_generalization_established=False,
      current_production_authority=False,
      per_seed=paired,
      full_lifecycle_equal_cost_verified=False,
      frozen_backbone_copy_allocation_verified_by_runtime_receipts_only=True,
      future_human_source_disjoint_validation_opened=False,
      model_promoted=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original-v6-zip",required=True,type=Path)
    ap.add_argument("--first",required=True,type=Path)
    ap.add_argument("--replica",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args()
    check(not args.output.exists() and not args.output.is_symlink(),
          "write-once independent review required")
    record=validate_reports(args.original_v6_zip,args.first,args.replica)
    with args.output.open("x",encoding="utf-8") as file:
        json.dump(record,file,sort_keys=True,indent=2,allow_nan=False)
        file.write("\n")
        file.flush();os.fsync(file.fileno())
    print(json.dumps({"status":record["status"],"seeds":len(record["per_seed"])},sort_keys=True))

if __name__=="__main__":main()
