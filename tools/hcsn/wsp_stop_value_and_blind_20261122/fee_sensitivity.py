"""Post hoc external settlement surcharge; the observed policy and transition law remain fixed."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("veto_rows",type=Path)
    parser.add_argument("out",type=Path)
    args=parser.parse_args()
    data=json.loads(args.veto_rows.read_text())
    result={}
    for multiplier in (1.0,1.25,2.0):
        result[str(multiplier)]={}
        for arm in ("EXACT_H2","EXACT_VPI","ALL_VPI"):
            delta=[]
            for r in data:
                incumbent=r["arms"]["KEEP"]
                proposed=r["arms"][arm]
                delta.append(proposed["value"]-incumbent["value"]
                             -(multiplier-1)*(proposed["cost"]-incumbent["cost"]))
            result[str(multiplier)][arm]=dict(worst=min(delta),worse=sum(d < -1e-10 for d in delta),
                                              mean=sum(delta)/len(delta))
    with args.out.open("x") as f:
        json.dump(dict(worlds=len(data),test="post hoc, external settlement surcharge unobserved by actor",
                       results=result),f,sort_keys=True,indent=2)
        f.write("\n")

if __name__=="__main__":
    main()
