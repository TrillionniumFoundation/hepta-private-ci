"""Close previously explicit interface gaps using the byte-pinned old V3 API.

Accepted-prefix feature reconstruction uses the inherited V3/V8 implementation.
The new direct reader is still evaluated by independent NumPy formulas. This
supplement does not replace the original independent partial reconstruction.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from .av_reconstruction import reader


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path):
    with gzip.open(path,"rt") as stream:return [json.loads(line) for line in stream]


def prefix_map(run):
    a,v=0,0;mapping={}
    for event in run["execution"]["events"]:
        if event.get("status")!="accepted":continue
        _,modality,level=event["action"].split(":")
        if modality=="audio":a=int(level)
        else:v=int(level)
        mapping[event["after"]]=(a,v)
    return mapping,(a,v)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--candidate",type=Path,required=True)
    parser.add_argument("--constant",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();base=args.candidate
    import torch
    from scipy.special import expit
    from experiments.hcsn_v8_execution_20261101.frontend import legacy_v3,replay
    legacy_v3.RECOVERED=base/"assets";replay.DATA=base/"assets/data"
    plan=json.loads((base/"PLAN.json").read_text())
    fits=json.loads((base/"FIT.json").read_text())
    for path,digest in plan["input_sha256"].items():assert sha(base/path)==digest
    main_rows=load_rows(base/"TRACES.jsonl.gz")
    constant_rows=load_rows(args.constant/"TRACES.jsonl.gz")
    data={};heads={};packets={};models={}
    for task in plan["tasks"]:
        data[task]=replay.legacy_data(task,"test")
        identity=json.loads((base/task/"HISTORICAL_INPUTS.json").read_text())
        assert identity["array_sha256"]==data[task]["metadata"]["array_sha256"]
        assert identity["source_ids"]==data[task]["ids"].astype(str).tolist()
        assert identity["content_sha256"]==hashlib.sha256(np.ascontiguousarray(data[task]["x"]).tobytes()).hexdigest()
        heads[task]=legacy_v3.LegacyV3Head(task)
    known_posteriors=set();known_final={}
    for run in main_rows:
        mapping,final=prefix_map(run)
        known_final[run["task"],run["index"],*final]=run["execution"]["output"]["probabilities"]
        known_posteriors.add((run["task"],run["index"],*final))
        if run["family"]!="direct":
            for update in run["updates"]:
                packet=update["row"] if run["family"]=="history" else update["packet"]
                a,v=int(round(packet[38]*3)),int(round(packet[39]*3))
                known_posteriors.add((run["task"],run["index"],a,v))
    def content_and_packet(task,index,a,v):
        key=task,index,a,v
        if key not in packets:
            content=replay.populated_cache(data[task],index,a,v)
            p=heads[task].classify(content)
            vectors=[np.zeros(16) if obs is None else np.asarray(obs.aligned) for obs in (content.audio,content.video)]
            packet=np.r_[*vectors,p,np.zeros(6-len(p)),a/3,v/3,0.]
            packets[key]=(p,packet)
        return packets[key]
    direct=[]
    for run in main_rows:
        if run["family"]!="direct":continue
        mapping,_=prefix_map(run)
        for decision in run["execution"]["decisions"]:
            if decision.get("mode")=="fixed":continue
            a,v=mapping[decision["content_fingerprint"]]
            key=run["task"],run["index"],a,v
            if key in known_posteriors:continue
            task,seed=run["task"],run["seed"]
            model_key=task,seed
            if model_key not in models:
                path=base/task/"fits"/f"direct-{seed}-selected.pt"
                assert sha(path)==fits[task][str(seed)]["direct"]["checkpoint_sha256"]
                models[model_key]={name:value.detach().cpu().numpy() for name,value in torch.load(path,map_location="cpu",weights_only=True).items()}
            _,packet=content_and_packet(task,run["index"],a,v)
            probability=expit(reader(models[model_key],"direct",packet,np.zeros(32),[]))
            error=0.
            for candidate in decision["plans"]:
                ga,gv=a,v
                for action in candidate["plan"].split("/"):
                    fields=action.split(":")
                    if fields[0]=="READ":
                        if fields[1]=="audio":ga=int(fields[2])
                        else:gv=int(fields[2])
                error=max(error,abs(float(probability[ga*4+gv])-candidate["correctness"]))
            assert error<2e-9
            direct.append({"task":task,"seed":seed,"index":run["index"],"levels":[a,v],"maximum_reader_probability_error":error})
    constant=[]
    for run in constant_rows:
        _,final=prefix_map(run)
        key=run["task"],run["index"],*final
        if key in known_final:continue
        probability,_=content_and_packet(run["task"],run["index"],*final)
        actual=run["execution"]["output"]["probabilities"]
        np.testing.assert_array_equal(probability,actual)
        constant.append({"task":run["task"],"index":run["index"],"levels":list(final),"common_head_probabilities_exact":True})
    assert len(direct)==4 and len(constant)==6
    sources={}
    for name,module in sys.modules.items():
        path=getattr(module,"__file__",None)
        if name.startswith("experiments.") and path and path.endswith(".py"):
            sources[path]=sha(Path(path))
    report={"schema":"hcsn-v10-AV-interface-gap-supplement.v1","previous_partial_results_preserved":True,
        "four_direct_decisions_closed":direct,"six_constant_head_endpoints_closed":constant,
        "new_model_state_and_reader_math_independent_NumPy":True,
        "old_V3_prefix_and_head_implementation_reused":True,"upstream_implementation_sha256":sources,
        "raw_media_or_new_recording_confirmation":False,
        "scope":"Previously missing accepted-cache interfaces reconstructed from copied feature NPZ and pinned old V3/V8 APIs; this is not a second independent media encoder implementation",
        "source_sha256":sha(Path(__file__))}
    with args.output.open("x") as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps({"direct_interface_gaps_closed":len(direct),"constant_endpoint_gaps_closed":len(constant)},indent=2))


if __name__=="__main__":main()
