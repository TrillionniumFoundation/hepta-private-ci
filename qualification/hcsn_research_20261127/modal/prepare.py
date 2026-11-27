"""Extract nonoverlapping causal motion windows from the original UCI archive."""
import argparse
import hashlib
import json
import time
import zipfile
from pathlib import Path

import numpy as np

SOURCE_SHA = '16ad0ce709f3f00df18f348610d15bce0884b79e2143f57f446493673f02b8e0'
AXES = [0, 1, 2, 8, 9, 10, 17, 18, 19]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(archive, output):
    start = time.perf_counter()
    if digest(archive) != SOURCE_SHA:
        raise ValueError('unexpected MHEALTH source')
    output.mkdir(exist_ok=True, parents=True)
    receipts = {}
    with zipfile.ZipFile(archive) as z:
        for person in range(1, 11):
            name = f'MHEALTHDATASET/mHealth_subject{person}.log'
            contents = z.read(name)
            import io
            raw = np.loadtxt(io.BytesIO(contents), dtype=np.float32)
            if raw.shape[1] != 24 or not np.isfinite(raw).all():
                raise ValueError(f'invalid source {name}')
            length = len(raw) // 128
            w = raw[:length * 128].reshape(length, 128, 24)
            labels = w[:, :, 23]
            valid = (labels[:, 0] >= 1) & (labels[:, 0] <= 12) & (labels == labels[:, :1]).all(1)
            indices = np.flatnonzero(valid)
            v = w[indices][:, :, AXES].reshape(-1, 8, 16, len(AXES))
            features = np.concatenate([v.mean(2), v.std(2)], axis=2)
            y = labels[indices, 0].astype(np.int64) - 1
            path = output / f'p{person:02d}.npz'
            np.savez_compressed(path, x=features, y=y, starts=128 * indices)
            receipts[str(person)] = {'source_sha256': hashlib.sha256(contents).hexdigest(),
                                     'prepared_sha256': digest(path), 'raw_rows': len(raw),
                                     'windows': len(indices), 'classes': np.bincount(y, minlength=12).tolist()}
    (output / 'data.json').write_text(json.dumps({'archive_sha256': SOURCE_SHA,
        'participant': receipts, 'prepare_wall': time.perf_counter() - start}, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('archive', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    prepare(a.archive, a.output)
