"""Verify the signed decisions of a fixed bounded edit on TRAIN and DEV with rational arithmetic."""
import argparse
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np
from qualification.hcsn_blocker_followup import experiment, metrics, readout_edit


def restore(evidence, root, want):
    catalog = json.loads((evidence/"archive_manifest.json").read_text())["archives"]
    restored = set()
    for filename, archive in catalog.items():
        wanted = [n for n in archive["files"] if want(n)]
        if not wanted:
            continue
        path = evidence/filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == archive["sha256"]
        with ZipFile(path) as z:
            for name in wanted:
                assert name not in restored and not Path(name).is_absolute() and ".." not in Path(name).parts
                raw = z.read(name)
                assert hashlib.sha256(raw).hexdigest() == archive["files"][name]["sha256"]
                dest=root/name
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(raw)
                restored.add(name)
    return restored


def training_inputs(name):
    if name in ("outcomes/fit.json","media/data_freeze.json","media/sources.json"):
        return True
    if name in ("media/roster/train.json","media/roster/dev.json","media/roster/test.json"):
        return True  # Original panel verifier checks the registered roster digests for all partitions.
    return any(name in (f"media/features/{s}.npz", f"media/receipts/{s}.json",
                        f"media/semantic/{s}.npz", f"media/semantic/{s}.receipt.json")
               or name.startswith(f"media/semantic/parts/{s}") for s in ("train","dev"))


def run(qual):
    here=Path(__file__).resolve().parent
    witness=json.loads((here/"coordinate_witness.json").read_text())
    d=[F(v) for v in witness["delta"]]
    l1=sum(abs(v) for v in d)
    assert len(d)==19 and l1<=1
    results={}
    with TemporaryDirectory() as folder:
        root=Path(folder)
        old=restore(qual/"hcsn_intervention_value/evidence",root/"old",lambda n:n=="primary/discovery/front_weights.json")
        new=restore(qual/"hcsn_blocker_followup/evidence",root/"new",training_inputs)
        assert len(old)==1 and new and not any(n in new for n in ("outcomes/test.json","media/features/test.npz","media/semantic/test.npz"))
        fit=json.loads((root/"new/outcomes/fit.json").read_text())[witness["head"]]
        incumbent=[F(float(v)) for v in [*fit["beta"], fit["bias"]]]
        w=[a+b for a,b in zip(incumbent,d,strict=True)]
        for split in ("train","dev"):
            data,keys=experiment.panel(root/"new/media",root/"old/primary/discovery",split)
            features=readout_edit.matrix(data,fit)
            gap=[sum(F(float(x))*v for x,v in zip(row,w,strict=True))-F(3,10) for row in features]
            yes=np.array([v>0 for v in gap])
            assert np.array_equal(yes, features@np.asarray(list(map(float,w)))>.30)
            assert min(map(abs,gap))>=F(1,10)
            value=metrics.evaluate(data,yes)
            counts={}
            for group in sorted(set(data["group"])):
                idx=data["group"]==group
                assert sum(idx)==4
                free=(data["scores"][idx,0].argmax(-1)==data["target"][idx]).astype(int)
                paid=(data["read_scores"][idx,0].argmax(-1)==data["target"][idx]).astype(int)
                gain=[F(int(p-f))-F(3,10) for p,f in zip(paid,free,strict=True)]
                bought=[int(v) for v in yes[idx]]
                diff=sum(b*g for b,g in zip(bought,gain,strict=True))/4
                diff_paid=diff-sum(gain)/4
                counts[str(group)]=[str(diff),str(diff_paid)]
            means=[sum(F(row[j]) for row in counts.values())/len(counts) for j in range(2)]
            worst=min(F(row[0]) for row in counts.values())
            assert min(means)>=F(3,100) and worst>=-F(1,20)
            assert np.allclose([float(x) for x in [*means,worst]], [value["delta_free"],value["delta_paid"],value["worst_delta_free"]],rtol=0,atol=1e-12)
            results[split]={"inputs":keys,"queries":len(gap),"bought_queries":data["query_id"][yes].tolist(),
                "bought":value["bought"],"gain_vs_free":str(means[0]),"gain_vs_paid":str(means[1]),"worst_vs_free":str(worst),
                "min_score_margin":float(min(map(abs,gap))),"source_contrasts":counts,
                "one_sided_source_p":value["one_sided_sign_p"],"original_evaluator_adopt":value["adopt"]}
    return {"fixed_starting_head":"full-svd-.1","exact_l1_displacement":str(l1),"changed_coordinates":sum(x!=0 for x in d),"panels":results}


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("qualification", type=Path)
    print(json.dumps(run(cli.parse_args().qualification),indent=2,sort_keys=True))
