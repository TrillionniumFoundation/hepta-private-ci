"""Pre-fit semantic, physical-prefix and official-encoder contract checks."""

import copy
import argparse
import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import torch

from . import encoder


def run(out):
    torch.set_num_threads(1)
    checks=[]
    records=json.loads((encoder.HERE/"TRAIN_COHORT.json").read_text())["records"]
    labels=encoder.target_guard(records,"train")
    checks.append(dict(name="train_binary_sentence_guard",passed=len(labels)==288 and np.bincount(labels).tolist()==[144,144]))
    for name,kind in [("refuse_emotion_as_sentence",0),("refuse_reversed_sentence_labels",1),("refuse_actor_alias",2)]:
        changed=copy.deepcopy(records)
        for row in changed:
            if kind==0:row["sentence_target"]=row["original_emotion_label"]
            elif kind==1:row["sentence_target"]=1-row["sentence_target"]
            else:row["actor"]="9999"
        try:encoder.target_guard(changed,"train");passed=False
        except ValueError:passed=True
        checks.append(dict(name=name,passed=passed))
    rng=np.random.default_rng(20261112)
    rate=44100;wave=rng.normal(0,.02,3*rate).astype(np.float32)
    timestamps=np.arange(76,dtype=float)*.04+.04
    accepted,detail=encoder.accepted_pcm(wave,timestamps,.013,rate)
    changed=wave.copy();changed[:detail["native_lo"]]=rng.normal(0,50,detail["native_lo"])
    changed[detail["native_hi"]:]=rng.normal(0,50,len(wave)-detail["native_hi"])
    revised,_=encoder.accepted_pcm(changed,timestamps,.013,rate)
    checks.append(dict(name="crop_before_resampling_future_and_past_isolation",passed=np.array_equal(accepted,revised),detail=detail))
    try:encoder.accepted_pcm(wave[:1000],timestamps,.013,rate);passed=False
    except ValueError:passed=True
    checks.append(dict(name="incomplete_native_prefix_refused",passed=passed))
    for module,expected in [("torchaudio.pipelines._wav2vec2.impl","d60fa8adb94e92e1a479fe94e09f521d0fe50056"),
                            ("torchaudio.pipelines._wav2vec2.utils","e690e8103c7a47a01d719e746e6c98a9c7f6c8db")]:
        content=Path(importlib.import_module(module).__file__).read_bytes()
        actual=hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()
        checks.append(dict(name=module+"/official_git_blob",passed=actual==expected,expected=expected,actual=actual))
    model=encoder.FrozenSpeech()
    features,ctc,transcript=model.infer(accepted)
    again,ctc_again,_=model.infer(revised)
    with torch.inference_mode():
        official,_=model.model(torch.from_numpy(accepted[None]))
    error=float(np.max(np.abs(official[0].numpy()-ctc)))
    checks.append(dict(name="official_forward_equals_extracted_final_aux",passed=error<=1e-6,max_error=error))
    checks.append(dict(name="frozen_descriptor_dimensions",passed=features.shape==(1652,) and ctc.shape==(49,29),
                       feature_shape=list(features.shape),ctc_shape=list(ctc.shape)))
    checks.append(dict(name="repeated_accepted_prefix_identical",passed=np.array_equal(features,again) and np.array_equal(ctc,ctc_again)))
    checks.append(dict(name="encoder_frozen_eval",passed=not model.model.training and all(not p.requires_grad for p in model.model.parameters()),
                       parameters=sum(p.numel() for p in model.model.parameters())))
    for name,array in [("long_input_refused",np.zeros(16001,np.float32)),("nonfinite_input_refused",np.full(16000,np.nan,np.float32))]:
        try:model.infer(array);passed=False
        except ValueError:passed=True
        checks.append(dict(name=name,passed=passed))
    result=dict(schema="hcsn.audio.pretrained.preflight.v1",passed=all(r["passed"] for r in checks),checks=checks,
        source_sha256={str(p.relative_to(encoder.ROOT)):encoder.sha(p) for p in [Path(__file__),Path(encoder.__file__)]},
        checkpoint_sha256=encoder.CHECKPOINT_SHA256,crema_waveform_loaded=False,development_loaded=False,target_head_fitted=False)
    encoder.write(out,result)
    print(json.dumps(dict(passed=result["passed"],checks=len(checks))))
    if not result["passed"]:raise RuntimeError("Pretrained audio preflight failed")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--out",type=Path,default=encoder.HERE/"CHECKS_FINAL.json")
    run(parser.parse_args().out)
