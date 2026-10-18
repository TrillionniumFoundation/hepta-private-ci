"""Unpromotable physical 48-case MultiRC/Encoder/Head pilot (P2.3).

Three independent entrypoints. The producing process reads only label-free
original source views and FIT labels; no CAL/TEST owner path. The numerical
reviewer replays the complete frozen Head fit from the original features. A
third, later process has the original human CAL/TEST labels and aggregates
only descriptive metrics, never a release/model-ranking decision.

This is NOT a security sandbox or independently signed model/evaluator custody.
Never upload raw features, source text, per-case logits, model tensors or gold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import gate
import matched_head as mh

SCHEMA = "hepta.stem.equal-size.original-48-pilot.v1"
MODELS = ("ettin400", "laya421")
FILES = ("bank.json", "head.json", "head-tensors.npz", "encoder-cost.json")
MAX_JSON = 24 * 1024 * 1024
MAX_NPZ = 3 * 1024 * 1024
SOURCE_SHA = "598dc04a67bc8e536589cfd68224a7b8b59a45e094ac4a2a5b51a5ac786c235a"
SRC_TRAIN_SHA = "ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728"
SRC_VALID_SHA = "5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada"


def check(condition, message):
    gate.require(condition, message)


def canonical(doc):
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path, *, limit=MAX_JSON):
    path = Path(path)
    check(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
          "missing, aliased or oversized P2.3 file")
    # open(NO-FOLLOW) and fstat once more to catch unreviewed link replacement.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        check(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= limit,
              "invalid P2.3 input file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read(limit + 1)
        check(len(content) == st.st_size, "P2.3 input changed during read")
        return content
    finally:
        os.close(fd)


def read_json(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            check(key not in out, "duplicate research JSON key")
            out[key] = value
        return out
    return json.loads(read_file(path), object_pairs_hook=unique,
                      parse_constant=lambda _: check(False, "non-finite JSON"))


def new_json(path, obj):
    path = Path(path)
    check(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
          "create-only ordinary P2.3 output required")
    b = canonical(obj) + b"\n"
    check(0 < len(b) <= MAX_JSON, "too large research JSON")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(b)
        f.flush()
        os.fsync(f.fileno())


def new_npz(path, product):
    import numpy as np
    path = Path(path)
    check(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
          "create-only private Head tensor file required")
    arrays = {}
    for stage in ("initial", "trained"):
        bundle = product[stage + "_head_tensors"]
        check(type(bundle) is dict and set(bundle) ==
              {"0.weight", "0.bias", "2.weight", "2.bias"}, "Head tensor inventory drift")
        for key, value in bundle.items():
            check(type(value) is np.ndarray and value.dtype == np.float32 and
                  np.isfinite(value).all(), "unapproved private Head tensor")
            arrays[stage + "_" + key] = value
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as file:
        np.savez_compressed(file, **arrays)
        file.flush()
        os.fsync(file.fileno())
    check(path.stat().st_size <= MAX_NPZ, "private Head tensor archive oversized")


def npz_product(path, receipt):
    import numpy as np
    data = read_file(path, limit=MAX_NPZ)
    from io import BytesIO
    with np.load(BytesIO(data), allow_pickle=False) as tensors:
        keys = {t + "_" + k for t in ("initial", "trained")
                for k in ("0.weight", "0.bias", "2.weight", "2.bias")}
        check(set(tensors.files) == keys, "private Head archive added or omitted tensor")
        return {"receipt": receipt,
                **{stage + "_head_tensors": {k: tensors[stage + "_" + k].copy()
                     for k in ("0.weight", "0.bias", "2.weight", "2.bias")}
                   for stage in ("initial", "trained")}}


def produce(model, panel_path, views_path, fit_path, source_receipt_path, stage, destination):
    """No original human CAL or TEST labels are accepted here."""
    check(model in MODELS, "only original pinned two Encoder candidates admitted")
    panel, views, fit = map(read_json, (panel_path, views_path, fit_path))
    check(gate.digest(panel) == SOURCE_SHA and
          len(panel["cases"]) == 48 and
          [sum(x["split"] == k for x in panel["cases"]) for k in ("fit", "cal", "test")]
          == [24, 8, 16], "not exact original-hosted 48-case MultiRC source identity")
    check(mh.validate_fit(panel, fit) and fit["production_authorized"] is False,
          "FIT-only original human training labels required")
    import physical_feature_bank as fb  # heavy real model loading occurs inside make_bank
    source_receipt = read_json(source_receipt_path)
    bank, cost = fb.make_bank(model, panel, views, source_receipt, Path(stage))
    check(cost["actual_encoder_forwards_observed"] == 48 and
          cost["actual_loaded_tensor_elements_reported"] == fb.PINNED_ORIGINAL_TENSOR_COUNTS[model]
          and cost["input_tokenization_nontruncated_reported"] is True and
          bank["model"] == model, "model forward census or truncation unverified")
    product = mh.train_one(panel, bank, fit)
    result = product["receipt"]
    check(result["trainable_params"] == 4161 and result["steps"] == 40 and
          result["has_test_labels"] is False and result["has_calibration_labels"] is False and
          result["authority"] == "DENY_ALL" and result["disposition"] == "HOLD_NO_GO" and
          result["production_promotion_permitted"] is False,
          "matched training head breached original source or authority")
    destination = Path(destination)
    check(destination.parent.is_dir() and not destination.parent.is_symlink() and
          not destination.exists(), "private case bank must be created once")
    destination.mkdir(mode=0o700)
    new_json(destination / "bank.json", bank)
    new_json(destination / "head.json", result)
    new_json(destination / "encoder-cost.json", cost)
    new_npz(destination / "head-tensors.npz", product)
    files = {filename: digest(read_file(destination / filename,
                                  limit=MAX_NPZ if filename.endswith(".npz") else MAX_JSON))
             for filename in FILES}
    seal = {"schema": SCHEMA, "model": model, "panel_sha256":SOURCE_SHA,
            "files_sha256": files, "source_weight_sha256":bank["source_weights_sha256"],
            "original_model_revision":bank["revision"],
            "feature_dimensions":bank["encoder_output_dimension"],
            "encoder_calls":cost["actual_encoder_forwards_observed"],
            "head_initial_sha256":result["initial_head_sha256"],
            "head_trained_sha256":result["head_weight_sha256"],
            "stage":"real_private_candidate_producer_not_independent_scoring",
            "original_human_test_labels_loaded":False,
            "promotion_permitted":False,"authority":"DENY_ALL", "disposition":"HOLD_NO_GO"}
    new_json(destination / "sealed.json", seal)
    return seal


def reviewed_private(model, panel_path, fit_path, directory):
    import matched_head_review as reviewer
    directory = Path(directory)
    check(directory.is_dir() and not directory.is_symlink() and model in MODELS,
          "invalid review directory")
    seal = read_json(directory / "sealed.json")
    check(type(seal) is dict and set(seal) == {
        "schema", "model", "panel_sha256", "files_sha256", "source_weight_sha256",
        "original_model_revision", "feature_dimensions", "encoder_calls", "head_initial_sha256",
        "head_trained_sha256", "stage", "original_human_test_labels_loaded",
        "promotion_permitted", "authority", "disposition"} and
        seal["schema"] == SCHEMA and seal["model"] == model and
        seal["panel_sha256"] == SOURCE_SHA and seal["encoder_calls"] == 48 and
        seal["original_human_test_labels_loaded"] is False and
        seal["promotion_permitted"] is False and
        seal["authority"] == "DENY_ALL" and seal["disposition"] == "HOLD_NO_GO",
        "missing/non-authorizing sealed original source identity")
    file_hashes = seal["files_sha256"]
    check(type(file_hashes) is dict and set(file_hashes) == set(FILES),
          "unregistered private producer files")
    for name in FILES:
        check(digest(read_file(directory / name,
                      limit=MAX_NPZ if name.endswith(".npz") else MAX_JSON)) == file_hashes[name],
              "altered after seal private model evidence")
    panel, labels, bank = read_json(panel_path), read_json(fit_path), read_json(directory / "bank.json")
    receipt = read_json(directory / "head.json")
    cost = read_json(directory / "encoder-cost.json")
    check(gate.digest(panel) == SOURCE_SHA and bank["model"] == model and
          bank["source_weights_sha256"] == seal["source_weight_sha256"] and
          bank["revision"] == seal["original_model_revision"] and
          bank["encoder_output_dimension"] == seal["feature_dimensions"] and
          cost["actual_encoder_forwards_observed"] == 48 and
          cost["actual_loaded_tensor_elements_reported"] > 400_000_000 and
          cost["original_issuer_signature_verified"] is False and
          cost["production_authorized"] is False and
          cost["authority"] == "DENY_ALL" and cost["disposition"] == "HOLD_NO_GO" and
          receipt["initial_head_sha256"] == seal["head_initial_sha256"] and
          receipt["head_weight_sha256"] == seal["head_trained_sha256"],
          "source/real model/head evidence mismatch")
    product = npz_product(directory / "head-tensors.npz", receipt)
    review = reviewer.independent_replay(panel, bank, labels, product)
    check(review["head_sha256"] == seal["head_trained_sha256"] and
          review["replayed_steps"] == 40 and review["promotion_permitted"] is False,
          "independent second implementation rejected genuine Head training")
    return seal, receipt, cost, review


def audit(model, panel_path, fit_path, directory, source_receipt_path, source_stage, out):
    # Separate process reopens the *original* pinned weight/tokenizer stage; a
    # self-reported producer cost is not an independent physical source audit.
    import physical_forward
    original = read_json(source_receipt_path)
    authentic = physical_forward.checked_receipt(original, Path(source_stage), model)
    seal, receipt, cost, review = reviewed_private(model, panel_path, fit_path, directory)
    check(cost["source_review_receipt_sha256"] == authentic["source_sha256_receipt"] and
          cost["actual_loaded_tensor_elements_reported"] > 400_000_000 and
          original["model"] == model and
          original["repo"] == gate.MODELS[model][0] and
          original["revision"] == gate.MODELS[model][1] and
          type(original.get("selected_source_inventory")) is list,
          "physical source bytes not independently bound to trained Head")
    original_weights = [x for x in original["selected_source_inventory"] if x.get("is_weight") is True]
    check(len(original_weights) == 1 and
          original_weights[0]["source_identity"] == seal["source_weight_sha256"] and
          original_weights[0]["source_identity_type"] == "lfs_sha256",
          "original model bytes differ from trained feature bank")
    report = {"schema":SCHEMA+".audit", "model":model,
              "panel_sha256":SOURCE_SHA,
              "source_weight_sha256":seal["source_weight_sha256"],
              "original_model_revision":seal["original_model_revision"],
              "encoder_calls_verified_from_producer_and_reviewer":seal["encoder_calls"],
              "real_parameter_elements_self_reported":cost["actual_loaded_tensor_elements_reported"],
              "original_input_tokens_self_reported":cost["total_real_input_tokens"],
              "process_cpu_ns_self_reported":cost["clock_cpu_ns_self_reported"],
              "process_wall_ns_self_reported":cost["clock_wall_ns_self_reported"],
              "peak_rss_kib_linux_self_reported":cost["peak_rss_kib_linux_self_reported"],
              "projection_counts_accounted":True,
              "independent_model_source_bytes_rehashed":True,
              "source_receipt_sha256":authentic["source_sha256_receipt"],
              "head_initial_sha256":seal["head_initial_sha256"],
              "head_final_sha256":seal["head_trained_sha256"],
              "head_replayed_steps":review["replayed_steps"],
              "head_replay_parameter_max_abs_error":review["parameter_max_abs_error"],
              "human_heldout_scored":False, "publisher_signing_verified":False,
              "model_production_promotion_permitted":False,
              "authority":"DENY_ALL", "disposition":"HOLD_NO_GO"}
    new_json(out, report)
    return report


def _sigmoid(logit):
    check(type(logit) in (float, int) and math.isfinite(logit) and -100 <= logit <= 100,
          "invalid uncalibrated original Head logit")
    return 1/(1+math.exp(-float(logit)))


def _metric(ordered, truth, baseline):
    check(len(ordered) == len(truth) > 0, "missing original human evaluation cases")
    probs = [_sigmoid(x) for x in ordered]
    score = sum((int(p >= .5) == y) for p,y in zip(probs,truth))/len(truth)
    brier = sum((p-y)**2 for p,y in zip(probs,truth))/len(truth)
    base_acc = sum((int(baseline >= .5)==y) for y in truth)/len(truth)
    base_brier = sum((baseline-y)**2 for y in truth)/len(truth)
    return {"cases":len(truth),"accuracy":score,"brier":brier,
            "fit_prior_constant_accuracy":base_acc,"fit_prior_constant_brier":base_brier}


def observe(model, panel_path, fit_label_path, original_fit_path, original_blind_path,
            owner_path, directory, audit_path, out):
    """Open original human held truth *only after* frozen model/Head audit."""
    import multirc_source_bridge as bridge
    panel=read_json(panel_path)
    # This entrypoint deliberately reads and checks source/Head evidence BEFORE
    # opening the separate original-human held-label source file.
    audit_doc=read_json(audit_path)
    seal,receipt,cost,review=reviewed_private(model,panel_path,fit_label_path,directory)
    check(audit_doc["schema"] == SCHEMA+".audit" and audit_doc["panel_sha256"] == SOURCE_SHA and
          audit_doc["model"] == model and audit_doc["independent_model_source_bytes_rehashed"] is True and
          audit_doc["head_final_sha256"] == seal["head_trained_sha256"] and
          audit_doc["head_initial_sha256"] == seal["head_initial_sha256"] and
          audit_doc["head_replayed_steps"] == 40 and
          audit_doc["source_receipt_sha256"] == cost["source_review_receipt_sha256"] and
          audit_doc["model_production_promotion_permitted"] is False and
          audit_doc["disposition"] == "HOLD_NO_GO",
          "original human observer had no verified source-and-Head audit")
    original_fit,original_blind,owner=(read_json(original_fit_path),
                                      read_json(original_blind_path),read_json(owner_path))
    recreated, _, fit, prov=bridge.convert(original_fit, original_blind)
    check(gate.digest(panel) == gate.digest(recreated) == SOURCE_SHA and
          prov["upstream_source_commit"] == bridge.ORIGINAL_SCRIPT_COMMIT and
          original_fit["metadata"]["train_sha256"] == SRC_TRAIN_SHA and
          original_fit["metadata"]["validation_sha256"] == SRC_VALID_SHA,
          "original source/case selection/publisher bytes are not frozen")
    check(type(owner) is dict and set(owner)== {
        "schema", "panel_id", "original_human_candidate_labels",
        "generated_intervention_labels_invented", "source_signature_independently_verified",
        "authority"} and
        owner["schema"] == "hepta.p0.multirc-original-human-labels.v1" and
        owner["panel_id"] == original_fit["metadata"]["panel_id"] and
        owner["generated_intervention_labels_invented"] is False and
        owner["source_signature_independently_verified"] is False and
        owner["authority"] == "DENY_ALL", "original held-label source mismatched")
    group_held = {"cal":set(),"test":set()}
    cal_ledger = {row["case_id"]: row["label"] for row in original_fit["cases"]
                  if row["split"] == "calibration" and row["condition"] == "original"}
    test_ledger=owner["original_human_candidate_labels"]
    check(type(test_ledger) is dict and all(type(x) is int and x in (0,1)
          for x in test_ledger.values()),"no original human publisher ground truth")
    fit_rate=sum(v["target"] for v in fit["targets"])/len(fit["targets"])
    scores={}
    for split, raw, truth_lookup, expected in (
        ("cal",receipt["raw_calibration_logits"],cal_ledger,8),
        ("test",receipt["raw_test_logits"],test_ledger,16),
    ):
        plan=[x for x in panel["cases"] if x["split"] == split]
        check(len(raw) == len(plan) == expected,"unmatched held source case count")
        xs,ys=[],[]
        for item,case in zip(raw,plan,strict=True):
            check(type(item) is dict and set(item)=={"case_id","logit"} and
                  item["case_id"] == case["case_id"] and
                  item["case_id"] in truth_lookup and
                  type(truth_lookup[item["case_id"]]) is int and
                  truth_lookup[item["case_id"]] in (0,1),
                  "changed case order or no independent original-human truth")
            xs.append(item["logit"])
            ys.append(truth_lookup[item["case_id"]])
            group_held[split].add(case["group_id"])
        scores[split] = _metric(xs,ys,fit_rate)
    check(len(group_held["test"])==8 and len(group_held["cal"])==4,
          "original human group independence missing")
    result={"schema":SCHEMA+".observer", "model":model,
            "panel_sha256":SOURCE_SHA,"original_dataset_revision":bridge.SOURCE_REVISION,
            "original_dataset_train_sha256":SRC_TRAIN_SHA,
            "original_dataset_validation_sha256":SRC_VALID_SHA,
            "head_sha256":seal["head_trained_sha256"],
            "head_seed":receipt["seed"],"head_steps":receipt["steps"],
            "head_params":receipt["trainable_params"],
            "held_accuracy_is_descriptive_not_model_selection":True,
            "calibration":scores["cal"],"test":scores["test"],
            "training_fit_cases":24, "test_independent_source_groups":8,
            "same_host_independent_process_not_external_issuer":True,
            "original_publisher_signature_verified":False,
            "chronological_future_window_verified":False,
            "negative_transfer_verified":False,
            "no_change_laya_policy_baseline_verified":False,
            "full_lifecycle_resource_parity_verified":False,
            "model_selected":None,"production_promotion_permitted":False,
            "physical_cell_split_permitted":False,"authority":"DENY_ALL",
            "disposition":"HOLD_NO_GO"}
    new_json(out,result)
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description="Original 48-case two-Encoder P2.3 (DENY_ALL)")
    sub=ap.add_subparsers(dest="command",required=True)
    for command in ("produce", "audit", "observe"):
        p=sub.add_parser(command)
        p.add_argument("--model",choices=MODELS,required=True)
        p.add_argument("--panel",required=True)
        p.add_argument("--directory",required=True)
        if command=="produce":
            for k in ("views", "fit", "receipt", "stage"):
                p.add_argument("--"+k,required=True)
        elif command=="audit":
            for k in ("fit", "receipt", "stage", "out"):
                p.add_argument("--"+k,required=True)
        else:
            for k in ("fit", "original-fit", "original-blind", "original-owner", "audit", "out"):
                p.add_argument("--"+k,required=True)
    a=ap.parse_args(argv)
    if a.command=="produce":
        x=produce(a.model,a.panel,a.views,a.fit,a.receipt,a.stage,a.directory)
        print(json.dumps({"model":a.model,"case_forwards":x["encoder_calls"],
                          "head_trainable_params":4161,"private_data_uploaded":False,
                          "production_permitted":False},sort_keys=True))
    elif a.command=="audit":
        x=audit(a.model,a.panel,a.fit,a.directory,a.receipt,a.stage,a.out)
        print(json.dumps({"model":a.model,"head_replayed_steps":x["head_replayed_steps"],
                          "head_replay_max_error":x["head_replay_parameter_max_abs_error"],
                          "production_permitted":False},sort_keys=True))
    else:
        x=observe(a.model,a.panel,a.fit,a.original_fit,a.original_blind,a.original_owner,
                  a.directory,a.audit,a.out)
        print(json.dumps({"model":a.model,"held_test_count":x["test"]["cases"],
                          "held_test_accuracy":x["test"]["accuracy"],
                          "held_test_brier":x["test"]["brier"],
                          "production_permitted":False},sort_keys=True))

if __name__=="__main__":main()
