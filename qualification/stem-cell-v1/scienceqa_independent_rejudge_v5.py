"""Independent source-first rejudgment of an archived physical Granite97/DINO ScienceQA panel.

The original model's frozen predictions are reopened from its SHA-pinned Actions
archive. A NEW process reacquires the original SHA-pinned publisher dataset,
reselects 96/32/64 cases without seeing labels, reconstructs the original
source+label SHA-256, then recomputes EVERY heldout metric. No model/trainer
code is imported, no labels/media/features are published or promoted.

Independent *software* validation from the same publisher is not an independent
human quality evaluator, prospective cohort, or visual-necessity certification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import zipfile

DATASET = "lmms-lab/ScienceQA-IMG"
REVISION = "b9984af01798586705cee1fbdfa80a6dcbef04f1"
SOURCE_SHA = "a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202"
FIT_SHA = "e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e"
HELD_SHA = "b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3"
PRED_SHA = "e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7"
ARCHIVE_SHA = "f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30"
SOURCE_SPLITS = {"train": 96, "validation": 32, "test": 64}
ARMS = (
    "text_only", "unaligned_equal_fusion", "rotated_equal_fusion",
    "bridge_image_only", "bridge_equal_fusion", "train_gate",
    "calibrated_fusion", "image_masked",
)
MEMBERS = frozenset((
    "independent-descriptive-review.json", "SHA256SUMS", "offline-tests.txt",
    "optimized-tests.txt", "physical-completed-or-absent.json",
    "physical-gate-optimized-tests.txt", "physical-gate-contract-tests.txt",
    "predictions-before-labels.sha256", "sealed-source-bound-predictions.json",
    "source-blobs-SHA256", "source-head.txt", "source-seals.json",
    "source-tree.txt", "versions.txt",
))

class V5Error(ValueError):
    pass

def need(condition, reason):
    if not condition:
        raise V5Error(reason)

def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()

def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()

def pairs_no_dup(pairs):
    out = {}
    for key, val in pairs:
        need(key not in out, "duplicate JSON field")
        out[key] = val
    return out

def parse(blob: bytes):
    try:
        obj = json.loads(blob, object_pairs_hook=pairs_no_dup,
                         parse_constant=lambda _: (_ for _ in ()).throw(V5Error("nonfinite JSON constant")))
        canonical(obj)  # rejects float 1e999
    except (UnicodeError, json.JSONDecodeError, OverflowError, TypeError, ValueError) as error:
        raise V5Error("invalid original JSON") from error
    need(type(obj) is dict, "not a JSON object")
    return obj

def read_archive(path: Path):
    need(path.is_file() and not path.is_symlink() and
         0 < path.stat().st_size <= 1_000_000, "unsafe or oversized archive")
    blob = path.read_bytes()
    need(sha(blob) == ARCHIVE_SHA, "original physical archive SHA mismatch")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = archive.infolist()
        names = [x.filename for x in members]
        need(set(names) == MEMBERS and len(names) == len(MEMBERS), "archive member inventory changed")
        need(sum(x.file_size for x in members) <= 1_000_000, "archive decompression budget")
        for info in members:
            need(0 < info.file_size <= 256_000 and info.compress_size <= 1_000_000 and
                 not stat.S_ISLNK(info.external_attr >> 16) and
                 "/" not in info.filename and "\\" not in info.filename,
                 "unsafe archive member")
        raw = {name: archive.read(name) for name in names}
    recorded = {}
    for line in raw["SHA256SUMS"].decode("ascii").splitlines():
        parts = line.split(None, 1)
        need(len(parts) == 2 and len(parts[0]) == 64, "bad original SHA list")
        name = parts[1].removeprefix("*").removeprefix("./")
        need(name not in recorded, "duplicate original SHA list")
        recorded[name] = parts[0]
    need(set(recorded) == MEMBERS - {"SHA256SUMS"}, "incomplete original SHA list")
    for filename, expected in recorded.items():
        need(sha(raw[filename]) == expected, "altered archived source file")
    return raw


def image_record(image):
    from PIL import Image
    need(type(image) is dict and type(image.get("bytes")) is bytes,
         "original image bytes required")
    raw = image["bytes"]
    need(0 < len(raw) <= 8 * 1024 * 1024, "original image byte limit")
    with Image.open(io.BytesIO(raw)) as im:
        need(im.format in ("JPEG", "PNG") and im.width * im.height <= 4_194_304
             and getattr(im, "n_frames", 1) == 1, "unsupported original image")
        im.load()
        rgb = im.convert("RGB")
        group = sha(canonical([list(rgb.size), "RGB"]) + rgb.tobytes())
    return raw, group


def public_record(row):
    need(type(row) is dict and set(row) == {"question", "hint", "choices", "image"},
         "unexpected source columns")
    q, hint, choices = row["question"], row["hint"], row["choices"]
    if (type(q) is not str or not 1 <= len(q.encode()) <= 4096 or
        type(hint) is not str or len(hint.encode()) > 2048 or
        type(choices) is not list or len(choices) != 4 or
        any(type(c) is not str or not 1 <= len(c.encode()) <= 1024 for c in choices)):
        return None
    blob, group = image_record(row["image"])
    return {"question": q, "hint": hint, "choices": choices}, blob, group


def select_original(public, sizes=SOURCE_SPLITS):
    need(type(public) is dict and set(public) == set(SOURCE_SPLITS) and
         type(sizes) is dict and set(sizes) == set(SOURCE_SPLITS), "wrong split inventory")
    used_images, used_text = set(), set()
    selected = {}
    for split in SOURCE_SPLITS:
        options = []
        for index, row in enumerate(public[split]):
            observed = public_record(row)
            if observed is None:
                continue
            fields, blob, group = observed
            text_hash = sha(canonical([fields["question"], fields["hint"], fields["choices"]]))
            token = sha(canonical(["e3-granite-dino-v1", split, index, group, text_hash]))
            options.append((token, index, fields, blob, group, text_hash))
        chosen = []
        for token, index, fields, blob, group, text_hash in sorted(options):
            if group in used_images or text_hash in used_text:
                continue
            used_images.add(group)
            used_text.add(text_hash)
            chosen.append((token, index, fields, blob, group))
            if len(chosen) == sizes[split]:
                break
        need(len(chosen) == sizes[split], "insufficient publisher source cases")
        selected[split] = chosen
    return selected


def sealed_source(selected, original_answers, *, sizes=SOURCE_SPLITS):
    cases, fit, held = [], [], []
    used_images = set()
    for split in SOURCE_SPLITS:
        need(len(selected[split]) == sizes[split], "split size changed")
        for token, index, fields, blob, group in selected[split]:
            image_hash = sha(blob)
            case_id = sha(canonical([REVISION, split, index, token, image_hash]))
            case = {"id":case_id, "group":group, "split":split,
                    "image":image_hash, "scope":"public-scienceqa-e3-research", **fields}
            cases.append(case)
            used_images.add(image_hash)
            label = original_answers(split, index)
            need(type(label) is int and 0 <= label < 4, "noncanonical publisher answer")
            record = {"id":case_id, "group":group, "split":split, "label":label}
            (held if split == "test" else fit).append(record)
    return {"cases":cases, "fit":fit, "held":held, "images":len(used_images),
            "source_sha256":sha(b"".join(canonical(v) for v in cases)),
            "fit_sha256":sha(b"".join(canonical(v) for v in fit)),
            "held_sha256":sha(b"".join(canonical(v) for v in held))}


def exact_mcnemar(harm, rescue):
    need(type(harm) is int and type(rescue) is int and 0 <= harm+rescue <= 64,
         "invalid paired outcome count")
    n = harm+rescue
    return min(1.0, 2*sum(math.comb(n, i) for i in range(min(harm,rescue)+1))/2**n) if n else 1.0


def score_original(archive, source_seal, *, strict_full=True):
    need(source_seal["source_sha256"] == SOURCE_SHA and
         source_seal["fit_sha256"] == FIT_SHA and
         source_seal["held_sha256"] == HELD_SHA and
         source_seal["images"] == 192, "publisher source/label reconstruction mismatch")
    original = parse(archive["source-seals.json"])
    pred = parse(archive["sealed-source-bound-predictions.json"])
    old_review = parse(archive["independent-descriptive-review.json"])
    witness = parse(archive["physical-completed-or-absent.json"])
    need(sha(archive["sealed-source-bound-predictions.json"]) == PRED_SHA and
         original["source_sha256"] == SOURCE_SHA and
         original["fit_labels_sha256"] == FIT_SHA and
         original["private_test_labels_sha256"] == HELD_SHA and
         witness["completed_original_pretrained_stage_and_scoring"] is True and
         witness["authority"] == "DENY_ALL" and
         pred["held_labels_visible_to_inference"] is False and
         pred["production_accepted"] is False and
         old_review["authority"] == "DENY_ALL", "unreviewed original archive")
    need(type(pred.get("arms")) is list and pred["arms"] == list(ARMS), "different archived model arms")
    labels = {v["id"]:v["label"] for v in source_seal["held"]}
    sources = {v["id"]:v for v in source_seal["cases"] if v["split"]=="test"}
    need(len(labels)==len(sources)==64 and len(set(v["group"] for v in sources.values()))==64,
         "unmatched independent heldout cohort")
    rows = pred.get("predictions")
    need(type(rows) is list and len(rows)==64, "incomplete archived prediction inventory")
    by_id={}; scores={name:{"correct":0,"nll":[],"brier":[],"right":{}} for name in ARMS}
    for row in rows:
        need(type(row) is dict and set(row)=={"id","group","split","source_input_sha256","arms"},
             "malformed original prediction row")
        rid = row["id"]
        need(rid in sources and rid not in by_id and row["split"]=="test" and
             row["group"]==sources[rid]["group"] and
             row["source_input_sha256"]==sha(canonical(sources[rid])),
             "original prediction altered source identity")
        by_id[rid]=row
        need(type(row["arms"]) is dict and set(row["arms"])==set(ARMS),
             "missing paired multimodal arm")
        need(row["arms"]["image_masked"]==row["arms"]["text_only"],
             "image mask changed text control")
        y=labels[rid]
        for arm in ARMS:
            probs=row["arms"][arm]
            need(type(probs) is list and len(probs)==4 and
                 all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1 for v in probs) and
                 abs(math.fsum(probs)-1)<1e-6, "original probabilities noncanonical")
            guess=max(range(4),key=lambda j:(probs[j],-j))
            score=scores[arm]
            correct=int(guess==y)
            score["correct"]+=correct
            score["right"][rid]=correct
            score["nll"].append(-math.log(max(probs[y], 1e-12)))
            score["brier"].append(math.fsum((p-int(k==y))**2 for k,p in enumerate(probs))/4)
    need(set(by_id)==set(labels),"prediction/label coverage mismatch")
    reports={}
    for arm,record in scores.items():
        current={"cases":64,"correct":record["correct"],"accuracy":record["correct"]/64,
                 "nll":math.fsum(record["nll"])/64,
                 "brier_4class_mean":math.fsum(record["brier"])/64}
        prior=old_review["arms"][arm]
        need(current["correct"]==prior["correct"] and all(
            abs(current[k]-prior[k]) <= 1e-10 for k in ("accuracy","nll","brier_4class_mean")),
            "publisher-label original published score cannot be reproduced: "+arm)
        reports[arm]=current
    compare={}
    baseline=scores["text_only"]["right"]
    for arm in ARMS:
        if arm in ("text_only","image_masked"):continue
        candidate=scores[arm]["right"]
        harm=sum(baseline[rid] and not candidate[rid] for rid in baseline)
        rescue=sum(not baseline[rid] and candidate[rid] for rid in baseline)
        expected=old_review["paired_vs_text_only"][arm]
        p=exact_mcnemar(harm,rescue)
        need(harm==expected["new_errors_vs_text"] and rescue==expected["rescued_errors_vs_text"] and
             abs(expected["mcnemar_unadjusted_exact_p"]-p)<1e-12,
             "publisher-label paired score mismatch: "+arm)
        compare[arm]={"new_errors":harm,"rescued_errors":rescue,"exact_p":p,
                       "six_test_bonferroni_p":min(1.,6*p)}
    return {"schema":"hepta.stem.scienceqa-independent-publisher-rejudgment.v5",
            "source_sha256":SOURCE_SHA,"fit_labels_sha256":FIT_SHA,
            "heldout_labels_sha256":HELD_SHA,"sealed_original_prediction_sha256":PRED_SHA,
            "archive_sha256":ARCHIVE_SHA,"cases":64,"arms":reports,"paired":compare,
            "publisher_source_reacquired_and_rehashed":True,
            "heldout_labels_independently_reconstructed":True,
            "independent_human_visual_necessity_adjudication":False,
            "independent_model_source_signature_verified":False,
            "old_future_window_test_established":False,
            "whole_lifecycle_cost_comparison_established":False,
            "trained_new_cell_in_v5":False,
            "new_pretrained_forward_in_v5":False,
            "multimodal_generation_established":False,
            "production_authorized":False,"stem_winner":None,"authority":"DENY_ALL"}


def acquire_publisher():
    """Fetch only the exact publisher Parquet bytes; no data scripts or model code."""
    from datasets import Image, load_dataset
    from huggingface_hub import HfApi, hf_hub_download
    info=HfApi().dataset_info(DATASET, revision=REVISION, files_metadata=True)
    need(info.sha==REVISION,"upstream ScienceQA dataset revision drift")
    inventory={x.rfilename:x for x in info.siblings if x.rfilename.endswith('.parquet')}
    need(3<=len(inventory)<=12 and sum((x.size or 0) for x in inventory.values())<=1024**3,
         "publisher dataset inventory drift")
    names={split:sorted(x for x in inventory if Path(x).name.startswith(split+'-'))
           for split in SOURCE_SPLITS}
    need(all(len(v)==1 for v in names.values()) and
         set(sum(names.values(),[]))==set(inventory),"unknown publisher shards")
    data_files={}
    for split, (name,) in names.items():
        info_file=inventory[name]
        need(type(info_file.size) is int and 0 < info_file.size < 512*1024**2,
             "invalid source size")
        path=Path(hf_hub_download(repo_id=DATASET, filename=name,
                                  repo_type='dataset', revision=REVISION))
        need(path.is_file() and path.stat().st_size==info_file.size,"physical publisher material changed")
        with path.open('rb') as f:
            digest=hashlib.file_digest(f,'sha256').hexdigest()
        lfs=getattr(info_file,'lfs',None)
        recorded=getattr(lfs,'sha256',None) if lfs else None
        if recorded is not None:
            need(digest==recorded,"publisher LFS SHA-256 drift")
        data_files[split]=str(path)
    data=load_dataset('parquet',data_files=data_files)
    public={split:data[split].select_columns(['question','hint','choices','image']).cast_column('image',Image(decode=False))
            for split in SOURCE_SPLITS}
    def answer(split, idx):
        return int(data[split][idx]['answer'])
    return public,answer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    archive=read_archive(args.archive)
    public,labels=acquire_publisher()
    selected=select_original(public)
    source=sealed_source(selected,labels)
    result=score_original(archive,source)
    need(not args.output.exists() and not args.output.is_symlink(),"create-only result required")
    with args.output.open('xb') as f:
        f.write(canonical(result))
        f.flush();os.fsync(f.fileno())
    print('V5 publisher-source rejudgment PASS: historical only, DENY_ALL')

if __name__=='__main__':
    main()
