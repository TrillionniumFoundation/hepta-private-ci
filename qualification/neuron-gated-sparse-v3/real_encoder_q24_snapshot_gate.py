#!/usr/bin/env python3
"""Fail-closed REAL public Encoder -> 32D Q24 *contract* (not a producer).

A receipt cannot authenticate itself: passing this tool only establishes
consistency against external frozen expected IDs and source/projector digests.
No promotion, no proof of independent Encoder execution, no heldout training.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "hepta.neuron.public-encoder-q24-feature-snapshot.v1"
Q = 1 << 24
MAX_VALUE = 8 * Q
MAX_ROWS = 8192

class Refused(ValueError):
    pass

def need(ok, reason):
    if not ok:
        raise Refused(reason)

def hex64(v):
    return type(v) is str and len(v) == 64 and all(c in "0123456789abcdef" for c in v)

def unique_json(raw):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            need(k not in out, "duplicate JSON member")
            out[k] = v
        return out
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(Refused("nonfinite JSON")))

def read(path, max_size=2_000_000):
    need(not path.is_symlink() and path.is_file(), "missing/symlink physical evidence")
    pre = path.stat()
    need(0 < pre.st_size <= max_size, "oversize evidence")
    raw = path.read_bytes()
    post = path.stat()
    attrs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    need(all(getattr(pre, a) == getattr(post, a) for a in attrs),
         "evidence changed during read")
    return raw

def validate(snapshot: dict, registry: dict, *, expected_encoder: str,
             expected_projection: str, expected_registry_sha: str) -> dict:
    need(hex64(expected_encoder) and hex64(expected_projection)
         and hex64(expected_registry_sha), "missing external pinned digests")
    need(type(snapshot) is dict and set(snapshot) == {
        "schema", "encoder_sha256", "projection_sha256", "registry_sha256",
        "projection_fit_case_ids", "feature_rows", "claimed_independent_provenance",
        "production_qualification", "ndu_eligible"
    }, "unknown snapshot schema")
    need(snapshot["schema"] == SCHEMA and
         snapshot["encoder_sha256"] == expected_encoder and
         snapshot["projection_sha256"] == expected_projection and
         snapshot["registry_sha256"] == expected_registry_sha,
         "snapshot identity not pinned to external expected source")
    need(snapshot["claimed_independent_provenance"] is False and
         snapshot["production_qualification"] is False and
         snapshot["ndu_eligible"] is False, "untrusted snapshot claimed authority")
    need(type(registry) is dict and set(registry) == {"fit_case_ids","heldout_case_ids"},
         "external source registry missing splits")
    fit, held = registry["fit_case_ids"], registry["heldout_case_ids"]
    need(type(fit) is list and type(held) is list
         and 2 <= len(fit) <= MAX_ROWS and 1 <= len(held) <= MAX_ROWS
         and all(type(x) is str and 0 < len(x) <= 128 for x in fit+held)
         and len(set(fit)) == len(fit)
         and len(set(held)) == len(held)
         and not set(fit).intersection(held),
         "leaked or malformed frozen split registry")
    need(type(snapshot["projection_fit_case_ids"]) is list and
         set(snapshot["projection_fit_case_ids"]) == set(fit) and
         len(snapshot["projection_fit_case_ids"]) == len(fit),
         "projection must use exact training IDs, never heldout cases")
    rows = snapshot["feature_rows"]
    need(type(rows) is list and len(rows) == len(fit)+len(held) <= MAX_ROWS,
         "missing or unbounded frozen feature rows")
    seen = set()
    for row in rows:
        need(type(row) is dict and set(row) == {
            "case_id","split","source_text_sha256","feature_q24"
        }, "unexpected snapshot row field (labels forbidden)")
        case_id, split, feat = row["case_id"], row["split"], row["feature_q24"]
        need(type(case_id) is str and case_id not in seen,
             "duplicate feature case")
        seen.add(case_id)
        need((split == "fit" and case_id in fit)
             or (split == "heldout" and case_id in held),
             "wrong split or unregistered case")
        need(hex64(row["source_text_sha256"]) and
             type(feat) is list and len(feat) == 32
             and all(type(x) is int and -MAX_VALUE <= x <= MAX_VALUE for x in feat),
             "invalid actual 32D Q24 feature")
    need(seen == set(fit).union(held), "missing feature case")
    return {
        "schema":"hepta.neuron.public-q24-snapshot-contract-audit.v1",
        "authority":"DENY_ALL", "decision":"NO_MODEL_PROMOTION",
        "split_count":{"fit":len(fit),"heldout":len(held)},
        "encoder_sha256":expected_encoder,
        "projection_sha256":expected_projection,
        "registry_sha256":expected_registry_sha,
        "all_external_case_ids_covered":True,
        "projection_restricted_to_frozen_train_ids":True,
        "feature_vector_width":32,
        "independent_encoder_execution_attested":False,
        "training_history_independently_attested":False,
        "original_selected_v1_a0_verified":False,
        "heldout_labels_observed_by_adapter":False,
        "real_future_window_efficacy_verified":False,
        "production_qualification":False, "ndu_eligible":False
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--encoder-sha256", required=True)
    p.add_argument("--projection-sha256", required=True)
    p.add_argument("--registry-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    a=p.parse_args()
    try:
        registry_raw=read(a.registry)
        need(hashlib.sha256(registry_raw).hexdigest()==a.registry_sha256,
             "external registry byte identity mismatch")
        result=validate(unique_json(read(a.snapshot)),unique_json(registry_raw),
                        expected_encoder=a.encoder_sha256,
                        expected_projection=a.projection_sha256,
                        expected_registry_sha=a.registry_sha256)
        with a.output.open("x") as out:
            json.dump(result,out,indent=2,sort_keys=True,allow_nan=False)
            out.write("\n")
        return 0
    except (Refused,OSError,ValueError,TypeError) as e:
        print("BLOCKED_REAL_Q24_SNAPSHOT: "+str(e),file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
