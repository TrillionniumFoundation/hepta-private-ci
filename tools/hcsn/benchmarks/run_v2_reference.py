"""Unmodified v1-HCSN on v2's data, to separate repair from dataset variation.

This extra diagnostic control was added after early v2 scores were seen. No
architecture, training setting or checkpoint selection rule is changed.
"""

import json
from pathlib import Path
import time
import jax
try:
    from .data import make_data,fingerprint,INPUT_DIM,OUTPUT_DIM
    from .models import init_model,matched_width
    from .train import make_trainer,train_model,evaluate_dataset
    from .run_benchmarks import source_hashes
except ImportError:
    from data import make_data,fingerprint,INPUT_DIM,OUTPUT_DIM
    from models import init_model,matched_width
    from train import make_trainer,train_model,evaluate_dataset
    from run_benchmarks import source_hashes


def main():
    folder=Path(__file__).parent;rows=[];start=time.perf_counter()
    trainer=make_trainer("hcsn");width,count=matched_width("hcsn",INPUT_DIM,OUTPUT_DIM)
    metadata=dict(scope="Post-declared diagnostic reference; unchanged v1 model on all v2 data",
                  source_hashes=source_hashes(),parameter_count=count,persistent_state_scalars=2*width)
    for task in ("memory","retrieval"):
        for seed in range(5):
            base=900000+100*seed
            suite={"train":make_data(task,base,2048),"validation":make_data(task,base+1,512),
                   "test":make_data(task,base+2,512),"long":make_data(task,base+3,512,length=64)}
            params=init_model("hcsn",jax.random.PRNGKey(2000+seed),INPUT_DIM,width,OUTPUT_DIM)
            trained,history,timing=train_model(params,"hcsn",suite["train"],suite["validation"],
                9000+seed,steps=300,trainer=trainer)
            metrics={k:evaluate_dataset(trainer[3],trained,v) for k,v in suite.items() if k!="train"}
            rows.append(dict(task=task,seed=seed,kind="hcsn_v1_reference",parameter_count=count,
                persistent_state_scalars=2*width,metrics=metrics,history=history,timing=timing,
                data_sha256={k:fingerprint(v) for k,v in suite.items()}))
            payload=dict(metadata=metadata,runs=rows,complete=False,elapsed_seconds=time.perf_counter()-start)
            (folder/"v2_reference_results.json").write_text(json.dumps(payload,indent=2))
            print(json.dumps(dict(task=task,seed=seed,test=metrics["test"]["accuracy"],
                                  long=metrics["long"]["accuracy"])),flush=True)
    payload["complete"]=True
    (folder/"v2_reference_results.json").write_text(json.dumps(payload,indent=2))


if __name__=="__main__":
    main()
