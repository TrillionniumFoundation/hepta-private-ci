"""Pin the already observed verification outputs for a real native replay.

Replay does not add independent statistical samples or refit any parameter.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from .qualify import confidence, load_data


def prepare(protocol, model, data, output):
    output.mkdir(parents=True,exist_ok=False)
    spec=json.loads(protocol.read_text());verification=json.loads((model/"verification-result.json").read_text())
    weights=json.loads((model/"weights.json").read_text());cal=json.loads((model/"calibration.json").read_text())
    x,y,_=load_data(data);cp,op,group=confidence(weights,cal,x)
    with gzip.open(data/"rows.jsonl.gz","rt") as f:raw=[json.loads(line) for line in f]
    host={"platform":platform.platform(),"machine":platform.machine(),
        "cpuinfo":Path('/proc/cpuinfo').read_text(),"cpu_quota":Path('/sys/fs/cgroup/cpu.max').read_text(),
        "memory_limit":Path('/sys/fs/cgroup/memory.max').read_text(),
        "context":"shared 8-vCPU 8-GiB container, local overlay filesystem; not a production-target-host assertion"}
    write_json(output/"host.json",host)
    rows=[]
    for i,row in enumerate(raw):
        utility=row["utility"]*2**32
        utility_q32=int(np.floor(utility+.5) if utility>=0 else np.ceil(utility-.5))
        rows.append({"pair":row["pair"],"features":np.rint(x[i]*2**24).astype(np.int64).tolist(),
            "confidence_ppm":int(cp[i]),"ood_ppm":int(op[i]),"declared_ood":row["is_declared_ood"],
            "joint_correct":int(y[i]),"terminal_value_q32":utility_q32,
            "observed_record_digest":hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "source_pair_digest":hashlib.sha256("\n".join(row["source_ids"]).encode()).hexdigest()})
    pins={"protocol":file_sha(protocol),"feature_profile":file_sha(Path(__file__).with_name('features.py')),
        "weights":file_sha(model/'weights.json'),"calibration":file_sha(model/'calibration.json'),
        "verification":file_sha(model/'verification-result.json'),"device":file_sha(output/'host.json'),
        "upstream_model":spec['input_sha256']['model'],"source_manifest":spec['input_sha256']['manifest'],
        "dataset":file_sha(data/'rows.jsonl.gz'),"measured_ece_ppm":verification['native_measured_ece_ppm'],
        "measured_false_acceptance_ppm":verification['native_measured_false_acceptance_ppm']}
    write_json(output/'packet.json',{"pins":pins,"rows":rows,"frozen_unix_ns":time.time_ns(),
        "weights_path":str((model/'weights.json').resolve()),"calibration_path":str((model/'calibration.json').resolve()),
        "verification_path":str((model/'verification-result.json').resolve())})
    bins=[]
    for g in range(4):
        use=group==g
        bins.append({'group':g,'n':int(use.sum()),'successes':int(y[use].sum()),
                     'confidence_ppm':int(cp[use][0]) if use.any() else None})
    write_json(output/'packet-receipt.json',{'packet_sha256':file_sha(output/'packet.json'),
        'rows':len(rows),'verification_bins':bins,'new_independent_samples':0,
        'native_replay_only':True,'terminal_values':'actual observed utility; no conditional-future-NDU claim'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','model','data','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.protocol,a.model,a.data,a.output)
