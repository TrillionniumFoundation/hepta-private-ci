"""Research-only source-material challenge for frozen V16 Head candidates.

Unlike V18's hash-only contract, check complete signed source bytes and three
signer roles, reject future-dated evidence, physically replay both archived
Heads from saved safetensors on supplied features, and recompute Brier against
independently signed labels. Does NOT authenticate source publisher, actual
Encoder forward, execution host or future efficacy. Never authorizes a split.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import unicodedata
from zipfile import ZipFile

import numpy as np
from safetensors.numpy import load as load_tensors

import v18_future_source_intake as previous

SCHEMA = "hepta.v20.original-material-challenge.research"
MATERIAL = "hepta.v20.source-material.v1"
EXECUTION = "hepta.v20.frozen-execution.v1"
LABELS = "hepta.v20.independent-labels.v1"
MODEL_FORMAT = "mmbert-original-frozen-feature-384-fp32-unattested-encoder"
PROB_TOLERANCE = 3.0e-5
METRIC_TOLERANCE = 4.0e-5
MAX_PACKET_BYTES = 4_000_000
WIDTH = 384
CLASSES = 4
TESTED_SEED = 41
V16 = "hepta.stem.specialization.v16.research"
SAVED_MODEL_SHA = {
    "41-extra_continued": "c63392b3e9dc9f3895ca9a5b75b306f764f06b6e768403053897dbfdab3f043f",
    "41-joint": "4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e",
    "41-joint_gate": "ac7e3f111f09067e08187cdda213a0d5f38ec77802e16d9a616c784cbbc56fd7",
}
# This is source identity, not model-publisher or host attestation.
V15_NORMALIZER_SHA = "ce35cf92094aa1ed560654bb7bb80cb12d7dfd4e4f22723b043e2c3c243f5dbc"
V18_INTAKE_SOURCE_SHA = "e811d6300992ab2e604681bdc494bd2c67a71046e2667e154e0d4f33e759ed02"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def bounded_bytes(path, limit=MAX_PACKET_BYTES):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
            "regular bounded original evidence required")
    with path.open("rb") as f:
        raw = f.read(limit + 1)
    require(0 < len(raw) <= limit, "unbounded source evidence")
    return raw


def duplicate_reject(pairs):
    output = {}
    for key, value in pairs:
        require(key not in output, "duplicate JSON key")
        output[key] = value
    return output


def read(path):
    def reject_constant(s):
        raise ValueError("nonfinite JSON constant: " + s)
    obj = json.loads(bounded_bytes(path), object_pairs_hook=duplicate_reject,
                     parse_constant=reject_constant)
    canonical(obj)
    return obj


def text_key(text):
    require(type(text) is str and 1 <= len(text.encode("utf-8")) <= 4096,
            "bounded source text required")
    # Reject content aliases invisible to exact-byte hashing.
    key = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    require(key and len(key) <= 4096, "empty normalized source text")
    return digest(key.encode())


def source_root_id(kind, value):
    require(type(value) is str and 1 <= len(value.encode()) <= 256,
            "bounded actual source identity required")
    return digest(canonical(["v20", kind, value]))


def bound_case(case, root_sha, family_sha, window, observed, normalized_text_sha):
    return digest(canonical(["v20", "case", root_sha, family_sha, window,
                             observed, normalized_text_sha]))


def load_old_texts(archive):
    raw = bounded_bytes(archive, 3_000_000)
    require(digest(raw) == previous.ARCHIVE, "wrong original publisher-data archive")
    with ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and len(names) <= 128,
                "original archive member collision/oversize")
        data = z.read("hepta-public-study/dataset.jsonl")
    require(digest(data) ==
            "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c",
            "original corpus content changed")
    rows = [json.loads(row, object_pairs_hook=duplicate_reject) for row in data.splitlines()]
    require(len(rows) == 128, "original full text roster missing")
    return {text_key(row["text"]) for row in rows}


def strict_model_state(blob, shapes):
    state = load_tensors(blob)
    require(set(state) == set(shapes) and all(
        value.dtype == np.float32 and value.shape == shapes[key] and
        bool(np.isfinite(value).all()) for key, value in state.items()),
        "invalid saved original model tensors")
    return state


def physically_reload(saved_v15, saved_v16):
    """Recompute from the saved physical V16 model bytes, not signed logits."""
    saved_v15, saved_v16 = Path(saved_v15), Path(saved_v16)
    require(saved_v15.is_dir() and saved_v16.is_dir() and
            not saved_v15.is_symlink() and not saved_v16.is_symlink(),
            "original bounded checkpoint directories required")
    manifest = read(saved_v16 / "sealed.json")
    require(manifest.get("schema") == V16 and
            manifest.get("production_authorized") is False and
            manifest.get("prospective_efficacy_verified") is False and
            manifest.get("held_labels_read") is False and
            manifest.get("archive_sha256") == previous.ARCHIVE and
            type(manifest.get("model_files")) is dict,
            "unauthorized/incomplete original V16 model seal")
    expected = SAVED_MODEL_SHA
    for name, expected_sha in expected.items():
        require(manifest["model_files"][name]["sha256"] == expected_sha,
                "pinned original model identity changed")
    normalizer_raw = bounded_bytes(saved_v15 / "normalizer.safetensors")
    require(digest(normalizer_raw) == V15_NORMALIZER_SHA, "pinned V15 shared normalizer changed")
    normalizer = strict_model_state(normalizer_raw, {"mean": (WIDTH,)})
    model_raw = {}
    for name, expected_sha in expected.items():
        data = bounded_bytes(saved_v16 / (name + ".safetensors"))
        require(digest(data) == expected_sha, "original physical model changed")
        model_raw[name] = data
    linear = strict_model_state(model_raw["41-extra_continued"],
                                {"bias": (4,), "weight": (4, WIDTH)})
    split_shapes = {"centers": (2, WIDTH)}
    for k in (0, 1):
        split_shapes[f"heads.{k}.weight"] = (4, WIDTH)
        split_shapes[f"heads.{k}.bias"] = (4,)
    split = strict_model_state(model_raw["41-joint"], split_shapes)
    gate = strict_model_state(model_raw["41-joint_gate"],
                              {"weight": (1, WIDTH), "bias": (1,)})
    return normalizer["mean"], linear, split, gate, digest(normalizer_raw)


def physically_predict(features, mean, linear, split, gate):
    require(features.dtype == np.float32 and features.ndim == 2
            and features.shape[1] == WIDTH and bool(np.isfinite(features).all()),
            "finite original-width candidate features required")
    z = features - mean
    z = z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)
    baseline = z @ linear["weight"].T + linear["bias"]
    routes = ((z @ gate["weight"].T + gate["bias"]).reshape(-1) > 0).astype("int64")
    candidate = np.empty((len(z), CLASSES), dtype=np.float32)
    for k in (0, 1):
        ix = np.flatnonzero(routes == k)
        candidate[ix] = (z[ix] @ split[f"heads.{k}.weight"].T
                         + split[f"heads.{k}.bias"])
    def softmax(x):
        x = x.astype(np.float64)
        ex = np.exp(x - x.max(1, keepdims=True))
        return ex / ex.sum(1, keepdims=True)
    return softmax(baseline), softmax(candidate), routes


def time_utc(x):
    return previous.observed_time(x)


def verify(retrospective, signed_source, signed_outcome, signed_material,
           signed_execution, signed_labels, *, source_key, executor_key,
           evaluator_key, existing_roots, original_archive, v15, v16, now=None):
    require(digest(Path(previous.__file__).read_bytes()) == V18_INTAKE_SOURCE_SHA,
            "signed-source historical verifier source drift")
    # Tested injected 'now' is exclusively a deterministic test capability.
    # CLI uses the wall clock and offers no --now bypass.
    now = datetime.now(timezone.utc) if now is None else now
    require(isinstance(now, datetime) and now.tzinfo is not None,
            "UTC-aware independent audit clock required")
    now = now.astimezone(timezone.utc)
    require(source_key != executor_key and executor_key != evaluator_key and
            source_key != evaluator_key, "three independent signing roles required")
    source, source_sha = previous.verified_packet(signed_source, source_key)
    outcome, outcome_sha = previous.verified_packet(signed_outcome, evaluator_key)
    material, material_sha = previous.verified_packet(signed_material, source_key)
    executor, executor_sha = previous.verified_packet(signed_execution, executor_key)
    labels, labels_sha = previous.verified_packet(signed_labels, evaluator_key)
    original = previous.verify_signed(retrospective, signed_source, signed_outcome,
               trusted_source_key=source_key, trusted_evaluator_key=evaluator_key,
               existing_root_sha256=existing_roots)
    require(original["verdict"] == "SIGNATURES_AND_NUMERIC_CONTRACTS_CONSISTENT_NOT_AUTHORIZED",
            "V18 two-signer source contract rejected")
    require(type(material) is dict and set(material) ==
            {"schema","source_payload_sha256","sealed_at","model_input_format","rows"}
            and material["schema"] == MATERIAL and
            material["source_payload_sha256"] == source_sha and
            material["model_input_format"] == MODEL_FORMAT,
            "source bytes/material not bound to V18")
    require(type(executor) is dict and set(executor) ==
            {"schema","source_payload_sha256","material_payload_sha256","sealed_at",
             "model_weight_sha256","rows"}
            and executor["schema"] == EXECUTION and
            executor["source_payload_sha256"] == source_sha and
            executor["material_payload_sha256"] == material_sha and
            executor["model_weight_sha256"] == SAVED_MODEL_SHA,
            "frozen executable model or actual material mismatch")
    require(type(labels) is dict and set(labels) ==
            {"schema","source_payload_sha256","execution_payload_sha256","sealed_at","rows"}
            and labels["schema"] == LABELS and
            labels["source_payload_sha256"] == source_sha and
            labels["execution_payload_sha256"] == executor_sha,
            "independent-label seal not bound to predictions")
    times = [time_utc(material["sealed_at"]),
             time_utc(executor["sealed_at"]), time_utc(labels["sealed_at"])]
    require(times == sorted(times) and all(t <= now for t in times),
            "not-yet-observed or causally reversed source/score seals")
    source_rows = source["rows"]
    material_rows = material["rows"]
    execution_rows = executor["rows"]
    label_rows = labels["rows"]
    observed = {x["case_sha256"]: x for x in source_rows}
    require(type(material_rows) is list and type(execution_rows) is list and
            type(label_rows) is list and len(material_rows) == len(execution_rows) ==
            len(label_rows) == len(source_rows), "complete physically joined source required")
    old_texts = load_old_texts(original_archive)
    text_seen = set(); cases = set()
    material_features = []
    observed_by_window = {"future1": [], "future2": []}
    for row in material_rows:
        require(type(row) is dict and set(row) ==
                {"case_sha256","root_id","family_id","window","observed_at", "text", "feature"},
                "bounded raw original source material required")
        case = row["case_sha256"]
        require(type(case) is str and case in observed and case not in cases,
                "unknown, repeated or missing source case")
        cases.add(case)
        source_row = observed[case]
        # V18 historic exclusions are SHA256(raw original group/case ID), not
        # V20's domain-separated signed hashes. Reject the RAW alias too.
        require(digest(row["root_id"].encode()) not in existing_roots and
                digest(row["family_id"].encode()) not in existing_roots,
                "reused original source root/family despite new namespace")
        root = source_root_id("root", row["root_id"])
        family = source_root_id("family", row["family_id"])
        txt = text_key(row["text"])
        require(txt not in text_seen and txt not in old_texts,
                "original AGNews source text replay or aliased new material")
        text_seen.add(txt)
        require(row["window"] == source_row["window"] and
                row["observed_at"] == source_row["observed_at"] and
                root == source_row["root_sha256"] and
                family == source_row["family_sha256"] and
                case == bound_case(case, root, family, row["window"],row["observed_at"],txt),
                "source hash not derived from original source bytes")
        stamp = time_utc(row["observed_at"])
        require(previous.AFTER <= stamp <= times[0],
                "post-freeze source timestamp is in future or after source seal")
        observed_by_window[row["window"]].append(stamp)
        raw_feature = row["feature"]
        require(type(raw_feature) is list and len(raw_feature) == WIDTH and
                all(type(x) in (float,int) and math.isfinite(x) and abs(x) <= 1e6
                    for x in raw_feature),
                "bounded numeric source feature is required")
        feature = np.asarray(raw_feature, dtype=np.float32)
        require(bool(np.isfinite(feature).all()),"source feature float32 overflow")
        material_features.append(feature)
    require(cases == set(observed), "missing source originals")
    require(all(len(x) >= 100 for x in observed_by_window.values()) and
            max(observed_by_window["future1"]) < min(observed_by_window["future2"]),
            "future windows overlap or do not advance")
    mean, base, split, gate, norm_sha = physically_reload(v15,v16)
    baseline, candidate, routes = physically_predict(np.stack(material_features),
                                                       mean,base,split,gate)
    executions={}
    for row in execution_rows:
        require(type(row) is dict and set(row) ==
                {"case_sha256","baseline_probability","candidate_probability","hard_route"},
                "execution record must include actual model predictions")
        cid=row["case_sha256"]
        require(type(cid) is str and cid in cases and cid not in executions,
                "unknown or repeated original executed case")
        executions[cid]=row
    scores={}
    for row in label_rows:
        require(type(row) is dict and set(row) == {"case_sha256","label"}
                and type(row["case_sha256"]) is str and row["case_sha256"] in cases
                and row["case_sha256"] not in scores and
                type(row["label"]) is int and 0 <= row["label"] < CLASSES,
                "invalid independent label/case roster")
        scores[row["case_sha256"]] = row["label"]
    require(len(scores) == len(cases), "original label outcome incomplete")
    old_outcomes={x["case_sha256"]:x for x in outcome["rows"]}
    require(set(old_outcomes) == cases, "V18 losses contain unknown outcome")
    errors=[]; gains={"future1":[], "future2":[]}; forg={"future1":[], "future2":[]}
    for i, row in enumerate(material_rows):
        cid=row["case_sha256"]
        observed_row=executions[cid]
        for field, computed in (("baseline_probability",baseline[i]),
                                ("candidate_probability",candidate[i])):
            values=observed_row[field]
            require(type(values) is list and len(values) == CLASSES and
                    all(type(x) in (float,int) and math.isfinite(x) and 0 <= x <= 1
                        for x in values), "bounded physically recalculable class vector")
            delta=float(np.max(np.abs(np.asarray(values)-computed)))
            require(delta <= PROB_TOLERANCE, "fake original Head execution probability")
            errors.append(delta)
        require(type(observed_row["hard_route"]) is int and
                observed_row["hard_route"] == int(routes[i]),
                "physical selected expert route mismatch")
        label=scores[cid]
        truth=np.zeros(4);truth[label]=1
        b_loss=float(np.square(baseline[i]-truth).sum())
        c_loss=float(np.square(candidate[i]-truth).sum())
        pair=old_outcomes[cid]
        require(abs(pair["no_change_loss"]-b_loss) <= METRIC_TOLERANCE and
                abs(pair["candidate_loss"]-c_loss) <= METRIC_TOLERANCE,
                "signed evaluator loss not reproducible from actual prediction and label")
        gains[row["window"]].append(b_loss-c_loss)
        forg[row["window"]].append(pair["old_task_candidate_loss"]-
                                    pair["old_task_baseline_loss"])
    # Old-task loss fields and physical source's Encoder forward remain unverified.
    # Even valid three-role signatures can be issued by one controlling actor.
    return {"schema": SCHEMA, "decision": "SIGNED_MATERIAL_AND_ORIGINAL_MODEL_NUMERIC_REPLAY_ONLY",
            "source_payload_sha256":source_sha,"outcome_payload_sha256":outcome_sha,
            "material_payload_sha256":material_sha,"execution_payload_sha256":executor_sha,
            "evaluator_label_payload_sha256":labels_sha,
            "v15_normalizer_file_sha256":norm_sha,
            "original_model_weight_sha256":SAVED_MODEL_SHA,
            "replayed_original_source_rows":len(cases),
            "independent_future_windows_claimed":2,
            "max_replayed_probability_error":max(errors),
            "historical_AGNews_text_collision_rejected":True,
            "clock_future_data_rejected":True,
            "original_encoder_forward_authenticated":False,
            "actual_source_publisher_custody_authenticated":False,
            "actual_executor_custody_authenticated":False,
            "independent_family_trust_verified":False,
            "old_task_retention_independently_verified":False,
            "measured_complete_lifecycle_cost_verified":False,
            "future_utility_independently_qualified":False,
            "unqualified_descriptive_window_gain":{k:sum(v)/len(v) for k,v in gains.items()},
            "unqualified_signed_old_task_loss_drift":{k:sum(v)/len(v) for k,v in forg.items()},
            "scientific_promotion_authorized":False, "production_authorized":False,
            "model_selected":None,"authority_posture":"DENY_ALL"}


def hold(retrospective, *, clock=None):
    stamp=(datetime.now(timezone.utc) if clock is None else clock)
    require(digest(Path(previous.__file__).read_bytes()) == V18_INTAKE_SOURCE_SHA,
            "signed-source historical verifier source drift")
    base=previous.blocked(retrospective)
    require(base["verdict"] == "HOLD_MISSING_NEW_INDEPENDENT_WINDOWS", "false baseline")
    return {"schema": SCHEMA,
            "decision":"HOLD_NO_REAL_SIGNED_POST_FREEZE_MATERIAL",
            "required_first_source_date_utc":previous.AFTER.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "audit_utc":stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "new_signed_future_roots":0,"independent_future_windows":0,
            "actual_source_publisher_custody_authenticated":False,
            "frozen_no_change_model_replaced":False,
            "scientific_promotion_authorized":False,"production_authorized":False,
            "authority_posture":"DENY_ALL"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--retrospective",required=True)
    p.add_argument("--output",required=True)
    for name in ("source", "outcomes", "material", "execution", "labels",
                 "source_key","executor_key","evaluator_key","original_inputs",
                 "original_archive","v15","v16"):
        p.add_argument("--" + name.replace("_","-"))
    a=p.parse_args()
    retrospective=read(a.retrospective)
    optional=(a.source,a.outcomes,a.material,a.execution,a.labels,a.source_key,
              a.executor_key,a.evaluator_key,a.original_inputs,a.original_archive,a.v15,a.v16)
    require(all(optional) or not any(optional),
            "all signed external materials and original private snapshots required together")
    if all(optional):
        key=lambda x:bounded_bytes(x,200).decode().strip()
        result=verify(retrospective,read(a.source),read(a.outcomes),read(a.material),
                      read(a.execution),read(a.labels),source_key=key(a.source_key),
                      executor_key=key(a.executor_key), evaluator_key=key(a.evaluator_key),
                      existing_roots=previous.original_roots(a.original_inputs),
                      original_archive=a.original_archive,v15=a.v15,v16=a.v16)
    else:
        result=hold(retrospective)
    target=Path(a.output)
    require(target.parent.is_dir() and not target.parent.is_symlink() and not target.exists(),
            "create-only original result required")
    with target.open("xb") as f:
        f.write(canonical(result));f.flush()
    return result


if __name__=="__main__":main()
