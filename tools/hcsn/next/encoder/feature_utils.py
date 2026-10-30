"""Shared frozen-feature selection and training-only projection utilities."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from sklearn.decomposition import PCA

FOLDER = Path(__file__).resolve().parent
CACHE = Path("/tmp/hcsn-next-encoder-assets")
SEED = 2026102907


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    if isinstance(value,str):
        value=" ".join(value.lower().split()).encode()
    return hashlib.sha256(value).hexdigest()


def choose(rows,count,classes,seed,seen):
    """Rows contain index, raw datum, label, immutable content fingerprint."""
    rng=np.random.default_rng(seed)
    selected=[]
    for label in range(classes):
        candidates=[row for row in rows if row[2]==label]
        chosen=0
        for index in rng.permutation(len(candidates)):
            row=candidates[index]
            if row[3] in seen:
                continue
            seen.add(row[3]);selected.append(row);chosen+=1
            if chosen==count//classes:
                break
        if chosen!=count//classes:
            raise ValueError("Insufficient distinct samples")
    rng.shuffle(selected)
    return selected


def session(path,threads=1):
    import onnxruntime as ort
    options=ort.SessionOptions()
    options.intra_op_num_threads=threads
    options.inter_op_num_threads=1
    return ort.InferenceSession(str(path),options,providers=["CPUExecutionProvider"])


def finish(name,features,labels,selection,metadata):
    """Fit one projection on clean training only; transform every split identically."""
    start=time.perf_counter()
    training=features["train"].reshape(-1,features["train"].shape[-1])
    pca=PCA(n_components=64,svd_solver="randomized",random_state=SEED,whiten=True)
    pca.fit(training)
    packed=dict(projection=pca.components_.T,center=pca.mean_,scale=np.sqrt(pca.explained_variance_))
    for split,values in features.items():
        x=pca.transform(values.reshape(-1,values.shape[-1])).reshape(values.shape[:2]+(64,)).astype(np.float32)
        assert np.isfinite(x).all()
        packed[split+"_x"]=x
        packed[split+"_dt"]=np.ones(x.shape[:2],np.float32)
        packed[split+"_y"]=labels[split].astype(np.int32)
    projection_seconds=time.perf_counter()-start
    path=CACHE/(name+"_features.npz")
    np.savez_compressed(path,**packed)
    manifests={s:[dict(source_row=int(r[0]),label=int(r[2]),raw_sha256=r[3]) for r in rows]
               for s,rows in selection.items()}
    sets={s:{r[3] for r in rows} for s,rows in selection.items()}
    overlap={a+"_"+b:len(sets[a]&sets[b]) for a,b in
             (("train","validation"),("train","test"))}
    overlap["validation_test"]=len(sets["validation"]&sets["test"])
    assert not any(overlap.values())
    metadata.update(dataset=name,selection=manifests,selected_exact_overlap=overlap,
        projection="Randomized PCA64 whiten, fixed seed, fit exclusively on clean training tokens",
        pca_retained_variance=float(pca.explained_variance_ratio_.sum()),
        projection_seconds=projection_seconds,features_sha256=sha(path),feature_cache=str(path),
        shapes={s:list(v.shape) for s,v in features.items()},output_shape_per_example=list(packed["train_x"].shape[1:]),
        protocol_sha256=sha(FOLDER/"protocol.json"),
        source_sha256={f.name:sha(f) for f in FOLDER.glob("*.py")},
        scope="Independent unimodal probes, not paired multimodal training",
        pretrained_overlap="Not audited; new holdout claim is for this head-training project")
    (FOLDER/(name+"_manifest.json")).write_text(json.dumps(metadata,indent=2)+"\n")
    print(json.dumps({k:v for k,v in metadata.items() if k not in ("selection","source_sha256")},indent=2),flush=True)
    return path
