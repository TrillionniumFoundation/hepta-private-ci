"""Post-confirmation diagnostic for repeated byte-identical test utterances."""
import argparse
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from verify import ARMS, SEEDS, block_hashes, sha

def summarize(archives, data):
    source = Path(__file__).with_name("SOURCE.json")
    if sha(data) != json.loads(source.read_text())["data"]["Test_Arabic_Digit.txt"]:
        raise ValueError("test file digest")
    hashes=block_hashes(data)
    first={}
    for i,h in enumerate(hashes):
        first.setdefault(h,i)
    ids=np.array(sorted(first.values()))
    scores={}
    for path in sorted(archives.rglob("*.zip")):
        with zipfile.ZipFile(path) as z:
            files=[n for n in z.namelist() if n.endswith("/test.npz")]
            for file in files:
                with np.load(io.BytesIO(z.read(file)),allow_pickle=False) as preds:
                    key=Path(file).parent.name
                    if key in scores: raise ValueError(key)
                    scores[key]=float(np.mean(preds["pred"][ids]==preds["y"][ids]))
    assert len(scores)==len(ARMS)*len(SEEDS)
    ordinary_gaps={}
    for seed in SEEDS:
        best=max(scores[f"{a}-{seed}"] for a in ("gru_frozen","gru_bp","flat"))
        ordinary_gaps[str(seed)]=best-scores[f"hcsn_frozen-{seed}"]
    return {"analysis":"post-confirmation, no refitting, first original occurrence per exact MFCC-line payload",
            "original":len(hashes),"unique":len(ids),"dedup_accuracy":scores,
            "strongest_conventional_minus_frozen_N32":ordinary_gaps}
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("archives",type=Path)
    p.add_argument("test_file",type=Path)
    a=p.parse_args()
    print(json.dumps(summarize(a.archives,a.test_file),indent=2,sort_keys=True))
