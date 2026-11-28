"""Pack an exact, small CREMA-D sample for a fixed-size private cloud source."""
import hashlib
import io
import json
import lzma
import sys
from pathlib import Path

import numpy as np


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build(root, dest):
    p=root/"data/data.npz"
    with p.open("rb") as f:
        assert hashlib.file_digest(f,"sha256").hexdigest()=="18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad"
    with np.load(p) as a:
        tr=np.flatnonzero(a["split"]==0)
        names=a["ids"]
        actor=np.array([s.split("_")[0] for s in names])
        train=np.random.default_rng(7506).choice(tr,(1,16)).ravel()
        def pick(fold):
            rows=np.flatnonzero(a["split"]==fold)
            return [rows[np.flatnonzero(actor[rows]==label)[0]] for label in sorted(set(actor[rows]))[:2]]
        chosen=np.asarray([*train,*pick(1),*pick(2)])
        audio=a["audio"]
        mean=audio[tr].mean((0,1),dtype=np.float64).astype(np.float32)
        sd=audio[tr].std((0,1),dtype=np.float64).clip(.01).astype(np.float32)
        samples=dict(v=a["images"][chosen],audio=((audio[chosen]-mean)/sd),y=a["labels"][chosen],
                     ids=names[chosen],tokens=a["tokens"],indices=chosen,fold=a["split"][chosen])
    lawpath=root/"src/law4.npz"
    assert sha(lawpath.read_bytes())=="de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4"
    with np.load(lawpath) as a:
        entries={k:a[k] for k in a}
    kernel=entries.pop("kernel")
    n=kernel.view(np.uint32).reshape(4097,20).copy()
    for _ in range(3):
        n[1:]=n[1:]-n[:-1]
    # Store the increments in per-series order for LZMA. Invert with unsigned cumulative sums.
    buffer=io.BytesIO()
    np.savez(buffer,**samples,**{"law_"+k:v for k,v in entries.items()},third_differences=n.T.copy())
    payload=lzma.compress(buffer.getvalue(),preset=9)
    dest.mkdir(exist_ok=True,parents=True)
    (dest/"subset.xz").write_bytes(payload)
    manifest=dict(packed_sha256=sha(payload),bytes=len(payload),values_sha256={k:sha(v.tobytes()) for k,v in samples.items()},
                  law_sha256={k:sha(v.tobytes()) for k,v in entries.items()},kernel_sha256=sha(kernel.tobytes()),
                  source_table_sha256=sha(lawpath.read_bytes()),indices=chosen.tolist(),names=names[chosen].tolist(),dtype="float32")
    (dest/"subset.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(len(payload),manifest["packed_sha256"],flush=True)


if __name__=="__main__":
    build(Path(sys.argv[1]),Path(sys.argv[2]))
