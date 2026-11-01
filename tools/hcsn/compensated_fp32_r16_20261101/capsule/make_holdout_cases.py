"""Reproduce the pre-evaluation V1 manifest; never consult candidate outputs."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

EXPECTED_SHA256 = '317162122a0f6d43143b42b37c12e48f8e8888276d5018784b887848b420a86c'


def run(output):
    if output.exists():
        raise ValueError('Manifest output is create-only')
    lower = np.asarray([.04,.01,.08,0,0,1e-4,.01,.5,20])
    upper = np.asarray([.15,.2,.8,1,.6,.1,20,10,100])
    rng, count = np.random.default_rng(2026110107), 128
    u = np.column_stack([(rng.permutation(count)+rng.random(count))/count for _ in range(9)])
    values = lower+(upper-lower)*u
    for index in (5,6):
        values[:,index] = np.exp(np.log(lower[index])+(np.log(upper[index])-np.log(lower[index]))*u[:,index])
    rows = [{'id':f'lhs_{i:03d}', 'theta':theta.tolist()} for i,theta in enumerate(values.astype(np.float32))]
    encoded = (json.dumps({'schema':'hcsn.r16.financial-independent-lhs.v1',
                           'seed':2026110107, 'rows':rows}, indent=2)+'\n').encode()
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != EXPECTED_SHA256:
        raise ValueError('Generator differs from frozen V1 manifest: '+actual)
    with output.open('xb') as handle:
        handle.write(encoded)
    print(json.dumps({'sha256':actual, 'points':count}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
