"""Prepare a fixed event-time grid from the original SHD HDF5 corpus."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import h5py
import numpy as np

DIGESTS = {
    'train': '2bddb4bd46732f09982b7d1631b7c29c19853c73d3d240e3eb32bba909bdd6c1',
    'test': '47d8621a092cb483bea9448a93c0a3375a6726d370045090c2f7a77f70f95df3',
}
SCALES = {'natural': 1., 'fast': .8, 'slow': 1.2}


def prepare(source, dest, split):
    started = time.perf_counter()
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    assert digest == DIGESTS[split], (source, digest)
    dest.mkdir(exist_ok=True, parents=True)
    scales = SCALES if split == 'test' else {'natural': 1.}
    with h5py.File(source) as data:
        labels = data['labels'][:]
        speakers = data['extra/speaker'][:]
        count = len(labels)
        mats = {name: np.zeros((count, 28, 28), dtype=np.int32) for name in scales}
        outside = dict.fromkeys(scales, 0)
        events = 0
        for i in range(count):
            t = np.asarray(data['spikes/times'][i], dtype=np.float64)
            locations = np.asarray(data['spikes/units'][i], dtype=np.int64)
            assert np.all((0 <= locations) & (locations < 700)) and np.all(t >= 0)
            assert len(locations) == len(t)
            events += len(t)
            for name, scale in scales.items():
                bins = np.floor((t * scale)/.05).astype(np.int64)
                valid = bins < 28
                mats[name][i] = np.bincount(bins[valid]*28 + locations[valid]//25,
                                            minlength=784).reshape(28,28)
                outside[name] += int((~valid).sum())
        for name, a in mats.items():
            assert int(a.sum()) == events - outside[name]
            assert a.max() < 65536
            tmp = dest / (split+'-'+name+'.partial')
            with tmp.open('wb') as handle:
                np.savez_compressed(handle, counts=a.astype(np.uint16), y=labels, speaker=speakers,
                                    row=np.arange(count))
            os.replace(tmp,dest / (split+'-'+name+'.npz'))
    receipt = dict(split=split, records=count, original_events=events, excluded_events=outside,
                   hdf5_sha256=digest, preprocessing_wall_s=time.perf_counter()-started,
                   representation='event counts, axis order record / time (50ms) / 25 cochlear locations')
    (dest/(split+'-data.json')).write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt), flush=True)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('source',type=Path); p.add_argument('dest',type=Path)
    p.add_argument('split',choices=DIGESTS)
    a=p.parse_args()
    prepare(a.source,a.dest,a.split)
