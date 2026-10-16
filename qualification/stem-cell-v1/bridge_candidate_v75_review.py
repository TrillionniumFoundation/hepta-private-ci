"""Independent source-first V7.5 candidate numerical and TRAIN-only review.

Uses original V6 immutable labels only AFTER a separate no-label logits seal.
Re-executes saved candidate FP32 tensor bytes with Torch-free NumPy and checks
saved Torch logits and previously observed candidate probabilities. Any report
is DENY_ALL and says nothing about prospective generalization or 10T ability.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import time

import numpy as np

from bridge_candidate_v75 import (SCHEMA, PREDICTION_SCHEMA, SEEDS, ARMS,
    _digest, _json, _hex, _load, _case_rows, _write, check_source_bindings, BATCHES)
from bridge_gradient_archive_replay import require, read_regular_file
from bridge_numpy_receipt import verify, _external, _manifest, _read_tensor_archive
from bridge_portable_v74_review import old_score


def audit_one(features_dir, prediction_dir, checkpoint, rows,
              previous_probabilities, *, seed, arm, allow_synthetic=False):
    start_cpu,start_wall = time.process_time_ns(),time.perf_counter_ns()
    require(seed in SEEDS and arm in ARMS, "original fixed V7.5 candidate identity required")
    source_index = check_source_bindings(features_dir, rows, allow_synthetic=allow_synthetic)
    feature_index_raw=read_regular_file(Path(features_dir)/"index.json")
    pred_index_raw=read_regular_file(Path(prediction_dir)/"index.json")
    pred_index=_load(pred_index_raw)
    require(pred_index.get("schema")==PREDICTION_SCHEMA and pred_index.get("status")=="sealed"
            and pred_index.get("seed")==seed and pred_index.get("arm")==arm
            and pred_index.get("original_features_index_sha256")==_digest(feature_index_raw)
            and pred_index.get("payload_contains_targets") is False
            and pred_index.get("producer_label_isolation_independently_proven") is False
            and pred_index.get("production_authorized") is False
            and pred_index.get("torch_producer_self_reported") is True
            and pred_index.get("actual_host_attested") is False,
            "separately sealed original frozen Torch producer receipt required")
    all_rows=pred_index.get("batches")
    require(type(all_rows) is list and len(all_rows)==BATCHES,
            "eight original source batches must be present")
    checkpoint_raw=read_regular_file(checkpoint)
    checkpoint_sha=_digest(checkpoint_raw)
    require(checkpoint_sha==pred_index.get("checkpoint_sha256"),
            "candidate frozen weight ZIP mismatch against presealed predictions")
    require(type(previous_probabilities) in (list,tuple) and len(previous_probabilities)==128
            and all(type(p) in (int,float) and math.isfinite(p) and 0 <= p <= 1
                    for p in previous_probabilities),
            "complete existing candidate old Binding TRAIN probabilities required")
    numerical=[]
    measured=[]
    source_ids=[]
    max_existing_diff=0.
    output_scope=[]
    for i,(original,pred) in enumerate(zip(source_index["batches"],all_rows,strict=True)):
        require(pred.get("batch")==i and pred.get("name")==f"batch-{i:03d}.json"
                and pred.get("feature_sha256")==original["feature_sha256"]
                and pred.get("manifest_sha256")==original["manifest_sha256"]
                and pred.get("case_ids_sha256")==_digest(_json(original["case_ids"])),
                "wrong original source input or arbitrary candidate observed batch")
        for f in ("sha256", "manifest_sha256", "feature_sha256", "case_ids_sha256"):
            _hex(pred[f])
        folder=Path(features_dir)/f"batch-{i:03d}"
        manifest=folder/"manifest.json"
        archive=folder/"features.npz"
        observation=Path(prediction_dir)/pred["name"]
        observation_raw=read_regular_file(observation)
        require(_digest(observation_raw)==pred["sha256"],
                "existing external logits bytes mutated after prelabel seal")
        manifest_raw=read_regular_file(manifest)
        archive_raw=read_regular_file(archive,maximum=30_000_000)
        require(_digest(manifest_raw)==original["manifest_sha256"] and
                _digest(archive_raw)==original["feature_sha256"],
                "sealed original source feature bytes replaced")
        # Explicitly confirm which immutable original cases these tensors claim;
        # NumPy execution verifies only feature->logit, not issuer provenance.
        parsed=_manifest(manifest_raw,archive_raw,_read_tensor_archive(archive_raw))
        require(parsed["case_ids"]==original["case_ids"] and
                parsed["case_source_sha256"]==original["case_source_sha256"] and
                parsed["encoder_digest"]==source_index["model_sha256"] and
                parsed["tokenizer_digest"]==source_index["tokenizer_sha256"] and
                parsed["preprocessor_digest"]==source_index["preprocess_sha256"],
                "case-level source identity or Encoder identity mismatched")
        review=verify(checkpoint, archive, manifest, observation,
                      checkpoint_sha=checkpoint_sha,
                      manifest_sha=original["manifest_sha256"],
                      logit_abs_tolerance=0.002)
        require(review["independent_tensor_forward_performed"] is True and
                review["model_parameter_count"]==42562 and
                review["case_count"]==16 and
                review["production_authorized"] is False,
                "independent actual saved candidate weight logits not verified")
        measured.append(review["max_abs_logit_error"])
        external=_external(observation_raw,checkpoint_sha,original["feature_sha256"],parsed["case_ids"])
        positive=np.exp(external[:,1] - np.logaddexp(external[:,0],external[:,1]))
        for j,p in enumerate(positive.tolist()):
            expected=previous_probabilities[i*16+j]
            if abs(p-expected)>max_existing_diff:max_existing_diff=abs(p-expected)
            require(abs(p-expected)<=0.001 and (p>.5)==(expected>.5),
                    "existing old-task score not produced by sealed candidate checkpoint")
            numerical.append(float(p))
        source_ids.extend(parsed["case_ids"])
        output_scope.append(dict(batch=i,manifest_sha256=original["manifest_sha256"],
                                 external_logits_sha256=pred["sha256"],
                                 max_abs_num_error=review["max_abs_logit_error"],
                                 case_count=16))
    require(source_ids==_case_rows(rows),"complete original source ordering lost")
    score=old_score(rows,numerical)
    # For synthetic input, this remains an analytic TEST score, not old-task
    # pretrained retention: *never* reinterpret the labels as fresh supervision.
    return dict(schema="hepta.bridge.candidate-v75.independent-numeric-review.v1",
        seed=seed,arm=arm,status="SOURCE_BOUND_NUMERIC_CHECK_NOT_TASK_QUALIFICATION",
        source_origin=source_index["origin"],
        feature_origin_reported_by_producer=source_index["origin"],
        pretrained_feature_issuer_authenticated=False,
        authenticator_witness_verified=False,
        checkpoint_sha256=checkpoint_sha,torch_logits_presealed=True,
        candidate_parameter_count=42562,case_count=128,
        batches=output_scope,old_binding_train_score=score,
        max_abs_torch_numpy_logit_error=max(measured),
        max_abs_existing_probability_error=max_existing_diff,
        numerical_checks_passed=True,
        training_labels_accessible_to_source_builder=True,
        independent_label_isolation_established=False,
        source_independent_future_windows=0,
        independent_new_task_utility_verified=False,
        old_task_future_retention_verified=False,
        shared_encoder_multimodal_generation_proven=False,
        ndu_selection_authorized=False,cell_split_authorized=False,
        model_promotion_authorized=False,production_authorized=False,
        measured_cpu_ns=time.process_time_ns()-start_cpu,
        measured_wall_ns=time.perf_counter_ns()-start_wall)


def audit_grid(originals, features, outputs, predictions_root, *, report):
    """Require genuine completed V7.4 nine-arm study before numeric review."""
    from bridge_portable_v74_review import evaluate, read
    require(report is not None, "create-only independent review output required")
    checked=evaluate(outputs,originals)  # existing 4500-step / tensor audit
    rows=originals["source"]["reader_train"]
    source=check_source_bindings(features,rows,allow_synthetic=False)
    require(source["origin"] in ("exact_historical_cache","new_pretrained_physical_encoding"),
            "no synthetic substitute for actual pretrained candidate qualification")
    results={}
    for seed in SEEDS:
        for arm in ARMS:
            folder=Path(outputs)/f"seed-{seed}"/arm
            panel=read(folder/"old-binding-train.json",maximum=8_000_000)
            result=audit_one(features,Path(predictions_root)/f"seed-{seed}"/arm,
                   folder/"candidate.pt",rows,panel["probabilities"],
                   seed=seed,arm=arm,allow_synthetic=False)
            for key in ("accuracy","both_worlds_correct","evidence_switch_rate"):
                require(abs(result["old_binding_train_score"][key] -
                            panel["metrics"][key])<=1e-12,
                        "independent original held-label score mismatch")
            results[f"{seed}/{arm}"]=dict(checkpoint_sha256=result["checkpoint_sha256"],
                score=result["old_binding_train_score"],
                maximum_numeric_error=result["max_abs_torch_numpy_logit_error"],
                maximum_existing_probability_error=result["max_abs_existing_probability_error"])
    receipt=dict(schema="hepta.bridge.candidate-v75.full-nine-review.v1",
            status="ALL_NUMERIC_RECEIPTS_CONSISTENT_NOT_PROMOTION",
            cases=128,source_origin=source["origin"],
            parent_review_status=checked["status"],
            all_nine_candidates_verified=len(results)==9,models=results,
            original_heldout_source_evaluated=False,
            source_independent_future_windows=0,
            independent_issuer_signature_verified=False,
            any_model_promotion_authorized=False,
            ndu_authority=False,cell_split_authorized=False,
            production_authorized=False)
    _write(report,_json(receipt))
    return receipt


def main():
    import argparse
    from bridge_portable_v74 import originals
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("v4","v5","v6","features","v74_run","predictions","report"):
        parser.add_argument("--"+name.replace("_","-"),type=Path,required=True)
    args=parser.parse_args()
    require(not args.report.exists() and not args.report.is_symlink(),
            "independent review report is write-once")
    source=originals(args.v4,args.v5,args.v6)
    result=audit_grid(source,args.features,args.v74_run,args.predictions,report=args.report)
    print(json.dumps(dict(schema=result["schema"],reviewed_models=len(result["models"]),
                         production_authorized=False),sort_keys=True))


if __name__=="__main__":
    main()
