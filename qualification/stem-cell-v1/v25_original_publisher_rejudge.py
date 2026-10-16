#!/usr/bin/env python3
"""V25: read-only original-publisher-label rejudgment of frozen E3 ScienceQA.

No train, no new Encoder inference and no positive production authority. The
original-publisher file bytes must agree with the historical *pre-existing*
source and test-label SHA256 seals before any score is disclosed. The original
public dataset is historical, not a new independently sampled future cohort.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import v24_multimodal_causal_bounds as v24

SCHEMA = "hepta.stem.v25.original-publisher-historical-rejudge.v1"
PUB = "lmms-lab/ScienceQA-IMG"
PUB_REVISION = "b9984af01798586705cee1fbdfa80a6dcbef04f1"
STAGER_SHA = "3ca8f55ed6b7143729258e4a1e53693614460950"
CONTRACT_SHA = "bd6d95ff957c3855b71a8778d7c13f61ff4d6a7a"
SIZES = {"train": 96, "validation": 32, "test": 64}
SRC_KEYS = frozenset({"id", "group", "split", "image", "question", "hint", "choices", "scope"})
LABEL_KEYS = frozenset({"id", "group", "split", "label"})


class Invalid(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical(d: Any) -> bytes:
    return (json.dumps(d, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def disallow_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def parse_strict(data: bytes) -> Any:
    def bad_constant(_: str) -> None:
        raise Invalid("invalid nonfinite JSON")
    try:
        obj = json.loads(data, object_pairs_hook=disallow_duplicates, parse_constant=bad_constant)
        canonical(obj)
        return obj
    except (UnicodeDecodeError, OverflowError, ValueError, TypeError) as exc:
        raise Invalid("noncanonical/invalid JSON") from exc


def pinned_file(path: Path, expected_sha: str, limit: int) -> bytes:
    require(v24.h64(expected_sha), "invalid pinned SHA")
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
            "missing, symlinked or oversized immutable material")
    raw = path.read_bytes()
    require(sha(raw) == expected_sha, "original source/held-label seal mismatch")
    return raw


def strict_lines(payload: bytes, minimum: int, maximum: int) -> list[dict]:
    require(payload.endswith(b"\n"), "JSONL must end in newline")
    lines = payload.splitlines(keepends=True)
    require(minimum <= len(lines) <= maximum, "staged source/label count changed")
    output = []
    for line in lines:
        record = parse_strict(line)
        require(type(record) is dict and line == canonical(record), "original canonical JSONL bytes changed")
        output.append(record)
    return output


def source_identity(sources: list[dict], labels: list[dict], *, sealed_pred: dict) -> dict[str, int]:
    """One-to-one join with 192 source-only rows and 64 original TEST labels."""
    require(type(sources) is list and len(sources) == sum(SIZES.values()), "incomplete source inventory")
    require(type(labels) is list and len(labels) == SIZES["test"], "incomplete original publisher test labels")
    counts = {s: 0 for s in SIZES}
    inventory = {}
    for row in sources:
        require(type(row) is dict and set(row) == SRC_KEYS, "source fields unauthorized/missing")
        for field in ("id", "group", "image"):
            require(v24.h64(row[field]), "source identity invalid")
        require(row["id"] not in inventory and row["split"] in SIZES and
                row["scope"] == "public-scienceqa-e3-research", "duplicate/mismatched source scope")
        require(type(row["question"]) is str and type(row["hint"]) is str and
                type(row["choices"]) is list and len(row["choices"]) == 4 and
                all(type(x) is str for x in row["choices"]), "invalid original source structure")
        counts[row["split"]] += 1
        inventory[row["id"]] = row
    require(counts == SIZES, "original source split drift")
    held = {k: row for k, row in inventory.items() if row["split"] == "test"}
    seen = set()
    label_map = {}
    for row in labels:
        require(type(row) is dict and set(row) == LABEL_KEYS and
                v24.h64(row["id"]) and v24.h64(row["group"]) and
                row["split"] == "test" and type(row["label"]) is int and
                0 <= row["label"] <= 3, "invalid original test label")
        ident = row["id"]
        require(ident not in seen and ident in held and held[ident]["group"] == row["group"],
                "label not joined to the original SOURCE CASE")
        seen.add(ident)
        label_map[ident] = row["label"]
    require(seen == set(held), "partial original heldout label coverage")
    require(type(sealed_pred.get("predictions")) is list and len(sealed_pred["predictions"]) == 64,
            "prediction roster changed")
    pred_ids = set()
    for case in sealed_pred["predictions"]:
        key = case.get("id")
        require(key not in pred_ids and key in held and
                case.get("group") == held[key]["group"] and
                case.get("split") == "test" and
                case.get("source_input_sha256") == sha(canonical(held[key])),
                "original prediction is not bound to original public source")
        pred_ids.add(key)
    require(pred_ids == seen, "partial predictions/labels")
    return label_map


def exact_mcnemar(rescues: int, harms: int) -> float:
    return v24.exact_p(rescues, harms)


def evaluate_original(pred: dict, review: dict, targets: dict[str,int]) -> dict:
    """Independently compute every probability metric and paired outcome.

    This function never imports the original producer, trainer, source stager,
    original evaluator or any model tensors; labels enter only after identity
    and SHA checks in caller.  Do not reuse exposed historical labels to tune.
    """
    require(len(targets) == 64 and all(type(y) is int and 0 <= y < 4 for y in targets.values()),
            "missing/forged original target")
    cases = pred["predictions"]
    require(len(cases) == 64 and {r["id"] for r in cases} == set(targets), "source identity drift")
    ordered = sorted(cases, key=lambda row: row["id"])
    predicted = {arm: [] for arm in v24.ARMS}
    original_labels = []
    scored: dict[str,dict] = {}
    for item in ordered:
        original_labels.append(targets[item["id"]])
        for arm in v24.ARMS:
            vals = item["arms"][arm]
            require(type(vals) is list and len(vals) == 4, "invalid original prediction")
            for p in vals:
                require(type(p) in (float,int) and math.isfinite(p) and 0 <= p <= 1,
                        "invalid original probability")
            require(abs(math.fsum(vals)-1) <= 1e-6,"bad original probability normalization")
            predicted[arm].append(v24.top(tuple(vals)))
    base = [int(x==y) for x,y in zip(predicted["text_only"], original_labels)]
    for arm in sorted(v24.ARMS):
        guesses = predicted[arm]
        cur = [int(x==y) for x,y in zip(guesses,original_labels)]
        accuracy = sum(cur)
        brier = math.fsum(math.fsum((v-int(k==original_labels[i]))**2
                             for k,v in enumerate(item["arms"][arm]))/4
                         for i,item in enumerate(ordered))/64
        nll = math.fsum(-math.log(max(item["arms"][arm][original_labels[i]],1e-12))
                        for i,item in enumerate(ordered))/64
        original = review["arms"][arm]
        require(type(original) is dict and type(original.get("correct")) is int and
                accuracy == original["correct"] and
                abs(brier - original["brier_4class_mean"]) < 5e-13 and
                abs(nll - original["nll"]) < 5e-13,
                "original publisher labels disagree with original independent reviewer")
        rescue = sum(x==0 and y==1 for x,y in zip(base,cur))
        harm = sum(x==1 and y==0 for x,y in zip(base,cur))
        if arm in v24.PAIR_ARMS:
            pair = review["paired_vs_text_only"][arm]
            require(rescue == pair["rescued_errors_vs_text"] and harm == pair["new_errors_vs_text"] and
                    exact_mcnemar(rescue,harm) == pair["mcnemar_unadjusted_exact_p"],
                    "original publisher labels disagree with archived matched-pair counts")
        elif arm != "text_only":
            require(rescue == harm == 0 and guesses == predicted["text_only"],
                    "frozen original mask disagreement")
        scored[arm] = {"original_historical_correct":accuracy,"original_historical_nll":nll,
                      "original_historical_brier_4class":brier,
                      "paired_rescues_vs_text":rescue,"paired_harms_vs_text":harm,
                      "paired_exact_mcnemar_p":exact_mcnemar(rescue,harm)}
    # This exact policy was defined V24 before this V25 publisher-label opening.
    # Replay the archived scores only: NO image model is run in this method.
    if v24.PRIMARY_THRESHOLD != 0.005:
        raise Invalid("unexpected frozen previous-study threshold")
    lazy = []
    planned_calls = 0
    for item in ordered:
        txt = item["arms"]["text_only"]
        image = item["arms"]["bridge_image_only"]
        use_image = sorted(txt,reverse=True)[0]-sorted(txt,reverse=True)[1] < v24.PRIMARY_THRESHOLD
        planned_calls += int(use_image)
        lazy.append(image if use_image else txt)
    lazy_correct = [int(v24.top(tuple(p))==y) for p,y in zip(lazy,original_labels)]
    lazy_rescues=sum(x==0 and y==1 for x,y in zip(base,lazy_correct))
    lazy_harms=sum(x==1 and y==0 for x,y in zip(base,lazy_correct))
    lazy_changed=sum(v24.top(tuple(p))!=guess for p,guess in zip(lazy,predicted["text_only"]))
    require(planned_calls == 21 and lazy_changed == 19,"old frozen V24 planned route changed")
    lazy_brier=math.fsum(math.fsum((p-int(k==original_labels[i]))**2 for k,p in enumerate(vals))/4
                         for i,vals in enumerate(lazy))/64
    lazy_nll=math.fsum(-math.log(max(vals[original_labels[i]],1e-12)) for i,vals in enumerate(lazy))/64
    return {"all_original_arms": scored,
            "precommitted_v24_label_blind_route": {
                "threshold":v24.PRIMARY_THRESHOLD,"conditional_image_calls_planned":planned_calls,
                "changed_top1_vs_text":lazy_changed,
                "historical_correct":sum(lazy_correct),
                "historical_accuracy":sum(lazy_correct)/64,
                "historical_rescues_vs_text":lazy_rescues,
                "historical_harms_vs_text":lazy_harms,
                "historical_exact_mcnemar_p":exact_mcnemar(lazy_rescues,lazy_harms),
                "historical_brier_4class":lazy_brier,
                "historical_nll":lazy_nll,
                "actual_conditional_encoder_forward_count":None,
                "actual_conditional_service_latency_ms":None,
                "actual_conditional_cpu_or_energy_cost":None,
                "archived_vision_features_were_computed_for_all_64":True
            }}


def verify_staged(seals: dict, source_path: Path, label_path: Path, stage_seal_path: Path,
                  pred: dict, review: dict) -> dict:
    require(type(seals) is dict and type(review) is dict and type(pred) is dict,
            "invalid original archive")
    source_digest = v24.SOURCE_SHA256
    label_digest = seals.get("private_test_labels_sha256")
    require(v24.h64(label_digest) and label_digest == review.get("holdout_targets_sha256"),
            "original withheld label digest missing")
    raw_sources = pinned_file(source_path,source_digest,32*1024*1024)
    raw_labels = pinned_file(label_path,label_digest,8*1024*1024)
    require(stage_seal_path.is_file() and not stage_seal_path.is_symlink() and
            0 < stage_seal_path.stat().st_size < 64*1024,"stage seal missing/oversized")
    stage_seal = parse_strict(stage_seal_path.read_bytes())
    require(type(stage_seal) is dict and stage_seal.get("dataset") == PUB and
            stage_seal.get("dataset_revision") == PUB_REVISION and
            stage_seal.get("source_sha256") == source_digest and
            stage_seal.get("private_test_labels_sha256") == label_digest and
            stage_seal.get("fit_labels_sha256") == seals.get("fit_labels_sha256") and
            stage_seal.get("cohort_sha256") == seals.get("cohort_sha256") and
            stage_seal.get("raw_image_count") == 192 and
            stage_seal.get("externally_independent_labels") is False and
            stage_seal.get("production_accepted") is False,
            "publisher stage seal differs from the historic E3 sealed cohort")
    sources = strict_lines(raw_sources,192,192)
    labels = strict_lines(raw_labels,64,64)
    target = source_identity(sources,labels,sealed_pred=pred)
    return evaluate_original(pred,review,target)


def base_receipt() -> dict:
    return {"schema":SCHEMA, "original_historical_archive_sha256":v24.ARCHIVE_SHA256,
            "original_publisher_dataset":PUB,"publisher_revision":PUB_REVISION,
            "original_source_sha256":v24.SOURCE_SHA256,
            "original_prediction_sha256":v24.PRED_SHA256,
            "original_stager_git_blob_sha":STAGER_SHA,"original_contract_git_blob_sha":CONTRACT_SHA,
            "original_source_custody_independent_from_upstream_release":False,
            "external_independent_human_visual_necessity_annotated":False,
            "source_is_historical_public_release_not_future":True,
            "original_model_recomputed_in_this_run":False,
            "new_encoder_forwards":0,"new_training_updates":0,
            "model_issuer_signature_verified":False,
            "future_independent_source_windows":0,"target_host_4096_cell_cost_qualified":False,
            "production_authorized":False,"stem_winner_verified":False,
            "scientific_promotion_authorized":False,"authority_posture":"DENY_ALL"}


def run(archive_path: Path, out: Path, source_path: Path|None=None,
        label_path: Path|None=None, stage_seal_path: Path|None=None) -> dict:
    pred,review,seals=v24.verify_archive(archive_path)
    v24.analyze(pred,review,seals)
    result=base_receipt()
    paths=[source_path,label_path,stage_seal_path]
    if all(p is None for p in paths):
        result.update({"decision":"HOLD_ORIGINAL_PUBLIC_SOURCE_AND_LABEL_BYTES_NOT_REOPENED",
                       "original_publisher_labels_independently_rescored":False,
                       "v24_conditional_route_historical_accuracy":None,
                       "score_from_aggregate_inference":False})
    else:
        require(all(isinstance(p,Path) for p in paths),"incomplete original source/label/seal triple")
        findings=verify_staged(seals,source_path,label_path,stage_seal_path,pred,review)
        result.update({"decision":"HISTORICAL_PUBLISHER_LABEL_RECOUNT_ONLY_NO_PROMOTION",
                       "original_publisher_labels_independently_rescored":True,
                       "source_file_sha256_original_matched":True,
                       "original_test_label_file_sha256_original_matched":True,
                       "score_from_aggregate_inference":False,**findings})
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("x",encoding="utf-8") as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n");f.flush();os.fsync(f.fileno())
    return result


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive",type=Path,required=True)
    ap.add_argument("--sources",type=Path)
    ap.add_argument("--labels",type=Path)
    ap.add_argument("--stage-seals",type=Path)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    out=run(args.archive,args.output,args.sources,args.labels,args.stage_seals)
    print(json.dumps({"decision":out["decision"],"original_publisher_labels_independently_rescored":
                      out["original_publisher_labels_independently_rescored"],
                      "production_authorized":False},sort_keys=True))


if __name__ == "__main__":
    main()
