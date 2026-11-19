"""Six concrete profiles. Identity aliases share ONE real call, never three."""

import base64
import hashlib
import io
import json
import time

import numpy as np
from PIL import Image

from content_reconcile.policy import compile_joint, repair, sample_joint, sample_original
from data import caption
from independent.accounting import WorkLedger
from independent.evaluation import full_reference_work
from model import JointModel


PROFILES=(("Q_zero","zero","compiled"),("T_zero","zero","two_stage"),
          ("Q_log2","log2","compiled"),("T_log2","log2","two_stage"),
          ("Q_infinity","infinity","compiled"),("identity","infinity","factorized"))
IDENTITY_ALIASES=("original_factorized_KEEP","two_stage_tau_infinity","efficient_static_identity")


def render_pairs(generator,pairs,ledger):
    n=len(pairs)
    ledger.decoder("output",rows=n,pixels=192)
    ledger.charge_kernel("output","quantize",scalar_ops=384*n,compare_ops=384*n)
    images=JointModel.decode_images(generator,pairs[:,1]).reshape(n,8,8,3)
    images=np.rint(np.clip(images,0,1)*255).astype(np.uint8)
    outputs=[]
    for pair,image in zip(pairs.tolist(),images):
        stream=io.BytesIO()
        Image.fromarray(image).save(stream,format="PNG")
        png=stream.getvalue()
        entry={"caption":caption(pair[0]),"choices":{"text":pair[0],"image":pair[1]},
               "png_sha256":hashlib.sha256(png).hexdigest(),"png_base64":base64.b64encode(png).decode("ascii")}
        payload=json.dumps(entry,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        ledger.record("output",output_bytes=len(png)+len(payload),serialized_requests=1,png_renders=1)
        outputs.append(entry)
    return outputs


def execute(generator,x,profile,seed):
    name,tau,form=profile
    n=len(x)
    reference=full_reference_work(generator)
    ledger=WorkLedger("runtime-"+name,total_cap=n*2*reference)
    # Full per-request envelope including at most132 exact comparison fallbacks.
    # Admission only: unexecuted fallback work is never charged.
    envelope=reference+(144*35+144*3+132*10 if form=="compiled" else 100)
    if envelope>2*reference: raise RuntimeError("per-request envelope exceeds original cap")
    started=time.process_time_ns()
    p,q=generator.forward_full(x,ledger)
    rng=np.random.default_rng(seed)
    original,actions=None,None
    if form=="compiled":
        joint,_,_,_=compile_joint(p,q,tau,ledger,"runtime_Q")
        pairs=sample_joint(joint,rng,ledger,"runtime_sample")
    else:
        original=sample_original(p,q,rng,ledger,"runtime_sample")
        pairs=original
        if tau!="infinity": pairs,actions=repair(p,q,original,tau,ledger,"runtime_repair")
        else: actions=np.zeros(n,dtype=np.int8)
    outputs=render_pairs(generator,pairs,ledger)
    elapsed=time.process_time_ns()-started
    if name=="identity" and ledger.consumed_units!=n*reference:
        raise RuntimeError("identity sampler differs from original useful work inventory")
    return {"profile":name,"tau":tau,"form":form,"rows":n,"CPU_ns":elapsed,"work_units":ledger.consumed_units,
        "ledger":ledger.snapshot(),"original_pairs":None if original is None else original.tolist(),
        "actions":None if actions is None else actions.tolist(),"final_pairs":pairs.tolist(),"outputs":outputs,
        "original_pairs_semantics":"not defined for Q sampling; ancestry is not fabricated" if original is None else "actual first-stage independent draws",
        "aliases":list(IDENTITY_ALIASES) if name=="identity" else [],
        "request_cap_units":2*reference,"per_request_inventory_envelope":envelope,"reference_units":reference,
        "sampler_seed":seed,"cap_violations":0}
