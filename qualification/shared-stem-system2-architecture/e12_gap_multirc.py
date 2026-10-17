"""Label-blind, original-pretrained MultiRC -> E12 global action-gap control.

Exact historical model logits, NOT new Encoder inference. The action-gap
utility is the synthetic E12 law, NOT an identified MultiRC task utility.
Do not load any score/label member or human validation material in this module.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
from math import exp, isfinite
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from e12_action_gap import evaluate_actions, make_actions
from e12_action_gap_study import canonical, write_once

ARCHIVE_SHA = "1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17"
OBS_SHA = "c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840"
OBS_ID = "7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5"
SLATE = "a109a0d75f7e1fa523460d00125daddb7ae394f3f8126c01b6f65b9736abda57"
PANEL = "d25c3fd649572189a87bb7c9507195bb4de319ad1d9d0d652bdd1d476e88fc62"
MEMBER = "multirc-native-candidate-audit/audit.json"
SEAL = "multirc-native-candidate-audit/COMMITTED.json"
ARMS = ("conditioned", "mean_pool_query_fused", "no_evidence", "no_query")
SCHEMA = "hepta.e12.action-gap-original-multirc.v1"
MAX_MAPS = 32


def no_duplicate(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = val
    return result


def parse_json(data: bytes) -> dict:
    if type(data) is not bytes or not 0 < len(data) <= 2_000_000:
        raise ValueError("oversized/empty original member")
    result = json.loads(data, object_pairs_hook=no_duplicate,
                        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    if type(result) is not dict:
        raise ValueError("not a JSON object")
    return result


def read_original(archive: str) -> dict:
    """Open only two allowlisted unlabeled members of a SHA-frozen ZIP."""
    path = Path(archive)
    if (path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size < 4_000_000
            or sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA):
        raise ValueError("missing or incorrect historical real-model ZIP")
    with ZipFile(path) as z:
        files = z.infolist()
        names = [f.filename for f in files]
        if (not 2 <= len(files) <= 60 or len(set(names)) != len(names)
                or MEMBER not in names or SEAL not in names
                or sum(f.file_size for f in files) > 4_000_000
                or any(f.is_dir() or PurePosixPath(f.filename).is_absolute()
                       or ".." in PurePosixPath(f.filename).parts
                       or f.file_size > 2_000_000 or f.compress_size > 2_000_000
                       or ((f.external_attr >> 16) & 0o170000) == 0o120000
                       for f in files)):
            raise ValueError("unsafe historical ZIP inventory")
        raw = z.read(MEMBER)
        seal = parse_json(z.read(SEAL))
    if sha256(raw).hexdigest() != OBS_SHA:
        raise ValueError("original model predictions altered")
    if (seal.get("observation_sha256") != OBS_SHA or seal.get("observation_id") != OBS_ID
            or seal.get("labels_loaded") is not False or seal.get("production_authorized") is not False
            or seal.get("schema") != "hepta.multirc.genuine-answer-slate-seal.v1"):
        raise ValueError("original label-blind source seal invalid")
    obs = parse_json(raw)
    if (obs.get("schema") != "hepta.multirc.genuine-answer-slate-frozen-readers.v1"
            or obs.get("observation_id") != OBS_ID or obs.get("slate_id") != SLATE
            or obs.get("source_panel_id") != PANEL or obs.get("evaluation_labels_loaded") is not False
            or obs.get("production_authorized") is not False or obs.get("actual_candidate_count") != 33
            or obs.get("passage_count") != 4 or obs.get("question_count") != 8
            or obs.get("actual_reader_calls") != 132 or obs.get("shared_evidence_encoder_calls") != 4
            or obs.get("actual_question_encoder_calls") != 33):
        raise ValueError("original model/source scope mismatch")
    semantic = sha256(json.dumps({k: v for k, v in obs.items() if k != "observation_id"},
                                 sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if semantic != OBS_ID:
        raise ValueError("original model semantic observation digest invalid")
    rows, preds = obs.get("rows"), obs.get("predictions")
    required = {"source_group", "question_slot", "task_id", "candidate_id", "original_v1_candidate"}
    if (type(rows) is not list or len(rows) != 33 or type(preds) is not dict
            or set(preds) != set(ARMS) or any(type(p) is not list or len(p) != 33 for p in preds.values())
            or len({r.get("task_id") for r in rows}) != 33
            or len({r.get("source_group") for r in rows}) != 4
            or len({(r.get("source_group"), r.get("question_slot")) for r in rows}) != 8):
        raise ValueError("incomplete source family / candidate panel")
    for row in rows:
        if (type(row) is not dict or set(row) != required
                or type(row["task_id"]) is not str or len(row["task_id"]) != 32
                or type(row["source_group"]) is not str or len(row["source_group"]) != 32
                or type(row["question_slot"]) is not int or row["question_slot"] not in (0, 1)
                or type(row["candidate_id"]) is not int or not 0 <= row["candidate_id"] <= 10**9
                or type(row["original_v1_candidate"]) is not bool):
            raise ValueError("invalid genuine answer source record")
    for arm, predictions in preds.items():
        weights = set()
        for record, row in zip(predictions, rows):
            if (type(record) is not dict
                    or set(record) != {"source_group", "question_slot", "task_id", "logits", "weights_sha256"}
                    or any(record[k] != row[k] for k in ("source_group", "question_slot", "task_id"))
                    or type(record["weights_sha256"]) is not str or len(record["weights_sha256"]) != 64
                    or type(record["logits"]) is not list or len(record["logits"]) != 2
                    or any(type(x) not in (float, int) or not isfinite(x) for x in record["logits"])):
                raise ValueError("forged reader model logit/candidate")
            weights.add(record["weights_sha256"])
        if len(weights) != 1:
            raise ValueError("per-row reader weights swapped")
    return obs


def positive(logits: list[float]) -> float:
    z = logits[1] - logits[0]
    return 1 / (1 + exp(-z)) if z >= 0 else exp(z) / (1 + exp(z))


def x0_from_conditional(p: float) -> str:
    if type(p) is not float or not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("untrusted original posterior")
    return str(Q(round((2 * p - 1) * 1024), 1024))


def mapped_to_reader(action: str | None) -> str | None:
    if action == "direct":
        return "conditioned"
    if action == "coupled":
        return "mean_pool_query_fused"
    if action in (None, "stop", "hold"):
        return None  # abstain; never fabricate a correct answer
    raise ValueError("unregistered legal routing action")


def fixed_confidence(p: float) -> str:
    return "mean_pool_query_fused" if abs(Q(str(p)) - Q(1, 2)) <= Q(1, 8) else "conditioned"


def plan() -> dict:
    return {"schema": SCHEMA, "model_zip_sha256": ARCHIVE_SHA,
            "observation_sha256": OBS_SHA, "input": "historical_original_pretrained_logits",
            "task_family": "human_MultiRC_4_passages_8_questions_33_answers",
            "reader_controls": list(ARMS), "actions": ["direct", "coupled", "stop"],
            "mapping": {"direct": "conditioned", "coupled": "mean_pool_query_fused", "stop": "abstain"},
            "x0": "round_ties_even((2*p_conditioned-1)*1024)/1024",
            "depth": 3, "initial": "zero", "max_maps": MAX_MAPS,
            "penalty": "1/512 synthetic E12 coupled only; NOT measured reader cost",
            "fixed_confidence_cut": "1/8", "cost_comparison": "separate historic/full-service unknown",
            "training": "no new trained parameters", "authority": "DENY_ALL"}


def propose(archive: str, output: str) -> str:
    source = read_original(archive)
    rows = []
    for i, original in enumerate(source["rows"]):
        pmap = {arm: positive(source["predictions"][arm][i]["logits"]) for arm in ARMS}
        x0 = x0_from_conditional(pmap["conditioned"])
        outcome = evaluate_actions(make_actions(x0, 3), max_maps=MAX_MAPS)
        rows.append({**original, "p": pmap, "x0": x0, "outcome": asdict(outcome),
                     "policies": {
                         "conditioned": "conditioned",
                         "mean_pool_query_fused": "mean_pool_query_fused",
                         "no_evidence": "no_evidence",
                         "no_query": "no_query",
                         "fixed_confidence": fixed_confidence(pmap["conditioned"]),
                         "cheap_one_map": mapped_to_reader(outcome.cheap_one_map),
                         "certified_action_gap": mapped_to_reader(outcome.selected),
                     }})
    return write_once(output, {"schema": SCHEMA + ".blind", "plan": plan(),
                               "archive_sha256": ARCHIVE_SHA,
                               "observation_id": OBS_ID, "slate_id": SLATE,
                               "source_prediction_sha256": OBS_SHA,
                               "rows": rows, "original_labels_opened": False,
                               "model_calls_new": 0, "model_outputs_are_historical": True,
                               "E12_utility_is_real_task_identified": False,
                               "natural_task_gain_established": False,
                               "online_cost_advantage_verified": False,
                               "production_accepted": False, "authority": "DENY_ALL"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print(json.dumps({"sha256": propose(args.archive, args.output), "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
