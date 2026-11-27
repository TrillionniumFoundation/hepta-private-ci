"""E14 original pretrained MultiRC candidates -> label-blind fixed routing.

Uses ONE pinned historical GitHub Actions ZIP as original model inference.
Only an allowlisted PRE-LABEL model artifact is decompressed; owner labels and
historical score files are never opened here. All System 2 math is a *toy*
nonlinear finite FBSDE from E12, not a trained semantic/value model.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction as F
from hashlib import sha256
from math import exp, isfinite
import json
from pathlib import Path, PurePosixPath
from time import process_time_ns
from zipfile import ZipFile

from e12_nonlinear_cert import Law, operator, solve

ARCHIVE_SHA = "1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17"
OBS_SHA = "c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840"
OBS_ID = "7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5"
PANEL = "d25c3fd649572189a87bb7c9507195bb4de319ad1d9d0d652bdd1d476e88fc62"
SLATE = "a109a0d75f7e1fa523460d00125daddb7ae394f3f8126c01b6f65b9736abda57"
SCHEMA = "hepta.e14.original-human-multirc-labelblind-fbsde.v1"
ARMS = ("conditioned", "mean_pool_query_fused", "no_evidence", "no_query")
POLICIES = ARMS + ("fixed_confidence", "cheap_one_map", "e12_full_tree")
MEMBER = "multirc-native-candidate-audit/audit.json"
SEAL = "multirc-native-candidate-audit/COMMITTED.json"
CUT = F(9, 100)  # exploratory, fixed before viewing human candidate labels


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def strict_json(raw: bytes):
    if type(raw) is not bytes or not 0 < len(raw) <= 2_000_000:
        raise ValueError("missing or unbounded JSON bytes")
    return json.loads(raw, object_pairs_hook=reject_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_once(path: str, obj) -> str:
    data = canonical(obj)
    with Path(path).open("xb") as handle:
        handle.write(data)
    return sha256(data).hexdigest()


def read_prelabel(archive_path: str, *, required_sha: str = ARCHIVE_SHA) -> dict:
    """DO NOT z.read() the scored members or human-label material."""
    p = Path(archive_path)
    if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size < 4_000_000:
        raise ValueError("missing/unsafe original ZIP")
    if sha256(p.read_bytes()).hexdigest() != required_sha:
        raise ValueError("original archive not byte-pinned")
    with ZipFile(p) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if (not 2 <= len(infos) <= 60 or len(set(names)) != len(names)
                or MEMBER not in names or SEAL not in names or
                any(i.is_dir() or PurePosixPath(i.filename).is_absolute()
                    or ".." in PurePosixPath(i.filename).parts
                    or i.file_size > 2_000_000 or i.compress_size > 2_000_000
                    or ((i.external_attr >> 16) & 0o170000) == 0o120000
                    for i in infos)
                or sum(i.file_size for i in infos) > 4_000_000):
            raise ValueError("malformed ZIP inventory")
        # Crucial: historical scores are in this ZIP, but NOT decompressed or
        # passed to the prediction generator. Owner dataset is never loaded.
        obs_raw = z.read(MEMBER)
        seal = strict_json(z.read(SEAL))
    if (required_sha == ARCHIVE_SHA and sha256(obs_raw).hexdigest() != OBS_SHA):
        raise ValueError("historical model prediction bytes changed")
    if (type(seal) is not dict or seal.get("schema") != "hepta.multirc.genuine-answer-slate-seal.v1"
            or seal.get("labels_loaded") is not False
            or seal.get("production_authorized") is not False
            or seal.get("observation_sha256") != sha256(obs_raw).hexdigest()
            or seal.get("observation_id") != OBS_ID):
        raise ValueError("historical prelabel owner seal incomplete")
    obs = strict_json(obs_raw)
    if (type(obs) is not dict or obs.get("schema") != "hepta.multirc.genuine-answer-slate-frozen-readers.v1"
            or obs.get("observation_id") != OBS_ID or obs.get("source_panel_id") != PANEL
            or obs.get("slate_id") != SLATE or obs.get("evaluation_labels_loaded") is not False
            or obs.get("production_authorized") is not False
            or obs.get("actual_candidate_count") != 33 or obs.get("question_count") != 8
            or obs.get("passage_count") != 4 or obs.get("shared_evidence_encoder_calls") != 4
            or obs.get("actual_question_encoder_calls") != 33
            or obs.get("actual_reader_calls") != 132):
        raise ValueError("unregistered original real MultiRC archive")
    d = sha256(json.dumps({k:v for k,v in obs.items() if k != "observation_id"},
                          sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if d != OBS_ID:
        raise ValueError("original receipt semantic identity mismatch")
    rows = obs.get("rows")
    predictions = obs.get("predictions")
    if (type(rows) is not list or len(rows) != 33 or type(predictions) is not dict
            or set(predictions) != set(ARMS) or len({r.get("task_id") for r in rows}) != 33
            or len({r.get("source_group") for r in rows}) != 4
            or len({(r.get("source_group"), r.get("question_slot")) for r in rows}) != 8):
        raise ValueError("original genuine candidate denominator incomplete")
    for arm, preds in predictions.items():
        if type(preds) is not list or len(preds) != 33:
            raise ValueError("missing real Reader arm")
        weights = set()
        for r, v in zip(rows, preds):
            if (type(r) is not dict or set(r) != {"source_group", "question_slot", "task_id", "candidate_id", "original_v1_candidate"}
                    or type(v) is not dict or set(v) != {"source_group", "question_slot", "task_id", "logits", "weights_sha256"}
                    or (v["source_group"], v["question_slot"], v["task_id"]) !=
                       (r["source_group"], r["question_slot"], r["task_id"])
                    or type(r["question_slot"]) is not int or r["question_slot"] not in (0, 1)
                    or type(r["candidate_id"]) is not int or not 0 <= r["candidate_id"] <= 1_000_000_000
                    or type(r["original_v1_candidate"]) is not bool
                    or type(v["weights_sha256"]) is not str or len(v["weights_sha256"]) != 64
                    or type(v["logits"]) is not list or len(v["logits"]) != 2
                    or any(type(x) not in (float, int) or not isfinite(x) for x in v["logits"])):
                raise ValueError("mismatched real candidate, Reader or original weights")
            weights.add(v["weights_sha256"])
        if len(weights) != 1:
            raise ValueError("changed per-row Reader parameters")
    return obs


def positive(logits: list[float]) -> float:
    a, b = logits
    delta = b - a
    return 1 / (1 + exp(-delta)) if delta >= 0 else exp(delta) / (1 + exp(delta))


def law_from_prob(p: float) -> Law:
    if type(p) is not float or not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("untrusted pretrained posterior")
    # quantization was fixed before any labels. Pure inference scores only.
    x0 = F(round((2 * p - 1) * 1024), 1024)
    return Law(depth=3, a="1/3", x0=str(x0))


def build_rows(obs: dict) -> list[dict]:
    out = []
    for i, r in enumerate(obs["rows"]):
        probs = {arm: positive(obs["predictions"][arm][i]["logits"]) for arm in ARMS}
        law = law_from_prob(probs["conditioned"])
        initial = (F(0),) * (2 ** law.depth - 1)
        start = process_time_ns()
        cheap = operator(law, initial)[0]
        cheap_cpu = process_time_ns() - start
        cert = solve(law, tolerance="1/10000", bits=16, max_calls=24)
        root = F(cert.trace.states[0].y)
        bound = F(cert.fixed_point_error_bound)
        cheap_switch = abs(cheap) <= CUT
        # A rigorous inner interval below the arbitrary exploratory cutoff;
        # inconclusive boundary remains on original conditioned Reader.
        full_switch = abs(root) + bound <= CUT
        fixed_switch = abs(F(str(probs["conditioned"])) - F(1, 2)) <= F(1, 8)
        routes = {arm: arm for arm in ARMS}
        routes.update(fixed_confidence="mean_pool_query_fused" if fixed_switch else "conditioned",
                      cheap_one_map="mean_pool_query_fused" if cheap_switch else "conditioned",
                      e12_full_tree="mean_pool_query_fused" if full_switch else "conditioned")
        out.append({**r, "probs": probs, "law": asdict(law), "cheap_root": str(cheap),
                    "cheap_cpu_ns": cheap_cpu, "cert": asdict(cert), "policy_arms": routes})
    return out


def produce(archive: str, path: str) -> str:
    obs = read_prelabel(archive)
    rows = build_rows(obs)
    if len(rows) != 33:
        raise ValueError("missing original predictions")
    return write_once(path, {
        "schema": SCHEMA, "authority": "DENY_ALL", "archive_sha256": ARCHIVE_SHA,
        "prelabel_observation_id": OBS_ID, "slate_id": SLATE,
        "original_labels_accessed": False, "human_labels_present_in_prediction_rows": False,
        "new_pretrained_forward_count": 0, "actual_live_routing": False,
        "source_family": "aps/super_glue-MultiRC-retrospective-four-passages",
        "threshold_derived_from_labelblind_feature_distribution": True,
        "exploratory_cutoff": str(CUT), "policies": list(POLICIES), "production_accepted": False,
        "rows": rows,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prelabel-archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps({"prelabel_sha256": produce(args.prelabel_archive, args.output),
                      "authority": "DENY_ALL"}, sort_keys=True))
