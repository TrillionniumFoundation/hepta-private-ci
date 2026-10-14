"""Research-only paired physical-preflight gate; never selection or activation."""
from __future__ import annotations

from public_stem_material_v8 import CATALOG, RECEIPT, PROBE_TEXTS, probe_input_digest, AdmissionError


def check_pair(receipts: dict) -> dict:
    if type(receipts) is not dict or set(receipts) != set(CATALOG):
        raise AdmissionError("both exact candidate physical receipts required")
    expected_probe = probe_input_digest(PROBE_TEXTS)
    revisions = []
    snapshots = []
    for name in sorted(CATALOG):
        r = receipts[name]
        profile = CATALOG[name]
        if type(r) is not dict or r.get("schema") != RECEIPT or r.get("candidate") != name:
            raise AdmissionError("wrong candidate or physical receipt schema")
        if (r.get("repo_id") != profile["repo_id"] or r.get("pooling") != profile["pooling"]
                or r.get("normalization") != profile["normalization"]
                or r.get("feature_width") != profile["width"]):
            raise AdmissionError("model/profile identity drift")
        if r.get("probe_input_sha256") != expected_probe or r.get("probe_count") != len(PROBE_TEXTS):
            raise AdmissionError("physical probe input cohort drift")
        if type(r.get("forward_calls")) is not int or r["forward_calls"] < 2:
            raise AdmissionError("physical repeated forwards not established")
        if (type(r.get("wall_ns")) is not int or r["wall_ns"] <= 0
                or type(r.get("cpu_ns")) is not int or r["cpu_ns"] <= 0):
            raise AdmissionError("invalid measured execution")
        for field, length in (("revision", 40), ("snapshot_digest", 64),
                              ("plan_sha256", 64), ("feature_sha256", 64)):
            value = r.get(field)
            if type(value) is not str or len(value) != length or value == "0" * length or any(x not in "0123456789abcdef" for x in value):
                raise AdmissionError("missing exact physical source identity: " + field)
        if (r.get("production_accepted") is not False
                or r.get("pretrained_source_independently_attested") is not False
                or r.get("matched_pair_completed") is not False
                or r.get("heldout_efficacy_evaluated") is not False
                or r.get("authority") != "DENY_ALL"):
            raise AdmissionError("untrusted production or outcome claim")
        revisions.append(r["revision"])
        snapshots.append(r["snapshot_digest"])
    if len(set(snapshots)) != 2:
        raise AdmissionError("candidate snapshots are not distinct")
    return {"schema":"hepta.public-stem-physical-pair-preflight.v9",
            "probe_input_sha256":expected_probe,"candidates":sorted(CATALOG),
            "paired_physical_preflight_complete":True,
            "same_provenance_and_dataset_verified":False,
            "matched_training_completed":False,
            "independent_future_efficacy_verified":False,
            "production_accepted":False,"authority":"DENY_ALL"}
