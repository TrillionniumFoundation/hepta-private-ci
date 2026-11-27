"""Prepare the pinned CREMA-D corpus and record object identities and phase costs."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

import numpy as np
from qualification.hcsn_closure_av_20261125.decoder_original import decode

UPSTREAM = "1658cd342dff90010aa843eaeebd53610a08b1dc"
ELIGIBLE = "1013 1017 1028 1029 1033 1037 1042 1045 1068 1070 1071 1079 1081 1088 1090".split()
EMOTIONS = ("ANG", "DIS", "FEA", "HAP", "NEU", "SAD")
SENTENCES = ("DFA", "IOM")
SALT = "hepta-boundary-transfer-20261126-a620/"

def digest(data):
    return hashlib.sha256(data).hexdigest()

def read_url(url, limit):
    for attempt in range(4):
        try:
            with urlopen(url, timeout=35) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("oversized media")
            return data
        except OSError:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)

def prepare(root):
    begun = time.monotonic()
    root.mkdir(parents=True, exist_ok=True)
    actors = sorted(ELIGIBLE, key=lambda a: digest((SALT + a).encode()))
    splits = {"train": actors[:6], "dev": actors[6:9], "test": actors[9:]}
    keys = [(name, actor, sentence, emotion) for name, group in splits.items()
            for actor in group for sentence in SENTENCES for emotion in EMOTIONS]
    def acquire_key(key):
        part, actor, sentence, emotion = key
        clip = f"{actor}_{sentence}_{emotion}_XX"
        path = f"VideoFlash/{clip}.flv"
        base = f"CheyneyComputerScience/CREMA-D/{UPSTREAM}/{path}"
        pointer = read_url("https://raw.githubusercontent.com/" + base, 1024).decode()
        fields = dict(line.split(" ", 1) for line in pointer.splitlines())
        sha = fields["oid"].split(":")[1]
        flv = root / (clip + ".flv")
        media = flv.read_bytes() if flv.exists() else read_url("https://media.githubusercontent.com/media/" + base, int(fields["size"]))
        if digest(media) != sha or len(media) != int(fields["size"]):
            raise ValueError("LFS identity mismatch " + clip)
        if not flv.exists():
            flv.write_bytes(media)
        features, _ = decode(flv)
        return part, clip, actor, EMOTIONS.index(emotion), np.asarray(features, dtype=np.float32), sha
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(acquire_key, keys))
    train = np.stack([r[4] for r in rows if r[0] == "train"])
    mean = train.mean(axis=(0, 2), dtype=np.float64)[:, None]
    sd = np.maximum(train.std(axis=(0, 2), dtype=np.float64)[:, None], 1e-6)
    meta = {"repository": "CheyneyComputerScience/CREMA-D", "commit": UPSTREAM, "license": "ODbL-1.0 / DbCL-1.0",
            "actor_splits": splits, "normalization": "train-only, per feature per modality", "clips": {}}
    for part in splits:
        group = [r for r in rows if r[0] == part]
        feats = (np.stack([r[4] for r in group]) - mean) / sd
        feat = feats.reshape(len(group), 2, 8, 4, 128).mean(axis=3)
        np.savez_compressed(root / (part + ".npz"), x=feat.astype(np.float32),
                            y=np.array([r[3] for r in group]), actors=np.array([r[2] for r in group]),
                            clips=np.array([r[1] for r in group]))
        meta["clips"][part] = [{"id": r[1], "sha256": r[5]} for r in group]
    meta["preparation_wall_seconds"] = time.monotonic() - begun
    meta["arrays"] = {p: digest((root / (p + ".npz")).read_bytes()) for p in splits}
    (root / "data_receipt.json").write_text(json.dumps(meta, indent=2) + "\n")
    print({k:v for k,v in meta.items() if k != "clips"}, flush=True)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    prepare(p.parse_args().root)
