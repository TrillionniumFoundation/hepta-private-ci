"""Real-model V7.5 candidate prelabel seal; never a replacement for V7.4 training.

Two processes: (1) this Torch/actual original TokenBank *producer* after all
nine V7.4 models are already saved, (2) the independent NumPy reviewer. No
missing-Encoder synthetic fallback. Results are source/train-only and DENY_ALL.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import io
import json
import math
import time
import zipfile

from bridge_candidate_v75 import (SCHEMA, SEEDS, ARMS, BATCHES, _mkdir, _write,
    _json, _digest, seal_features, seal_logits, seal_scope_receipt)
from bridge_gradient_archive_replay import decode_fp32_checkpoint, require
from bridge_portable_v74 import (originals, material_preflight, cache_preflight,
    _cases, source_id, canonical, sha)
from bridge_portable_v74_review import evaluate as v74_evaluate


def seal_actual(v4,v5,v6,snapshot,run,output,*,cache=None):
    """Validate real historical material, then separately seal all 9 logits."""
    started=time.perf_counter_ns()
    archive=originals(v4,v5,v6)
    # A missing 195MB pretrained source fails before expensive candidate
    # receipt replay and before creating any attempted seal directories.
    material=material_preflight(snapshot,archive["model"])
    require(material["ready"], "original public pretrained Granite97 material absent: deny V7.5")
    # Fully check all nine authentic *already completed* train receipts next.
    previous=v74_evaluate(run,archive)
    require(previous["status"]=="SOURCE_AND_NUMERIC_RECEIPTS_CONSISTENT_NOT_PRODUCTION",
            "genuine prior nine-arm candidate stage did not complete")
    original_cache=cache_preflight(cache,archive["v5_cache_sha256"]) if cache else None
    require(cache is None or original_cache["exact"],
            "explicit original TokenBank must be byte-identical")
    # Torch and NumPy import ONLY after positive source and material preflight.
    import numpy as np
    import torch
    from token_features import TokenBank
    from bridge_campaign_utils import build_reader
    from bridge_numpy_forward import weights_from_checkpoint, bridge_forward
    from token_campaign_utils import infer
    from group_loop import parameter_digest as typed_digest
    from group_encoder import file_digest

    torch.set_num_threads(1)
    rows=archive["source"]["reader_train"]
    cases=_cases(rows)
    bank=TokenBank.from_snapshot(snapshot,batch_size=16,chunk_tokens=64)
    require(bank.preprocess_sha256==archive["original_preprocess_sha256"],
            "original public TokenBank ABI mismatch")
    if original_cache and original_cache["exact"]:
        bank.restore_local(cache)
        origin="exact_historical_cache"
    else:
        bank.register(cases)
        origin="new_pretrained_physical_encoding"

    # Original 3 warmups must be verified on these actual bytes *before* any
    # claim that future candidate logits use the historical source semantics.
    previous_original={}
    with zipfile.ZipFile(v6,"r") as z:
        for seed in SEEDS:
            root=f"reader-v6-bridge/seed-{seed}/bridge/"
            raw=z.read(root+"warmup.pt")
            weights,meta=weights_from_checkpoint(raw)
            require(meta["execution_parameter_sha256"]==
                    archive["warmup"][seed]["execution_parameter_sha256"],
                    "historical warmup tensor source wrong")
            saved=json.loads(z.read(root+"warmup-binding-train.json"))
            require(saved["case_ids"] == [c.case_id for c in cases],
                    "historical warmup case IDs differ")
            calc=[]
            for i in range(BATCHES):
                data=bank.batch(cases[i*16:(i+1)*16])
                inputs=data.features()
                arrays=tuple(v.detach().cpu().numpy().copy() for v in inputs)
                logits=bridge_forward(weights,arrays[:3],arrays[3:],steps=3)
                safe=np.asarray(logits,dtype=np.float64)
                p=np.exp(safe[:,1]-np.logaddexp(safe[:,0],safe[:,1]))
                calc.extend(p.tolist())
            historic=saved["probabilities"]
            require(len(historic)==len(calc)==128,"original old prediction evidence incomplete")
            drift=max(abs(a-b) for a,b in zip(calc,historic))
            flips=sum((a>.5)!=(b>.5) for a,b in zip(calc,historic))
            require(drift<=.001 and flips==0,
                    "original Granite TokenBank reencoding does not reproduce frozen V6 outputs")
            previous_original[str(seed)]=dict(old_cases=128,max_absolute_deviation=drift,
                prediction_class_flips=flips,
                original_seed_warmup_checkpoint_sha256=archive["warmup"][seed]["model_file_sha256"])

    # Build one shared physical feature bank for all nine *frozen* candidates.
    output=Path(output)
    _mkdir(output)
    feature_dir=output/"features"
    original_model=archive["model"]
    model_sha=original_model["sha256"]["model.safetensors"]
    require(bank.encoder.material==original_model,
            "original material identity changed during real encoding")
    source_receipt=seal_features(feature_dir,rows,
        (bank.batch(cases[i*16:(i+1)*16]) for i in range(BATCHES)),
        model_sha=model_sha,tokenizer_sha=bank.encoder.tokenizer_digest,
        preprocess_sha=bank.preprocess_sha256,
        principal_sha=_digest(b"hepta.bridge.v75.source-bound.research-principal"),
        purpose_sha=_digest(b"hepta.bridge.v75.original-train.numeric-review"),
        origin=origin)
    frozen={}
    for seed in SEEDS:
        for arm in ARMS:
            folder=Path(run)/f"seed-{seed}"/arm
            manifest=json.loads((folder/"candidate-model.json").read_text())
            weights_path=folder/"candidate.pt"
            require(manifest["seed"]==seed and manifest["architecture"]["arm"]=="bridge"
                    and manifest["initial_execution_parameter_sha256"]==
                        archive["warmup"][seed]["execution_parameter_sha256"]
                    and file_digest(weights_path)==manifest["file_sha256"],
                    "frozen candidate weights from wrong original V7.4 lineage")
            model=build_reader("bridge",seed)
            model.load_state_dict(torch.load(weights_path,map_location="cpu",weights_only=True),strict=True)
            model.eval().requires_grad_(False)
            require(typed_digest(model)==manifest["execution_parameter_sha256"],
                    "candidate model tensor values mismatch")
            def real_torch_inference(arrs):
                inputs=tuple(torch.from_numpy(arrs[name].copy()) for name in
                   ("facts","question","candidate","fact_mask","question_mask","candidate_mask"))
                with torch.no_grad():
                    result=model(*inputs,steps=3)
                return result.detach().cpu().numpy().copy()
            dest=output/"predictions"/f"seed-{seed}"/arm
            dest.parent.mkdir(parents=True,exist_ok=True)
            result=seal_logits(feature_dir,dest,seed=seed,arm=arm,
                               checkpoint=weights_path,torch_predict=real_torch_inference)
            frozen[f"{seed}/{arm}"]=result["checkpoint_sha256"]
    assembled=seal_scope_receipt(feature_dir,output/"predictions",
                     output=output/"prelabel-assembly.json",original_rows=rows)
    _write(output/"completed.json",_json(dict(
         schema="hepta.bridge.v75.real-prelabel.completed.v1",
         status="CANDIDATE_LOGITS_SEALED_NOT_SCORED",
         original_v74_source_status=previous["status"],
         source_origin=origin,source_index_sha256=_digest((feature_dir/"index.json").read_bytes()),
         eight_shared_feature_batches=True,torch_candidate_forward_batches=9*BATCHES,
         nine_model_checkpoint_sha256=frozen,old_warmup_original_granite_parity=previous_original,
         producer_physical_pretrained_encoder_batches=bank.forward_batches,
         producer_encoder_cpu_ns=bank.cpu_ns,
         producer_runtime_wall_ns=time.perf_counter_ns()-started,
         independent_future_task_utility_proven=False,
         model_selection_authorized=False,ndu_authority=False,cell_split_authorized=False,
         production_authorized=False)))
    return assembled


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("v4","v5","v6","snapshot","run","output","cache"):
        parser.add_argument("--"+name,type=Path,required=name!="cache")
    args=parser.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(),
            "V7.5 producer output must be new, no hidden resume")
    seal_actual(args.v4,args.v5,args.v6,args.snapshot,args.run,args.output,cache=args.cache)


if __name__=="__main__":
    main()
