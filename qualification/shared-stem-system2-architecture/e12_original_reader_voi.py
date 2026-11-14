"""Frozen original-pretrained Reader information/cost admission (research only).

The proposer receives three LABEL-FREE source members only. It cannot score
answers, train on future labels, choose thresholds after seeing truth, or issue
an FBSDE admission. This is retrospective archive replay, NOT fresh inference.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path

SCHEMA = "hepta.e12.original-reader-voi-prelabel.v1"
SOURCE_SHA = {
    "granite": "6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57",
    "mmbert": "d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac",
    "multirc": "c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840",
}
REVISIONS = {
    "granite97": "835ad14087e140460703cf0fae09f97d469d65c2",
    "mmbert_small": "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a",
}
POLICIES = ("stop", "uncertain_060", "uncertain_075", "always_mmbert")


def _no_duplicates(pairs):
    ret = {}
    for key, value in pairs:
        if key in ret:
            raise ValueError("duplicate JSON member")
        ret[key] = value
    return ret


def exact_json(data: bytes):
    if not (1 <= len(data) <= 200_000):
        raise ValueError("source size unsupported")
    return json.loads(data, object_pairs_hook=_no_duplicates,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def read_source(path, identity):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA[identity]:
        raise ValueError(f"original immutable {identity} source mismatch")
    return exact_json(raw)


def _p(v):
    if type(v) not in (float, int) or not math.isfinite(v) or not 0 < v < 1:
        raise ValueError("invalid physical prediction probability")
    return v


def _meter(v):
    if type(v) is not int or not 0 < v < 10**11:
        raise ValueError("invalid original per-request meter")
    return v


def physical(model, name):
    if (type(model) is not dict or model.get("model_id") != name or
        model.get("revision") != REVISIONS[name] or
        model.get("authority") != "DENY_ALL" or
        model.get("production_accepted") is not False or
        model.get("model_weights_executed_locally") is not True or
        model.get("actual_encoder_forward_count") != 352 or
        type(model.get("future_predictions")) is not list or
        len(model["future_predictions"]) != 192 or
        type(model.get("model_load_wall_ns")) is not int or
        model["model_load_wall_ns"] <= 0):
        raise ValueError("invalid original physical model manifest")
    mapping = {}
    test_ids = set()
    for row in model["future_predictions"]:
        if type(row) is not dict or set(row) != {
            "case_id", "encoder_forward_ns", "group_id", "head_ns",
            "input_tokens", "joint_input_digest", "probs", "split"
        } or row["split"] not in ("test", "new_holdout"):
            raise ValueError("wrong model row or split")
        ident = row["case_id"]
        if type(ident) is not str or len(ident) != 24 or ident in mapping or ident in test_ids:
            raise ValueError("missing or duplicate authentic case identity")
        if type(row["group_id"]) is not str or len(row["group_id"]) != 64 or type(row["joint_input_digest"]) is not str or len(row["joint_input_digest"]) != 64:
            raise ValueError("missing source or request digest")
        if type(row["input_tokens"]) is not int or not 0 < row["input_tokens"] <= 512:
            raise ValueError("unbounded token count")
        _meter(row["encoder_forward_ns"])
        if type(row["head_ns"]) is not dict or "learned_gate" not in row["head_ns"]:
            raise ValueError("missing physical head work")
        _meter(row["head_ns"]["learned_gate"])
        if type(row["probs"]) is not dict or "learned_gate" not in row["probs"]:
            raise ValueError("missing frozen Reader output")
        _p(row["probs"]["learned_gate"])
        if "label" in row or "correct" in row or "truth" in row:
            raise ValueError("held outcome is forbidden in prelabel source")
        if row["split"] == "test":
            test_ids.add(ident)
        else:
            mapping[ident] = row
    if len(mapping) != 128 or len(test_ids) != 64 or set(mapping) & test_ids:
        raise ValueError("incomplete out-of-sample model roster")
    return mapping


def multirc_blind(m):
    if (type(m) is not dict or m.get("schema") != "hepta.multirc.genuine-answer-slate-frozen-readers.v1" or
        m.get("evaluation_labels_loaded") is not False or
        m.get("production_authorized") is not False or
        m.get("actual_candidate_count") != 33 or m.get("question_count") != 8 or
        m.get("passage_count") != 4 or type(m.get("rows")) is not list or
        type(m.get("predictions")) is not dict):
        raise ValueError("wrong original unlabeled MultiRC experiment")
    candidates = m["rows"]
    signatures = [(v["task_id"], v["source_group"], v["question_slot"]) for v in candidates]
    if len(set(signatures)) != 33 or len({a[1] for a in signatures}) != 4 or len({(a[1],a[2]) for a in signatures}) != 8:
        raise ValueError("incomplete human-answer slate")
    spans = defaultdict(list)
    for arm in ("conditioned", "mean_pool_query_fused", "no_evidence", "no_query"):
        if type(m["predictions"].get(arm)) is not list or len(m["predictions"][arm]) != 33:
            raise ValueError("missing original control")
        for index, row in enumerate(m["predictions"][arm]):
            if (type(row) is not dict or row.get("task_id") != signatures[index][0] or
                row.get("source_group") != signatures[index][1] or
                row.get("question_slot") != signatures[index][2] or
                type(row.get("logits")) is not list or len(row["logits"]) != 2):
                raise ValueError("changed candidate, order or prediction")
            a, b = row["logits"]
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in (a,b)):
                raise ValueError("nonfinite physical logit")
            if arm == "conditioned":
                p = 1 / (1 + math.exp(max(-700, min(700, a-b))))
                spans[(row["source_group"], row["question_slot"])].append(p)
    widths = [max(p)-min(p) for p in spans.values()]
    if len(widths) != 8:
        raise ValueError("missing original complete question")
    return {"questions": 8, "answers": 33, "source_groups": 4,
            "max_conditioned_span": max(widths),
            "mean_conditioned_span": sum(widths)/len(widths),
            "questions_with_span_at_most_001": sum(x <= .001 for x in widths),
            "answer_sufficient_for_fbsde_admission": False,
            "answer_information_diagnostic_only": True}


def produce(granite_path, mmbert_path, multirc_path, output):
    g = read_source(granite_path, "granite")
    m = read_source(mmbert_path, "mmbert")
    multi = read_source(multirc_path, "multirc")
    gr, mr = physical(g, "granite97"), physical(m, "mmbert_small")
    if set(gr) != set(mr) or g["source_only_future_sha256"] != m["source_only_future_sha256"]:
        raise ValueError("paired models do not share the identical original source panel")
    bound = multirc_blind(multi)
    if bound["questions_with_span_at_most_001"] != 8:
        raise ValueError("registered original Reader adequacy diagnosis changed")
    rows = []
    for case_id in sorted(gr):
        a, b = gr[case_id], mr[case_id]
        if (a["group_id"],a["joint_input_digest"]) != (b["group_id"],b["joint_input_digest"]):
            raise ValueError("cross-model input mismatch")
        p = _p(a["probs"]["learned_gate"])
        secondary = _p(b["probs"]["learned_gate"])
        confidence = max(p, 1-p)
        arms = {}
        for arm in POLICIES:
            use = (arm == "always_mmbert" or
                   (arm == "uncertain_060" and confidence < .60) or
                   (arm == "uncertain_075" and confidence < .75))
            arms[arm] = {"model": "mmbert_small" if use else "granite97",
                         "probability": secondary if use else p,
                         "additional_encoder_calls": int(use),
                         "additional_observed_forward_ns": (
                             b["encoder_forward_ns"]+b["head_ns"]["learned_gate"] if use else 0)}
        rows.append({"case_id": case_id, "group_id": a["group_id"],
                     "joint_input_digest": a["joint_input_digest"],
                     "granite_prob": p, "mmbert_prob": secondary,
                     "base_observed_forward_ns": a["encoder_forward_ns"]+a["head_ns"]["learned_gate"],
                     "arms": arms})
    payload = {"schema": SCHEMA,"authority":"DENY_ALL","rows":rows,
               "source_sha256":SOURCE_SHA,"model_revisions":REVISIONS,
               "model_archived_outputs_not_fresh_calls":True,
               "multirc_prelabel":bound, "policies":list(POLICIES),
               "task_identified_fbsde_coefficients_present":False,
               "neural_continuation_real_task_gain_qualified":False,
               "system2_full_fbsde_admitted":False,
               "production_authorized":False}
    data=(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with open(output,'xb') as f:
        f.write(data)
        f.flush()
        import os
        os.fsync(f.fileno())
    return sha256(data).hexdigest()


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    for name in ("granite", "mmbert", "multirc", "output"):
        p.add_argument("--"+name, required=True)
    args=p.parse_args()
    print(json.dumps({"sha256":produce(args.granite,args.mmbert,args.multirc,args.output),
                      "authority":"DENY_ALL"}))
