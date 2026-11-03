"""Independent original-artifact cross-domain Cell Split adjudication.

Read-only research gate: original pretrained ModernBERT/BANKING77 and
DINOv2/Beans evidence. Not a new model forward, a stochastic FBSDE,
an independent publisher signature or production model selection.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from math import comb
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

ORIGINALS = {
    "modern_trial": (12083091720, "8bd2d2ba3b2de9f2fe1b99042b471c016d78f90c8305d7d82c91bf1a23138bed", "trial.json"),
    "modern_targets": (12080419743, "140191b7915923b51a447c9cabc43d6dbba96060ae4dee90716f1fd2539821fb", "targets.json"),
    "modern_review": (12083375095, "fcc4ed2e27c612ad6c348722f3a3575cbbbb89700f7399f94403a5cde66700d0", "review.json"),
    "beans_review": (12093212961, "25017e776d9ae010513f6ce417e5b067b77b1d63edf9b1dffd7a2a0a905056ef", "independent-v9-summary.json"),
}
SCHEMA = "hepta.hdcf.original-crossdomain-evidence-v10"
MAX_BYTES = 200_000


class Denied(ValueError):
    pass


def need(condition: bool, why: str) -> None:
    if not condition:
        raise Denied(why)


def strict_json(raw: bytes):
    need(type(raw) is bytes and 0 < len(raw) < MAX_BYTES, "invalid JSON size")
    def unique(pairs):
        out = {}
        for k, v in pairs:
            need(k not in out, "duplicate JSON key")
            out[k] = v
        return out
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(Denied("nonfinite JSON")))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise Denied("invalid JSON") from exc


def read_original(path: str | Path, kind: str) -> dict:
    need(kind in ORIGINALS, "unknown original archive")
    _id, sha256, filename = ORIGINALS[kind]
    path = Path(path)
    need(not path.is_symlink() and path.is_file() and
         stat.S_ISREG(path.stat().st_mode) and path.stat().st_size <= MAX_BYTES,
         "unsupported archive file")
    with path.open("rb") as f:
        need(hashlib.file_digest(f, "sha256").hexdigest() == sha256,
             "different original Actions ZIP bytes")
    try:
        with ZipFile(path) as z:
            infos = z.infolist()
            need(len(infos) == 1 and infos[0].filename == filename and
                 infos[0].file_size < MAX_BYTES and
                 (infos[0].external_attr >> 16) & 0o170000 != 0o120000,
                 "unsafe/incomplete original ZIP")
            data = z.read(filename)
    except (OSError, KeyError, ValueError) as exc:
        raise Denied("invalid original ZIP") from exc
    obj = strict_json(data)
    need(type(obj) is dict, "original JSON not an object")
    return obj


def _digest(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(b"hepta.hdcf.frozen-feature.v1\0" + raw).hexdigest()


def _exact_pair(a: int, b: int) -> float:
    need(type(a) is type(b) is int and a >= 0 and b >= 0 and a + b <= 4096,
         "wrong paired outcome")
    n = a + b
    return min(1.0, (2 * sum(comb(n, k) for k in range(min(a, b)+1))) / (2 ** n)) if n else 1.0


def _score_modern(trial: dict, targets: dict, review: dict) -> dict:
    need(trial.get("schema") == "hepta.hdcf.actual-head-trial.v1" and
         targets.get("schema") == "hepta.hdcf.banking77-blind-targets.v1" and
         review.get("schema") == "hepta.hdcf.original-pretrained-head-review.v1" and
         targets.get("source_revision") == "57ec275d8078af65b7731c2a98be812d844a6d6b" and
         review.get("source_code_sha") == targets.get("original_code_sha") ==
         "758205d3de23ccbf76649b1446c271101dc917b0" and
         review.get("observed_encoder_forward_calls") == 96 and
         review.get("model_snapshot_sha256") == "43138a5545ce4e7996d91735f2330519a8913304d3abf257f6cfdfbe0541283d" and
         trial.get("encoder_forward_count") == 0 and
         trial.get("head_params_per_arm") == 1538,
         "wrong original ModernBERT identity/cost profile")
    for source in (trial, review, review.get("paired_science_gate", {}), review.get("score", {})):
        need(source.get("production_authorized") is False, "production authority claimed")
    need(review.get("pretrained_publisher_signature_independently_verified") is False and
         review.get("end_to_end_tco_verified") is False and
         review.get("paired_science_gate", {}).get("disposition") == "HOLD_NO_GO",
         "unqualified ModernBERT claim")
    need(trial.get("trial_identity") == review.get("score", {}).get("trial_identity") ==
         review.get("paired_science_gate", {}).get("trial_identity") and
         review.get("real_feature_receipt_digest") is not None,
         "trial lineage changed")
    labels = targets.get("targets")
    need(type(labels) is list and len(labels) == 32, "original held census changed")
    mapping = {}
    for r in labels:
        need(type(r) is dict and set(r) == {"id","family","type","target"} and
             type(r["target"]) is int and r["target"] in (0,1) and
             r["id"] not in mapping and r["family"] == "BANKING77-test-original",
             "ambiguous held labels")
        mapping[r["id"]] = r
    target_doc = {"schema":"hepta.hdcf.blind-targets.v1",
                  "bundle_digest":trial["bundle_digest"],"targets":labels}
    need(_digest(target_doc) == review["score"]["target_digest"],
         "labels differ from sealed modern reviewer")
    names = {"frozen", "shared_dense", "shared_one_touch", "split", "swapped"}
    need(set(trial.get("arms", {})) == names and set(trial.get("predictions", {})) == names and
         set(review["score"]["results"]) == names, "incomplete original arms")
    hits: dict[str, dict] = {}
    for arm in names:
        rows = trial["predictions"][arm]
        need(type(rows) is list and len(rows) == 32, "incomplete predictions")
        found = {}
        brier = 0.0
        for row in rows:
            need(type(row) is dict and set(row) == {"id", "family", "type", "p1"},
                 "invalid prediction row")
            key = row["id"]
            p = row["p1"]
            need(key in mapping and key not in found and
                 (row["family"], row["type"]) ==
                 (mapping[key]["family"], mapping[key]["type"]) and
                 type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1,
                 "cross-arm/source mismatch")
            y = mapping[key]["target"]
            found[key] = (p >= .5) == bool(y)
            brier += (p-y)**2
        need(len(found) == 32, "partial prediction")
        official = review["score"]["results"][arm]
        need(sum(found.values()) == official["correct"] and
             math.isclose(brier/32, official["brier"], abs_tol=2e-14) and
             official["n"] == 32, "historical blind score not replayed")
        hits[arm] = found
    trained = ("shared_dense","shared_one_touch","split")
    need(all(trial["arms"][arm]["actual_sgd_steps"] == 256 for arm in trained) and
         trial["arms"]["shared_one_touch"]["estimated_parameter_touches"] ==
         trial["arms"]["split"]["estimated_parameter_touches"] == 196864 and
         trial["arms"]["frozen"]["actual_sgd_steps"] == 0 and
         trial["arms"]["swapped"]["actual_sgd_steps"] == 0,
         "unmatched work profile")
    split, shared = hits["split"], hits["shared_one_touch"]
    wins = sum(split[k] and not shared[k] for k in split)
    losses = sum(not split[k] and shared[k] for k in split)
    return {"modality":"text", "task":"BANKING77 four-intent-to-binary retrospective",
            "original_cases":32, "shared_correct":sum(shared.values()),
            "split_correct":sum(split.values()), "split_only_correct":wins,
            "shared_only_correct":losses, "nominal_case_level_p":_exact_pair(wins, losses),
            "head_train_updates_per_trained_arm":256,
            "equal_touch_work_per_arm":196864,
            "split_cost_benefit_qualified":False}


def _score_beans(b: dict) -> dict:
    need(b.get("schema") == "hepta.hdcf.original-beans-dino-v9-readout.v1" and
         b.get("source_run_id") == 38680856403 and
         b.get("model_revision") == "150c8e7bb7cef2d30ec31b13a517af14840ee3f7" and
         b.get("model") == "facebook/dinov2-small" and
         b.get("binary_task") == "healthy_vs_diseased_binary_reanalysis" and
         b.get("genuine_original_train_cases") == 36 and
         b.get("genuine_original_held_cases") == 24 and
         b.get("binary_original_visual_prototype_correct") == 21 and
         b.get("original_publisher_train_test_sha_verified") is True and
         b.get("source_original_images_sha_verified") is True and
         b.get("new_dino_image_forwards") == 0 and
         b.get("original_dino_image_forwards_reported") == 60,
         "original DINO study not authenticated by its source reviewer")
    for flag in ("production_authorized","model_selected","source_independent_issuers",
                 "publisher_origin_signature_verified","total_service_cost_attested",
                 "independent_future_NDU_utility"):
        need(b.get(flag) is False, "unsupported DINO authority/source claim")
    need(b.get("disposition") == "HOLD_NO_GO_DENY_ALL", "no-go removed")
    arms = b["head_arms"]
    need(set(arms) == {"frozen","shared_dense","shared_one_touch","split","swapped"},
         "incomplete Beans arms")
    counts = {k: v["correct"] for k, v in arms.items()}
    need(counts == {"frozen":11,"shared_dense":16,"shared_one_touch":16,
                    "split":16,"swapped":16}, "original Beans scores changed")
    pair = b["matched_split_vs_shared_one_touch"]
    need(pair["split_only_correct"] == pair["shared_only_correct"] == 0 and
         pair["both_correct"] == 16 and pair["both_incorrect"] == 8 and
         pair["source_independent"] is False and
         pair["efficacy_certified"] is False and
         pair["nominal_two_sided_exact_mcnemar"] == 1.,
         "original Beans matched paired result changed")
    works = b["paid_head_work"]
    need(works["split"] == works["shared_one_touch"] ==
         {"estimated_parameter_touches":98560,"steps":256} and
         works["frozen"]["steps"] == 0 and works["swapped"]["steps"] == 0,
         "unmatched Beans training cost")
    for arm in arms.values():
        need(arm["wins_vs_pretrained_vision_prototype"] +
             arm["losses_vs_pretrained_vision_prototype"] <= 24,
             "invalid visual reference pairing")
    against = arms["split"]
    need((against["wins_vs_pretrained_vision_prototype"],
          against["losses_vs_pretrained_vision_prototype"]) == (3,8),
         "lost strong visual baseline")
    return {"modality":"image","task":"Beans healthy-vs-diseased binary retrospective",
            "original_cases":24,"shared_correct":16,"split_correct":16,
            "split_only_correct":0,"shared_only_correct":0,
            "nominal_case_level_p":1.0,
            "strong_frozen_visual_correct":21,
            "split_only_vs_visual":3, "visual_only_vs_split":8,
            "nominal_vs_visual_p":_exact_pair(3,8),
            "head_train_updates_per_trained_arm":256,
            "equal_touch_work_per_arm":98560,
            "split_cost_benefit_qualified":False}


def audit_documents(documents: dict[str,dict]) -> dict:
    need(type(documents) is dict and set(documents) == set(ORIGINALS),
         "missing independently sealed source")
    text = _score_modern(documents["modern_trial"],documents["modern_targets"],
                         documents["modern_review"])
    image = _score_beans(documents["beans_review"])
    # These two publisher families are not a statistically meaningful number
    # of independently sampled future task sources: prohibit pooled p-values.
    return {"schema":SCHEMA,"original_artifact_sha256":{k:v[1] for k,v in ORIGINALS.items()},
            "panels":[text,image], "independent_source_family_count_certified":0,
            "source_families_distinct_descriptively":2,
            "joint_pooled_significance_test_performed":False,
            "complete_lifecycle_tco_attested":False,
            "time_disjoint_future_cohorts_verified":False,
            "real_audio_video_encoder_evidence":False,
            "physical_4096_cell_model_selection_authorized":False,
            "cell_split_promoted":False,
            "production_authorized":False,
            "disposition":"HOLD_NO_GO_DENY_ALL"}


def audit_paths(paths: dict[str, str]) -> dict:
    need(set(paths) == set(ORIGINALS), "missing pinned original artifact")
    return audit_documents({k:read_original(v,k) for k,v in paths.items()})


def download_original(kind: str, out: str, token: str) -> None:
    """Authenticated GitHub API -> unauthenticated HTTPS signed CDN redirect."""
    need(kind in ORIGINALS and type(token) is str and len(token) >= 16,
         "unauthorized original evidence download")
    artifact_id, expected_sha, _ = ORIGINALS[kind]
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = build_opener(NoRedirect())
    url = "https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/" + str(artifact_id) + "/zip"
    try:
        opener.open(Request(url, headers={"Authorization":"Bearer " + token,
                     "Accept":"application/vnd.github+json",
                     "X-GitHub-Api-Version":"2022-11-28",
                     "User-Agent":"hepta-v10-independent-audit"}),timeout=45)
    except HTTPError as e:
        need(e.code in (301,302,303,307,308) and e.headers.get("Location"),
             "no signed download redirect")
        location=e.headers["Location"]
    else:
        raise Denied("unexpected direct artifact payload")
    parsed=urlsplit(location)
    need(parsed.scheme == "https" and parsed.hostname not in ("api.github.com","github.com")
         and parsed.username is None and parsed.password is None and len(location)<8192,
         "untrusted archive redirect")
    dest=Path(out)
    fd=os.open(dest, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as sink, opener.open(Request(location,headers={
            "Accept":"application/zip", "User-Agent":"hepta-v10-independent-audit"}),timeout=90) as src:
            total=0
            digest=hashlib.sha256()
            while block:=src.read(65536):
                total+=len(block)
                need(total<=MAX_BYTES,"oversized original artifact")
                sink.write(block)
                digest.update(block)
            sink.flush();os.fsync(sink.fileno())
        need(total>0 and digest.hexdigest()==expected_sha,"wrong original ZIP checksum")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def main() -> None:
    parser=argparse.ArgumentParser(description="HDCF original-source crossdomain V10 HOLD gate")
    sub=parser.add_subparsers(dest="command",required=True)
    dl=sub.add_parser("download")
    dl.add_argument("--kind",choices=sorted(ORIGINALS),required=True)
    dl.add_argument("--out",required=True)
    audit=sub.add_parser("audit")
    for kind in ORIGINALS:
        audit.add_argument("--"+kind.replace("_","-"),required=True)
    audit.add_argument("--out",required=True)
    args=parser.parse_args()
    if args.command=="download":
        download_original(args.kind,args.out,os.environ.get("GH_TOKEN",""))
        return
    paths={kind:getattr(args,kind) for kind in ORIGINALS}
    result=audit_paths(paths)
    fd=os.open(args.out, os.O_WRONLY|os.O_CREAT|os.O_EXCL|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"w",encoding="ascii") as out:
        out.write(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
        out.flush();os.fsync(out.fileno())
    print("CROSSDOMAIN_V10_ORIGINAL_EVIDENCE_HOLD_NO_GO_DENY_ALL")


if __name__=="__main__":
    main()
