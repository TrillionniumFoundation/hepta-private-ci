"""Independent, read-only review of exact-head *real* P1 GitHub physical artifacts.

No model downloads, unpickling, public label access, training, production writer,
selection, issuer signing or tool authority. Reads only small JSON-in-ZIP receipts.
A passing receipt proves consistency of *reported* original execution at one SHA,
NOT full independent hardware attestation, scientific efficacy or production use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import zipfile

import gate

SCHEMA = "hepta.stem.equal-size.p1-physical-evidence-review.v1"
SOURCE_SCHEMA = "hepta.stem.equal-size.physical-byte-review.v1"
FORWARD_SCHEMA = "hepta.stem.equal-size.physical-forward.v1"
P1_MODEL_SET = frozenset(("ettin400", "laya421"))
HEAD = "b2ac32e34dc0c69d5cb57db7ae7a2ea718bb910f"
MAX_ZIP_BYTES = 128 * 1024
MAX_JSON_BYTES = 16 * 1024
# Exact uploaded ZIP byte identities from P1 run 39034514849, NOT estimates.
# Artifact IDs: ettin400=12108091511; laya421=12107424477.
PINNED_ZIP_SHA256 = {
    "ettin400": "c40d8c2f7610d55f2447d65845b4e6cb488e2b26af2f39a7a8d46127c5d30b1a",
    "laya421": "41e31a2d34cc6a4e2a9c411953aa28a273b21a3b7406602fd216581754d209fd",
}



def check(ok, reason):
    if not ok:
        raise gate.Denied(reason)


def _strict_pairs(pairs):
    d = {}
    for k, v in pairs:
        check(k not in d, "duplicate key in original runner receipt")
        d[k] = v
    return d


def _read_json(b):
    check(type(b) is bytes and 1 <= len(b) <= MAX_JSON_BYTES,
          "oversized/absent physical receipt")
    return json.loads(b.decode("utf-8"), object_pairs_hook=_strict_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(gate.Denied("nonfinite physical JSON")))


def _int(v, *, positive=True):
    return type(v) is int and v >= (1 if positive else 0)


def _sha(v):
    return type(v) is str and bool(re.fullmatch(r"[0-9a-f]{64}", v))


def _commit(v):
    return type(v) is str and bool(re.fullmatch(r"[0-9a-f]{40}", v))


def _bounded_float(v, low=0., high=1.):
    return type(v) in (float, int) and math.isfinite(v) and low <= v <= high


def read_artifact(path, model, *, head=HEAD):
    """Read only two known JSON files of an explicitly SHA-bound artifact ZIP.

    Caller-provided ZIP filename is not an attestation of GitHub provenance;
    the independent GitHub artifact ID + run/job URL must be retained separately.
    """
    check(model in P1_MODEL_SET and head == HEAD and isinstance(path, (str, Path)),
          "unregistered physical experiment input")
    p = Path(path)
    check(p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_ZIP_BYTES,
          "invalid physical GitHub artifact file")
    expected = {f"hepta-reviewed-{model}.json", f"hepta-forward-{model}.json"}
    archive_bytes = p.read_bytes()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    check(archive_sha256 == PINNED_ZIP_SHA256[model],
          "model artifact ZIP does not match pinned original GitHub evidence")
    with zipfile.ZipFile(p) as archive:
        info = archive.infolist()
        check(len(info) == 2 and {i.filename for i in info} == expected and
              len({i.filename for i in info}) == len(info),
              "physical artifact missing/extra/duplicated files")
        for i in info:
            mode = i.external_attr >> 16
            check(i.flag_bits & 1 == 0 and not i.is_dir() and
                  (i.create_system != 3 or stat.S_ISREG(mode)) and
                  0 < i.file_size <= MAX_JSON_BYTES and
                  i.compress_size <= MAX_JSON_BYTES,
                  "unsafe ZIP physical artifact member")
        source = _read_json(archive.read(f"hepta-reviewed-{model}.json"))
        forward = _read_json(archive.read(f"hepta-forward-{model}.json"))
    return source, forward, archive_sha256


def audit_one(model, source, forward):
    check(model in P1_MODEL_SET and type(source) is dict and type(forward) is dict,
          "unexpected physical original result")
    repo, revision, nominal, kind = gate.MODELS[model]
    check(set(source) == {
        "actual_model_forward_verified", "all_four_models_complete", "authority",
        "disposition", "file_count", "independently_rehashed_exact_physical_bytes",
        "issuer_signature_verified", "model", "production_promotion_permitted", "repo",
        "revision", "schema", "source_sha256_receipt", "total_bytes_rehashed"},
        "physical source review changed or added fields")
    check(source["schema"] == SOURCE_SCHEMA and source["repo"] == repo and
          source["revision"] == revision and source["model"] == model and
          source["file_count"] == 5 and source["authority"] == "DENY_ALL" and
          source["disposition"] == "HOLD_NO_GO" and
          source["independently_rehashed_exact_physical_bytes"] is True and
          source["actual_model_forward_verified"] is False and
          source["all_four_models_complete"] is False and
          source["issuer_signature_verified"] is False and
          source["production_promotion_permitted"] is False and
          _sha(source["source_sha256_receipt"]) and
          _int(source["total_bytes_rehashed"]) and
          500_000_000 <= source["total_bytes_rehashed"] <= 2_500_000_000,
          "incorrect exact original byte/source identity")
    check(set(forward) == {
        "authority", "clock_cpu_ns_self_reported", "clock_wall_ns_self_reported",
        "disposition", "equal_head_training_budget_verified", "heldout_human_task_score",
        "isolated_allowlist_runtime_snapshot_verified", "model", "output",
        "peak_rss_kib_linux_self_reported", "production_promotion_permitted",
        "publisher_signature_verified", "real_forward_on_fixed_unlabeled_probe", "schema",
        "source_receipt_sha256", "source_weight_bytes_rehashed", "two_arm_scientific_winner_verified"},
        "physical model load receipt changed or added fields")
    check(forward["schema"] == FORWARD_SCHEMA and forward["model"] == model and
          forward["source_receipt_sha256"] == source["source_sha256_receipt"] and
          forward["source_weight_bytes_rehashed"] == source["total_bytes_rehashed"] and
          forward["authority"] == "DENY_ALL" and forward["disposition"] == "HOLD_NO_GO" and
          forward["isolated_allowlist_runtime_snapshot_verified"] is True and
          forward["real_forward_on_fixed_unlabeled_probe"] is True and
          forward["equal_head_training_budget_verified"] is False and
          forward["heldout_human_task_score"] is None and
          forward["two_arm_scientific_winner_verified"] is False and
          forward["publisher_signature_verified"] is False and
          forward["production_promotion_permitted"] is False,
          "forward/source permission or identity mismatch")
    x = forward["output"]
    check(type(x) is dict and x.get("original_cpu_base_forward_calls") == 1 and
          _int(x.get("actual_tensor_values_loaded")) and
          _int(x.get("input_tokens")) and x["input_tokens"] <= 128 and
          x.get("torch_pickle_loaded") is False and
          type(x.get("weights_only_loader_used")) is bool and
          type(x.get("actual_native_decision_probability")) is bool and
          _int(forward["clock_wall_ns_self_reported"]) and
          _int(forward["clock_cpu_ns_self_reported"]) and
          _int(forward["peak_rss_kib_linux_self_reported"]),
          "missing measured original forward")
    if model == "ettin400":
        check(set(x) == {"actual_native_decision_probability", "actual_tensor_values_loaded",
                         "feature_dimension", "feature_sha256", "input_tokens",
                         "original_cpu_base_forward_calls", "output_type", "torch_pickle_loaded",
                         "weights_only_loader_used"} and
              x["output_type"] == "frozen_encoder_cls_fp32_sha256_not_decision_probability" and
              x["feature_dimension"] == 1024 and _sha(x["feature_sha256"]) and
              x["weights_only_loader_used"] is True and
              x["actual_native_decision_probability"] is False,
              "Ettin claim is not a real frozen encoder feature")
    else:
        check(set(x) == {"actual_native_decision_probability", "actual_tensor_values_loaded",
                         "input_tokens", "original_cpu_base_forward_calls",
                         "original_staged_tokenizer_was_not_modified", "output_type",
                         "probability", "runtime_tokenizer_config_modified",
                         "runtime_tokenizer_config_sha256", "torch_pickle_loaded",
                         "weights_only_loader_used"} and
              x["output_type"] == "native_laya_noul_probability_not_comparable_to_ettin_cls" and
              _bounded_float(x["probability"]) and
              x["weights_only_loader_used"] is False and
              x["actual_native_decision_probability"] is True and
              x["original_staged_tokenizer_was_not_modified"] is True and
              type(x["runtime_tokenizer_config_modified"]) is bool and
              _sha(x["runtime_tokenizer_config_sha256"]),
              "Laya native original decision result incomplete")
    return {
        "model": model, "repo": repo, "revision": revision,
        "published_approx_params": nominal,
        "observed_loaded_tensor_values": x["actual_tensor_values_loaded"],
        "observed_bytes_rehashed": source["total_bytes_rehashed"],
        "source_receipt_sha256": source["source_sha256_receipt"],
        "input_tokens": x["input_tokens"],
        "base_encoder_forward_calls": x["original_cpu_base_forward_calls"],
        "cpu_ns_self_reported": forward["clock_cpu_ns_self_reported"],
        "wall_ns_self_reported": forward["clock_wall_ns_self_reported"],
        "peak_rss_kib_linux_self_reported": forward["peak_rss_kib_linux_self_reported"],
        "native_probability_or_cls_digest": x.get("feature_sha256", x.get("probability")),
        "actual_original_model_load_and_forward_reported": True,
        "head_training_and_human_scoring_verified": False,
        "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
    }


def audit_both(artifact_ettin, artifact_laya, *, head=HEAD):
    check(head == HEAD, "cannot relabel original physical evidence with another commit")
    evidence = []
    for model, path in (("ettin400", artifact_ettin), ("laya421", artifact_laya)):
        source, forward, zsha = read_artifact(path, model, head=head)
        record = audit_one(model, source, forward)
        record["artifact_zip_sha256"] = zsha
        evidence.append(record)
    check(len(evidence) == 2 and {e["model"] for e in evidence} == P1_MODEL_SET,
          "incomplete physical two-model panel")
    a, b = evidence
    return {
        "schema": SCHEMA,
        "producer_pr": 2579,
        "exact_source_commit": head,
        "source_models": evidence,
        "tensor_ratio_ettin_vs_laya": a["observed_loaded_tensor_values"] / b["observed_loaded_tensor_values"],
        "observed_param_counts_same_exact_budget": a["observed_loaded_tensor_values"] == b["observed_loaded_tensor_values"],
        "output_contracts_directly_comparable": False,
        "matched_input_tokens_verified": False,
        "matched_sgd_training_verified": False,
        "original_human_benchmark_verified": False,
        "independent_issuer_signature_verified": False,
        "prospective_negative_transfer_verified": False,
        "full_lifecycle_host_cost_verified": False,
        "selected_replacement": None,
        "model_promotion_permitted": False,
        "physical_cell_split_permitted": False,
        "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Read-only audit of exact P1 real physical-model evidence")
    p.add_argument("--ettin", type=Path, required=True)
    p.add_argument("--laya", type=Path, required=True)
    p.add_argument("--head", default=HEAD)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    result = audit_both(args.ettin, args.laya, head=args.head)
    check(args.out.parent.is_dir() and not args.out.parent.is_symlink() and
          not args.out.exists(), "refusing overwrite or symlinked output")
    data = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    print("Original P1 two-model CPU forward evidence audited; no same-budget winner; HOLD_NO_GO")


if __name__ == "__main__":
    main()
