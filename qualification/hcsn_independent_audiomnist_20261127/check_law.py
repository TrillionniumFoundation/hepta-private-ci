"""Compare the full output sequence against the existing published-law implementation."""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from receiver import Cell


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('upstream',type=Path);ap.add_argument('table',type=Path)
    a=ap.parse_args();sys.path.insert(0,str(a.upstream.resolve().parent))
    spec=importlib.util.spec_from_file_location('upstream_table',a.upstream)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    law=Cell(a.table);g=np.random.default_rng(92117)
    with np.load(a.table) as z:
        rows=[]
        for sigma in (.1,1.,3.):
            x=g.normal(0,sigma,(128,6,12))
            ref=mod.propagate(x,dict(z),'literal');actual,_=law.run(x)
            rows.append(np.max(np.abs(actual-ref),axis=(0,1,2)).tolist())
    if np.max(rows)>1.5e-5:raise ArithmeticError(rows)
    print(json.dumps({'absolute_discrepancy_boundary_equity_loss_probability':rows,'table_sha256':hashlib.sha256(a.table.read_bytes()).hexdigest(),'upstream_source_sha256':hashlib.sha256(a.upstream.read_bytes()).hexdigest(),'probe_seed':92117},indent=2))
