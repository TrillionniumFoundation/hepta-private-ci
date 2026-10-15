"""E3 historical ScienceQA five-arm source-bound composer and independent scorer.

The original Granite/DINO experiment is re-used by SHA, never overwritten.
OCR and native multimodal arms must have their own genuine physical receipts.
Historical public test labels are read only in score mode, never compose mode.
This DOES NOT attest weights, visual necessity, chronological futures or NDU.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from math import comb, fsum

ARMS = ("text_only", "ocr_text", "unaligned_vision",
        "aligned_bridge", "native_multimodal")
BASE_MAP = {"text_only": "text_only",
            "unaligned_vision": "unaligned_equal_fusion",
            "aligned_bridge": "train_gate"}
ORIGINAL = "hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions"
OCR = "hepta.e3.ocr-granite-physical.v1"
NATIVE = "hepta.e3.native-gemma2-physical.v1"
FIVE = "hepta.e3.historical-five-arm-source-predictions.v1"
SCORE = "hepta.e3.historical-five-arm-score.v1"
GRANITE = ("ibm-granite/granite-embedding-97m-multilingual-r2",
           "835ad14087e140460703cf0fae09f97d469d65c2")
GEMMA = ("google/embeddinggemma-2",
         "914f7f89142e33e77833254d9c9b90c3cef7303b")
MAX_BYTES = 4 * 1024 * 1024

class FiveArmError(ValueError):
    pass

def demand(ok, reason):
    if not ok:
        raise FiveArmError(reason)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def hex64(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

def no_dupes(pairs):
    o = {}
    for key, value in pairs:
        demand(key not in o, "duplicate JSON key")
        o[key] = value
    return o

def loads(raw):
    def no_constant(x):
        raise FiveArmError("nonfinite JSON token " + x)
    obj = json.loads(raw, object_pairs_hook=no_dupes, parse_constant=no_constant)
    def finite(x):
        if type(x) is float: demand(math.isfinite(x), "invalid float")
        if type(x) is dict:
            for v in x.values(): finite(v)
        if type(x) is list:
            for v in x: finite(v)
    finite(obj)
    demand(type(obj) is dict, "document object required")
    return obj

def pinned(path, expected):
    demand(hex64(expected), "invalid expected SHA-256")
    path = Path(path)
    demand(path.is_file() and not path.is_symlink() and
           0 < path.stat().st_size <= MAX_BYTES, "unsafe input")
    raw = path.read_bytes()
    demand(digest(raw) == expected, "input SHA-256 drift")
    return loads(raw), raw

def probs(values):
    demand(type(values) is list and len(values) == 4, "four probabilities required")
    demand(all(type(x) in (int, float) and math.isfinite(x)
               and 0 <= x <= 1 for x in values), "nonfinite/out-of-range probability")
    demand(abs(fsum(values) - 1) <= 1e-4, "probability normalization")
    return values

def physical(doc, schema, model, counter):
    demand(doc.get("schema") == schema, "missing original physical schema")
    demand(doc.get("authority") == "DENY_ALL" and
           doc.get("production_accepted") is False and
           doc.get("stem_selected") is False and
           doc.get("signed_model_origin_authenticated") is False,
           "missing strict nonauthorizing flags")
    actual = doc.get("model")
    demand(type(actual) is dict and
           (actual.get("repo"), actual.get("revision")) == model and
           hex64(actual.get("pipeline_digest")), "unpinned physical Encoder identity")
    demand(type(doc.get(counter)) is int and doc[counter] > 0,
           "missing original physical model execution count")
    rows = doc.get("rows")
    demand(type(rows) is list and len(rows) == 64, "incomplete physical TEST panel")
    found = {}
    for row in rows:
        demand(type(row) is dict and
               set(row) == {"id", "group", "source_input_sha256", "probabilities"},
               "target-bearing or unsupported prediction schema")
        rid = row["id"]
        demand(hex64(rid) and hex64(row["group"]) and
               hex64(row["source_input_sha256"]) and rid not in found,
               "unbound/duplicate physical source")
        probs(row["probabilities"])
        found[rid] = row
    return found

def compose(original, ocr, native, *, original_sha, ocr_sha, native_sha):
    demand(original.get("schema") == ORIGINAL and
           original.get("production_accepted") is False and
           original.get("held_labels_visible_to_inference") is False and
           original.get("independent_ground_truth_observer") is False,
           "original pretrained research receipt missing/noncanonical")
    stem = original.get("stem_model", {})
    demand(type(stem) is dict and
           (stem.get("repo"), stem.get("revision")) == GRANITE and
           hex64(stem.get("sha256")), "unpinned original Granite")
    vision = original.get("vision_model", {})
    demand(type(vision) is dict and
           vision.get("repo") == "facebook/dinov2-small" and
           vision.get("revision") == "ed25f3a31f01632728cabb09d1542f84ab7b0056" and
           hex64(vision.get("sha256")), "unpinned original DINO")
    fit = original.get("fit", {})
    demand(fit.get("private_cell_head_parameters") == 769 and
           fit.get("cell_optimizer_updates") == 80 and
           fit.get("train_cases") == 96 and
           fit.get("calibration_cases") == 32 and
           fit.get("holdout_cases") == 64, "original learned Head not qualified")
    for k in ("physical_text_forward_batches", "physical_vision_forward_batches"):
        demand(type(original.get(k)) is int and original[k] > 0,
               "missing actual original-model forwards")
    source_sha = original.get("source_sha256")
    demand(hex64(source_sha) and
           ocr.get("source_sha256") == source_sha and
           native.get("source_sha256") == source_sha,
           "not the exact shared ScienceQA source set")
    ocr_rows = physical(ocr, OCR, GRANITE, "physical_granite_forward_batches")
    native_rows = physical(native, NATIVE, GEMMA, "physical_joint_encode_batches")
    demand(ocr.get("ocr_engine") == "tesseract" and
           type(ocr.get("physical_ocr_calls")) is int and
           ocr["physical_ocr_calls"] == 192,
           "no real OCR of complete shared source")
    demand(native.get("native_joint_text_image") is True and
           native.get("audio_tower_loaded") is False and
           native.get("train_only_private_head_parameters") == 769 and
           native.get("train_only_head_updates") == 80 and
           native.get("future_labels_visible") is False and
           type(native.get("source_token_preflight_rows")) is int and
           native["source_token_preflight_rows"] == 1344 and
           type(native.get("max_conservative_context_tokens")) is int and
           1 <= native["max_conservative_context_tokens"] <= 8192 and
           native.get("native_context_limit") == 8192 and
           native.get("max_image_soft_tokens_charged") == 1120 and
           native.get("text_tokenizer_truncation_disabled") is True and
           native.get("image_tokens_physically_verified") is False,
           "native multimodal evaluation/Head training not qualified")
    refs = original.get("predictions")
    demand(type(refs) is list and len(refs) == 64, "original paired heldout missing")
    result, ids = [], set()
    for x in refs:
        demand(type(x) is dict and
               set(x) == {"id", "group", "split", "source_input_sha256", "arms"} and
               x["split"] == "test", "unexpected original TEST row")
        rid = x["id"]
        demand(hex64(rid) and rid not in ids and
               rid in ocr_rows and rid in native_rows, "not a complete 64-case join")
        ids.add(rid)
        arm = x["arms"]
        demand(type(arm) is dict and all(a in arm for a in BASE_MAP.values()),
               "original required control missing")
        for side in (ocr_rows[rid], native_rows[rid]):
            demand(side["group"] == x["group"] and
                   side["source_input_sha256"] == x["source_input_sha256"],
                   "source/group/case mismatch across physical arms")
        value = {k: probs(arm[v]) for k, v in BASE_MAP.items()}
        value["ocr_text"] = ocr_rows[rid]["probabilities"]
        value["native_multimodal"] = native_rows[rid]["probabilities"]
        demand(set(value) == set(ARMS), "five physical arms required")
        result.append({"id": rid, "group": x["group"],
                       "source_input_sha256": x["source_input_sha256"],
                       "arms": value})
    demand(set(ocr_rows) == ids and set(native_rows) == ids,
           "partial/surplus source inventory")
    return {"schema": FIVE, "source_sha256": source_sha,
            "original_pretrained_prediction_sha256": original_sha,
            "ocr_pretrained_prediction_sha256": ocr_sha,
            "native_pretrained_prediction_sha256": native_sha,
            "cohort": "historical_scienceqa_test_not_future", "cases": result,
            "human_visual_necessity_adjudicated": False,
            "original_model_origin_independently_signed": False,
            "stem_winner": None, "production_accepted": False, "authority": "DENY_ALL"}

def exact_p(rescued, harmed):
    n = rescued + harmed
    return min(1.0, 2 * sum(comb(n, j) for j in range(min(rescued, harmed) + 1)) / (2 ** n)) if n else 1.0

def score(combined, held):
    demand(combined.get("schema") == FIVE and
           combined.get("authority") == "DENY_ALL" and
           combined.get("production_accepted") is False and
           combined.get("human_visual_necessity_adjudicated") is False and
           combined.get("stem_winner") is None, "unreviewed model-selection claim")
    cases = combined.get("cases")
    demand(type(cases) is list and len(cases) == 64 and
           combined.get("cohort") == "historical_scienceqa_test_not_future",
           "false future or missing historical TEST inventory")
    demand(type(held) is list and len(held) == 64, "original label count")
    truth = {}
    for x in held:
        demand(type(x) is dict and
               set(x) == {"id", "group", "split", "label"} and
               x["split"] == "test" and hex64(x["id"]) and
               hex64(x["group"]) and x["id"] not in truth and
               type(x["label"]) is int and 0 <= x["label"] < 4,
               "invalid source-separated original test label")
        truth[x["id"]] = (x["group"], x["label"])
    observed, acc, brier, saved = set(), {a:0 for a in ARMS}, {a:[] for a in ARMS}, {a:[] for a in ARMS}
    for row in cases:
        demand(type(row) is dict and
               set(row) == {"id", "group", "source_input_sha256", "arms"} and
               row["id"] in truth and row["id"] not in observed and
               truth[row["id"]][0] == row["group"] and
               hex64(row["source_input_sha256"]), "changed label-group or duplicate")
        observed.add(row["id"])
        pred = row["arms"]
        demand(type(pred) is dict and set(pred) == set(ARMS), "missing physical arm")
        y = truth[row["id"]][1]
        for a in ARMS:
            v = probs(pred[a])
            guess = max(range(4), key=lambda j: (v[j], -j))
            flag = int(guess == y)
            saved[a].append(flag)
            acc[a] += flag
            brier[a].append(fsum((v[j] - int(j == y))**2 for j in range(4))/4)
    demand(observed == set(truth), "label/prediction source difference")
    controls = {}
    ref = saved["text_only"]
    for arm in ARMS[1:]:
        vals = saved[arm]
        saved_cases = sum(a==0 and b==1 for a,b in zip(ref,vals))
        harmed = sum(a==1 and b==0 for a,b in zip(ref,vals))
        controls[arm] = {"rescued":saved_cases, "harmed":harmed,
                         "discordant":saved_cases+harmed,
                         "exact_two_sided_mcnemar_p":exact_p(saved_cases,harmed)}
    # Holm step-down adjustment across four paired exploratory tests.
    ordered = sorted(controls, key=lambda a: controls[a]["exact_two_sided_mcnemar_p"])
    highest = 0.0
    for ix, arm in enumerate(ordered):
        raw = controls[arm]["exact_two_sided_mcnemar_p"]
        highest = max(highest, min(1.0, (len(ordered)-ix)*raw))
        controls[arm]["holm_adjusted_p"] = highest
    return {"schema": SCORE, "source_sha256": combined["source_sha256"],
            "historical_test_cases":64, "accuracy":{a:acc[a]/64 for a in ARMS},
            "correct":acc, "brier_mean":{a:fsum(brier[a])/64 for a in ARMS},
            "paired_vs_text_only":controls, "independent_original_label_attestation":False,
            "real_future_windows_available":False,
            "visual_necessity_adjudicated":False, "cost_matched":False,
            "stem_winner":None, "production_accepted":False,"authority":"DENY_ALL"}

def write_new(path, value):
    path=Path(path)
    demand(not path.exists() and not path.is_symlink(), "cannot overwrite evidence")
    raw=(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
    with path.open("xb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    return digest(raw)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest="command",required=True)
    a=sub.add_parser("compose")
    for n in ("original","original_sha","ocr","ocr_sha","native","native_sha"):
        a.add_argument("--"+n.replace("_","-"),required=True)
    a.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("score")
    for n in ("combined","combined_sha","held","held_sha"):
        p.add_argument("--"+n.replace("_","-"),required=True)
    p.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    if args.command=="compose":
        orig,_=pinned(args.original,args.original_sha)
        ocr,_=pinned(args.ocr,args.ocr_sha)
        native,_=pinned(args.native,args.native_sha)
        result=compose(orig,ocr,native,original_sha=args.original_sha,
                       ocr_sha=args.ocr_sha,native_sha=args.native_sha)
    else:
        combined,_=pinned(args.combined,args.combined_sha)
        path=Path(args.held)
        demand(not path.is_symlink() and path.is_file() and
               0<path.stat().st_size<=MAX_BYTES, "held labels unavailable")
        raw=path.read_bytes()
        demand(hex64(args.held_sha) and digest(raw)==args.held_sha,
               "original held-label seal drift")
        rows=[]
        for line in raw.splitlines():
            demand(0 < len(line) <= 2048, "invalid label-line")
            rows.append(loads(line))
        result=score(combined,rows)
    seal=write_new(args.output,result)
    print(json.dumps({"output_sha256":seal,"record":args.command,
                      "authority":"DENY_ALL","stem_winner":None},sort_keys=True))

if __name__=="__main__":
    main()
