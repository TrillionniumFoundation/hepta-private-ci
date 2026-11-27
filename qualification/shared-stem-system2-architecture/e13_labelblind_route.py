"""E13 real archived-model proposals with certified *toy* E12 System 2 gating.

The proposer is intentionally LABEL-BLIND. Its only CLI archive is an old
physical prediction ZIP (two already-evaluated model outputs), never the
original label-bearing archive. All routing is retrospective/hypothetical.
No additional pretrained Encoder was run; no live online serving took place.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from time import process_time_ns
from zipfile import ZipFile

from e7_archive import PHYSICAL_SHA, physical_rows
from e12_nonlinear_cert import Law, operator, solve, rat

SCHEMA = "hepta.e13.real-prediction-label-blind-fbsde-route.v1"
CUT = Q(1, 4)
DEPTH = 2
QUANT = 64
ARMS = ("granite_only", "mmbert_only", "confidence_075", "cheap_one_map", "e12_certified")


def nondup(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def write_once(path: str, value: object) -> str:
    data = canon(value)
    with Path(path).open("xb") as f:
        f.write(data)
    return sha256(data).hexdigest()


def read_prelabel_members(physical_zip: str) -> dict[str, bytes]:
    """Read exactly six unsupervised original physical members, never ZIP scorers.

    The original artifact also contains post-label `independent-scores.json`;
    unlike the generic ZIP helper, this function does NOT decompress or
    access that member. The caller never receives an original label.
    """
    path = Path(physical_zip)
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= 20_000_000:
        raise ValueError("missing or unsupported physical source archive")
    if sha256(path.read_bytes()).hexdigest() != PHYSICAL_SHA:
        raise ValueError("original source archive byte identity mismatch")
    names = ("granite97.report.json", "mmbert_small.report.json",
             "granite97.stdout.log", "mmbert_small.stdout.log",
             "pre-score-seals.sha256", "current-source.sha")
    with ZipFile(path) as z:
        infos = z.infolist()
        if (not 0 < len(infos) <= 100
                or len({i.filename for i in infos}) != len(infos)
                or any(i.is_dir() or PurePosixPath(i.filename).is_absolute()
                       or ".." in PurePosixPath(i.filename).parts
                       or i.file_size > 2_000_000 or i.compress_size > 2_000_000
                       or ((i.external_attr >> 16) & 0o170000) == 0o120000
                       for i in infos)
                or sum(i.file_size for i in infos) > 10_000_000
                or not set(names) <= set(z.namelist())):
            raise ValueError("physical ZIP integrity or source member inventory failed")
        # NEVER z.read() historical label/scorer members on the proposer side.
        return {name: z.read(name) for name in names}

def quantized_x0(granite_prob: float) -> str:
    """P-only label-blind uncertainty, floor to an exact 1/64 rational grid."""
    if type(granite_prob) is not float or not 0 <= granite_prob <= 1:
        raise ValueError("invalid physical input probability")
    p = Q(str(granite_prob))
    uncertainty = 2 * min(p, 1 - p)
    return str(Q((uncertainty * QUANT).numerator // (uncertainty * QUANT).denominator, QUANT))


def _route_one(cid: str, g: dict, m: dict) -> dict:
    if g["group_id"] != m["group_id"] or g["joint_input_digest"] != m["joint_input_digest"]:
        raise ValueError("paired physical source mismatch")
    gp = g["probs"]["learned_gate"]
    mp = m["probs"]["learned_gate"]
    x0 = quantized_x0(gp)
    law = Law(depth=DEPTH, x0=x0, a="1/3")
    # Actual research numerical work, not a pretend model call.
    start = process_time_ns()
    cheap = operator(law, (Q(0),) * (2**law.depth - 1))[0]
    cheap_cpu = process_time_ns() - start
    result = solve(law, tolerance="1/10000", bits=16, max_calls=24)
    root = rat(result.trace.states[0].y)
    certified_margin = Q(result.fixed_point_error_bound)
    # Conservative gating: a decision is false unless the whole value
    # interval is on the high side of the fixed threshold. Uncertain cases
    # stay on Granite, no opportunistic post-label action recovery.
    use_e12 = root - certified_margin > CUT
    use_cheap = cheap > CUT
    use_conf = max(gp, 1 - gp) < .75
    routes = {"granite_only": False, "mmbert_only": True,
              "confidence_075": use_conf, "cheap_one_map": use_cheap,
              "e12_certified": use_e12}
    return {
        "case_id": cid, "group_id": g["group_id"],
        "joint_input_digest": g["joint_input_digest"],
        "granite_prob": gp, "mmbert_prob": mp,
        "granite_archived_ns": g["encoder_forward_ns"] + g["head_ns"]["learned_gate"],
        "mmbert_archived_ns": m["encoder_forward_ns"] + m["head_ns"]["learned_gate"],
        "x0": x0, "law": asdict(law),
        "cheap_root": str(cheap), "cheap_cpu_ns": cheap_cpu,
        "cert": asdict(result),
        "routes": routes,
    }


def produce(physical_zip: str, output: str) -> str:
    source = physical_rows(read_prelabel_members(physical_zip))
    rows = [_route_one(cid, source["granite97"][cid], source["mmbert_small"][cid])
            for cid in sorted(source["granite97"])]
    if len(rows) != 128 or len({row["group_id"] for row in rows}) != 128:
        raise ValueError("incomplete physical case grouping")
    return write_once(output, {
        "schema": SCHEMA, "authority": "DENY_ALL", "physical_archive_sha256": PHYSICAL_SHA,
        "human_labels_loaded_by_proposer": False,
        "historical_source_archive_accessed": False,
        "new_pretrained_encoder_forwards": 0,
        "online_routing_executed": False,
        "numerical_model_is_fixed_nonlinear_toy": True,
        "all_human_sources_are_retrospective_one_AGNews_family": True,
        "depth": DEPTH, "decision_threshold": str(CUT), "quantization": QUANT,
        "arms": list(ARMS), "production_accepted": False, "rows": rows,
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--physical", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print(json.dumps({"sealed_sha256": produce(args.physical, args.output),
                      "authority": "DENY_ALL"}, sort_keys=True))
