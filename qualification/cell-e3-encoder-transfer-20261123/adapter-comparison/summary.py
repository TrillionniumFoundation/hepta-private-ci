"""Add same-architecture gold and label-permutation diagnostic scores to the readout."""
import json
from pathlib import Path
from panel import DOMAINS, panel

work=Path("work")
data=panel()
test=[r for r in data if r["split"]=="holdout"]
old=[r for r in data if r["split"]=="old-test"]
comp=[r for r in data if r["split"]=="composition"]
res=json.loads((work/"results.json").read_bytes())
for arm in ("gold","shuffled"):
    rd=json.loads((work/("cold-"+arm+".json")).read_bytes())
    nums={r["id"]:r["answer"] for r in rd["rows"]}
    assert len(nums)==len(rd["rows"])==len(test)+len(old)+len(comp)
    def ok(r):
        return nums[r["id"]]==r["label"]
    pairs=0
    for i in range(0,len(DOMAINS),2):
        a,b=DOMAINS[i:i+2]
        pairs+=sum(ok(x) and ok(y) for x,y in zip([r for r in comp if r["domain"]==a],
                                                  [r for r in comp if r["domain"]==b],strict=True))
    res["scores"][arm]=dict(total=sum(map(ok,test)),old=sum(map(ok,old)),pairs=pairs,
                            domain={d:sum(ok(r) for r in test if r["domain"]==d) for d in DOMAINS},
                            registered_gate=None,qualifying_arm=False,input_tokens=rd["input_tokens"],
                            wall_seconds=rd["wall_seconds"],encoder_inputs=rd["encoder_inputs"])
(work/"results.json").write_text(json.dumps(res,indent=2,sort_keys=True)+"\n")
print("E3_ADAPTER_RESULT",json.dumps(res,separators=(",",":")))
