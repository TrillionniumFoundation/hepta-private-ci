"""Independently compare every cell table with the original per-query scoring function."""
import argparse
import itertools
import json
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from qualification.hcsn_blocker_followup import experiment, metrics, selector
from qualification.hcsn_intervention_value.replay import unpack
from cell_policy_bound import compile_panel, summarize


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("qualification",type=Path)
    args=cli.parse_args()
    here=Path(__file__).resolve().parent
    saved=json.loads((here/"observable_result.json").read_text())
    cert=json.loads((here/"cell_mixture_bound.json").read_text())
    q=np.array([float(F(v)) for v in cert["cell_probabilities"]])
    info={}
    with TemporaryDirectory() as folder:
        root=Path(folder)
        unpack(args.qualification/"hcsn_intervention_value/evidence",root/"old")
        unpack(args.qualification/"hcsn_blocker_followup/evidence",root/"new")
        for split in ("train","dev"):
            data,identity=experiment.panel(root/"new/media",root/"old/primary/discovery",split)
            assert identity==saved[split]["sealed_inputs"]
            cells=selector.cells(experiment.features(data))
            coefficients=compile_panel(saved[split])
            for mask in itertools.product([False,True],repeat=8):
                scored=metrics.evaluate(data,np.array(mask)[cells])
                tabl=summarize(coefficients,mask)
                assert scored["buy"]==tabl["buys"]
                assert all(abs(float(tabl[a])-scored[b])<1e-12 for a,b in [
                    ("gain_free","delta_free"),("gain_paid","delta_paid"),("worst","worst_delta_free")])
            gain=selector.target(data)-.30
            by_source=[]
            for group in sorted(set(data["group"])):
                ix=data["group"]==group
                by_source.append([np.mean(q[cells[ix]]*gain[ix]),np.mean((q[cells[ix]]-1)*gain[ix])])
            macro=np.mean(by_source,0)
            assert np.min(np.array(by_source)[:,0])>=-.05-1e-12
            info[split]={"queries":len(cells),"tables_verified":256,
                "mean_vs_free":macro[0],"mean_vs_paid":macro[1],"worst_vs_free":float(np.min(np.array(by_source)[:,0]))}
    assert abs(min(min(r["mean_vs_free"],r["mean_vs_paid"]) for r in info.values())-float(F(cert["common_gain"])))<1e-12
    print(json.dumps(info,sort_keys=True,indent=2))
