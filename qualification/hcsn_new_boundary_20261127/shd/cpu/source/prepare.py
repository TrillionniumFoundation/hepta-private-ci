"""Build the SHD event-time features; never load the official test labels here."""
import argparse
import hashlib
import itertools
import json
import resource
import time
from pathlib import Path

import h5py
import numpy as np

DATA = {
    "train": ("2bddb4bd46732f09982b7d1631b7c29c19853c73d3d240e3eb32bba909bdd6c1", 8156),
    "test": ("47d8621a092cb483bea9448a93c0a3375a6726d370045090c2f7a77f70f95df3", 2264),
}
TAUS = np.array([.035, .100])


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def speaker_split(y, speakers):
    pairs = itertools.combinations(sorted(map(int, np.unique(speakers))), 2)
    ordered = sorted(pairs, key=lambda s: hashlib.sha256(f"hepta-shd-dev-v1/{s[0]}/{s[1]}".encode()).hexdigest())
    for pair in ordered:
        dev = np.isin(speakers, pair)
        if all(np.bincount(y[filt], minlength=20).min() >= 8 for filt in (dev, ~dev)):
            return pair, dev
    raise ValueError("No admissible training/development split")


def traces(times, units, audit=False):
    times = times.astype(np.float64)
    groups = units.astype(np.int32) // 25
    assert np.all((groups >= 0) & (groups < 28))
    assert np.all(times[:-1] <= times[1:])
    query = np.arange(1, 13) / 10.
    if times.size:
        query[-1] = max(query[-1], times[-1])
    end = np.searchsorted(times, query, side="right")
    start = 0
    prev = 0.
    state = np.zeros((2, 28))
    result = []
    err = 0.
    for q, last in zip(query, end):
        state *= np.exp(-(q-prev)/TAUS)[:, None]
        for j, tau in enumerate(TAUS):
            add = np.exp((times[start:last]-q)/tau)
            state[j] += np.bincount(groups[start:last], add, minlength=28)
            if audit:
                direct = np.bincount(groups[:last], np.exp((times[:last]-q)/tau), minlength=28)
                err = max(err, np.max(np.abs(direct-state[j])))
        result.append(state.astype(np.float32).reshape(-1))
        prev = q
        start = last
    assert end[-1] == len(times)
    return np.stack(result), err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0, c0 = time.perf_counter(), time.process_time()
    receipt = {"source": {}, "arrays": {}, "test_label_access": False, "protocol": digest(Path(__file__).with_name("PROTOCOL.md"))}
    for split, (expected, n) in DATA.items():
        fpath = args.input / f"shd_{split}.h5"
        assert digest(fpath) == expected
        err, ev, long = 0., 0, 0
        feat = np.empty((n, 12, 56), dtype=np.float32)
        with h5py.File(fpath, "r") as f:
            speakers = f["extra/speaker"][:].astype(np.int16)
            assert n == len(speakers)
            times = f["spikes/times"]
            units = f["spikes/units"]
            for i in range(n):
                row = times[i]
                ft, diff = traces(row, units[i], audit=split == "train" and i in {0, 500, 4000, 8000})
                err = max(err, diff)
                feat[i] = np.log1p(ft)
                ev += len(row)
                long += bool(row.size and row[-1] > 1.2)
            if split == "train":
                y = f["labels"][:].astype(np.int64)
                pair, dev = speaker_split(y, speakers)
                np.save(args.out/"labels_train.npy", y)
                np.save(args.out/"devmask.npy", dev)
                receipt["dev_speakers"] = list(pair)
                receipt["fit_n"] = int((~dev).sum())
                receipt["dev_n"] = int(dev.sum())
        assert err < 1e-8
        np.save(args.out/f"x_{split}.npy", feat)
        np.save(args.out/f"people_{split}.npy", speakers)
        receipt["source"][split] = dict(sha256=expected, records=n, source_events=ev, after_1p2s_records=long, independent_max_abs=err)
    receipt["arrays"] = {f.name: digest(f) for f in sorted(args.out.glob("*.npy"))}
    receipt.update(wall_s=time.perf_counter()-t0, cpu_s=time.process_time()-c0, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (args.out/"prepare.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
