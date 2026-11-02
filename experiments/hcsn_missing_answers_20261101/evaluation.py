"""Split dev calibration and confirmation; require publication between phases."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import time

import numpy as np
import torch

from . import campaign as c


def setup(out, baseline):
    protocol=c.load(out/"PROTOCOL.json"); candidates=c.load(out/"ALL_CHECKPOINTS.json")
    originals=c.load(baseline/"ALL_CHECKPOINTS.json")
    if candidates["failures"] or not candidates["source_unchanged"] or c.sources()!=protocol["source_hashes"]:
        raise ValueError("Incomplete candidates or source drift")
    old={(r["task"],r["core"],r["seed"]):r for r in originals["fits"]}
    rows=[]
    for r in candidates["fits"]:
        for version,record,root in (("missing_trained",r,out),("historical_base_only",old[r["task"],r["core"],r["seed"]],baseline)):
            path=root/record["checkpoint"]
            if c.sha(path)!=record["checkpoint_sha256"]:raise ValueError("Checkpoint changed")
            rows.append(dict(task=r["task"],core=r["core"],seed=r["seed"],version=version,
                checkpoint=str(path),checkpoint_sha256=record["checkpoint_sha256"]))
    identity=dict(candidate_sha256=c.sha(out/"ALL_CHECKPOINTS.json"),
        historical_candidate_sha256=c.sha(baseline/"ALL_CHECKPOINTS.json"),
        protocol_sha256=c.sha(out/"PROTOCOL.json"),evaluation_source_sha256=c.sha(__file__))
    return protocol,rows,identity


def net(row):
    model=c.model(row["core"],row["seed"]).eval()
    model.load_state_dict(torch.load(row["checkpoint"],weights_only=True,map_location="cpu"))
    return model


def calibrate(out, baseline):
    protocol,rows,identity=setup(out,baseline)
    c.save(out/"EVALUATION_PROTOCOL.json",dict(frozen_utc=datetime.now(timezone.utc).isoformat(),
        identity=identity,calibration=protocol["calibration"],confirmation=protocol["confirmation"],
        gates=protocol["gates"],policy="All calibrations freeze and publish before confirmation; no post-confirmation refit"))
    cpu,wall=time.process_time(),time.perf_counter();records=[]
    for row in rows:
        model=net(row); logits=[];labels=[];stage=protocol["calibration"]
        for condition in stage["conditions"]:
            arrays=c.batch(row["task"],stage["episodes"],stage["seed"],stage["split"],condition)
            mask=arrays["y"]>=0
            logits.append(c.study.predict(model,arrays)[mask]);labels.append(arrays["y"][mask])
        calibration=c.calibrate(np.concatenate(logits),np.concatenate(labels),stage)
        records.append(dict(**row,calibration=calibration))
    summary=dict(records=records,identity=identity,cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-wall,evaluation_protocol_sha256=c.sha(out/"EVALUATION_PROTOCOL.json"))
    c.save(out/"ALL_CALIBRATIONS.json",summary)
    return dict(calibrations=len(records),calibration_sha256=c.sha(out/"ALL_CALIBRATIONS.json"),identity=identity)


def confirm(out,baseline,calibration_sha,publication):
    protocol,_,identity=setup(out,baseline)
    if c.sha(out/"ALL_CALIBRATIONS.json")!=calibration_sha or len(publication)!=40:
        raise ValueError("Exact published calibration SHA and source commit required")
    calibrated=c.load(out/"ALL_CALIBRATIONS.json")
    if identity!=calibrated["identity"]:raise ValueError("Identity drift since calibration")
    folder=out/"confirmation";folder.mkdir(exist_ok=False)
    c.save(folder/"STARTED.json",dict(frozen_calibration_sha256=calibration_sha,
        publication_commit=publication,identity=identity))
    cpu,wall=time.process_time(),time.perf_counter();records=[]
    for row in calibrated["records"]:
        model=net(row);stage=protocol["confirmation"]
        for condition in stage["conditions"]:
            arrays=c.batch(row["task"],stage["episodes"],stage["seed"],stage["split"],condition)
            mask=arrays["y"]>=0;logits=c.study.predict(model,arrays)[mask];y=arrays["y"][mask]
            available=arrays.get("target_available",mask)[mask]
            metrics,p,accepted=c.metrics(logits,y,available,row["calibration"])
            raw=folder/f'{row["task"]}_{row["core"]}_{row["seed"]}_{row["version"]}_{condition}.npz'
            np.savez_compressed(raw,logits=logits,probabilities=p,labels=y,available=available,accepted=accepted)
            record={k:row[k] for k in ("task","core","seed","version","checkpoint_sha256")}
            record.update(condition=condition,metrics=metrics,raw_sha256=c.sha(raw),raw_file=raw.name,
                data_sha256={k:c.hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest() for k,v in arrays.items()})
            records.append(record);c.save(raw.with_suffix(".json"),record)
        print(json.dumps({k:row[k] for k in ("task","core","seed","version")}),flush=True)
    summary=dict(records=records,cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        source_unchanged=c.sources()==protocol["source_hashes"],identity=identity,
        calibration_sha256=calibration_sha,publication_commit=publication,
        energy_joules=None,all_blockers_closed=False,production_activation=False)
    c.save(folder/"SUMMARY.json",summary)
    return dict(records=len(records),source_unchanged=summary["source_unchanged"])


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("calibrate","confirm"));p.add_argument("--out",type=Path,required=True)
    p.add_argument("--baseline",type=Path,required=True);p.add_argument("--calibration-sha");p.add_argument("--publication")
    a=p.parse_args();torch.set_num_threads(1)
    result=calibrate(a.out,a.baseline) if a.mode=="calibrate" else confirm(a.out,a.baseline,a.calibration_sha,a.publication)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=="__main__":main()
