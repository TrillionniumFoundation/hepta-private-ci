#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Export every saved TRAIN witness with original bytes and a fresh Fraction check.

Input is the published wsp_followup_20261105 directory at the pinned research
commit. No model forward, teacher recomputation, training, new witness search,
validation or TEST access occurs here. Output must be a new directory.
"""
import argparse
import gzip
import json
import pathlib
import resource
import time
from reference import SEMANTICS, bound, encode, fraction_read, reference, sha

PRIOR_COMMIT = "85f507fb2e1c9e8ad9941451641bb4ec3f1dccb4"
PROTOCOL_SHA = "3d5a657a7f79a5edf1e98365256b898152e384ade4031231e24f03f8f9ecdfd5"
FIT_IDS = (11, 23, 37, 53, 71)


def payload(path):
    if path.is_file():
        return path.read_bytes()
    parts = json.loads(path.with_name(path.name + ".parts.json").read_text())
    result = bytearray()
    for item in parts["parts"]:
        if pathlib.Path(item["name"]).name != item["name"]:
            raise ValueError("unsafe archived part name")
        data = path.with_name(item["name"]).read_bytes()
        if len(data) != item["bytes"] or sha(data) != item["sha256"]:
            raise ValueError("archived part mismatch")
        result.extend(data)
    if len(result) != parts["bytes"] or sha(result) != parts["sha256"]:
        raise ValueError("archived payload mismatch")
    return bytes(result)


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    data = gzip.compress(raw, mtime=0) if path.name.endswith(".gz") else raw
    with path.open("xb") as stream:
        stream.write(data)
    return {"name": path.name, "bytes": len(data), "sha256": sha(data), "decoded_bytes": len(raw)}


def prior_comparison(fresh, old):
    p = fresh["proof"]
    for key in ("radius_squared", "radius_upper", "dual_vector_squared_norm", "weighted_F64_error_bound"):
        actual_key = key.replace("F64", "f64")
        if fraction_read(p[actual_key]) != fraction_read(old[key]):
            raise ValueError("prior exact scalar mismatch: " + key)
    if [fraction_read(x) for x in p["dual_vector"]] != [fraction_read(x) for row in old["dual_vector"] for x in row]:
        raise ValueError("prior dual vector mismatch")
    if [fraction_read(x) for x in p["per_head_f64_absolute_error_bound"]] != [fraction_read(x) for x in old["per_head_F64_absolute_error_bound"]]:
        raise ValueError("prior roundoff bound mismatch")
    for old_name, new_name in (("ideal_real", "ideal_real"), ("F64_necessary_relaxation", "f64_necessary_relaxation")):
        for name in ("d", "left_squared", "right_squared"):
            if fraction_read(p[new_name][name]) != fraction_read(old[old_name][name]):
                raise ValueError("prior comparison scalar mismatch")
        for name in ("d_positive", "strict_separation"):
            if p[new_name][name] != old[old_name][name]:
                raise ValueError("prior comparison flag mismatch")


def main(args):
    started, cpu = time.monotonic(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    cert = args.prior / "train_margin_certificate"
    science = args.prior / "ndu_policy"
    protocol_bytes = (cert / "PROTOCOL_FROZEN.json").read_bytes()
    if sha(protocol_bytes) != PROTOCOL_SHA:
        raise ValueError("prior frozen protocol differs")
    protocol = json.loads(protocol_bytes)
    source_checks = {}
    for name, expected in protocol["files"]["science"].items():
        actual = sha(payload(science / name))
        if actual != expected:
            raise ValueError("scientific source or model bytes changed: " + name)
        source_checks["science/" + name] = actual
    for name, expected in protocol["files"]["new"].items():
        actual = sha((cert / name).read_bytes())
        if actual != expected:
            raise ValueError("prior certificate implementation changed: " + name)
        source_checks["prior_certificate/" + name] = actual
    reports = []
    files = []
    try:
        for fit in FIT_IDS:
            model_archive = payload(science / f"execution_r1/run/models/fit_{fit}_C.json.gz")
            model_bytes = gzip.decompress(model_archive)
            witness_bytes = payload(cert / f"execution_r1/run/producer/fit_{fit}_WITNESS.json.gz")
            witness = json.loads(gzip.decompress(witness_bytes))
            original_report = json.loads(gzip.decompress(payload(cert / f"execution_r1/run/producer/fit_{fit}_RESULT.json.gz")))
            rows = []
            for r in witness:
                hidden = encode(r["hidden"])
                if sha(bytes.fromhex(hidden)) != r["hidden_sha256"]:
                    raise ValueError("upstream hidden bytes mismatch")
                rows.append({"source_row": r["global_row_index"], "state_sha256": r["state_sha256"],
                             "teacher_table_sha256": r["teacher_table_sha256"],
                             "hidden_f64_le_hex": hidden, "hidden_sha256": r["hidden_sha256"],
                             "multiplier_f64_le_hex": encode([r["multiplier"]]),
                             "teacher_q_f64_le_hex": encode(r["teacher_q"]), "legal": r["legal"],
                             "target_action": r["target_action"], "competitor_action": r["competitor_action"]})
            params = bound({"semantics": SEMANTICS, "checkpoint_json": model_bytes.decode(),
                            "source": {"fit_id": fit, "protocol_sha256": PROTOCOL_SHA,
                                       "feature_source_sha256": protocol["files"]["joint"]["joint_deploy.py"],
                                       "teacher_source_sha256": protocol["files"]["science"]["planning.py"],
                                       "original_witness_record_sha256": sha(witness_bytes)}, "rows": rows})
            exact = reference(params)
            prior_comparison(exact, original_report["exact_certificate"])
            if exact["proof"]["verdict"] != original_report["status"]:
                raise ValueError("prior verdict changed")
            files.append(save(args.output / f"fit_{fit}_REQUEST.json.gz", params))
            files.append(save(args.output / f"fit_{fit}_REFERENCE.json.gz", exact))
            reports.append({"fit": fit, "witness_rows": len(rows), "checkpoint_archive_sha256": sha(model_archive),
                            "checkpoint_raw_sha256": sha(model_bytes), "witness_archive_sha256": sha(witness_bytes),
                            "wire_witness_sha256": params["expected_witness_sha256"],
                            "complete_witness_not_aggregated": True,
                            "fresh_Fraction_equals_published_proof": True, "verdict": exact["proof"]["verdict"]})
            print(json.dumps(reports[-1]), flush=True)
        save(args.output / "INPUT_MANIFEST.json", {"schema": "hepta-native-certificate-inputs-v1",
             "prior_research_repository": "TrillionniumFoundation/hepta-private-ci",
             "prior_research_commit": PRIOR_COMMIT, "prior_protocol_sha256": PROTOCOL_SHA,
             "files": files, "fits": reports, "total_witness_rows": sum(x["witness_rows"] for x in reports),
             "source_checks": source_checks, "source_semantics_reexecuted": False,
             "new_scientific_efficacy": False, "wall_seconds": time.monotonic()-started,
             "self_cpu_seconds": time.process_time()-cpu, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    except BaseException as error:
        save(args.output / "FAILED.json", {"error": repr(error), "completed_fits": reports,
             "wall_seconds": time.monotonic()-started, "self_cpu_seconds": time.process_time()-cpu})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    main(parser.parse_args())
