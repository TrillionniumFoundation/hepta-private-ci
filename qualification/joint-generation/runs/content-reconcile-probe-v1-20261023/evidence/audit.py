"""Reconstruct missing fixed runtime p/q, never resample/rerender/rescore models."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import traceback

import numpy as np
from PIL import Image

from content_reconcile.policy import TAUS,compile_joint,repair
from content_reconcile.run import identity,PRIOR,SEEDS
from data import parse_caption,templates
from independent.accounting import WorkLedger
from independent.inference import FrozenGenerator
from independent.run import cpu_clock,write_json
from model import JointModel


OUT=Path(__file__).resolve().parent
RUN=OUT.parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_identity():
    files=[OUT/"audit.py",OUT/"PROTOCOL.md",RUN/"build.json",RUN/"behavior.json",PRIOR/"train-inputs.npz"]
    files+=sorted((RUN/"models").glob("*.npz"))+sorted(RUN.glob("R-*.npz"))+sorted(RUN.glob("service-*.json"))
    return {"original_identity":identity(),"files":{str(p):sha(p) for p in files}}


def audit(freeze):
    if audit_identity()!=json.loads(Path(freeze).read_text())["identity"]:raise ValueError("audit identity changed")
    build=json.loads((RUN/"build.json").read_text())
    with np.load(PRIOR/"train-inputs.npz",allow_pickle=False) as data:
        fit=data["fit_full"].copy()
    x=fit[np.linspace(0,len(fit)-1,64,dtype=int)]
    reference=templates()
    common_CPU=cpu_clock()
    costs,ledgers,checks={},{},{}
    for family in ("H","A"):
        old_units=build["ledgers"][family]["consumed_units"]-build["ledgers"][family]["stages"]["inherited_nine_candidate_build"]["consumed_units"]
        ledgers[family]=WorkLedger(family+"-audit",250_000_000-old_units)
        costs[family]={"audit_shared_CPU":common_CPU,"audit_active_CPU":0.,"original_added_CPU":build["costs"][family]["added_CPU"]}
        checks[family]=[]
    status=0;error=None
    try:
        for si,seed in enumerate(SEEDS):
            families=("H","A") if si%2==0 else ("A","H")
            for family in families:
                start=cpu_clock();ledger=ledgers[family]
                try:
                    model=JointModel.load(RUN/"models"/f"{family}-{seed}.npz")
                    generator=FrozenGenerator(model,prepare_low=False)
                    p,q=generator.forward_full(x,ledger)
                    archived={"p":p,"q":q}
                    joints={}
                    for tau in TAUS:
                        joint,_,_,_=compile_joint(p,q,tau,ledger,"runtime_Q_reconstruction")
                        joints[tau]=joint;archived[tau+"/Q"]=joint
                    with np.load(RUN/f"R-{seed}.npz",allow_pickle=False) as table:image_sem=table["image_sem"].copy()
                    reports=[]
                    for path in sorted(RUN.glob(f"service-{family}-{seed}-*.json")):
                        report=json.loads(path.read_text())
                        pairs=np.asarray(report["final_pairs"],dtype=np.int64)
                        if report["form"]=="compiled":
                            if report["original_pairs"] is not None or report["actions"] is not None:raise ValueError("invented Q ancestry")
                            support=joints[report["tau"]][np.arange(64),pairs[:,0],pairs[:,1]]
                            if np.any(support<=0):raise ValueError("recorded static draw outside its reconstructed support")
                            ledger.charge_kernel("support_check","positive_Q",compare_ops=64)
                        else:
                            original=np.asarray(report["original_pairs"],dtype=np.int64)
                            fixed,actions=repair(p,q,original,report["tau"],ledger,"recorded_action_check")
                            if not np.array_equal(fixed,pairs) or not np.array_equal(actions,report["actions"]):
                                raise ValueError("recorded repair does not follow frozen p/q rule")
                        for pair,output in zip(pairs.tolist(),report["outputs"]):
                            png=base64.b64decode(output["png_base64"])
                            if hashlib.sha256(png).hexdigest()!=output["png_sha256"]:raise ValueError("PNG hash mismatch")
                            if output["choices"]!={"text":pair[0],"image":pair[1]} or parse_caption(output["caption"])!=pair[0]:
                                raise ValueError("output code/caption mismatch")
                            pixels=np.asarray(Image.open(io.BytesIO(png)).convert("RGB"),dtype=np.float64).reshape(-1)/255
                            observed=int(np.mean((reference-pixels)**2,axis=1).argmin())
                            if observed!=image_sem[pair[1]]:raise ValueError("recorded pixels disagree with original decoded-code semantics")
                            ledger.charge_kernel("recorded_PNG_observation","template_distance",scalar_ops=3*12*192-12,
                                div_ops=192+12,compare_ops=11,counts={"recorded_PNGs_checked":1})
                            ledger.record("recorded_PNG_observation",PNG_bytes_read=len(png))
                        reports.append({"profile":report["profile"],"recorded_requests_checked":64,"same_source_receipt_sha256":sha(path)})
                    if len(reports)!=6:raise ValueError("not all six recorded profiles checked")
                    target=OUT/f"runtime-probabilities-{family}-{seed}.npz"
                    np.savez_compressed(target,**archived)
                    ledger.record("audit_export",serialized_bytes=target.stat().st_size,captured_runtime_probability_rows=64)
                    checks[family].append({"seed":seed,"profiles":reports,"capture_sha256":sha(target)})
                finally:costs[family]["audit_active_CPU"]+=cpu_clock()-start
                if common_CPU+costs[family]["audit_active_CPU"]+costs[family]["original_added_CPU"]>3:
                    raise RuntimeError("remaining added CPU cap exceeded")
        scheduler=max(0.,cpu_clock()-common_CPU-sum(c["audit_active_CPU"] for c in costs.values()))
        for family in ("H","A"):
            cost=costs[family]
            cost["audit_scheduler_CPU"]=scheduler
            cost["audit_added_CPU"]=common_CPU+cost["audit_active_CPU"]+scheduler
            cost["combined_added_CPU"]=cost["original_added_CPU"]+cost["audit_added_CPU"]
            cost["combined_complete_CPU"]=build["costs"][family]["inherited_CPU"]+cost["combined_added_CPU"]
            cost["combined_complete_units"]=build["ledgers"][family]["consumed_units"]+ledgers[family].consumed_units
            inherited=build["ledgers"][family]["stages"]["inherited_nine_candidate_build"]["consumed_units"]
            cost["combined_added_units"]=cost["combined_complete_units"]-inherited
            if cost["combined_added_CPU"]>3 or cost["combined_complete_CPU"]>10 or cost["combined_added_units"]>250_000_000 or cost["combined_complete_units"]>12_000_000_000:
                raise RuntimeError("combined audit/probe cap exceeded")
    except Exception:status=1;error=traceback.format_exc()
    result={"exit_code":status,"costs":costs,"audit_ledgers":{f:l.snapshot() for f,l in ledgers.items()},"checks":checks,
        "error":error,"freeze_sha256":sha(freeze),"new_service_calls":0,"new_behavior_sampling_draws":0,"new_model_renders":0,
        "extra_capture_forward_rows_per_family":192,"original_service_requests_per_family":1152,
        "scope":"fixed evidence reconstruction; no primary/greedy quality rescore, new sampling, rerendering or timing rerun",
        "actual_audit_CPU_before_receipt":cpu_clock()}
    write_json(OUT/"audit-result.json",result)
    print(json.dumps({"exit_code":status,"costs":costs,"error":error}));return status


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("freeze","run"));parser.add_argument("--freeze",required=True)
    args=parser.parse_args()
    if args.action=="freeze":write_json(args.freeze,{"identity":audit_identity(),"scope":"only reconstruction of omitted runtime evidence, no new probe"})
    else:raise SystemExit(audit(args.freeze))
