"""Fixed queue and independent confirmation of each preregistered wave."""
import json,itertools
from pathlib import Path
if __name__=="__main__":
    waves=[]
    frontier=[(8,8,1,"mixed"),(32,32,1,"native32"),(64,64,1,"float64"),(32,8,2,"mixed"),
       (8,32,2,"native32"),(64,8,1,"mixed"),(8,64,1,"float64"),(32,32,2,"mixed")]
    other=list(itertools.product((8,32,64),(8,32,64),(1,2),("native32","mixed","float64")))
    combos=frontier+[x for x in other if x not in frontier]
    for seed in (74177,84177,94177):
        for i,(n,t,d,p) in enumerate(combos):
            for j,task in enumerate(("office","beijing")):
                arms=["gru","attention","lif","newton","halley"];s=(i+j)%len(arms)
                waves.append(dict(task=task,n=n,t=t,depth=d,precision=p,seed=seed,arms=arms[s:]+arms[:s]))
    plan=dict(id="HCSN-ROCm-long-stream-full-operator-20261127-v1",waves=waves,steps=64,batch=6,
      dev_checkpoints=[0,4,8,16,32,48,64],lr=.003,clip=2,
      quality_targets={"office":.14,"beijing":.19},reference_targets="Absolute Brier on independent dev set fixed in advance. Report time to first reached threshold from fresh process including imports, initialization and dev checks; censored arms, failure counts, entire curves. For hitting arms score the first threshold checkpoint and dev-selected checkpoint on chronological/site holdout. Original CPU study 0.5 BA; these targets do not imply above-chance BA.",
      windows="Nested true contiguous 8,32,64 histories with common anchors and IDs. 96 train/32 dev/48 test maxima; day and station group-balanced. Normalization on retained training observations only. Group/source split in gpu_panel.py. Reused published office historical test days and same Berlin-independent Beijing stations/year as completed CPU, so an additional systematic validation on overlapping domains.",
      physics="Exact pinned finite-state transport, symmetric remap, first-event probability, action/readout. Both physical arms have identical learnable initialization. Native32, mixed FP32 learning/FP64 physical, native float64. Depth2 first stage emits only previous centered receiver boundaries to learned 6-dimensional inter-layer projection. Conventional arms receive full conventional representations. Same width exposes gross/effective capacity disparity, parameters recorded.",
      wall_budget_s=37800,wall_policy="Serial wave execution in a single process supervisor, isolated fresh Python worker for each fit and cold test. Stop at first completed wave after 10.5 active campaign hours or when full three-seed grid has completed; partial waves and failed arms retained. If time remains after all planned waves, no artificial padding. No downtime charged toward per-worker method costs.",
      device="ROG 8060S ROCm, genuine GPU tensor probe; synchronize each development checkpoint, completed optimizer unit, reload/eval. Collect GPU peak bytes and full process wall for every slot. Save CPU selected/threshold states, checksums, raw ids/labels/probs, and fit timing. Wall estimates include MIopen/Tensor cold start for conventional networks.",
      quantization="A separate post-training weight-rounding diagnostic with symmetric per-tensor int8 dequantized inference on GPU. Explicit float inference measures quantization distortion but does not claim native INT8 acceleration.")
    Path("gpu_protocol.json").write_text(json.dumps(plan,indent=1)+"\n")
