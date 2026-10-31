"""Exercise the exact primary deployment/CAS path on eight old validation cases."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import numpy as np
import torch

from ..field_bridge_20261027.audit import reconstruct_features
from ..field_bridge_20261027.run import setup, write_json, digest
from ..v6.data import make_batch
from ..v6.observer import observe_tensors
from .learning import make_model
from .native_fast import NativeFastBridge
from .primary_common import P
from .primary_evaluate import deploy_batch
from .primary_media import MediaStore, read_media
from .primary_runtime import fit_controllers, select


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",required=True)
    parser.add_argument("--native",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    corpus,observers,originals,_=setup(args,audit=True)
    batch=make_batch(corpus,"validation",8,271027,offset=700,corruption="heavy_noise")
    model=make_model(originals[17],17,P["recipe"])
    rng=np.random.default_rng(271031)
    def synthetic(n,role):
        x0,x1=rng.random((n,8)),rng.random((n,8))
        values=np.column_stack((x0[:,0],x1[:,1],x0[:,2]+x1[:,2],x1[:,3],x0[:,4]))*.2
        return dict(x0=x0,x1=x1,returns=values,role=role)
    streams,native_streams,counts={},{},{}
    media=MediaStore(out/"media.zip")
    with NativeFastBridge(args.native,P["native_library_sha256"]) as bridge:
        fitted=fit_controllers(synthetic(32,"train"),synthetic(16,"development"),bridge,"contract")
        original_step=model.step
        step_examples=[]
        def counted(state,action):
            step_examples.append((action,len(state.h)))
            return original_step(state,action)
        with patch.object(model,"step",side_effect=counted), patch(
                "experiments.multimodal_output_portfolio.field_bridge_20261027.task.build_bank",
                side_effect=AssertionError("No counterfactual bank during deployment")):
            for control in ("fixed","native","history","reset"):
                rows,native=io.StringIO(),io.StringIO()
                readout=None if control=="fixed" else fitted["models"]["native" if control=="reset" else control]
                previous=len(step_examples)
                count=deploy_batch(model,readout,control,4,bridge,observers,batch,17003,
                    dict(seed=17,arm="contract_"+control,split="validation",corruption="heavy_noise",
                         batch_start=0,batch_seed=271027),out/"temporary",media,rows,native)
                records=[json.loads(line) for line in rows.getvalue().splitlines()]
                assert count==len(records)==8 and not (out/"temporary").exists()
                assert sum(n for _,n in step_examples[previous:])==8+sum(r["action"]!=0 for r in records)
                assert all(r["resources"]["finish_unchosen_continuations_executed"]==0 for r in records)
                streams[control]=records;native_streams[control]=native.getvalue()
                counts[control]=len(native.getvalue().splitlines())
    info=media.close()
    maxima={"feature":0.,"score":0.}
    with zipfile.ZipFile(out/"media.zip") as archive:
        for control,records in streams.items():
            restored=[[read_media(archive,r["artifacts"][stage]) for r in records] for stage in range(3)]
            for stage in (0,1):
                x=reconstruct_features(observers["reward"],batch.observation,restored[stage],
                                       [r["artifacts"][stage] for r in records])
                error=float(np.max(np.abs(x-np.asarray([r[f"public_features{stage}"] for r in records]))))
                maxima["feature"]=max(maxima["feature"],error)
                assert error==0
            pixels=torch.cat([x[0] for x in restored[2]]);captions=[x[1] for x in restored[2]]
            for name,observer in observers.items():
                rescored=observe_tensors(observer,pixels,captions,batch.target.pixels,batch.target.labels)
                assert rescored==[r[name] for r in records]
            for r in records:
                raw=r["decision_bytes_utf8"].encode()
                assert hashlib.sha256(raw).hexdigest()==r["decision_sha256"]
                assert json.loads(raw)==r["decision"]
                decision=r["decision"]["committed_monotonic_ns"]
                assert max(a["readback_monotonic_ns"] for a in r["artifacts"][:2])<decision<r["artifacts"][2]["readback_monotonic_ns"]
            if control in {"native","history","reset"}:
                with NativeFastBridge(args.native,P["native_library_sha256"]) as bridge:
                    expected,_=select(fitted["models"]["native" if control=="reset" else control],
                        np.array([r["public_features0"] for r in records]),np.array([r["public_features1"] for r in records]),
                        bridge=bridge,case_prefix="contract-replay",reset=control=="reset")
                    assert expected.tolist()==[r["action"] for r in records]
    assert counts=={"fixed":0,"native":8,"history":0,"reset":8}
    assert info["logical_files"]==192 and info["unique_files"]<info["logical_files"]
    write_json(out/"DUPLICATE_STORAGE_IDENTITY.json",info)
    write_json(out/"PRIMARY_DEPLOYMENT_CONTRACT.json",{
        "schema":"hepta.field-bridge.v2.primary-deployment-contract.1","passed":True,
        "source_sha256":digest(__file__),"rows":32,"old_validation_source_ids":batch.source_ids,
        "synthetic_fit_labels":True,"reserved_test_retention_scored":False,
        "actual_selected_continuations_only":True,"exact_preview_and_score_reconstruction":True,
        "native_and_history_replay_actions_exact":True,"native_receipt_rows":counts,
        "decision_bytes_and_chronology_verified":True,"media":info,"max_discrepancies":maxima})
    print(json.dumps({"passed":True,"rows":32,"unique_media":info["unique_files"],"max_discrepancies":maxima}))


if __name__=="__main__":
    main()
