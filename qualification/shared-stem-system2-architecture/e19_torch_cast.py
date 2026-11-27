"""E19 real PyTorch CPU dtype-cast control on ORIGINAL archived logits.

No pretrained weights loaded, no BF16 Encoder/Reader forward. This physically
executes Torch CPU FP32->BF16/FP16 casts and reference group centering.
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from e14_multirc_route import ARMS, ARCHIVE_SHA, read_prelabel, write_once
from e19_precision_pack import encode_group,group_source,margins_for


def actual_torch_casts(obs):
    import torch
    source_groups=group_source(obs)
    counters={"original_questions":0,"original_candidates":0,
              "compared_numeric_scalars":0,"mismatch_count":0}
    with torch.no_grad():
        for _,indices in source_groups:
            counters["original_questions"]+=1
            counters["original_candidates"]+=len(indices)
            for arm in ARMS:
                logits=margins_for(obs,arm,indices)
                expected=encode_group(logits)
                raw=torch.tensor(logits,dtype=torch.float32,device="cpu")
                if tuple(raw.shape)!=(len(indices),2):
                    raise ValueError("incomplete original batch geometry")
                margins=raw[:,1]-raw[:,0]
                base=margins.double().mean().float()
                for kind, torch_kind in (("bf16",torch.bfloat16),("fp16",torch.float16)):
                    # The first arm actually CASTS each two-logit value to a
                    # low-precision tensor. Subtraction is done AFTER cast.
                    low_pair=raw.to(torch_kind)
                    before=(low_pair.float()[:,1]-low_pair.float()[:,0]).tolist()
                    # Next arm performs real FP32 subtraction first, then cast.
                    after=margins.to(torch_kind).float().tolist()
                    # Here the signed margin is centered in FP32, then
                    # physically cast to low precision. Reconstruct in FP32.
                    centered=((margins-base).to(torch_kind).float()+base).tolist()
                    for profile, actual in (
                        (f"{kind}_two_logits_then_sub",before),
                        (f"{kind}_margin_after_sub",after),
                        (f"{kind}_question_centered_with_fp32_anchor",centered),
                    ):
                        reference=expected[profile]
                        for got,want in zip(actual,reference,strict=True):
                            counters["compared_numeric_scalars"]+=1
                            if float(got)!=float(want):
                                counters["mismatch_count"]+=1
                                raise ValueError("Torch hardware CPU dtype-cast/reference numerical drift")
    if counters["original_questions"]!=8 or counters["original_candidates"]!=33:
        raise ValueError("incomplete real source groups")
    if counters["compared_numeric_scalars"]!=33*4*2*3:
        raise ValueError("incomplete 792 physical CPU comparisons")
    return {"schema":"hepta.e19.original-logit-cpu-torch-lowprecision-cast.v1",
            "authority":"DENY_ALL", "original_archive_sha256":ARCHIVE_SHA,
            "device":"cpu", "torch":str(torch.__version__),
            "physical_fp32_to_bf16_fp16_tensor_casts_executed":True,
            "no_original_model_weights_loaded":True,
            "no_pretrained_encoder_or_reader_forward":True,
            "numeric_roundtrip_comparisons":counters["compared_numeric_scalars"],
            "numeric_mismatches":counters["mismatch_count"],
            "all_results_independent_from_human_labels":True,
            "actual_BF16_model_quality_or_serving_latency_measured":False,
            "production_accepted":False}


def run(archive, output):
    return write_once(output,actual_torch_casts(read_prelabel(archive)))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    print(run(args.archive,args.output),"DENY_ALL")
