"""Reproduce NumPy/Torch differential forward using 12 authentic V6 checkpoints.

The original Encoder/token cache IS NOT included: probes are deliberately
synthetic encoded FP32 tensors. The result is a numerical-conformance receipt,
not language-model performance, multi-hop generalization or NDU evidence.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import time
import zipfile

import numpy as np
import torch

from bridge_gradient_archive_replay import (V6_ZIP_SHA256, sha_file, require)
from bridge_numpy_forward import bridge_forward, weights_from_checkpoint
from bridge_numpy_reference_torch import reference

TOKEN_READER_BLOB_SHA = "ca814a855c35e3d6fcf50883dba6d66b325d5c54"
BRIDGE_READER_BLOB_SHA = "a9e7fba84fdff03e3f65c9d67bf42d59ee931cd1"
TOLERANCE = 0.0015


def probes(seed=349):
    generator=np.random.default_rng(seed)
    shape=(3,4,5,384)
    x=(generator.normal(size=shape).astype(np.float32),
       generator.normal(size=(3,3,384)).astype(np.float32),
       generator.normal(size=(3,2,384)).astype(np.float32))
    fm=np.ones((3,4,5),dtype=np.bool_); fm[:,1,-1]=False; fm[0,3,:]=False
    qm=np.ones((3,3),dtype=np.bool_);qm[1,-1]=False
    cm=np.ones((3,2),dtype=np.bool_);cm[2,-1]=False
    return x,(fm,qm,cm)


def run(archive):
    begin_wall,begin_cpu=time.perf_counter_ns(),time.process_time_ns()
    require(sha_file(archive)==V6_ZIP_SHA256,"real original frozen V6 source required")
    torch.set_num_threads(1)
    observations=[]
    maximum=0.0
    with zipfile.ZipFile(archive,"r") as z:
        features,masks=probes()
        probe_sha=sha256(b"".join(x.tobytes(order="C") for x in features+masks)).hexdigest()
        for seed in (41,47,53):
            for name in ("warmup","natural_only","replay","contrastive"):
                path=f"reader-v6-bridge/seed-{seed}/bridge/{name}.pt"
                raw=z.read(path)
                w,identity=weights_from_checkpoint(raw)
                actual=bridge_forward(w,features,masks,steps=3,return_trace=True)
                expected=reference(w,features,masks,steps=3)
                errors={"state":0.,"logits":0.,"fact_attention":0.,"token_attention":0.}
                for stage1,stage2 in zip(actual["steps"],expected):
                    for label,a,b in zip(errors,stage1,stage2):
                        err=float(np.max(np.abs(a-b)))
                        errors[label]=max(errors[label],err)
                        maximum=max(maximum,err)
                require(all(v <= TOLERANCE for v in errors.values()),
                        "NumPy/Torch reference numeric mismatch")
                observations.append(dict(seed=seed,phase=name,
                    original_checkpoint_sha256=sha256(raw).hexdigest(),
                    real_trained_parameter_digest=identity["training_parameter_sha256"],
                    parameter_count=identity["parameter_count"],
                    tensor_count=identity["tensor_count"],
                    per_axis_max_abs_error=errors,
                    native_pretrained_token_features_used=False))
    require(len(observations)==12,"twelve pretrained checkpoint identities required")
    return dict(schema="hepta.bridge.original-v6-numpy-torch-conformance.v7.3",
        date_utc="2026-10-15",original_v6_archive_sha256=V6_ZIP_SHA256,
        original_model_source_git_blobs={"token_reader.py":TOKEN_READER_BLOB_SHA,
                                           "bridge_reader.py":BRIDGE_READER_BLOB_SHA},
        synthetic_feature_probe_sha256=probe_sha,probe_case_count=3,
        tested_recurrent_depth=3,checkpoint_count=12,
        checkpoints=observations,
        numerical_max_abs_error=maximum,precommitted_max_abs_error=TOLERANCE,
        independent_numpy_forward_conformance_passed=True,
        reference_torch_source="independently_transcribed_v6_source_operator_graph",
        actual_training_executed_this_run=False,pretrained_encoder_executed=False,
        authentic_original_token_features_available=False,
        semantic_correctness_tested=False,future_task_generalization_verified=False,
        cell_split_authorized=False,native_ndu_admitted=False,model_selected=False,
        production_authorized=False,
        python_version=platform.python_version(),torch_version=str(torch.__version__),
        numpy_version=str(np.__version__),
        CPU_ns=time.process_time_ns()-begin_cpu,wall_ns=time.perf_counter_ns()-begin_wall,
        observed_cost_scope="original_zip_read_decode_synthetic_features_numpy_and_torch_forward_review")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-v6-zip',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(),"create-only report required")
    receipt=run(args.original_v6_zip)
    with args.output.open('x',encoding='utf-8') as out:
        json.dump(receipt,out,indent=2,sort_keys=True,allow_nan=False)
        out.write('\n');out.flush();os.fsync(out.fileno())
    print(json.dumps({k:receipt[k] for k in
           ('checkpoint_count','numerical_max_abs_error','independent_numpy_forward_conformance_passed')},sort_keys=True))
if __name__=='__main__': main()
