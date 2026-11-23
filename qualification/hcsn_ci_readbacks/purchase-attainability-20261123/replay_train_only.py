"""Replay the fixed TRAIN-only search output on the two previously observed panels."""
import argparse
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from qualification.hcsn_blocker_followup import experiment, metrics, readout_edit
from verify_coordinate_witness import restore, training_inputs

SEAL = "e8b15f7ec750acaaf3127d2c16357ec5433cdba51f35f116052c183a2da81e80"


def evaluate(qualification):
    here=Path(__file__).resolve().parent
    raw=(here/"train_only_seal.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SEAL
    fit_seal=json.loads(raw)
    assert fit_seal["fit_labels"]==["train"]
    assert hashlib.sha256((here/"find_coordinate_witness.py").read_bytes()).hexdigest()==fit_seal["source_sha256"]
    delta=[F(v) for v in fit_seal["delta"]]
    panels={}
    with TemporaryDirectory() as folder:
        root=Path(folder)
        restore(qualification/"hcsn_intervention_value/evidence",root/"old",lambda s:s=="primary/discovery/front_weights.json")
        restore(qualification/"hcsn_blocker_followup/evidence",root/"new",training_inputs)
        base=json.loads((root/"new/outcomes/fit.json").read_text())["full-svd-.1"]
        initial=list(map(lambda v:F(float(v)),[*base["beta"],base["bias"]]))
        weights=[v+d for v,d in zip(initial,delta,strict=True)]
        for split in ("train","dev"):
            data,inputs=experiment.panel(root/"new/media",root/"old/primary/discovery",split)
            X=readout_edit.matrix(data,base)
            gap=[sum(F(float(x))*w for x,w in zip(row,weights,strict=True))-F(3,10) for row in X]
            bought=np.array([v>0 for v in gap])
            assert np.array_equal(bought,X@np.array([float(w) for w in weights])>.30)
            if split=="train":
                assert min(map(abs,gap))>=F(1,10)
            scored=metrics.evaluate(data,bought)
            keys=("utility","buy","bought","delta_free","delta_paid","worst_delta_free","one_sided_sign_p","adopt","sources")
            panels[split]={"inputs":inputs,"minimum_margin":float(min(map(abs,gap))),
                **{k:scored[k] for k in keys}, "bought_ids":data["query_id"][bought].tolist()}
    return {"seal_sha256":SEAL,"l1":str(sum(map(abs,delta))),"changed_coordinates":sum(v!=0 for v in delta),
            "fit_on":["train"],"panels":panels}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qualification",type=Path)
    print(json.dumps(evaluate(parser.parse_args().qualification),indent=2,sort_keys=True))
