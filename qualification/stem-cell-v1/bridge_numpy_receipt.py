"""Independent, presealed feature/weight -> prediction parity for a V6 Bridge.

Consumes six bounded FP32/boolean *already encoded* tensors, a separately
committed feature-manifest SHA256, a pinned CPU-FP32 model SHA256, and logits
sealed by an independent producer. NumPy independently evaluates the same
Bridge model and compares every case without reading task labels.

Authenticates only explicit bytes under supplied expected digests. Hashes or
agreement do NOT authenticate a model issuer, Encoder, host, true source,
training chronology, future task quality, permission or NDU effectiveness.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import time

import numpy as np

from bridge_gradient_archive_replay import (read_regular_file, parse_json, require)
from bridge_numpy_forward import bridge_forward, weights_from_checkpoint

FEATURE_SCHEMA = "hepta.bridge.numeric-features.v7.3"
OBSERVED_SCHEMA = "hepta.bridge.external-logits.v7.3"
REPORT_SCHEMA = "hepta.bridge.independent-prediction-replay.v7.3"
HEX = re.compile(r"[0-9a-f]{64}\Z")
NAMES = ("facts", "question", "candidate", "fact_mask", "question_mask", "candidate_mask")


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _sha_checked(v):
    require(type(v) is str and HEX.fullmatch(v) is not None, "canonical SHA256 required")
    return v


def _read_tensor_archive(raw):
    """Bounded NPZ with exactly the registered 6 safe .npy buffers."""
    import zipfile
    require(isinstance(raw, bytes) and 0 < len(raw) <= 30_000_000,
            "bounded original feature archive required")
    with zipfile.ZipFile(io.BytesIO(raw),"r") as arc:
        entries = arc.infolist()
        require(len(entries) == 6 and sum(e.file_size for e in entries) <= 64_000_000
                and all(e.filename.endswith(".npy") for e in entries)
                and {e.filename for e in entries} == {name+".npy" for name in NAMES},
                "exact six bounded canonical non-pickle NumPy arrays required")
        arrays={}
        for entry in entries:
            name=entry.filename[:-4]
            payload=arc.read(entry)
            require(len(payload) == entry.file_size, "truncated feature tensor")
            # Parse the declared NPY header BEFORE numpy allocates any tensor.
            # An untrusted header cannot claim a TB shape inside a tiny ZIP.
            header_stream=io.BytesIO(payload)
            version=np.lib.format.read_magic(header_stream)
            require(version in ((1,0),(2,0)), "bounded supported NPY header version required")
            reader=(np.lib.format.read_array_header_1_0 if version == (1,0)
                    else np.lib.format.read_array_header_2_0)
            shape, fortran, dtype=reader(header_stream,max_header_size=4096)
            require(not fortran and 1 <= len(shape) <= 4
                    and all(type(d) is int and 1 <= d <= 4096 for d in shape)
                    and math.prod(shape)*dtype.itemsize <= 16_000_000
                    and dtype == (np.dtype(np.bool_) if name.endswith("mask")
                                  else np.dtype(np.float32)),
                    "untrusted NPY header exceeds bounded dtype/shape limits")
            value=np.load(io.BytesIO(payload),allow_pickle=False,max_header_size=4096)
            require(type(value) is np.ndarray and value.nbytes <= 16_000_000
                    and value.flags.c_contiguous and value.dtype ==
                    (np.bool_ if name.endswith("mask") else np.float32),
                    "registered contiguous typed feature tensors required")
            value.setflags(write=False)
            arrays[name]=value
        return arrays


def _manifest(blob, archive_raw, arrs):
    manifest=parse_json(blob)
    require(type(manifest) is dict and manifest.get("schema") == FEATURE_SCHEMA
            and manifest.get("labels_present") is False
            and manifest.get("production_authorized") is False
            and set(manifest)=={
                "schema","labels_present","production_authorized","case_ids",
                "case_source_sha256","encoder_digest","tokenizer_digest",
                "preprocessor_digest","principal_digest","purpose_digest",
                "generation","tensor_archive_sha256","tensors"},
            "exact no-label feature admission schema required")
    for key in ("encoder_digest","tokenizer_digest","preprocessor_digest",
                "principal_digest","purpose_digest","tensor_archive_sha256"):
        _sha_checked(manifest[key])
    require(manifest["tensor_archive_sha256"] == _sha(archive_raw),
            "feature ZIP bytes do not match committed identity")
    require(type(manifest["generation"]) is int and manifest["generation"] >= 1,
            "exact nonzero generation required")
    cases=manifest["case_ids"]
    require(type(cases) is list and len(cases) == len(set(cases))
            and 1 <= len(cases) <= 32
            and all(type(case) is str and 0 < len(case.encode('utf-8')) <= 512 for case in cases),
            "complete unique bounded case identity required")
    require(type(manifest["case_source_sha256"]) is list
            and len(manifest["case_source_sha256"]) == len(cases),
            "one original-source digest per case required")
    for sha in manifest["case_source_sha256"]:_sha_checked(sha)
    tensors=manifest["tensors"]
    require(type(tensors) is dict and set(tensors) == set(NAMES),
            "all registered six tensor descriptors required")
    for name in NAMES:
        t=arrs[name]
        r=tensors[name]
        require(type(r) is dict and set(r)=={"dtype","shape","raw_sha256"}
                and r["dtype"] == ("bool" if name.endswith("mask") else "float32")
                and r["shape"] == list(t.shape)
                and r["raw_sha256"] == _sha(t.tobytes(order='C')),
                "registered feature geometry/tensor content changed")
    require(arrs["facts"].shape[0]==len(cases),"one prediction per case")
    return manifest


def _external(blob, checkpoint_sha, zip_sha, cases):
    row=parse_json(blob)
    require(type(row) is dict and set(row)=={
        "schema","labels_present","checkpoint_sha256", "tensor_archive_sha256",
        "case_ids","logits","production_authorized"},
        "sealed external logits schema required")
    require(row["schema"] == OBSERVED_SCHEMA and row["labels_present"] is False
            and row["production_authorized"] is False
            and row["checkpoint_sha256"] == checkpoint_sha
            and row["tensor_archive_sha256"] == zip_sha
            and row["case_ids"] == cases,
            "external producer logits are not bound to original inputs/model")
    require(type(row["logits"]) is list and len(row["logits"]) == len(cases)
            and all(type(entry) is list and len(entry) == 2 for entry in row["logits"]),
            "bounded complete external logits rows required")
    logits=np.array(row["logits"])
    require(logits.shape == (len(cases),2) and logits.dtype.kind in "fi"
            and bool(np.isfinite(logits).all()),
            "complete finite independent paired class logits required")
    return logits


def verify(checkpoint, archive, manifest, external, *, checkpoint_sha,
           manifest_sha, logit_abs_tolerance=0.002):
    """Recompute each inference with frozen external expected bytes, fail-closed."""
    start_wall,start_cpu=time.perf_counter_ns(),time.process_time_ns()
    model_raw=read_regular_file(checkpoint)
    npz_raw=read_regular_file(archive,maximum=30_000_000)
    manifest_raw=read_regular_file(manifest)
    external_raw=read_regular_file(external)
    require(_sha(model_raw)==_sha_checked(checkpoint_sha),
            "independently frozen actual model checkpoint SHA required")
    require(_sha(manifest_raw)==_sha_checked(manifest_sha),
            "independently frozen feature manifest SHA required")
    arrays=_read_tensor_archive(npz_raw)
    binding=_manifest(manifest_raw,npz_raw,arrays)
    original=_external(external_raw,_sha(model_raw),_sha(npz_raw),binding["case_ids"])
    weights,identifier=weights_from_checkpoint(model_raw)
    local=bridge_forward(weights,
       (arrays["facts"],arrays["question"],arrays["candidate"]),
       (arrays["fact_mask"],arrays["question_mask"],arrays["candidate_mask"]),
       steps=3)
    require(type(logit_abs_tolerance) is float and 0 < logit_abs_tolerance <= 0.002,
            "registered strict absolute tolerance required")
    deltas=np.abs(local.astype(np.float64)-original.astype(np.float64))
    maximum=float(np.max(deltas))
    require(maximum <= logit_abs_tolerance,
            "independent FP32 logits disagree with external frozen predictions")
    require(np.array_equal(np.argmax(local,axis=-1),np.argmax(original,axis=-1)),
            "independent top-class decision differs despite bounded numeric error")
    local64=local.astype(np.float64)
    positive=np.exp(local64[:,1]-np.logaddexp(local64[:,0],local64[:,1]))
    # Sanitize: never log tokens, raw tensors, logits, targets or row-level probabilities.
    return dict(schema=REPORT_SCHEMA,case_count=len(binding["case_ids"]),
        model_checkpoint_sha256=_sha(model_raw),
        model_tensor_digest=identifier["training_parameter_sha256"],
        model_parameter_count=identifier["parameter_count"],
        feature_manifest_sha256=_sha(manifest_raw),feature_tensor_archive_sha256=_sha(npz_raw),
        external_observations_sha256=_sha(external_raw),
        max_abs_logit_error=maximum,absolute_tolerance=logit_abs_tolerance,
        finite_probabilities=bool(np.isfinite(positive).all()),
        exact_external_model_and_case_binding=True,
        independent_tensor_forward_performed=True,
        pretrained_encoder_executed=False,source_issuer_authenticated=False,
        semantic_task_labels_read=False,future_task_quality_established=False,
        native_ndu_admitted=False,
        production_authorized=False,
        numpy_cpu_ns=time.process_time_ns()-start_cpu,
        numpy_wall_ns=time.perf_counter_ns()-start_wall,
        measurement_scope="read_prebuilt_weight_feature_and_external_logits_run_numpy_check_write_receipt_excluded")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ("checkpoint","archive","manifest","external","output"):
        p.add_argument("--"+flag,required=True,type=Path)
    p.add_argument("--checkpoint-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    args=p.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(),
            "write-once review output required")
    receipt=verify(args.checkpoint,args.archive,args.manifest,args.external,
           checkpoint_sha=args.checkpoint_sha256,manifest_sha=args.manifest_sha256)
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(receipt,stream,indent=2,sort_keys=True,allow_nan=False)
        stream.write("\n")
        stream.flush();os.fsync(stream.fileno())
    print(json.dumps({"verified":True,"schema":REPORT_SCHEMA,
                      "case_count":receipt["case_count"]},sort_keys=True))

if __name__=="__main__":main()
